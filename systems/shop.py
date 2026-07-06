# systems/shop.py
"""
상점 시스템 - Balance v2
- 소모품, 장비, 랜덤박스, 참치캔 상점, 도박
- 장비 스탯 상한제 (개별 + 총합)
- 밸런스 조정된 가격 체계
- 경제 기반:
    · 초반(Lv1~10): 일수입 ~8,000원 → 소모품/기초장비
    · 중반(Lv11~30): 일수입 ~20,000원 → 중급장비/랜덤박스
    · 후반(Lv31~50): 일수입 ~40,000원 → 고급장비/참치캔 아이템
    · 엔드(Lv51~70): 일수입 ~60,000원 → 전설장비/주간보스
"""

import discord
import random
from datetime import datetime, timedelta

from config import (
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING,
    RARITY_TIERS, DAILY_LIMITS, MAX_LEVEL,
    BOT_ICON_URL, GAMBLE_MIN_BET, GAMBLE_MAX_BET,
    SKILL_TREE_TRADE
)
from models.user import (
    load_user_data, save_user_data,
    get_skill_effect, check_daily_limit, increment_daily_count,
    apply_money_reward, get_active_buff_value
)


# ============================================================
# 장비 스탯 상한 설정
# ============================================================

EQUIPMENT_STAT_CAPS = {
    # 개별 장비 1개당 최대 스탯
    "per_piece": {
        "atk": 18,          # 공격력 % (1개당 최대 +18%)
        "hp": 20,           # 체력 % (1개당 최대 +20%)
        "crit_rate": 10,    # 크리티컬 확률 % (1개당 최대 +10%)
        "crit_damage": 25,  # 크리티컬 데미지 % (1개당 최대 +25%)
        "speed": 12,        # 속도 % (1개당 최대 +12%)
        "defense": 15,      # 방어력 % (1개당 최대 +15%)
        "evasion": 8,       # 회피 % (1개당 최대 +8%)
    },
    # 장비 전체 합산 최대 스탯 (모든 슬롯 합계)
    "total": {
        "atk": 50,          # 총 공격력 최대 +50%
        "hp": 55,           # 총 체력 최대 +55%
        "crit_rate": 25,    # 총 크리티컬 확률 최대 +25%
        "crit_damage": 60,  # 총 크리티컬 데미지 최대 +60%
        "speed": 30,        # 총 속도 최대 +30%
        "defense": 40,      # 총 방어력 최대 +40%
        "evasion": 20,      # 총 회피 최대 +20%
    },
    # 장비 슬롯 수
    "max_slots": 4,         # 무기, 방어구, 장신구, 특수
    # 인벤토리 최대
    "max_inventory": 50,
}

# 장비 슬롯 정의
EQUIPMENT_SLOTS = {
    "weapon": {"name": "무기", "emoji": "⚔️", "main_stat": "atk"},
    "armor": {"name": "방어구", "emoji": "🛡️", "main_stat": "hp"},
    "accessory": {"name": "장신구", "emoji": "💍", "main_stat": "crit_rate"},
    "special": {"name": "특수", "emoji": "✨", "main_stat": "speed"},
}


# ============================================================
# 장비 등급별 스탯 범위 (밸런스 조정)
# ============================================================

EQUIPMENT_GRADE_STATS = {
    "common": {
        "grade_name": "일반",
        "emoji": "⬜",
        "color": 0x9e9e9e,
        "stat_range": {"min_pct": 1, "max_pct": 5},
        "sub_stat_count": 0,
        "sub_stat_range": {"min_pct": 0, "max_pct": 0},
    },
    "uncommon": {
        "grade_name": "고급",
        "emoji": "🟩",
        "color": 0x4caf50,
        "stat_range": {"min_pct": 3, "max_pct": 8},
        "sub_stat_count": 1,
        "sub_stat_range": {"min_pct": 1, "max_pct": 3},
    },
    "rare": {
        "grade_name": "희귀",
        "emoji": "🟦",
        "color": 0x2196f3,
        "stat_range": {"min_pct": 5, "max_pct": 12},
        "sub_stat_count": 1,
        "sub_stat_range": {"min_pct": 2, "max_pct": 5},
    },
    "epic": {
        "grade_name": "영웅",
        "emoji": "🟪",
        "color": 0x9c27b0,
        "stat_range": {"min_pct": 8, "max_pct": 15},
        "sub_stat_count": 2,
        "sub_stat_range": {"min_pct": 3, "max_pct": 7},
    },
    "legendary": {
        "grade_name": "전설",
        "emoji": "🟨",
        "color": 0xff9800,
        "stat_range": {"min_pct": 12, "max_pct": 18},
        "sub_stat_count": 2,
        "sub_stat_range": {"min_pct": 5, "max_pct": 10},
    },
}


# ============================================================
# 소모품 정의 (밸런스 조정)
# ============================================================

