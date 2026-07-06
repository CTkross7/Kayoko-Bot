# models/user.py
# ──────────────────────────────────────────────────────────
# 유저 데이터 모델 (밸런스 v2)
# ──────────────────────────────────────────────────────────

import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any



from config import (
    KST, MAX_LEVEL, SKILL_TREE_TRACKING, SKILL_TREE_COMBAT,
    SKILL_TREE_TRADE, SKILL_EFFECTS, get_exp_for_level,
    SKILL_POINTS_PER_LEVEL, MAX_SKILL_LEVEL,
    KIDNAP_BASE_SUCCESS_RATE, KIDNAP_MAX_SUCCESS_RATE,
    KIDNAP_MIN_SUCCESS_RATE, KIDNAP_BASE_COOLDOWN,
    KIDNAP_MIN_COOLDOWN, KIDNAP_BASE_MONEY_REWARD,
    DAILY_LIMITS, NEWBIE_PROTECTION_DAYS,
    CATCHUP_EXP_BONUS_MAX, CATCHUP_LEVEL_REFERENCE,
    MONEY_SOFT_CAP_BASE, MONEY_SOFT_CAP_PER_LEVEL,
    ACHIEVEMENTS,
)
from data_manager import load_json, save_json, get_user_filepath


def _now_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def _today_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _this_week_str() -> str:
    """이번 주 월요일 날짜 문자열 (주간 리셋용)"""
    now = datetime.now(KST)
    monday = now - timedelta(days=now.weekday())
    return monday.strftime("%Y-%m-%d")


# ═══════════════════════════════════════════════════════════
# 유저 데이터 타입 교정 헬퍼
# ═══════════════════════════════════════════════════════════

def _sanitize_user_data(data: dict) -> bool:
    """
    유저 데이터의 주요 필드 타입을 검증하고 교정합니다.
    잘못된 타입(예: list가 dict여야 하는 곳)을 안전하게 변환합니다.

    반환: 교정이 발생했으면 True
    """
    fixed = False

    # ── dict여야 하는 필드들 ──
    dict_fields = {
        "achievements": {},
        "cats": {},
        "skills": {SKILL_TREE_TRACKING: 0, SKILL_TREE_COMBAT: 0, SKILL_TREE_TRADE: 0},
        "equipment": {"weapon": None, "tool": None, "accessory": None},
        "daily_counts": {},
        "battle_stats": {},
        "labyrinth_stats": {},
        "weekly_boss": {},
        "gamble_stats": {},
        "gacha_results": {},
        "total_assault_results": {},
        "item_inventory": {},
        "active_buffs": {},
        "unlocked_titles": {},
        "region_dex_progress": {},
    }

    for field, default in dict_fields.items():
        if field in data and not isinstance(data[field], dict):
            data[field] = default
            fixed = True

    # ── list여야 하는 필드들 ──
    list_fields = {
        "equipment_inventory": [],
        "battle_team": [],
        "unlocked_regions": ["alley"],
        "backup_purchases": [],
    }

    for field, default in list_fields.items():
        if field in data and not isinstance(data[field], list):
            data[field] = default
            fixed = True

    return fixed


