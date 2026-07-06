# models/equipment.py
# ──────────────────────────────────────────────────────────
# 장비 시스템 데이터 모델
# ──────────────────────────────────────────────────────────

import random
from typing import Optional

from config import (
    EQUIPMENT_FILE, SKILL_TREE_COMBAT, SKILL_TREE_TRACKING, SKILL_TREE_TRADE,
)
from data_manager import load_json

# ═══════════════════════════════════════════════════════════
# 장비 등급 정의
# ═══════════════════════════════════════════════════════════

EQUIPMENT_GRADES = {
    "common": {
        "name": "일반",
        "emoji": "⬜",
        "color": 0x95A5A6,
        "stat_multiplier": 1.0,
    },
    "uncommon": {
        "name": "고급",
        "emoji": "🟩",
        "color": 0x2ECC71,
        "stat_multiplier": 1.3,
    },
    "rare": {
        "name": "희귀",
        "emoji": "🟦",
        "color": 0x3498DB,
        "stat_multiplier": 1.7,
    },
    "epic": {
        "name": "영웅",
        "emoji": "🟪",
        "color": 0x9B59B6,
        "stat_multiplier": 2.2,
    },
    "legendary": {
        "name": "전설",
        "emoji": "🟨",
        "color": 0xF1C40F,
        "stat_multiplier": 3.0,
    },
}

# 장비 슬롯 정의
EQUIPMENT_SLOTS = {
    "weapon": {
        "name": "무기",
        "emoji": "🗡️",
        "primary_stat": "attack",
        "description": "전투 시 공격력에 영향을 줍니다.",
    },
    "tool": {
        "name": "도구",
        "emoji": "🔧",
        "primary_stat": "kidnap_bonus",
        "description": "납치 성공률에 영향을 줍니다.",
    },
    "accessory": {
        "name": "장신구",
        "emoji": "💍",
        "primary_stat": "hp_bonus",
        "description": "전투 시 냥이의 체력에 영향을 줍니다.",
    },
}

# ═══════════════════════════════════════════════════════════
# 장비 데이터 캐시
# ═══════════════════════════════════════════════════════════

_EQUIPMENT_CACHE = {}  # {equipment_id: equipment_data}


def load_equipment_data() -> dict:
    """equipment.json에서 장비 정의 데이터를 로드합니다."""
    global _EQUIPMENT_CACHE
    raw = load_json(EQUIPMENT_FILE, {})
    _EQUIPMENT_CACHE = raw
    return raw


def get_equipment_definition(equip_id: str) -> Optional[dict]:
    """장비 ID로 장비 정의 데이터를 조회합니다."""
    if not _EQUIPMENT_CACHE:
        load_equipment_data()
    return _EQUIPMENT_CACHE.get(equip_id)


def get_all_equipment() -> dict:
    """전체 장비 정의 데이터를 반환합니다."""
    if not _EQUIPMENT_CACHE:
        load_equipment_data()
    return _EQUIPMENT_CACHE


# ═══════════════════════════════════════════════════════════
# 장비 인스턴스 생성 (유저 인벤토리용)
# ═══════════════════════════════════════════════════════════

def create_equipment_instance(equip_id: str) -> Optional[dict]:
    """
    장비 정의를 기반으로 유저가 소유할 장비 인스턴스를 생성합니다.
    등급에 따라 스탯에 랜덤 변동폭을 적용합니다.

    반환: {
        "id": "wooden_bat",
        "name": "나무 배트",
        "slot": "weapon",
        "grade": "common",
        "stats": {"attack": 12},
        "unique_id": "wooden_bat_a3f2"  # 중복 구분용
    }
    """
    definition = get_equipment_definition(equip_id)
    if not definition:
        return None

    grade = definition.get("grade", "common")
    grade_info = EQUIPMENT_GRADES.get(grade, EQUIPMENT_GRADES["common"])
    multiplier = grade_info["stat_multiplier"]

    # 기본 스탯에 등급 배율 + 랜덤 변동(±10%) 적용
    base_stats = definition.get("base_stats", {})
    final_stats = {}
    for stat_key, base_val in base_stats.items():
        variance = random.uniform(0.9, 1.1)
        final_stats[stat_key] = round(base_val * multiplier * variance)

    # 고유 ID 생성 (같은 장비라도 스탯이 다를 수 있으므로)
    suffix = ''.join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=4))
    unique_id = f"{equip_id}_{suffix}"

    return {
        "id": equip_id,
        "unique_id": unique_id,
        "name": definition.get("name", "???"),
        "slot": definition.get("slot", "weapon"),
        "grade": grade,
        "stats": final_stats,
        "description": definition.get("description", ""),
    }