CONSUMABLE_ITEMS = {
    "hp_potion_s": {
        "name": "소형 회복약",
        "emoji": "🧪",
        "description": "전투 중 HP를 20% 회복합니다.",
        "price": 800,
        "currency": "money",
        "max_stack": 30,
        "effect_type": "battle_heal",
        "effect_value": 20,
        "required_level": 1,
    },
    "hp_potion_m": {
        "name": "중형 회복약",
        "emoji": "🧴",
        "description": "전투 중 HP를 40% 회복합니다.",
        "price": 2500,
        "currency": "money",
        "max_stack": 20,
        "effect_type": "battle_heal",
        "effect_value": 40,
        "required_level": 10,
    },
    "hp_potion_l": {
        "name": "대형 회복약",
        "emoji": "🏺",
        "description": "전투 중 HP를 70% 회복합니다.",
        "price": 6000,
        "currency": "money",
        "max_stack": 10,
        "effect_type": "battle_heal",
        "effect_value": 70,
        "required_level": 25,
    },
    "exp_boost_s": {
        "name": "경험치 부스트 (소)",
        "emoji": "📗",
        "description": "다음 10회 행동의 경험치 +15%",
        "price": 3000,
        "currency": "money",
        "max_stack": 5,
        "effect_type": "buff",
        "buff_key": "exp_boost",
        "buff_value": 15,
        "buff_uses": 10,
        "required_level": 5,
    },
    "exp_boost_m": {
        "name": "경험치 부스트 (중)",
        "emoji": "📘",
        "description": "다음 25회 행동의 경험치 +25%",
        "price": 8000,
        "currency": "money",
        "max_stack": 3,
        "effect_type": "buff",
        "buff_key": "exp_boost",
        "buff_value": 25,
        "buff_uses": 25,
        "required_level": 15,
    },
    "exp_boost_l": {
        "name": "경험치 부스트 (대)",
        "emoji": "📙",
        "description": "다음 50회 행동의 경험치 +40%",
        "price": 20000,
        "currency": "money",
        "max_stack": 2,
        "effect_type": "buff",
        "buff_key": "exp_boost",
        "buff_value": 40,
        "buff_uses": 50,
        "required_level": 30,
    },
    "money_boost_s": {
        "name": "골드 부스트 (소)",
        "emoji": "💰",
        "description": "다음 10회 행동의 보상금 +15%",
        "price": 2500,
        "currency": "money",
        "max_stack": 5,
        "effect_type": "buff",
        "buff_key": "money_boost",
        "buff_value": 15,
        "buff_uses": 10,
        "required_level": 5,
    },
    "money_boost_m": {
        "name": "골드 부스트 (중)",
        "emoji": "💵",
        "description": "다음 25회 행동의 보상금 +25%",
        "price": 7000,
        "currency": "money",
        "max_stack": 3,
        "effect_type": "buff",
        "buff_key": "money_boost",
        "buff_value": 25,
        "buff_uses": 25,
        "required_level": 15,
    },
    "tracking_charm": {
        "name": "추적의 부적",
        "emoji": "🔮",
        "description": "다음 15회 납치의 희귀 냥이 등장률 +20%",
        "price": 5000,
        "currency": "money",
        "max_stack": 3,
        "effect_type": "buff",
        "buff_key": "rare_boost",
        "buff_value": 20,
        "buff_uses": 15,
        "required_level": 10,
    },
    "revive_feather": {
        "name": "부활의 깃털",
        "emoji": "🪶",
        "description": "전투 패배 시 1회 부활 (HP 30%)",
        "price": 12000,
        "currency": "money",
        "max_stack": 5,
        "effect_type": "battle_revive",
        "effect_value": 30,
        "required_level": 20,
    },
}


# ============================================================
# 장비 상점 아이템 (등급별 가격 - 밸런스 조정)
# ============================================================

EQUIPMENT_SHOP_PRICES = {
    "common": {"price": 3000, "currency": "money", "required_level": 1},
    "uncommon": {"price": 8000, "currency": "money", "required_level": 8},
    "rare": {"price": 25000, "currency": "money", "required_level": 18},
    "epic": {"price": 70000, "currency": "money", "required_level": 35},
    "legendary": {"price": 200000, "currency": "money", "required_level": 50},
}


# ============================================================
# 랜덤 박스 (밸런스 조정)
# ============================================================

RANDOM_BOXES = {
    "basic_box": {
        "name": "기본 랜덤 박스",
        "emoji": "📦",
        "description": "일반~희귀 등급 장비가 나옵니다.",
        "price": 5000,
        "currency": "money",
        "required_level": 5,
        "grade_weights": {
            "common": 55,
            "uncommon": 35,
            "rare": 10,
        },
    },
    "advanced_box": {
        "name": "고급 랜덤 박스",
        "emoji": "🎁",
        "description": "고급~영웅 등급 장비가 나옵니다.",
        "price": 18000,
        "currency": "money",
        "required_level": 15,
        "grade_weights": {
            "uncommon": 45,
            "rare": 40,
            "epic": 15,
        },
    },
    "premium_box": {
        "name": "프리미엄 랜덤 박스",
        "emoji": "💎",
        "description": "희귀~전설 등급 장비가 나옵니다.",
        "price": 50000,
        "currency": "money",
        "required_level": 30,
        "grade_weights": {
            "rare": 50,
            "epic": 38,
            "legendary": 12,
        },
    },
    "tuna_box": {
        "name": "참치캔 프리미엄 박스",
        "emoji": "🐟",
        "description": "영웅~전설 등급 장비! (참치캔 전용)",
        "price": 5,
        "currency": "tuna_can",
        "required_level": 20,
        "grade_weights": {
            "epic": 70,
            "legendary": 30,
        },
    },
}