def create_default_user_data(username: str) -> dict:
    """신규 유저의 기본 데이터를 생성합니다."""
    now = _now_str()
    today = _today_str()

    return {
        # ── 기본 정보 ──
        "username": username,
        "agreement": False,
        "created_at": now,
        "last_active": now,

        # ── 성장 시스템 ──
        "level": 1,
        "exp": 0,
        "skill_points": 0,
        "skills": {
            SKILL_TREE_TRACKING: 0,
            SKILL_TREE_COMBAT: 0,
            SKILL_TREE_TRADE: 0,
        },

        # ── 지역 시스템 ──
        "current_region": "alley",
        "unlocked_regions": ["alley"],
        "region_dex_progress": {},

        # ── 냥이 인벤토리 ──
        "cats": {},

        # ── 재화 ──
        "money": 0,
        "tuna_can": 5,

        # ── 통계 ──
        "total_attempts": 0,
        "success": 0,
        "fail": 0,
        "total_kidnaps": 0,

        # ── 납치 관련 ──
        "kidnap_cooldown_until": None,
        "daily_kidnap_count": 0,
        "last_kidnap_day": today,

        # ── 일일 제한 카운터 ──
        "daily_counts": {
            "kidnap": 0,
            "battle": 0,
            "labyrinth": 0,
            "gamble": 0,
            "equipment_buy": 0,
        },
        "daily_counts_date": today,

        # ── 자동 납치 ──
        "auto_kidnap_purchased": False,
        "auto_kidnap_upgrade_level": 0,

        # ── 장비 시스템 ──
        "equipment": {
            "weapon": None,
            "tool": None,
            "accessory": None,
        },
        "equipment_inventory": [],

        # ── 전투 ──
        "battle_team": [],
        "battle_stats": {
            "total_battles": 0,
            "victories": 0,
            "defeats": 0,
            "total_damage_dealt": 0,
            "total_damage_taken": 0,
        },

        # ── 미궁 ──
        "labyrinth_best_floor": 0,
        "labyrinth_current_floor": 0,
        "labyrinth_stats": {
            "total_runs": 0,
            "highest_floor": 0,
            "total_floors_cleared": 0,
            "total_money_earned": 0,
            "total_exp_earned": 0,
        },

        # ── 주간 보스 ──
        "weekly_boss": {
            "attempts_this_week": 0,
            "kills_this_week": 0,
            "last_week_key": _this_week_str(),
            "total_kills": 0,
        },

        # ── 도박 ──
        "gacha_results": {},
        "total_assault_results": {},
        "gamble_stats": {
            "total_bets": 0,
            "total_wins": 0,
            "total_losses": 0,
            "total_wagered": 0,
            "total_profit": 0,
            "total_loss": 0,
        },

        # ── 아이템 인벤토리 ──
        "item_inventory": {},

        # ── 버프 시스템 ──
        "active_buffs": {},

        # ── 튜토리얼 ──
        "tutorial_step": "welcome",
        "tutorial_completed": False,

        # ── 일일 보상 ──
        "last_daily_reward": None,

        # ── 칭호 ──
        "unlocked_titles": {},
        "equipped_title": None,

        # ── 도전과제 ──
        "achievements": {},

        # ── 기타 ──
        "backup_purchases": [],
    }

create_user_data = create_default_user_data
def load_user_data(user_id, username: str = "Unknown") -> dict:
    """유저 데이터를 로드합니다. 없으면 새로 생성합니다."""
    user_id_str = str(user_id)
    filepath = get_user_filepath(user_id_str)
    today = _today_str()
    this_week = _this_week_str()

    if not os.path.isfile(filepath):
        data = create_default_user_data(username)
        save_user_data(user_id_str, data)
        return data

    data = load_json(filepath, {})

    # 기본값 보충 (스키마 업데이트 호환)
    defaults = create_default_user_data(username)
    updated = False
    for key, default_val in defaults.items():
        if key not in data:
            data[key] = default_val
            updated = True
        elif isinstance(default_val, dict) and isinstance(data[key], dict):
            for sub_key, sub_val in default_val.items():
                if sub_key not in data[key]:
                    data[key][sub_key] = sub_val
                    updated = True

    # ── 타입 교정 (list→dict 등 잘못된 타입 마이그레이션) ──
    if _sanitize_user_data(data):
        updated = True

    # tuna_cans → tuna_can 마이그레이션
    if "tuna_cans" in data:
        data["tuna_can"] = data.get("tuna_can", 0) + data.pop("tuna_cans", 0)
        updated = True

    # equipped → equipment 마이그레이션
    if "equipped" in data and isinstance(data["equipped"], dict):
        equip = data.get("equipment", {"weapon": None, "tool": None, "accessory": None})
        old_equipped = data.pop("equipped")
        for slot_key in ["weapon", "tool", "accessory"]:
            if equip.get(slot_key) is None and old_equipped.get(slot_key) is not None:
                equip[slot_key] = old_equipped[slot_key]
        data["equipment"] = equip
        updated = True

    # 일일 초기화
    if data.get("last_kidnap_day") != today:
        data["daily_kidnap_count"] = 0
        data["last_kidnap_day"] = today
        updated = True

    # 일일 제한 카운터 리셋
    if data.get("daily_counts_date") != today:
        data["daily_counts"] = {k: 0 for k in DAILY_LIMITS}
        data["daily_counts_date"] = today
        updated = True

    # 주간 보스 리셋
    weekly_boss = data.get("weekly_boss", {})
    if weekly_boss.get("last_week_key") != this_week:
        weekly_boss["attempts_this_week"] = 0
        weekly_boss["kills_this_week"] = 0
        weekly_boss["last_week_key"] = this_week
        data["weekly_boss"] = weekly_boss
        updated = True

    # 만료된 버프 정리
    _cleanup_expired_buffs(data)

    # 유저 이름 업데이트
    if username != "Unknown" and data.get("username") != username:
        data["username"] = username
        updated = True

    data["last_active"] = _now_str()

    if updated:
        save_user_data(user_id_str, data)

    return data


