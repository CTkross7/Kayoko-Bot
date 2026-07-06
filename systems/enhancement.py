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

def promote_to_enhanced(user_data: dict, cat_name: str) -> tuple[bool, str, dict | None]:
    """
    스택형 cats에서 1마리를 꺼내 0성 강화 인스턴스로 만든다.
    반환: (성공, 메시지, 인스턴스 or None)
    """
    _ensure(user_data)
    cats = user_data.get("cats", {})
    if not isinstance(cats, dict):
        return False, "인벤토리 데이터 오류입니다.", None

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
