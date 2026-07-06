# systems/enhancement.py
# ──────────────────────────────────────────────────────────
# 냥이 성작(星作)/초월 강화 + 엘리그마 경제
#
#  설계 원칙:
#   · 강화 냥이는 개별 인스턴스로 enhanced_cats(리스트)에 저장 →
#     스택형 일반 cats(dict)와 완전 분리 (인벤/편성/판매 분리)
#   · 순수 함수 — user_data(dict)만 변경, 저장은 호출측(원자적 save)
#   · 실패/파괴/드랍 판정 실패해도 데이터 훼손 없이 명확한 결과 반환
#   · 모든 수치는 config 상수 → 밸런스/인플레 튜닝 용이
# ──────────────────────────────────────────────────────────

from __future__ import annotations

import random
import uuid
from datetime import datetime

import config as _cfg
from models.cat import get_cat_by_name

MAX_STAR = _cfg.MAX_STAR
MAX_TRANSCEND = _cfg.MAX_TRANSCEND


# ═══════════════════════════════════════════════════════════
# 데이터 모델 헬퍼 (전부 추가적 — 기존 필드 훼손 없음)
# ═══════════════════════════════════════════════════════════

def _ensure(user_data: dict):
    user_data.setdefault("eligma", 0)
    if not isinstance(user_data.get("enhanced_cats"), list):
        user_data["enhanced_cats"] = []
    user_data.setdefault("eligma_today", 0)
    user_data.setdefault("eligma_today_date", "")


def _today() -> str:
    return datetime.now(_cfg.KST).strftime("%Y-%m-%d")


def _rarity_of(cat_name: str) -> str:
    cat = get_cat_by_name(cat_name)
    if not cat:
        return "common"
    from config import get_rarity_tier
    return get_rarity_tier(cat.get("rarity", 100)).get("key", "common")


def _rarity_mult(cat_name: str) -> float:
    return _cfg.RARITY_COST_MULT.get(_rarity_of(cat_name), 1.0)


def get_instance(user_data: dict, iid: str) -> dict | None:
    for inst in user_data.get("enhanced_cats", []):
        if isinstance(inst, dict) and inst.get("iid") == iid:
            return inst
    return None


# ═══════════════════════════════════════════════════════════
# 비용 계산
# ═══════════════════════════════════════════════════════════

def star_cost(cat_name: str, cur_star: int) -> dict:
    """cur_star → cur_star+1 성작 비용."""
    m = _rarity_mult(cat_name)
    eligma = round(_cfg.STAR_BASE_ELIGMA * m * (_cfg.STAR_ELIGMA_GROWTH ** cur_star))
    gold = round(_cfg.STAR_BASE_GOLD * m * (_cfg.STAR_GOLD_GROWTH ** cur_star))
    return {"eligma": int(eligma), "gold": int(gold)}


def transcend_cost(cat_name: str, cur_t: int) -> dict:
    """cur_t → cur_t+1 초월 비용 (5성 필수)."""
    m = _rarity_mult(cat_name)
    eligma = round(_cfg.TRANSCEND_BASE_ELIGMA * m * (_cfg.TRANSCEND_ELIGMA_GROWTH ** cur_t))
    gold = round(_cfg.TRANSCEND_BASE_GOLD * m * (_cfg.TRANSCEND_GOLD_GROWTH ** cur_t))
    return {"eligma": int(eligma), "gold": int(gold)}


# ═══════════════════════════════════════════════════════════
# 강화 냥이 스탯 (편성/전투에서 강해짐)
# ═══════════════════════════════════════════════════════════

def enhanced_multiplier(star: int, transcend: int) -> float:
    """강화 냥이 스탯 배율."""
    return 1.0 + star * _cfg.STAR_STAT_MULT + transcend * _cfg.TRANSCEND_STAT_MULT


def get_enhanced_stats(instance: dict) -> dict:
    """강화 인스턴스의 실효 스탯(공격/HP/코인)을 base 냥이 기준으로 계산."""
    base = get_cat_by_name(instance.get("name", "")) or {}
    mult = enhanced_multiplier(instance.get("star", 0), instance.get("transcend", 0))
    return {
        "name": instance.get("name", "?"),
        "base_power": int(base.get("base_power", 10) * mult),
        "hp": int(base.get("hp", 100) * mult),
        "coin_power": int(base.get("coin_power", 10) * mult),
        "attack_type": base.get("attack_type", "none"),
        "defense_type": base.get("defense_type", "none"),
        "star": instance.get("star", 0),
        "transcend": instance.get("transcend", 0),
        "mult": round(mult, 2),
    }