def save_user_data(user_id, data: dict):
    """유저 데이터를 저장합니다."""
    filepath = get_user_filepath(str(user_id))
    save_json(filepath, data)


# ═══════════════════════════════════════════════════════════
# 경험치 / 레벨업
# ═══════════════════════════════════════════════════════════

def add_exp(user_data: dict, amount: int, apply_catchup: bool = True, apply_buffs: bool = True) -> dict:
    if amount <= 0:
        return {
            "leveled_up": False,
            "old_level": user_data.get("level", 1),
            "new_level": user_data.get("level", 1),
            "levels_gained": 0,
            "skill_points_gained": 0,
            "bonus_applied": 1.0,
        }

    bonus_mult = 1.0

    if apply_catchup:
        catchup = calculate_catchup_bonus(user_data)
        bonus_mult += catchup

    if apply_buffs:
        buff_mult = get_active_buff_value(user_data, "exp_boost")
        if buff_mult > 1.0:
            bonus_mult *= buff_mult

    final_amount = int(amount * bonus_mult)

    user_data["exp"] = user_data.get("exp", 0) + final_amount
    old_level = user_data.get("level", 1)
    current_level = old_level
    total_skill_points = 0

    while current_level < MAX_LEVEL:
        required = get_exp_for_level(current_level)
        if user_data["exp"] >= required:
            user_data["exp"] -= required
            current_level += 1
            total_skill_points += SKILL_POINTS_PER_LEVEL
        else:
            break

    user_data["level"] = current_level
    user_data["skill_points"] = user_data.get("skill_points", 0) + total_skill_points

    levels_gained = current_level - old_level

    if levels_gained > 0:
        _check_level_achievements(user_data)

    return {
        "leveled_up": levels_gained > 0,
        "old_level": old_level,
        "new_level": current_level,
        "levels_gained": levels_gained,
        "skill_points_gained": total_skill_points,
        "bonus_applied": bonus_mult,
    }


# ═══════════════════════════════════════════════════════════
# 스킬 시스템
# ═══════════════════════════════════════════════════════════

def get_skill_effect(user_data: dict, skill_tree: str, effect_name: str) -> float:
    """유저의 특정 스킬 효과 값을 계산합니다."""
    skill_level = user_data.get("skills", {}).get(skill_tree, 0)
    per_level = SKILL_EFFECTS.get(skill_tree, {}).get(effect_name, 0)
    return skill_level * per_level


def allocate_skill_point(user_data: dict, skill_tree: str) -> tuple:
    """스킬 포인트를 투자합니다."""
    if skill_tree not in [SKILL_TREE_TRACKING, SKILL_TREE_COMBAT, SKILL_TREE_TRADE]:
        return False, "잘못된 스킬 트리입니다."

    if user_data.get("skill_points", 0) <= 0:
        return False, "투자할 스킬 포인트가 없습니다."

    current_level = user_data.get("skills", {}).get(skill_tree, 0)
    if current_level >= MAX_SKILL_LEVEL:
        return False, "이미 최대 레벨에 도달한 스킬입니다."

    user_data["skill_points"] -= 1
    user_data["skills"][skill_tree] = current_level + 1

    skill_names = {
        SKILL_TREE_TRACKING: "🐾 추적",
        SKILL_TREE_COMBAT: "⚔️ 전투",
        SKILL_TREE_TRADE: "💰 거래",
    }

    return True, f"{skill_names[skill_tree]} 스킬이 Lv.{current_level + 1}로 상승했습니다!"


# ═══════════════════════════════════════════════════════════
# 납치 스탯
# ═══════════════════════════════════════════════════════════