# ============================================================
# 참치캔 상점 아이템
# ============================================================

TUNA_ITEMS = {
    "daily_pass": {
        "name": "일일 패스",
        "emoji": "📋",
        "description": "오늘 하루 납치/전투 횟수 제한 +20% 증가",
        "price": 3,
        "effect_type": "daily_limit_boost",
        "effect_value": 20,
        "max_stack": 1,
    },
    "skill_reset": {
        "name": "스킬 초기화 물약",
        "emoji": "🔄",
        "description": "투자한 스킬 포인트를 전부 회수합니다.",
        "price": 8,
        "effect_type": "skill_reset",
        "effect_value": 0,
        "max_stack": 99,
    },
    "name_change": {
        "name": "이름 변경권",
        "emoji": "📛",
        "description": "캣맘 닉네임을 변경합니다. (현재 미구현)",
        "price": 2,
        "effect_type": "name_change",
        "effect_value": 0,
        "max_stack": 99,
    },
    "tuna_exp_boost": {
        "name": "황금 참치 부스트",
        "emoji": "🌟",
        "description": "다음 100회 행동의 경험치 +50%",
        "price": 10,
        "effect_type": "buff",
        "buff_key": "exp_boost",
        "buff_value": 50,
        "buff_uses": 100,
        "max_stack": 1,
    },
    "inventory_expand": {
        "name": "장비 인벤토리 확장",
        "emoji": "🎒",
        "description": "장비 인벤토리 +10칸 (최대 100칸)",
        "price": 15,
        "effect_type": "inventory_expand",
        "effect_value": 10,
        "max_stack": 5,
    },
}


# ============================================================
# 장비 생성
# ============================================================

def generate_equipment(grade: str, slot: str | None = None) -> dict:
    """등급에 맞는 랜덤 장비 생성 (스탯 캡 적용)"""
    grade_info = EQUIPMENT_GRADE_STATS.get(grade)
    if not grade_info:
        grade_info = EQUIPMENT_GRADE_STATS["common"]
        grade = "common"

    # 슬롯 랜덤 선택
    if slot is None:
        slot = random.choice(list(EQUIPMENT_SLOTS.keys()))

    slot_info = EQUIPMENT_SLOTS[slot]
    per_piece_cap = EQUIPMENT_STAT_CAPS["per_piece"]

    # 메인 스탯 생성
    main_stat_key = slot_info["main_stat"]
    stat_range = grade_info["stat_range"]
    main_stat_value = random.randint(stat_range["min_pct"], stat_range["max_pct"])
    # 개별 캡 적용
    main_stat_value = min(main_stat_value, per_piece_cap.get(main_stat_key, 99))

    stats = {main_stat_key: main_stat_value}

    # 서브 스탯 생성
    sub_count = grade_info["sub_stat_count"]
    if sub_count > 0:
        sub_range = grade_info["sub_stat_range"]
        possible_subs = [k for k in per_piece_cap.keys() if k != main_stat_key]
        chosen_subs = random.sample(possible_subs, min(sub_count, len(possible_subs)))

        for sub_key in chosen_subs:
            sub_value = random.randint(sub_range["min_pct"], sub_range["max_pct"])
            sub_value = min(sub_value, per_piece_cap.get(sub_key, 99))
            stats[sub_key] = sub_value

    # 장비 이름 생성
    name_prefixes = {
        "common": ["낡은", "평범한", "기본"],
        "uncommon": ["튼튼한", "개량된", "강화된"],
        "rare": ["정교한", "빛나는", "숙련된"],
        "epic": ["영웅의", "축복받은", "마법의"],
        "legendary": ["전설의", "신화적", "궁극의"],
    }
    name_suffixes = {
        "weapon": ["발톱", "이빨", "꼬리채찍", "고양이 펀치"],
        "armor": ["털갑옷", "방패", "보호대", "가디건"],
        "accessory": ["목걸이", "리본", "귀걸이", "방울"],
        "special": ["운동화", "부적", "망토", "날개"],
    }

    prefix = random.choice(name_prefixes.get(grade, ["기본"]))
    suffix = random.choice(name_suffixes.get(slot, ["장비"]))
    name = f"{prefix} {suffix}"

    equipment = {
        "id": f"eq_{int(datetime.now().timestamp() * 1000)}_{random.randint(1000,9999)}",
        "name": name,
        "grade": grade,
        "slot": slot,
        "stats": stats,
        "created_at": datetime.now().isoformat(),
    }

    return equipment


def get_equipment_total_stats(user_data: dict) -> dict:
    """현재 장착 중인 장비의 총 스탯 합산 (캡 적용)"""
    equipment = user_data.get("equipment", {})
    equipment_inventory = user_data.get("equipment_inventory", [])
    total_caps = EQUIPMENT_STAT_CAPS["total"]

    total_stats = {}

    for slot_key, eq_id in equipment.items():
        if not eq_id or slot_key not in EQUIPMENT_SLOTS:
            continue

        # 인벤토리에서 장비 찾기
        eq_data = None
        for eq in equipment_inventory:
            if isinstance(eq, dict) and eq.get("id") == eq_id:
                eq_data = eq
                break

        if not eq_data:
            continue

        stats = eq_data.get("stats", {})
        for stat_key, stat_value in stats.items():
            total_stats[stat_key] = total_stats.get(stat_key, 0) + stat_value

    # 총합 캡 적용
    for stat_key in total_stats:
        cap = total_caps.get(stat_key, 999)
        total_stats[stat_key] = min(total_stats[stat_key], cap)

    return total_stats