def star_label(instance: dict) -> str:
    """`⭐⭐⭐ / 🌟🌟` 형태 별 표기 (편성/인벤 분리표기용)."""
    s = instance.get("star", 0)
    t = instance.get("transcend", 0)
    txt = _cfg.STAR_EMOJI * s if s else "0성"
    if t:
        txt += " " + _cfg.TRANSCEND_EMOJI * t
    return txt


# ═══════════════════════════════════════════════════════════
# 일반 → 강화 인스턴스 승격 (cats에서 1마리 소모)
# ═══════════════════════════════════════════════════════════

def has_enhanced_of(user_data: dict, cat_name: str) -> bool:
    """이미 같은 이름의 강화 인스턴스가 있는지."""
    for inst in user_data.get("enhanced_cats", []) or []:
        if isinstance(inst, dict) and inst.get("name") == cat_name:
            return True
    return False


def promote_to_enhanced(user_data: dict, cat_name: str, force: bool = False) -> tuple[bool, str, dict | None]:
    """
    스택형 cats에서 1마리를 꺼내 0성 강화 인스턴스로 만든다.
    force=False(기본)면 이미 같은 이름의 강화 냥이가 있을 때 등록을 거부한다.
    반환: (성공, 메시지, 인스턴스 or None)
    """
    _ensure(user_data)
    cats = user_data.get("cats", {})
    if not isinstance(cats, dict):
        return False, "인벤토리 데이터 오류입니다.", None

    # ★ 중복 방지: 이미 같은 이름의 강화 냥이가 있으면 기본 거부
    if not force and has_enhanced_of(user_data, cat_name):
        return False, (
            f"이미 **{cat_name}**의 강화 인스턴스가 존재합니다.\n"
            f"기존 강화 냥이를 계속 육성하거나, `/강화해제`로 되돌린 뒤 다시 등록하세요.\n"
            f"(정말로 별도 강화 인스턴스를 추가하려면 관리자에게 문의)"
        ), None

    # 이름으로 보유 확인
    key = None
    for cid, info in cats.items():
        nm = info.get("name", cid) if isinstance(info, dict) else cid
        if nm == cat_name:
            key = cid
            break
    if key is None:
        return False, f"**{cat_name}** 냥이(일반)를 보유하고 있지 않습니다.", None

    info = cats[key]
    count = info.get("count", 1) if isinstance(info, dict) else 1
    if count <= 0:
        return False, "보유 수량이 없습니다.", None

    # 1마리 차감
    if count <= 1:
        del cats[key]
    else:
        info["count"] = count - 1

    inst = {"iid": uuid.uuid4().hex[:12], "name": cat_name, "star": 0, "transcend": 0}
    user_data["enhanced_cats"].append(inst)
    return True, f"**{cat_name}**을(를) 강화 대상으로 등록했습니다. (0성)", inst


def depromote_enhanced(user_data: dict, iid: str) -> tuple[bool, str, dict | None]:
    """
    강화 인스턴스를 제거하고 일반 cats에 1마리 되돌린다.
    강화 진행도(성/전무)는 소실되며, 투자한 재료의 일부를 엘리그마로 환급.
    반환: (성공, 메시지, 되돌린 인스턴스 or None)
    """
    _ensure(user_data)
    lst = user_data.get("enhanced_cats") or []
    if not isinstance(lst, list):
        return False, "❌ 강화 냥이 데이터 오류입니다.", None

    idx = None
    for i, inst in enumerate(lst):
        if isinstance(inst, dict) and inst.get("iid") == iid:
            idx = i; break
    if idx is None:
        return False, "❌ 해당 강화 냥이를 찾을 수 없습니다.", None

    inst = lst.pop(idx)
    name = inst.get("name", "?")
    star = int(inst.get("star", 0) or 0)
    transc = int(inst.get("transcend", 0) or 0)

    # 일반 cats에 1마리 반환 (name 키로 저장 — 기존 관행과 동일)
    cats = user_data.setdefault("cats", {})
    if not isinstance(cats, dict):
        cats = {}
        user_data["cats"] = cats
    slot = cats.get(name)
    if isinstance(slot, dict):
        slot["count"] = int(slot.get("count", 0)) + 1
    elif isinstance(slot, (int, float)):
        cats[name] = int(slot) + 1
    else:
        # 새 슬롯 (rarity 조회는 실패해도 문제 없음)
        rarity = _rarity_of(name)
        cats[name] = {"name": name, "rarity": rarity, "count": 1}

    # 환급: 소모한 재료의 30%를 엘리그마로 환급 (파괴/실패 소진분은 회수 불가 → 자원 낭비 인센티브 유지)
    refund_eligma = 0
    for s in range(star):
        refund_eligma += star_cost(name, s)["eligma"]
    for t in range(transc):
        refund_eligma += transcend_cost(name, t)["eligma"]
    refund_eligma = int(refund_eligma * 0.3)
    if refund_eligma > 0:
        user_data["eligma"] = user_data.get("eligma", 0) + refund_eligma

    detail = f"성작 {star}성 · 전무 {transc}성" if (star or transc) else "0성"
    tail = f"\n💠 엘리그마 **+{refund_eligma:,}** 환급" if refund_eligma > 0 else ""
    return True, (f"♻️ **{name}** 강화 인스턴스를 해제하고 일반 인벤토리로 되돌렸습니다.\n"
                  f"소실 진행도: {detail}{tail}"), inst