# ═══════════════════════════════════════════════════════════
# 장비 장착/해제
# ═══════════════════════════════════════════════════════════

def equip_item(user_data: dict, unique_id: str) -> tuple:
    """
    인벤토리의 장비를 장착합니다.
    기존 장착 장비가 있으면 자동으로 인벤토리로 교체됩니다.

    반환: (성공여부: bool, 메시지: str)
    """
    inventory = user_data.get("equipment_inventory", [])
    equipment_slots = user_data.get("equipment", {"weapon": None, "tool": None, "accessory": None})

    # 인벤토리에서 해당 장비 찾기
    target_item = None
    target_index = -1
    for i, item in enumerate(inventory):
        if item.get("unique_id") == unique_id:
            target_item = item
            target_index = i
            break

    if target_item is None:
        return False, "인벤토리에서 해당 장비를 찾을 수 없습니다."

    slot = target_item.get("slot")
    if slot not in equipment_slots:
        return False, f"유효하지 않은 장비 슬롯입니다: {slot}"

    # 기존 장착 장비를 인벤토리로 교체
    currently_equipped = equipment_slots.get(slot)
    if currently_equipped is not None:
        inventory.append(currently_equipped)

    # 새 장비 장착
    equipment_slots[slot] = target_item
    inventory.pop(target_index)

    user_data["equipment"] = equipment_slots
    user_data["equipment_inventory"] = inventory

    slot_info = EQUIPMENT_SLOTS.get(slot, {})
    slot_name = slot_info.get("name", slot)
    grade_info = EQUIPMENT_GRADES.get(target_item.get("grade", "common"), {})
    grade_emoji = grade_info.get("emoji", "")

    return True, f"{grade_emoji} **{target_item['name']}**을(를) {slot_name} 슬롯에 장착했습니다!"


def unequip_item(user_data: dict, slot: str) -> tuple:
    """
    장착된 장비를 해제하여 인벤토리로 되돌립니다.

    반환: (성공여부: bool, 메시지: str)
    """
    equipment_slots = user_data.get("equipment", {"weapon": None, "tool": None, "accessory": None})

    if slot not in equipment_slots:
        return False, f"유효하지 않은 슬롯입니다: {slot}"

    currently_equipped = equipment_slots.get(slot)
    if currently_equipped is None:
        slot_info = EQUIPMENT_SLOTS.get(slot, {})
        return False, f"{slot_info.get('name', slot)} 슬롯에 장착된 장비가 없습니다."

    inventory = user_data.get("equipment_inventory", [])
    inventory.append(currently_equipped)
    equipment_slots[slot] = None

    user_data["equipment"] = equipment_slots
    user_data["equipment_inventory"] = inventory

    return True, f"**{currently_equipped['name']}**을(를) 해제하여 인벤토리로 되돌렸습니다."


# ═══════════════════════════════════════════════════════════
# 장비 효과 계산
# ═══════════════════════════════════════════════════════════