def can_equip_check_cap(user_data: dict, new_equipment: dict, target_slot: str) -> tuple[bool, str]:
    """장비 장착 시 총합 캡 초과 여부 확인"""
    equipment = user_data.get("equipment", {})
    equipment_inventory = user_data.get("equipment_inventory", [])
    total_caps = EQUIPMENT_STAT_CAPS["total"]

    # 현재 총 스탯 (교체할 슬롯 제외)
    current_stats = {}
    for slot_key, eq_id in equipment.items():
        if slot_key == target_slot or not eq_id or slot_key not in EQUIPMENT_SLOTS:
            continue

        eq_data = None
        for eq in equipment_inventory:
            if isinstance(eq, dict) and eq.get("id") == eq_id:
                eq_data = eq
                break

        if eq_data:
            for stat_key, stat_value in eq_data.get("stats", {}).items():
                current_stats[stat_key] = current_stats.get(stat_key, 0) + stat_value

    # 새 장비 추가 후 확인
    new_stats = new_equipment.get("stats", {})
    for stat_key, stat_value in new_stats.items():
        combined = current_stats.get(stat_key, 0) + stat_value
        cap = total_caps.get(stat_key, 999)
        if combined > cap:
            return False, f"{stat_key} 합산이 {cap}%를 초과합니다. (현재 {current_stats.get(stat_key,0)}% + 신규 {stat_value}% = {combined}%)"

    return True, ""


# ============================================================
# 구매 함수
# ============================================================

def buy_consumable(user_data: dict, item_key: str) -> tuple[bool, str]:
    """소모품 구매"""
    item = CONSUMABLE_ITEMS.get(item_key)
    if not item:
        return False, "존재하지 않는 아이템입니다."

    # 레벨 체크
    if user_data.get("level", 1) < item.get("required_level", 1):
        return False, f"Lv.{item['required_level']} 이상 필요합니다."

    # 가격 체크
    price = item["price"]
    currency = item.get("currency", "money")

    # 교역 스킬 할인 (돈 구매 시)
    if currency == "money":
        discount = get_skill_effect(user_data, "trade", "shop_discount")
        if discount > 0:
            price = max(1, int(price * (1 - discount / 100)))

    if currency == "money":
        if user_data.get("money", 0) < price:
            return False, f"자금이 부족합니다. (필요: {price:,}원)"
    elif currency == "tuna_can":
        if user_data.get("tuna_can", 0) < price:
            return False, f"참치캔이 부족합니다. (필요: {price}개)"

    # 스택 체크
    inventory = user_data.get("item_inventory", {})
    current = inventory.get(item_key, 0)
    max_stack = item.get("max_stack", 99)
    if current >= max_stack:
        return False, f"최대 보유량({max_stack}개)에 도달했습니다."

    # 구매 실행
    if currency == "money":
        user_data["money"] -= price
    elif currency == "tuna_can":
        user_data["tuna_can"] = user_data.get("tuna_can", 0) - price

    inventory[item_key] = current + 1
    user_data["item_inventory"] = inventory

    return True, f"**{item['name']}** 구매 완료! (-{price:,}{'원' if currency == 'money' else ' 참치캔'})"


def buy_equipment_by_grade(user_data: dict, grade: str) -> tuple[bool, str, dict | None]:
    """등급 지정 장비 구매"""
    shop_info = EQUIPMENT_SHOP_PRICES.get(grade)
    if not shop_info:
        return False, "존재하지 않는 등급입니다.", None

    # 레벨 체크
    if user_data.get("level", 1) < shop_info.get("required_level", 1):
        return False, f"Lv.{shop_info['required_level']} 이상 필요합니다.", None

    # 일일 제한
    limit_ok, remaining = check_daily_limit(user_data, "equipment_buy")
    if not limit_ok:
        return False, f"오늘의 장비 구매 횟수를 모두 소진했습니다. (제한: {DAILY_LIMITS.get('equipment_buy', 10)}회)", None

    # 인벤토리 공간
    eq_inv = user_data.get("equipment_inventory", [])
    max_inv = user_data.get("equipment_inventory_max", EQUIPMENT_STAT_CAPS["max_inventory"])
    if len(eq_inv) >= max_inv:
        return False, f"장비 인벤토리가 가득 찼습니다. ({len(eq_inv)}/{max_inv})", None

    # 가격
    price = shop_info["price"]
    currency = shop_info.get("currency", "money")

    # 교역 스킬 할인
    if currency == "money":
        discount = get_skill_effect(user_data, "trade", "shop_discount")
        if discount > 0:
            price = max(1, int(price * (1 - discount / 100)))

    if currency == "money":
        if user_data.get("money", 0) < price:
            return False, f"자금이 부족합니다. (필요: {price:,}원)", None
    elif currency == "tuna_can":
        if user_data.get("tuna_can", 0) < price:
            return False, f"참치캔이 부족합니다. (필요: {price}개)", None

    # 구매 실행
    if currency == "money":
        user_data["money"] -= price
    elif currency == "tuna_can":
        user_data["tuna_can"] = user_data.get("tuna_can", 0) - price

    # 장비 생성
    equipment = generate_equipment(grade)
    eq_inv.append(equipment)
    user_data["equipment_inventory"] = eq_inv
    increment_daily_count(user_data, "equipment_buy")

    return True, f"**{equipment['name']}** 획득! (-{price:,}{'원' if currency == 'money' else ' 참치캔'})", equipment