# ═══════════════════════════════════════════════════════════
# 성작 (노란별)
# ═══════════════════════════════════════════════════════════

def star_up(user_data: dict, iid: str) -> tuple[bool, str]:
    """
    강화 인스턴스를 1성 올린다. (재료 검사 → 성공/실패/파괴 판정)
    데이터 안전: 재료 부족 등 사전 실패 시 데이터 무변경.
    """
    _ensure(user_data)
    inst = get_instance(user_data, iid)
    if inst is None:
        return False, "❌ 해당 강화 냥이를 찾을 수 없습니다."

    star = inst.get("star", 0)
    if star >= MAX_STAR:
        return False, f"✅ 이미 최대 성급({MAX_STAR}성)입니다. `/초월`로 전무 강화를 진행하세요."

    cost = star_cost(inst["name"], star)
    eligma = user_data.get("eligma", 0)
    gold = user_data.get("money", 0)
    if eligma < cost["eligma"] or gold < cost["gold"]:
        return False, (f"❌ 재료 부족\n필요: {_cfg.ELIGMA_EMOJI} {cost['eligma']:,} · 💰 {cost['gold']:,}원\n"
                       f"보유: {_cfg.ELIGMA_EMOJI} {eligma:,} · 💰 {gold:,}원")

    # 재료 소모 (이 시점 이후 확정 변경)
    user_data["eligma"] = eligma - cost["eligma"]
    user_data["money"] = gold - cost["gold"]

    fail_ch = _cfg.STAR_FAIL_CHANCE.get(star, 0.0)
    destroy_ch = _cfg.STAR_DESTROY_CHANCE.get(star, 0.0)
    roll = random.random()

    if roll < destroy_ch:
        inst["star"] = max(0, star - 1)
        return True, (f"💥 **파괴!** 강화에 크게 실패하여 성급이 하락했습니다.\n"
                      f"{inst['name']} → **{star_label(inst)}** (재료 소진)")
    if roll < destroy_ch + fail_ch:
        return True, (f"⚠️ **실패...** 재료만 소진되었습니다. (성급 유지: {star}성)\n"
                      f"소모: {_cfg.ELIGMA_EMOJI} {cost['eligma']:,} · 💰 {cost['gold']:,}원")

    inst["star"] = star + 1
    tail = "  ✨ **5성 달성! 이제 `/초월` 가능**" if inst["star"] == MAX_STAR else ""
    return True, (f"✅ **성작 성공!** {inst['name']} → **{star_label(inst)}**{tail}\n"
                  f"소모: {_cfg.ELIGMA_EMOJI} {cost['eligma']:,} · 💰 {cost['gold']:,}원")


# ═══════════════════════════════════════════════════════════
# 초월 (전무 파란별) — 5성 필수
# ═══════════════════════════════════════════════════════════