def get_effective_kidnap_stats(user_data: dict) -> dict:
    """현재 유저의 납치 관련 실효 스탯을 계산합니다."""
    success_rate = KIDNAP_BASE_SUCCESS_RATE
    cooldown = KIDNAP_BASE_COOLDOWN
    money_multiplier = 1.0
    rare_bonus = 0.0

    success_rate += get_skill_effect(user_data, SKILL_TREE_TRACKING, "kidnap_success_bonus")
    rare_bonus += get_skill_effect(user_data, SKILL_TREE_TRACKING, "rare_chance_bonus")

    level = user_data.get("level", 1)
    cooldown -= level * 0.15  # 레벨당 -0.15초 (기존 0.2에서 하향)

    sell_bonus = get_skill_effect(user_data, SKILL_TREE_TRADE, "sell_price_bonus")
    money_multiplier += sell_bonus / 100.0

    # 장비 납치 보너스 (str / dict / None 모두 안전 처리)
    equipment_slots = user_data.get("equipment", {"weapon": None, "tool": None, "accessory": None})
    if isinstance(equipment_slots, dict):
        for slot_key, equipped_item in equipment_slots.items():
            if equipped_item is None:
                continue
            if isinstance(equipped_item, dict):
                item_stats = equipped_item.get("stats", {})
                if isinstance(item_stats, dict):
                    success_rate += item_stats.get("kidnap_bonus", 0)
            # str인 경우는 여기서는 스킵 (get_total_equipment_stats에서 처리)

    # 납치 버프 아이템 체크
    kidnap_boost = get_active_buff_value(user_data, "kidnap_boost")
    if kidnap_boost > 0:
        success_rate += kidnap_boost

    # 골드 버프 체크
    gold_boost = get_active_buff_value(user_data, "gold_boost")
    if gold_boost > 1.0:
        money_multiplier *= gold_boost

    success_rate = max(KIDNAP_MIN_SUCCESS_RATE, min(KIDNAP_MAX_SUCCESS_RATE, success_rate))
    cooldown = max(KIDNAP_MIN_COOLDOWN, cooldown)

    return {
        "success_rate": round(success_rate, 1),
        "cooldown": round(cooldown, 1),
        "money_multiplier": round(money_multiplier, 2),
        "rare_bonus": round(rare_bonus, 1),
    }


# ═══════════════════════════════════════════════════════════
# 일일 제한 시스템
# ═══════════════════════════════════════════════════════════

def check_daily_limit(user_data: dict, activity: str) -> tuple[bool, int, int]:
    """
    일일 제한을 확인합니다.

    반환: (제한 내 여부, 현재 횟수, 최대 횟수)
    """
    max_count = DAILY_LIMITS.get(activity, 999)
    counts = user_data.get("daily_counts", {})
    current = counts.get(activity, 0)
    return current < max_count, current, max_count


def increment_daily_count(user_data: dict, activity: str):
    """일일 카운터를 1 증가시킵니다."""
    counts = user_data.setdefault("daily_counts", {})
    counts[activity] = counts.get(activity, 0) + 1


def get_daily_counts_summary(user_data: dict) -> dict:
    """모든 일일 카운터의 현황을 반환합니다."""
    counts = user_data.get("daily_counts", {})
    summary = {}
    for activity, max_count in DAILY_LIMITS.items():
        current = counts.get(activity, 0)
        summary[activity] = {"current": current, "max": max_count, "remaining": max(0, max_count - current)}
    return summary


# ═══════════════════════════════════════════════════════════
# 뉴비 보호 시스템
# ═══════════════════════════════════════════════════════════

def is_newbie(user_data: dict) -> bool:
    """유저가 뉴비 보호 기간인지 확인합니다."""
    created_at_str = user_data.get("created_at")
    if not created_at_str:
        return False

    try:
        created_at = datetime.strptime(created_at_str, "%Y-%m-%d %H:%M:%S")
        created_at = created_at.replace(tzinfo=KST)
        now = datetime.now(KST)
        return (now - created_at).days < NEWBIE_PROTECTION_DAYS
    except (ValueError, TypeError):
        return False


def get_newbie_days_remaining(user_data: dict) -> int:
    """뉴비 보호 기간 남은 일수를 반환합니다."""
    created_at_str = user_data.get("created_at")
    if not created_at_str:
        return 0

    try:
        created_at = datetime.strptime(created_at_str, "%Y-%m-%d %H:%M:%S")
        created_at = created_at.replace(tzinfo=KST)
        now = datetime.now(KST)
        remaining = NEWBIE_PROTECTION_DAYS - (now - created_at).days
        return max(0, remaining)
    except (ValueError, TypeError):
        return 0


# ═══════════════════════════════════════════════════════════
# 캐치업 보너스
# ═══════════════════════════════════════════════════════════