def open_random_box(user_data: dict, box_key: str) -> tuple[bool, str, dict | None]:
    """랜덤 박스 개봉"""
    box = RANDOM_BOXES.get(box_key)
    if not box:
        return False, "존재하지 않는 박스입니다.", None

    # 레벨 체크
    if user_data.get("level", 1) < box.get("required_level", 1):
        return False, f"Lv.{box['required_level']} 이상 필요합니다.", None

    # 인벤토리 공간
    eq_inv = user_data.get("equipment_inventory", [])
    max_inv = user_data.get("equipment_inventory_max", EQUIPMENT_STAT_CAPS["max_inventory"])
    if len(eq_inv) >= max_inv:
        return False, f"장비 인벤토리가 가득 찼습니다. ({len(eq_inv)}/{max_inv})", None

    # 가격
    price = box["price"]
    currency = box.get("currency", "money")

    if currency == "money":
        discount = get_skill_effect(user_data, "trade", "shop_discount")
        if discount > 0:
            price = max(1, int(price * (1 - discount / 100)))
        if user_data.get("money", 0) < price:
            return False, f"자금이 부족합니다. (필요: {price:,}원)", None
        user_data["money"] -= price
    elif currency == "tuna_can":
        if user_data.get("tuna_can", 0) < price:
            return False, f"참치캔이 부족합니다. (필요: {price}개)", None
        user_data["tuna_can"] = user_data.get("tuna_can", 0) - price

    # 등급 추첨
    grade_weights = box["grade_weights"]
    grades = list(grade_weights.keys())
    weights = list(grade_weights.values())
    result_grade = random.choices(grades, weights=weights, k=1)[0]

    # 장비 생성
    equipment = generate_equipment(result_grade)
    eq_inv.append(equipment)
    user_data["equipment_inventory"] = eq_inv

    return True, f"**{equipment['name']}** 획득! ({EQUIPMENT_GRADE_STATS[result_grade]['emoji']} {result_grade.upper()})", equipment


def buy_tuna_item(user_data: dict, item_key: str) -> tuple[bool, str]:
    """참치캔 상점 아이템 구매"""
    item = TUNA_ITEMS.get(item_key)
    if not item:
        return False, "존재하지 않는 아이템입니다."

    price = item["price"]
    if user_data.get("tuna_can", 0) < price:
        return False, f"참치캔이 부족합니다. (필요: {price}개)"

    # 효과별 처리
    effect_type = item.get("effect_type")

    if effect_type == "buff":
        # 버프 적용
        active_buffs = user_data.get("active_buffs", {})
        buff_key = item["buff_key"]
        existing = active_buffs.get(buff_key, {})

        if isinstance(existing, dict) and existing.get("uses_remaining", 0) > 0:
            # 기존 버프에 횟수 추가
            existing["uses_remaining"] += item["buff_uses"]
            existing["value"] = max(existing.get("value", 0), item["buff_value"])
        else:
            active_buffs[buff_key] = {
                "value": item["buff_value"],
                "uses_remaining": item["buff_uses"],
                "applied_at": datetime.now().isoformat(),
            }
        user_data["active_buffs"] = active_buffs

    elif effect_type == "skill_reset":
        # 스킬 초기화
        skills = user_data.get("skills", {})
        total_refund = sum(skills.values())
        user_data["skills"] = {"tracking": 0, "combat": 0, "trade": 0}
        user_data["skill_points"] = user_data.get("skill_points", 0) + total_refund

    elif effect_type == "daily_limit_boost":
        # 일일 제한 부스트 (당일만)
        daily_boost = user_data.get("daily_limit_boost", {})
        today = datetime.now().strftime("%Y-%m-%d")
        daily_boost["date"] = today
        daily_boost["boost_pct"] = item["effect_value"]
        user_data["daily_limit_boost"] = daily_boost

    elif effect_type == "inventory_expand":
        current_max = user_data.get("equipment_inventory_max", EQUIPMENT_STAT_CAPS["max_inventory"])
        new_max = min(100, current_max + item["effect_value"])
        if new_max <= current_max:
            return False, "이미 최대 인벤토리 크기입니다. (100칸)"
        user_data["equipment_inventory_max"] = new_max

    # 참치캔 차감
    user_data["tuna_can"] = user_data.get("tuna_can", 0) - price

    return True, f"**{item['name']}** 사용 완료! (-{price} 참치캔)"