def transcend(user_data: dict, iid: str) -> tuple[bool, str]:
    _ensure(user_data)
    inst = get_instance(user_data, iid)
    if inst is None:
        return False, "❌ 해당 강화 냥이를 찾을 수 없습니다."

    if inst.get("star", 0) < MAX_STAR:
        return False, f"❌ 초월은 **{MAX_STAR}성 달성 후**부터 가능합니다. 먼저 성작을 완료하세요."

    t = inst.get("transcend", 0)
    if t >= MAX_TRANSCEND:
        return False, f"✅ 이미 최대 전무({MAX_TRANSCEND}성)입니다."

    cost = transcend_cost(inst["name"], t)
    eligma = user_data.get("eligma", 0)
    gold = user_data.get("money", 0)
    if eligma < cost["eligma"] or gold < cost["gold"]:
        return False, (f"❌ 재료 부족\n필요: {_cfg.ELIGMA_EMOJI} {cost['eligma']:,} · 💰 {cost['gold']:,}원\n"
                       f"보유: {_cfg.ELIGMA_EMOJI} {eligma:,} · 💰 {gold:,}원")

    user_data["eligma"] = eligma - cost["eligma"]
    user_data["money"] = gold - cost["gold"]

    fail_ch = _cfg.TRANSCEND_FAIL_CHANCE.get(t, 0.0)
    destroy_ch = _cfg.TRANSCEND_DESTROY_CHANCE.get(t, 0.0)
    roll = random.random()

    if roll < destroy_ch:
        inst["transcend"] = max(0, t - 1)
        return True, (f"💥 **초월 파괴!** 전무 단계가 하락했습니다.\n"
                      f"{inst['name']} → **{star_label(inst)}** (재료 소진)")
    if roll < destroy_ch + fail_ch:
        return True, (f"⚠️ **초월 실패...** 재료만 소진되었습니다. (전무 유지)\n"
                      f"소모: {_cfg.ELIGMA_EMOJI} {cost['eligma']:,} · 💰 {cost['gold']:,}원")

    inst["transcend"] = t + 1
    return True, (f"🌟 **초월 성공!** {inst['name']} → **{star_label(inst)}**\n"
                  f"소모: {_cfg.ELIGMA_EMOJI} {cost['eligma']:,} · 💰 {cost['gold']:,}원")


# ═══════════════════════════════════════════════════════════
# 엘리그마 드랍 (냥이 판매 시) — 일일 한도 + 희귀도 가중
# ═══════════════════════════════════════════════════════════

def roll_eligma_drop(user_data: dict, rarity: str) -> int:
    """
    냥이 판매 시 엘리그마 드랍 판정. 일일 한도(ELIGMA_DAILY_CAP) 적용.
    반환: 실제 지급된 엘리그마 수(0 가능). user_data에 즉시 반영.
    """
    _ensure(user_data)

    # 일일 카운터 리셋
    today = _today()
    if user_data.get("eligma_today_date") != today:
        user_data["eligma_today"] = 0
        user_data["eligma_today_date"] = today

    remaining = _cfg.ELIGMA_DAILY_CAP - user_data.get("eligma_today", 0)
    if remaining <= 0:
        return 0

    table = _cfg.ELIGMA_DROP_TABLE.get(rarity, _cfg.ELIGMA_DROP_TABLE["common"])
    if random.random() >= table["chance"]:
        return 0

    lo, hi = table["amount"]
    amount = random.randint(lo, hi)
    amount = min(amount, remaining)  # 일일 한도 초과분 제거
    if amount <= 0:
        return 0

    user_data["eligma"] = user_data.get("eligma", 0) + amount
    user_data["eligma_today"] = user_data.get("eligma_today", 0) + amount
    return amount


def eligma_status(user_data: dict) -> dict:
    _ensure(user_data)
    today = _today()
    gained = user_data.get("eligma_today", 0) if user_data.get("eligma_today_date") == today else 0
    return {
        "eligma": user_data.get("eligma", 0),
        "today": gained,
        "cap": _cfg.ELIGMA_DAILY_CAP,
        "remaining": max(0, _cfg.ELIGMA_DAILY_CAP - gained),
    }


# ═══════════════════════════════════════════════════════════
# 장비 티어 강화 (냥이 강화와 동일 패턴: 재료 + 실패/파괴)
# ═══════════════════════════════════════════════════════════

EQUIP_MAX = _cfg.EQUIP_MAX_ENHANCE

# ── 장비 정의 캐시 (equipment.json을 ID 키로 평탄화) ──
_EQUIP_DEF_BY_ID: dict | None = None