def calculate_catchup_bonus(user_data: dict) -> float:
    """
    캐치업 EXP 보너스를 계산합니다.
    기준 레벨보다 낮을수록 보너스가 커집니다.

    반환: 보너스 비율 (0.0 ~ CATCHUP_EXP_BONUS_MAX)
    """
    user_level = user_data.get("level", 1)

    if user_level >= CATCHUP_LEVEL_REFERENCE:
        return 0.0

    level_diff = CATCHUP_LEVEL_REFERENCE - user_level
    # 레벨 차이 1당 약 5% 보너스, 최대 100%
    bonus = min(CATCHUP_EXP_BONUS_MAX, level_diff * 0.05)
    return round(bonus, 2)


# ═══════════════════════════════════════════════════════════
# 소지금 소프트캡
# ═══════════════════════════════════════════════════════════

def get_money_soft_cap(user_data: dict) -> int:
    """유저 레벨 기반 소지금 소프트캡을 계산합니다."""
    level = user_data.get("level", 1)
    return MONEY_SOFT_CAP_BASE + (level * MONEY_SOFT_CAP_PER_LEVEL)


def apply_money_reward(user_data: dict, amount: int) -> tuple[int, bool]:
    """
    소지금 보상을 적용합니다. 소프트캡 초과 시 50% 감쇠.

    반환: (실제 지급량, 감쇠 적용 여부)
    """
    current_money = user_data.get("money", 0)
    soft_cap = get_money_soft_cap(user_data)
    diminished = False

    # 골드 버프 적용
    gold_boost = get_active_buff_value(user_data, "gold_boost")
    if gold_boost > 1.0:
        amount = int(amount * gold_boost)

    if current_money >= soft_cap:
        amount = max(1, int(amount * 0.5))
        diminished = True

    user_data["money"] = current_money + amount
    return amount, diminished


# ═══════════════════════════════════════════════════════════
# 버프 시스템
# ═══════════════════════════════════════════════════════════

def get_active_buff_value(user_data: dict, buff_key: str) -> float:
    """
    활성 버프의 값을 반환합니다. 만료되었으면 0 (또는 1.0 for multiplier).

    buff_key: "exp_boost", "gold_boost", "kidnap_boost", "rare_bait", "legendary_bait"
    """
    buffs = user_data.get("active_buffs", {})
    if not isinstance(buffs, dict):
        user_data["active_buffs"] = {}
        return 0.0

    buff = buffs.get(buff_key)

    if not buff:
        return 0.0

    # buff 자체가 dict가 아니면 제거
    if not isinstance(buff, dict):
        del buffs[buff_key]
        return 0.0

    buff_type = buff.get("type", "")

    if buff_type == "timed":
        # 시간 기반 버프 — 만료 체크
        expires_str = buff.get("expires_at")
        if expires_str:
            try:
                expires = datetime.fromisoformat(expires_str)
                now = datetime.now(KST)
                if now >= expires:
                    # 만료됨 → 제거
                    del buffs[buff_key]
                    return 0.0
            except (ValueError, TypeError):
                del buffs[buff_key]
                return 0.0
        return buff.get("value", 0.0)

    elif buff_type == "next_use":
        # 1회용 버프 — 값 반환 후 제거
        value = buff.get("value", 0.0)
        uses = buff.get("uses_remaining", 0)
        if uses <= 1:
            del buffs[buff_key]
        else:
            buff["uses_remaining"] = uses - 1
        return value

    return 0.0


def consume_next_use_buff(user_data: dict, buff_key: str) -> float:
    """1회용 버프를 소모하고 값을 반환합니다. 없으면 0."""
    return get_active_buff_value(user_data, buff_key)


def _cleanup_expired_buffs(user_data: dict):
    """만료된 시간 기반 버프를 정리합니다."""
    buffs = user_data.get("active_buffs", {})
    if not isinstance(buffs, dict):
        user_data["active_buffs"] = {}
        return
    if not buffs:
        return

    now = datetime.now(KST)
    expired_keys = []

    for key, buff in buffs.items():
        if not isinstance(buff, dict):
            expired_keys.append(key)
            continue
        if buff.get("type") == "timed":
            expires_str = buff.get("expires_at")
            if expires_str:
                try:
                    expires = datetime.fromisoformat(expires_str)
                    if now >= expires:
                        expired_keys.append(key)
                except (ValueError, TypeError):
                    expired_keys.append(key)

    for key in expired_keys:
        del buffs[key]


# ═══════════════════════════════════════════════════════════
# 도전과제 시스템
# ═══════════════════════════════════════════════════════════