def sell_equipment(user_data: dict, equipment_id: str) -> tuple[bool, str, int]:
    """장비 판매"""
    eq_inv = user_data.get("equipment_inventory", [])
    equipped = user_data.get("equipment", {})

    # 장착 중인지 확인
    for slot_key, eq_id in equipped.items():
        if eq_id == equipment_id:
            return False, "장착 중인 장비는 판매할 수 없습니다. 먼저 해제해주세요.", 0

    # 장비 찾기
    target = None
    target_index = -1
    for i, eq in enumerate(eq_inv):
        if isinstance(eq, dict) and eq.get("id") == equipment_id:
            target = eq
            target_index = i
            break

    if target is None:
        return False, "해당 장비를 찾을 수 없습니다.", 0

    # 판매 가격 (구매가의 30% + 교역 스킬 보너스)
    grade = target.get("grade", "common")
    base_price = EQUIPMENT_SHOP_PRICES.get(grade, {}).get("price", 1000)
    sell_price = int(base_price * 0.3)

    sell_bonus = get_skill_effect(user_data, "trade", "sell_price_bonus")
    if sell_bonus > 0:
        sell_price = int(sell_price * (1 + sell_bonus / 100))

    # 판매 실행
    eq_inv.pop(target_index)
    user_data["equipment_inventory"] = eq_inv
    user_data["money"] = user_data.get("money", 0) + sell_price

    return True, f"**{target.get('name', '장비')}** 판매 완료! (+{sell_price:,}원)", sell_price


# ============================================================
# 도박 함수
# ============================================================

def coin_flip(user_data: dict, bet: int) -> tuple[bool, str, int]:
    """동전 던지기 (50:50, 배당 1.9배)"""
    if bet < GAMBLE_MIN_BET:
        return False, f"최소 배팅금은 {GAMBLE_MIN_BET:,}원입니다.", 0
    if bet > GAMBLE_MAX_BET:
        return False, f"최대 배팅금은 {GAMBLE_MAX_BET:,}원입니다.", 0
    if user_data.get("money", 0) < bet:
        return False, "잔액이 부족합니다.", 0

    limit_ok, _ = check_daily_limit(user_data, "gamble")
    if not limit_ok:
        return False, f"오늘의 도박 횟수를 모두 소진했습니다. (제한: {DAILY_LIMITS.get('gamble', 20)}회)", 0

    user_data["money"] -= bet
    increment_daily_count(user_data, "gamble")

    win = random.random() < 0.5
    if win:
        winnings = int(bet * 1.9)
        user_data["money"] += winnings
        profit = winnings - bet
        stats = user_data.get("stats", {})
        stats["gamble_wins"] = stats.get("gamble_wins", 0) + 1
        stats["gamble_total_profit"] = stats.get("gamble_total_profit", 0) + profit
        user_data["stats"] = stats
        return True, f"🎉 승리! +{profit:,}원 (잔액: {user_data['money']:,}원)", profit
    else:
        stats = user_data.get("stats", {})
        stats["gamble_losses"] = stats.get("gamble_losses", 0) + 1
        stats["gamble_total_profit"] = stats.get("gamble_total_profit", 0) - bet
        user_data["stats"] = stats
        return True, f"😢 패배... -{bet:,}원 (잔액: {user_data['money']:,}원)", -bet


def slot_machine(user_data: dict, bet: int) -> tuple[bool, str, int]:
    """슬롯머신 (다양한 배당)"""
    if bet < GAMBLE_MIN_BET:
        return False, f"최소 배팅금은 {GAMBLE_MIN_BET:,}원입니다.", 0
    if bet > GAMBLE_MAX_BET:
        return False, f"최대 배팅금은 {GAMBLE_MAX_BET:,}원입니다.", 0
    if user_data.get("money", 0) < bet:
        return False, "잔액이 부족합니다.", 0

    limit_ok, _ = check_daily_limit(user_data, "gamble")
    if not limit_ok:
        return False, f"오늘의 도박 횟수를 모두 소진했습니다.", 0

    user_data["money"] -= bet
    increment_daily_count(user_data, "gamble")

    symbols = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎", "7️⃣"]
    weights = [30, 25, 20, 12, 8, 4, 1]

    reels = random.choices(symbols, weights=weights, k=3)
    reel_str = " | ".join(reels)

    # 배당 계산
    multiplier = 0
    if reels[0] == reels[1] == reels[2]:
        # 3개 일치
        symbol_mults = {
            "🍒": 3, "🍋": 4, "🍊": 5, "🍇": 8,
            "⭐": 15, "💎": 30, "7️⃣": 100,
        }
        multiplier = symbol_mults.get(reels[0], 3)
    elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        # 2개 일치
        multiplier = 1.5

    stats = user_data.get("stats", {})

    if multiplier > 0:
        winnings = int(bet * multiplier)
        user_data["money"] += winnings
        profit = winnings - bet
        stats["gamble_wins"] = stats.get("gamble_wins", 0) + 1
        stats["gamble_total_profit"] = stats.get("gamble_total_profit", 0) + profit
        user_data["stats"] = stats

        if multiplier >= 10:
            result_text = f"🎰 [ {reel_str} ] 🎰\n💥 **잭팟!** x{multiplier} = +{profit:,}원!"
        else:
            result_text = f"🎰 [ {reel_str} ] 🎰\n🎉 당첨! x{multiplier} = +{profit:,}원"
        return True, result_text, profit
    else:
        stats["gamble_losses"] = stats.get("gamble_losses", 0) + 1
        stats["gamble_total_profit"] = stats.get("gamble_total_profit", 0) - bet
        user_data["stats"] = stats
        return True, f"🎰 [ {reel_str} ] 🎰\n😢 꽝... -{bet:,}원", -bet


# ============================================================
# 임베드 빌더
# ============================================================