def _load_equip_defs() -> dict:
    """equipment.json을 로드하고 {id: definition}으로 평탄화 (카테고리 정보 포함)."""
    global _EQUIP_DEF_BY_ID
    if _EQUIP_DEF_BY_ID is not None:
        return _EQUIP_DEF_BY_ID
    from data_manager import load_json
    raw = load_json(_cfg.EQUIPMENT_FILE, {})
    flat: dict = {}
    if isinstance(raw, dict):
        for cat_key, items in raw.items():
            if not isinstance(items, list):
                continue
            slot_from_cat = {"weapons": "weapon", "tools": "tool", "accessories": "accessory"}.get(cat_key, cat_key)
            for it in items:
                if isinstance(it, dict) and it.get("id"):
                    d = dict(it)
                    d.setdefault("slot", slot_from_cat)
                    flat[it["id"]] = d
    _EQUIP_DEF_BY_ID = flat
    return flat


def get_equip_def(item_id: str) -> dict | None:
    return _load_equip_defs().get(item_id)


def _all_owned_equip_ids(user_data: dict) -> list[tuple[str, bool]]:
    """
    두 스키마(shop=inventory/equipped=ID문자열, 구=equipment/equipment_inventory=dict)에서
    보유 장비 ID 목록을 반환. [(item_id, is_equipped)]
    """
    result: list[tuple[str, bool]] = []
    seen: set[str] = set()

    # shop 스키마: equipped (dict, ID 문자열)
    equipped = user_data.get("equipped") or {}
    if isinstance(equipped, dict):
        for v in equipped.values():
            if isinstance(v, str) and v and v not in seen:
                seen.add(v); result.append((v, True))

    # shop 스키마: inventory (카테고리 dict, ID 리스트)
    inv = user_data.get("inventory") or {}
    if isinstance(inv, dict):
        for cat_list in inv.values():
            if isinstance(cat_list, list):
                for x in cat_list:
                    if isinstance(x, str) and x and x not in seen:
                        seen.add(x); result.append((x, False))

    # 구 스키마: equipment (dict, dict/str)
    legacy_slots = user_data.get("equipment") or {}
    if isinstance(legacy_slots, dict):
        for v in legacy_slots.values():
            if isinstance(v, dict):
                key = v.get("unique_id") or v.get("id")
                if key and key not in seen:
                    seen.add(key); result.append((key, True))
            elif isinstance(v, str) and v and v not in seen:
                seen.add(v); result.append((v, True))

    # 구 스키마: equipment_inventory (list, dict/str)
    for it in user_data.get("equipment_inventory") or []:
        if isinstance(it, dict):
            key = it.get("unique_id") or it.get("id")
            if key and key not in seen:
                seen.add(key); result.append((key, False))
        elif isinstance(it, str) and it and it not in seen:
            seen.add(it); result.append((it, False))

    return result


def equip_enhance_level(user_data: dict, item_id: str) -> int:
    """장비의 현재 강화 레벨. equipment_enhance dict에서 조회."""
    m = user_data.get("equipment_enhance") or {}
    if isinstance(m, dict):
        try:
            return int(m.get(item_id, 0))
        except (ValueError, TypeError):
            return 0
    return 0


def _set_enh_level(user_data: dict, item_id: str, level: int):
    m = user_data.get("equipment_enhance")
    if not isinstance(m, dict):
        m = {}
        user_data["equipment_enhance"] = m
    m[item_id] = int(level)


def equip_enhance_cost(rarity: str, level: int) -> dict:
    m = _cfg.EQUIP_RARITY_COST_MULT.get(rarity, 1.0)
    gold = round(_cfg.EQUIP_ENHANCE_BASE_GOLD * m * (_cfg.EQUIP_ENHANCE_GOLD_GROWTH ** level))
    eligma = round(_cfg.EQUIP_ENHANCE_BASE_ELIGMA * m * (_cfg.EQUIP_ENHANCE_ELIGMA_GROWTH ** level))
    return {"gold": int(gold), "eligma": int(eligma)}