def check_achievement(user_data: dict, achievement_id: str) -> tuple[bool, dict | None]:
    """
    도전과제 달성 여부를 확인하고, 미달성이면 보상을 지급합니다.

    반환: (새로 달성 여부, 보상 정보 또는 None)
    """
    # ── 방어 코드: achievements가 dict가 아니면 교정 ──
    achievements = user_data.get("achievements", {})
    if not isinstance(achievements, dict):
        achievements = {}
        user_data["achievements"] = achievements

    if achievement_id in achievements:
        return False, None  # 이미 달성

    achievement_def = ACHIEVEMENTS.get(achievement_id)
    if not achievement_def:
        return False, None

    # 달성 기록
    achievements[achievement_id] = {
        "achieved_at": _now_str(),
    }

    # 보상 지급
    reward_money = achievement_def.get("reward_money", 0)
    reward_exp = achievement_def.get("reward_exp", 0)

    if reward_money > 0:
        user_data["money"] = user_data.get("money", 0) + reward_money

    level_up_info = None
    if reward_exp > 0:
        level_up_info = add_exp(user_data, reward_exp, apply_catchup=False, apply_buffs=False)

    # 칭호 해금 (있는 경우)
    title = achievement_def.get("reward_title")
    if title:
        titles = user_data.get("unlocked_titles", {})
        if not isinstance(titles, dict):
            titles = {}
            user_data["unlocked_titles"] = titles
        titles[title] = _now_str()

    return True, {
        "name": achievement_def["name"],
        "desc": achievement_def["desc"],
        "money": reward_money,
        "exp": reward_exp,
        "level_up": level_up_info,
    }


def check_and_grant_achievements(user_data: dict) -> list[dict]:
    """
    유저 데이터를 기반으로 달성 가능한 모든 도전과제를 확인합니다.

    반환: 새로 달성된 도전과제 보상 정보 리스트
    """
    granted = []

    level = user_data.get("level", 1)
    cats = user_data.get("cats", {})
    cats_count = len(cats) if isinstance(cats, dict) else 0
    battle_stats = user_data.get("battle_stats", {})
    battle_wins = battle_stats.get("victories", 0) if isinstance(battle_stats, dict) else 0
    lab_stats = user_data.get("labyrinth_stats", {})
    labyrinth_highest = lab_stats.get("highest_floor", 0) if isinstance(lab_stats, dict) else 0
    money = user_data.get("money", 0)
    wb = user_data.get("weekly_boss", {})
    weekly_boss_kills = wb.get("total_kills", 0) if isinstance(wb, dict) else 0

    # 수집 도전과제
    if cats_count >= 1:
        ok, info = check_achievement(user_data, "first_catch")
        if ok:
            granted.append(info)
    if cats_count >= 10:
        ok, info = check_achievement(user_data, "collector_10")
        if ok:
            granted.append(info)
    if cats_count >= 25:
        ok, info = check_achievement(user_data, "collector_25")
        if ok:
            granted.append(info)

    # 전투 도전과제
    if battle_wins >= 10:
        ok, info = check_achievement(user_data, "battle_10")
        if ok:
            granted.append(info)

    return granted


# ═══════════════════════════════════════════════════════════
# 레벨 도전과제 내부 헬퍼
# ═══════════════════════════════════════════════════════════

def _check_level_achievements(user_data: dict):
    """레벨업 시 레벨 관련 도전과제를 확인합니다."""
    level = user_data.get("level", 1)

    # config.ACHIEVEMENTS에 정의된 레벨 관련 업적 ID 패턴에 맞춰 체크
    level_milestones = {
        5: "level_5",
        10: "level_10",
        15: "level_15",
        20: "level_20",
        25: "level_25",
        30: "level_30",
    }

    for milestone, ach_id in level_milestones.items():
        if level >= milestone:
            if ach_id in ACHIEVEMENTS:
                check_achievement(user_data, ach_id)
# ═══════════════════════════════════════════════════════════
# 튜토리얼 시스템
# ═══════════════════════════════════════════════════════════

def advance_tutorial(user_data: dict, expected_step: str, next_step: str) -> bool:
    """
    튜토리얼을 다음 단계로 진행합니다.

    - expected_step: 현재 있어야 하는 단계
    - next_step: 진행할 다음 단계

    반환: 진행 성공 여부
    """
    if user_data.get("tutorial_completed", False):
        return False

    current_step = user_data.get("tutorial_step", "welcome")

    if current_step != expected_step:
        return False

    user_data["tutorial_step"] = next_step

    # "completed" 단계에 도달하면 튜토리얼 완료 처리
    if next_step == "completed":
        user_data["tutorial_completed"] = True

    return True