def get_total_equipment_stats(user_data: dict) -> dict:
    """
    현재 장착된 모든 장비의 스탯을 합산하여 반환합니다.
    shop 스키마("equipped": {slot: id}) + 구 스키마("equipment": {slot: dict}) 모두 지원.
    강화 레벨(user_data["equipment_enhance"][id])이 있으면 스탯에 반영.

    반환: {"attack": 총합, "kidnap_bonus": 총합, "hp_bonus": 총합, ...}
    """
    try:
        from config import EQUIP_ENHANCE_STAT_MULT
    except Exception:
        EQUIP_ENHANCE_STAT_MULT = 0.12
    enh_map = user_data.get("equipment_enhance") or {}
    if not isinstance(enh_map, dict):
        enh_map = {}

    # shop 스키마의 equipped 슬롯을 먼저 병합
    equipment_slots = {}
    shop_equipped = user_data.get("equipped")
    if isinstance(shop_equipped, dict):
        equipment_slots.update(shop_equipped)
    legacy_equipment = user_data.get("equipment")
    if isinstance(legacy_equipment, dict):
        for k, v in legacy_equipment.items():
            equipment_slots.setdefault(k, v)

    if not equipment_slots:
        return {}

    total = {}

    for slot_key, equipped_item in equipment_slots.items():
        if equipped_item is None:
            continue

        # ★ equipped_item이 문자열(장비 ID)인 경우 → 정의에서 스탯 조회 + 강화 레벨 반영
        if isinstance(equipped_item, str):
            # shop 스키마 정의 파일(flat dict) 우선 사용
            try:
                from systems.enhancement import get_equip_def
                definition = get_equip_def(equipped_item)
            except Exception:
                definition = None
            if definition is None:
                definition = get_equipment_definition(equipped_item)
            if definition is None:
                continue
            base_stats = definition.get("stats") or definition.get("base_stats") or {}
            grade = definition.get("rarity", definition.get("grade", "common"))
            grade_info = EQUIPMENT_GRADES.get(grade, EQUIPMENT_GRADES.get("common", {"stat_multiplier": 1.0}))
            multiplier = grade_info.get("stat_multiplier", 1.0)
            enh_level = 0
            try:
                enh_level = int(enh_map.get(equipped_item, 0) or 0)
            except (ValueError, TypeError):
                pass
            enh_mult = 1.0 + enh_level * EQUIP_ENHANCE_STAT_MULT
            for stat_key, base_val in base_stats.items():
                try:
                    total[stat_key] = total.get(stat_key, 0) + int(int(base_val) * multiplier * enh_mult)
                except (ValueError, TypeError):
                    continue
            continue

        # ★ equipped_item이 dict가 아닌 다른 타입인 경우 건너뛰기
        if not isinstance(equipped_item, dict):
            continue

        # 정상 dict 처리 (+ 강화 레벨 반영: dict 내부 값 또는 enh_map 우선)
        item_stats = equipped_item.get("stats", {})
        if not isinstance(item_stats, dict):
            continue
        item_key = equipped_item.get("unique_id") or equipped_item.get("id")
        enh_level = 0
        try:
            enh_level = int(enh_map.get(item_key, equipped_item.get("enhance_level", 0)) or 0)
        except (ValueError, TypeError):
            pass
        enh_mult = 1.0 + enh_level * EQUIP_ENHANCE_STAT_MULT
        for stat_key, stat_val in item_stats.items():
            try:
                total[stat_key] = total.get(stat_key, 0) + int(int(stat_val) * enh_mult)
            except (ValueError, TypeError):
                continue

    return total


def format_equipment_embed_field(user_data: dict) -> str:
    """장착 현황을 임베드 필드용 문자열로 포맷합니다."""
    equipment_slots = user_data.get("equipment", {"weapon": None, "tool": None, "accessory": None})
    lines = []

    for slot_key, slot_info in EQUIPMENT_SLOTS.items():
        equipped = equipment_slots.get(slot_key)
        if equipped:
            grade_info = EQUIPMENT_GRADES.get(equipped.get("grade", "common"), {})
            grade_emoji = grade_info.get("emoji", "")
            stats_text = " / ".join(f"{k}: +{v}" for k, v in equipped.get("stats", {}).items())
            lines.append(f"{slot_info['emoji']} {slot_info['name']}: {grade_emoji} **{equipped['name']}** ({stats_text})")
        else:
            lines.append(f"{slot_info['emoji']} {slot_info['name']}: *비어있음*")

    return "\n".join(lines)