def _find_equipment(user_data: dict, item_id: str):
    """
    호환용 조회 헬퍼(과거 dict 형태 지원).
    반환: 정규화된 dict {id, name, grade/rarity, stats, enhance_level}
    """
    definition = get_equip_def(item_id)
    if definition:
        return {
            "id": item_id,
            "name": definition.get("name", "?"),
            "grade": definition.get("rarity", definition.get("grade", "common")),
            "stats": definition.get("stats", {}),
            "enhance_level": equip_enhance_level(user_data, item_id),
        }
    # 구 스키마 dict 조회 (unique_id 매칭)
    legacy_slots = user_data.get("equipment") or {}
    if isinstance(legacy_slots, dict):
        for v in legacy_slots.values():
            if isinstance(v, dict) and v.get("unique_id") == item_id:
                return v
    for it in user_data.get("equipment_inventory") or []:
        if isinstance(it, dict) and it.get("unique_id") == item_id:
            return it
    return None


def equip_enhance(user_data: dict, item_id: str) -> tuple[bool, str]:
    """
    장비를 +1 강화. shop/구 스키마 모두 지원.
    강화 레벨은 user_data["equipment_enhance"][item_id]에 저장 → 스키마 변경 없음.
    데이터 안전: 사전 실패 시 무변경.
    """
    _ensure(user_data)

    # 보유 확인 (양쪽 스키마)
    owned_ids = {oid for oid, _ in _all_owned_equip_ids(user_data)}
    if item_id not in owned_ids:
        return False, "❌ 해당 장비를 보유하고 있지 않습니다. (장착 중이거나 인벤토리에 있어야 합니다)"

    definition = get_equip_def(item_id)
    if definition is not None:
        rarity = definition.get("rarity", definition.get("grade", "common"))
        name = definition.get("name", "장비")
    else:
        # 구 스키마 dict fallback
        item = _find_equipment(user_data, item_id)
        if not item:
            return False, "❌ 장비 정의를 찾을 수 없습니다."
        rarity = item.get("grade", item.get("rarity", "common"))
        name = item.get("name", "장비")

    level = equip_enhance_level(user_data, item_id)
    if level >= EQUIP_MAX:
        return False, f"✅ 이미 최대 강화(+{EQUIP_MAX})입니다."

    cost = equip_enhance_cost(rarity, level)
    gold = user_data.get("money", 0)
    eligma = user_data.get("eligma", 0)
    if gold < cost["gold"] or eligma < cost["eligma"]:
        return False, (f"❌ 재료 부족\n필요: 💰 {cost['gold']:,}원 · {_cfg.ELIGMA_EMOJI} {cost['eligma']:,}\n"
                       f"보유: 💰 {gold:,}원 · {_cfg.ELIGMA_EMOJI} {eligma:,}")

    user_data["money"] = gold - cost["gold"]
    user_data["eligma"] = eligma - cost["eligma"]

    fail_ch = _cfg.EQUIP_FAIL_CHANCE.get(level, 0.0)
    destroy_ch = _cfg.EQUIP_DESTROY_CHANCE.get(level, 0.0)
    roll = random.random()

    if roll < destroy_ch:
        new_lv = max(0, level - 1)
        _set_enh_level(user_data, item_id, new_lv)
        return True, f"💥 **파괴!** {name} 강화 단계가 하락했습니다. → **+{new_lv}** (재료 소진)"
    if roll < destroy_ch + fail_ch:
        return True, f"⚠️ **실패...** {name} 강화 실패, 재료만 소진되었습니다. (유지: +{level})"

    _set_enh_level(user_data, item_id, level + 1)
    return True, (f"✅ **강화 성공!** {name} → **+{level + 1}**\n"
                  f"소모: 💰 {cost['gold']:,}원 · {_cfg.ELIGMA_EMOJI} {cost['eligma']:,}")


def list_enhanceable_equipment(user_data: dict) -> list:
    """
    강화 가능한 장비 목록 [(item_id, 표시명, level, rarity)].
    shop 스키마(inventory+equipped) + 구 스키마(equipment+equipment_inventory) 모두 포함.
    """
    out = []
    seen_ids = set()

    for item_id, is_equipped in _all_owned_equip_ids(user_data):
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        definition = get_equip_def(item_id)
        if definition:
            name = definition.get("name", "?")
            rarity = definition.get("rarity", definition.get("grade", "common"))
        else:
            item = _find_equipment(user_data, item_id)
            if not item:
                continue
            name = item.get("name", "?")
            rarity = item.get("grade", item.get("rarity", "common"))
        lv = equip_enhance_level(user_data, item_id)
        prefix = "[장착] " if is_equipped else ""
        out.append((item_id, f"{prefix}{name} +{lv}", lv, rarity))

    return out