def build_shop_main_embed(user_data: dict) -> discord.Embed:
    """상점 메인 임베드"""
    money = user_data.get("money", 0)
    tuna = user_data.get("tuna_can", 0)
    level = user_data.get("level", 1)

    embed = discord.Embed(
        title="🏪 냥이 상점",
        description=(
            f"💵 보유금: **{money:,}원** | 🐟 참치캔: **{tuna}개**\n"
            f"📊 레벨: Lv.**{level}**"
        ),
        color=COLOR_PRIMARY
    )

    embed.add_field(
        name="🧪 소모품 상점",
        value="회복약, 버프 아이템 등",
        inline=True
    )
    embed.add_field(
        name="⚔️ 장비 상점",
        value="등급별 장비 구매",
        inline=True
    )
    embed.add_field(
        name="📦 랜덤 박스",
        value="운빨 장비 뽑기!",
        inline=True
    )
    embed.add_field(
        name="🐟 참치캔 상점",
        value="프리미엄 아이템",
        inline=True
    )
    embed.add_field(
        name="🎰 도박장",
        value="동전 던지기, 슬롯머신",
        inline=True
    )

    # 교역 스킬 할인 표시
    discount = get_skill_effect(user_data, "trade", "shop_discount")
    if discount > 0:
        embed.set_footer(text=f"💼 교역 스킬 할인: -{discount}% 적용 중", icon_url=BOT_ICON_URL)
    else:
        embed.set_footer(text="카테고리를 선택하세요!", icon_url=BOT_ICON_URL)

    return embed


def build_consumable_shop_embed(user_data: dict) -> discord.Embed:
    """소모품 상점 임베드"""
    level = user_data.get("level", 1)
    money = user_data.get("money", 0)
    inventory = user_data.get("item_inventory", {})
    discount = get_skill_effect(user_data, "trade", "shop_discount")

    embed = discord.Embed(
        title="🧪 소모품 상점",
        description=f"💵 보유금: **{money:,}원**",
        color=COLOR_PRIMARY
    )

    for key, item in CONSUMABLE_ITEMS.items():
        price = item["price"]
        if discount > 0:
            price = max(1, int(price * (1 - discount / 100)))

        current = inventory.get(key, 0)
        max_stack = item.get("max_stack", 99)
        level_req = item.get("required_level", 1)

        status = ""
        if level < level_req:
            status = f" 🔒 Lv.{level_req}"
        elif current >= max_stack:
            status = " ✅ MAX"

        embed.add_field(
            name=f"{item['emoji']} {item['name']} — {price:,}원{status}",
            value=f"{item['description']}\n보유: {current}/{max_stack}",
            inline=False
        )

    if discount > 0:
        embed.set_footer(text=f"💼 교역 스킬 할인 -{discount}% 적용됨", icon_url=BOT_ICON_URL)

    return embed


def build_equipment_shop_embed(user_data: dict) -> discord.Embed:
    """장비 상점 임베드"""
    level = user_data.get("level", 1)
    money = user_data.get("money", 0)
    discount = get_skill_effect(user_data, "trade", "shop_discount")
    eq_count = len(user_data.get("equipment_inventory", []))
    eq_max = user_data.get("equipment_inventory_max", EQUIPMENT_STAT_CAPS["max_inventory"])

    embed = discord.Embed(
        title="⚔️ 장비 상점",
        description=(
            f"💵 보유금: **{money:,}원**\n"
            f"🎒 장비: **{eq_count}/{eq_max}**"
        ),
        color=COLOR_PRIMARY
    )

    # 스탯 상한 안내
    caps = EQUIPMENT_STAT_CAPS["total"]
    cap_text = (
        f"총합 상한: ATK {caps['atk']}% / HP {caps['hp']}% / "
        f"크리 {caps['crit_rate']}% / 크뎀 {caps['crit_damage']}%"
    )
    embed.add_field(name="📋 장비 스탯 상한", value=cap_text, inline=False)

    for grade, info in EQUIPMENT_SHOP_PRICES.items():
        grade_data = EQUIPMENT_GRADE_STATS.get(grade, {})
        price = info["price"]
        if discount > 0:
            price = max(1, int(price * (1 - discount / 100)))

        req_lv = info.get("required_level", 1)
        stat_range = grade_data.get("stat_range", {})
        sub_count = grade_data.get("sub_stat_count", 0)

        status = ""
        if level < req_lv:
            status = f" 🔒 Lv.{req_lv}"

        embed.add_field(
            name=f"{grade_data.get('emoji', '⬜')} {grade_data.get('grade_name', grade)} — {price:,}원{status}",
            value=(
                f"메인 스탯: {stat_range.get('min_pct', 0)}~{stat_range.get('max_pct', 0)}%\n"
                f"서브 스탯: {sub_count}개"
            ),
            inline=True
        )

    if discount > 0:
        embed.set_footer(text=f"💼 교역 스킬 할인 -{discount}% 적용됨", icon_url=BOT_ICON_URL)

    return embed


def build_random_box_embed(user_data: dict) -> discord.Embed:
    """랜덤 박스 임베드"""
    level = user_data.get("level", 1)
    money = user_data.get("money", 0)
    tuna = user_data.get("tuna_can", 0)
    discount = get_skill_effect(user_data, "trade", "shop_discount")

    embed = discord.Embed(
        title="📦 랜덤 박스",
        description=f"💵 보유금: **{money:,}원** | 🐟 참치캔: **{tuna}개**",
        color=COLOR_PRIMARY
    )

    for key, box in RANDOM_BOXES.items():
        price = box["price"]
        currency = box.get("currency", "money")

        if currency == "money" and discount > 0:
            price = max(1, int(price * (1 - discount / 100)))

        req_lv = box.get("required_level", 1)
        status = f" 🔒 Lv.{req_lv}" if level < req_lv else ""

        # 등급 확률 표시
        grade_weights = box.get("grade_weights", {})
        total_weight = sum(grade_weights.values())
        prob_text = " / ".join([
            f"{EQUIPMENT_GRADE_STATS.get(g, {}).get('emoji', '⬜')}{round(w/total_weight*100)}%"
            for g, w in grade_weights.items()
        ])

        currency_text = f"{price:,}원" if currency == "money" else f"{price} 참치캔"

        embed.add_field(
            name=f"{box['emoji']} {box['name']} — {currency_text}{status}",
            value=f"{box['description']}\n확률: {prob_text}",
            inline=False
        )

    return embed


def build_tuna_shop_embed(user_data: dict) -> discord.Embed:
    """참치캔 상점 임베드"""
    tuna = user_data.get("tuna_can", 0)

    embed = discord.Embed(
        title="🐟 참치캔 상점",
        description=f"🐟 보유 참치캔: **{tuna}개**",
        color=COLOR_PRIMARY
    )

    for key, item in TUNA_ITEMS.items():
        embed.add_field(
            name=f"{item['emoji']} {item['name']} — {item['price']} 🐟",
            value=item["description"],
            inline=False
        )

    embed.set_footer(text="참치캔은 전투/미궁/이벤트에서 획득할 수 있습니다!", icon_url=BOT_ICON_URL)
    return embed


def build_gamble_embed(user_data: dict) -> discord.Embed:
    """도박장 임베드"""
    money = user_data.get("money", 0)
    stats = user_data.get("stats", {})
    daily = user_data.get("daily_counts", {})
    gamble_today = daily.get("gamble", 0)
    gamble_limit = DAILY_LIMITS.get("gamble", 20)

    wins = stats.get("gamble_wins", 0)
    losses = stats.get("gamble_losses", 0)
    total_profit = stats.get("gamble_total_profit", 0)

    embed = discord.Embed(
        title="🎰 도박장",
        description=(
            f"💵 보유금: **{money:,}원**\n"
            f"📅 오늘 도박: **{gamble_today}/{gamble_limit}회**\n\n"
            f"배팅 범위: **{GAMBLE_MIN_BET:,}원 ~ {GAMBLE_MAX_BET:,}원**"
        ),
        color=COLOR_PRIMARY
    )

    embed.add_field(
        name="🪙 동전 던지기",
        value="승률 50%, 배당 1.9배",
        inline=True
    )
    embed.add_field(
        name="🎰 슬롯머신",
        value="2개 일치 1.5배 ~ 7️⃣ 잭팟 100배!",
        inline=True
    )

    profit_text = f"+{total_profit:,}원" if total_profit >= 0 else f"{total_profit:,}원"
    embed.add_field(
        name="📊 도박 전적",
        value=f"승: {wins} / 패: {losses} / 순수익: {profit_text}",
        inline=False
    )

    return embed


def build_equipment_detail_embed(equipment: dict) -> discord.Embed:
    """장비 상세 임베드"""
    grade = equipment.get("grade", "common")
    grade_info = EQUIPMENT_GRADE_STATS.get(grade, EQUIPMENT_GRADE_STATS["common"])
    slot = equipment.get("slot", "weapon")
    slot_info = EQUIPMENT_SLOTS.get(slot, {"name": "무기", "emoji": "⚔️"})

    embed = discord.Embed(
        title=f"{grade_info['emoji']} {equipment.get('name', '장비')}",
        description=f"**{grade_info['grade_name']}** 등급 | {slot_info['emoji']} {slot_info['name']}",
        color=grade_info.get("color", COLOR_PRIMARY)
    )

    stats = equipment.get("stats", {})
    stat_names = {
        "atk": "⚔️ 공격력", "hp": "❤️ 체력", "crit_rate": "🎯 크리티컬",
        "crit_damage": "💥 크리 데미지", "speed": "💨 속도",
        "defense": "🛡️ 방어력", "evasion": "🌀 회피",
    }
    per_caps = EQUIPMENT_STAT_CAPS["per_piece"]

    stat_lines = []
    for key, val in stats.items():
        cap = per_caps.get(key, 99)
        name = stat_names.get(key, key)
        bar_ratio = min(val / cap, 1.0)
        bar_len = 10
        filled = int(bar_ratio * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        stat_lines.append(f"{name}: **+{val}%** `{bar}` (캡: {cap}%)")

    embed.add_field(name="📊 스탯", value="\n".join(stat_lines) if stat_lines else "없음", inline=False)

    # 판매가
    base_price = EQUIPMENT_SHOP_PRICES.get(grade, {}).get("price", 1000)
    sell_price = int(base_price * 0.3)
    embed.set_footer(text=f"판매가: {sell_price:,}원 | ID: {equipment.get('id', 'N/A')}")

    return embed
