"""
systems/kidnap.py
냥이 납치 시스템 — 페이크+리얼 버튼 (둘 다 빨간색), 대기 10~20초
"""

import asyncio
import json
import os
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands
# ── 파일 상단 import 영역에 추가 ──
from utils.cooldown_lock import acquire_lock, release_lock, build_locked_embed


# ──────────────────────────────────────────────────────────────────
#  config 로딩
# ──────────────────────────────────────────────────────────────────
import config as _cfg

DATA_DIR = _cfg.DATA_DIR
USERS_DIR = _cfg.USERS_DIR
CATS_FILE = _cfg.CATS_FILE

COLOR_DEFAULT = _cfg.COLOR_DEFAULT
COLOR_SUCCESS = _cfg.COLOR_SUCCESS
COLOR_ERROR = _cfg.COLOR_ERROR
COLOR_WARNING = _cfg.COLOR_WARNING

RARITY_TIERS = _cfg.RARITY_TIERS
MAX_LEVEL = _cfg.MAX_LEVEL
SKILL_EFFECTS = _cfg.SKILL_EFFECTS
DAILY_LIMITS = _cfg.DAILY_LIMITS

ANTICHEAT_REACTION_WINDOW_MS = _cfg.ANTICHEAT_REACTION_WINDOW_MS
ANTICHEAT_REACTION_CONSECUTIVE = _cfg.ANTICHEAT_REACTION_CONSECUTIVE
ANTICHEAT_MAX_WARNINGS = _cfg.ANTICHEAT_MAX_WARNINGS
ANTICHEAT_WARNING_DECAY_DAYS = _cfg.ANTICHEAT_WARNING_DECAY_DAYS

NEWBIE_PROTECTION_DAYS = _cfg.NEWBIE_PROTECTION_DAYS
CATCHUP_EXP_BONUS_MAX = _cfg.CATCHUP_EXP_BONUS_MAX

KIDNAP_BASE_COOLDOWN = _cfg.KIDNAP_BASE_COOLDOWN
KIDNAP_MIN_COOLDOWN = _cfg.KIDNAP_MIN_COOLDOWN
KIDNAP_BASE_SUCCESS_RATE = _cfg.KIDNAP_BASE_SUCCESS_RATE
KIDNAP_MAX_SUCCESS_RATE = _cfg.KIDNAP_MAX_SUCCESS_RATE
KIDNAP_MIN_SUCCESS_RATE = _cfg.KIDNAP_MIN_SUCCESS_RATE
KIDNAP_BASE_MONEY_REWARD = _cfg.KIDNAP_BASE_MONEY_REWARD

_raw_hard_cap = getattr(_cfg, "KIDNAP_HARD_CAP", 85)
KIDNAP_HARD_CAP = _raw_hard_cap if _raw_hard_cap > 1 else _raw_hard_cap * 100

REACTION_PERFECT_MS = _cfg.REACTION_PERFECT_MS
REACTION_GREAT_MS = _cfg.REACTION_GREAT_MS
REACTION_GOOD_MS = _cfg.REACTION_GOOD_MS
REACTION_TIMEOUT_MS = _cfg.REACTION_TIMEOUT_MS
REACTION_PERFECT_BONUS = _cfg.REACTION_PERFECT_BONUS
REACTION_GREAT_BONUS = _cfg.REACTION_GREAT_BONUS
REACTION_GOOD_BONUS = _cfg.REACTION_GOOD_BONUS
REACTION_TIMEOUT_PENALTY = _cfg.REACTION_TIMEOUT_PENALTY

KIDNAP_SEARCHING_MESSAGES = _cfg.KIDNAP_SEARCHING_MESSAGES
KIDNAP_ACTIVATE_MESSAGES = _cfg.KIDNAP_ACTIVATE_MESSAGES
KIDNAP_FAKE_MESSAGES = _cfg.KIDNAP_FAKE_MESSAGES
KIDNAP_FAKE_BUTTON_LABELS = _cfg.KIDNAP_FAKE_BUTTON_LABELS
KIDNAP_REAL_BUTTON_LABELS = _cfg.KIDNAP_REAL_BUTTON_LABELS

MONEY_SOFT_CAP_PER_LEVEL = _cfg.MONEY_SOFT_CAP_PER_LEVEL
MONEY_SOFT_CAP_BASE = getattr(_cfg, "MONEY_SOFT_CAP_BASE", 50000)

ACHIEVEMENTS = _cfg.ACHIEVEMENTS
TUTORIAL_STEPS = _cfg.TUTORIAL_STEPS

BOT_ICON_URL = _cfg.BOT_ICON_URL
SEPARATOR = getattr(_cfg, "SEPARATOR", _cfg.EMBED_THIN_SEPARATOR)
RARITY_ORDER = getattr(_cfg, "RARITY_ORDER", ["common", "uncommon", "rare", "epic", "legendary", "mythic"])
FOOTER_TEXT = getattr(_cfg, "EMBED_FOOTER_TEXT", "카요코 봇")

# 상단 import 교체
try:
    from models.equipment import get_total_equipment_stats
except ImportError:
    def get_total_equipment_stats(user_data):
        return {"attack": 0, "hp_bonus": 0, "defense": 0}


def get_equipment_stats(uid_or_udata):
    """하위 호환 래퍼"""
    if isinstance(uid_or_udata, dict):
        return get_total_equipment_stats(uid_or_udata)
    udata = load_user(uid_or_udata)
    if udata is None:
        return {"attack": 0, "hp_bonus": 0, "defense": 0}
    return get_total_equipment_stats(udata)


# ──────────────────────────────────────────────────────────────────
#  ★ 밸런스 캡 상수 (효과 최대치 제한)
# ──────────────────────────────────────────────────────────────────

# 성공확률 절대 상한 (%) — config의 KIDNAP_HARD_CAP과 동일하게 85%
MAX_SUCCESS_RATE_CAP = 85.0

# 스킬 효과 상한
MAX_SKILL_SUCCESS_BONUS = 15.0       # 추적 스킬 성공률 보너스 최대 +15%
MAX_SKILL_RARE_BONUS_PCT = 50.0      # 추적 스킬 희귀 등장률 배율 최대 +50%
MAX_TRADE_SELL_BONUS_PCT = 40.0      # 상술 판매가 보너스 최대 +40%

# 장비 효과 상한
MAX_EQUIP_KIDNAP_BONUS = 10.0        # 장비 납치 성공률 보너스 최대 +10%
MAX_EQUIP_RARE_BONUS = 8.0           # 장비 희귀 등장 보너스 최대 +8%

# 반응속도 보너스 상한
MAX_REACTION_BONUS = 15.0            # 반응속도 보너스 최대 +15%

# 보상 배율 상한
MAX_MONEY_MULTIPLIER = 3.0           # 골드 보상 배율 최대 x3
MAX_EXP_MULTIPLIER = 2.5             # EXP 보상 배율 최대 x2.5

# 쿨다운 하한 (초)
MIN_COOLDOWN_FLOOR = 5.0             # 쿨다운 절대 하한 5초

# ──────────────────────────────────────────────────────────────────
#  상수 & 헬퍼
# ──────────────────────────────────────────────────────────────────

RARITY_EMOJI = {
    "common": "⬜", "uncommon": "🟩", "rare": "🟦",
    "epic": "🟪", "legendary": "🟨", "mythic": "🟥",
}


def _safe_rarity_str(raw):
    if isinstance(raw, str) and raw.lower() in RARITY_TIERS:
        return raw.lower()
    if isinstance(raw, str):
        return raw.lower()
    if isinstance(raw, (int, float)):
        val = float(raw)
        for key in ["mythic", "legendary", "epic", "rare", "uncommon", "common"]:
            tier = RARITY_TIERS.get(key, {})
            if val <= tier.get("min_rarity", 999):
                return key
        return "common"
    return "common"


def _rarity_color(rarity):
    return RARITY_TIERS.get(rarity, {}).get("color", COLOR_DEFAULT)


def _ensure_cat_dict(cat) -> dict:
    if isinstance(cat, dict):
        # ★ "id" 키가 없으면 "name"을 ID로 사용
        if "id" not in cat and "name" in cat:
            cat["id"] = cat["name"]
        return cat
    if isinstance(cat, str):
        return {"id": cat, "name": cat, "rarity": "common"}
    if isinstance(cat, (list, tuple)) and len(cat) >= 2:
        return {"id": str(cat[0]), "name": str(cat[1]), "rarity": "common"}
    return {"id": "unknown", "name": "미지의 냥이", "rarity": "common"}


def is_registered(uid) -> bool:
    """유저 JSON 파일이 존재하는지 확인"""
    return os.path.exists(os.path.join(USERS_DIR, f"{uid}.json"))


# ─── 파일 I/O ─────────────────────────────────────────────────────

def _user_path(uid):
    return os.path.join(USERS_DIR, f"{uid}.json")


def load_user(uid):
    """등록된 유저만 로드. 미등록이면 None 반환."""
    p = _user_path(uid)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_user(uid, data):
    os.makedirs(USERS_DIR, exist_ok=True)
    with open(_user_path(uid), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _default_user(uid):
    """신규 가입(/시작) 전용. kidnap 내부에서는 호출하지 않음."""
    return {
        "user_id": uid,
        "level": 1, "exp": 0, "money": 0,
        "skills": {"tracking": 0, "combat": 0, "trade": 0},
        "cats": {}, "catdex": {},
        "equipped": {"weapon": None, "tool": None, "accessory": None},
        "inventory": {"weapons": [], "tools": [], "accessories": []},
        "daily_actions": {"date": ""},
        "achievements": {},
        "tutorial_step": "welcome",
        "created_at": datetime.utcnow().isoformat(),
        "anticheat": {"reactions": [], "warnings": 0, "last_warning": None},
        "stats": {"total_kidnaps": 0, "successful_kidnaps": 0, "cats_caught": {}},
    }


def load_cats():
    try:
        with open(CATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    if isinstance(data, dict):
        # ★ dict 내부 항목에도 id 보정
        for k, v in data.items():
            if isinstance(v, dict) and "id" not in v:
                v["id"] = v.get("name", k)
        return data

    if isinstance(data, list):
        result = {}
        for i, cat in enumerate(data):
            if isinstance(cat, dict):
                # ★ "name"을 키(ID)로 사용 (기존: 인덱스 번호)
                cid = cat.get("name", str(i))
                cat["id"] = cid
                result[cid] = cat
            elif isinstance(cat, str):
                result[cat] = {"id": cat, "name": cat, "rarity": "common"}
        return result

    return {}

# ─── 레벨 / 경험치 ───────────────────────────────────────────────

def exp_required(level):
    return _cfg.get_exp_for_level(level)


def grant_exp(udata, amount):
    created = udata.get("created_at")
    if created:
        try:
            age = (datetime.utcnow() - datetime.fromisoformat(created)).days
        except (ValueError, TypeError):
            age = 999
        if age <= NEWBIE_PROTECTION_DAYS:
            ratio = 1.0 - (age / NEWBIE_PROTECTION_DAYS)
            bonus = ratio * CATCHUP_EXP_BONUS_MAX
            # ★ EXP 배율 캡 적용
            effective_mult = min(1.0 + bonus, MAX_EXP_MULTIPLIER)
            amount = int(amount * effective_mult)

    udata["exp"] = udata.get("exp", 0) + amount
    leveled = False
    while udata.get("level", 1) < MAX_LEVEL:
        needed = exp_required(udata["level"])
        if udata["exp"] >= needed:
            udata["exp"] -= needed
            udata["level"] += 1
            # ★ 레벨업 시 스킬 포인트 지급
            udata["skill_points"] = udata.get("skill_points", 0) + _cfg.SKILL_POINTS_PER_LEVEL
            leveled = True
        else:
            break
    return amount, leveled


# ─── 일일 한도 ────────────────────────────────────────────────────

# ─── 일일 한도 ────────────────────────────────────────────────────

def _check_daily(udata, action):
    today = time.strftime("%Y-%m-%d")
    daily = udata.setdefault("daily_actions", {})

    # ★ "date" 키와 "daily_counts_date" 키 모두 호환 처리
    stored_date = daily.get("date") or udata.get("daily_counts_date", "")

    if stored_date != today:
        # 날짜 변경 → 카운트 초기화 (date 키 포함)
        udata["daily_actions"] = {"date": today}
        udata["daily_counts_date"] = today
        # daily_counts도 동기화 초기화
        udata["daily_counts"] = {k: 0 for k in DAILY_LIMITS}
        daily = udata["daily_actions"]
    else:
        # date 키가 없었던 기존 데이터 보정
        if "date" not in daily:
            daily["date"] = today

    count = daily.get(action, 0)
    limit = DAILY_LIMITS.get(action, 999)
    return count < limit, count, limit


def _increment_daily(udata, action):
    daily = udata.setdefault("daily_actions", {})
    daily[action] = daily.get(action, 0) + 1
    # ★ daily_counts도 동기화
    dc = udata.setdefault("daily_counts", {})
    dc[action] = dc.get(action, 0) + 1

# ─── 안티치트 (v2 — systems/anticheat.py 위임) ──────────────

def _anticheat_check(udata, reaction_ms):
    """
    반응속도 기반 안티치트 검사.
    systems/anticheat.py의 복합 분석 함수를 호출합니다.
    
    반환: (통과 여부, 메시지)
    """
    try:
        from systems.anticheat import check_reaction_for_kidnap
        return check_reaction_for_kidnap(udata, reaction_ms)
    except ImportError:
        # anticheat 모듈 로드 실패 시 통과 처리
        return True, ""


# ─── 냥이 선택 ────────────────────────────────────────────────────

def select_kidnap_cat(udata, region=None):
    all_cats = load_cats()
    if not all_cats:
        return {"id": "unknown", "name": "미지의 냥이", "rarity": "common"}

    pool = [_ensure_cat_dict(c) for c in all_cats.values()]

    if not pool:
        return {"id": "unknown", "name": "미지의 냥이", "rarity": "common"}

    # ★ "region" (단수) 필드로 필터링 (기존: "regions" 복수)
    if region:
        region_pool = [c for c in pool if c.get("region") == region]
        if region_pool:
            pool = region_pool

    tracking_lv = udata.get("skills", {}).get("tracking", 0)
    raw_rare_bonus = tracking_lv * SKILL_EFFECTS.get("tracking", {}).get("rare_chance_bonus", 0.25)
    # ★ 희귀 등장률 보너스 캡 적용
    rare_bonus = min(raw_rare_bonus, MAX_SKILL_RARE_BONUS_PCT) / 100.0

    base_weights = {"common": 60, "uncommon": 25, "rare": 10, "epic": 4, "legendary": 0.8, "mythic": 0.2}
    weights = []
    for cat in pool:
        rarity = _safe_rarity_str(cat.get("rarity", "common"))
        w = base_weights.get(rarity, 1.0)
        rarity_idx = RARITY_ORDER.index(rarity) if rarity in RARITY_ORDER else 0
        if rarity_idx >= 2:
            w *= (1.0 + rare_bonus * (rarity_idx - 1))
        weights.append(w)

    chosen = random.choices(pool, weights=weights, k=1)[0]
    chosen = dict(chosen)
    chosen["rarity"] = _safe_rarity_str(chosen.get("rarity", "common"))
    # ★ "name"을 ID로 사용
    chosen.setdefault("id", chosen.get("name", "unknown"))
    chosen.setdefault("name", chosen["id"])

    return chosen


# ─── 보상 계산 ────────────────────────────────────────────────────

def calculate_kidnap_rewards(udata, cat, reaction_ms):
    cat = _ensure_cat_dict(cat)
    rarity = _safe_rarity_str(cat.get("rarity", "common"))
    tier = RARITY_TIERS.get(rarity, RARITY_TIERS.get("common", {}))

    sell_range = tier.get("sell_price_range", (300, 1000))
    base_money = random.randint(sell_range[0], sell_range[1])

    trade_lv = udata.get("skills", {}).get("trade", 0)
    raw_trade_bonus = trade_lv * SKILL_EFFECTS.get("trade", {}).get("sell_price_bonus", 2.5)
    # ★ 상술 판매가 보너스 캡 적용
    trade_bonus_pct = min(raw_trade_bonus, MAX_TRADE_SELL_BONUS_PCT) / 100.0
    money = int(base_money * (1.0 + trade_bonus_pct))

    # ★ 골드 보상 배율 캡 적용
    money = min(money, int(base_money * MAX_MONEY_MULTIPLIER))

    level = udata.get("level", 1)
    soft_cap = MONEY_SOFT_CAP_BASE + level * MONEY_SOFT_CAP_PER_LEVEL
    current_money = udata.get("money", 0)
    if current_money > soft_cap:
        money = int(money * 0.5)
    money = max(money, KIDNAP_BASE_MONEY_REWARD)

    catch_exp = tier.get("catch_exp", 5)
    if reaction_ms <= REACTION_PERFECT_MS:
        speed_mult = 1.5
    elif reaction_ms <= REACTION_GREAT_MS:
        speed_mult = 1.3
    elif reaction_ms <= REACTION_GOOD_MS:
        speed_mult = 1.1
    else:
        speed_mult = 1.0
    # ★ EXP 배율 캡 적용
    speed_mult = min(speed_mult, MAX_EXP_MULTIPLIER)
    exp = int(catch_exp * speed_mult)

    parts = []
    if trade_bonus_pct > 0:
        parts.append(f"거래 스킬 +{trade_bonus_pct*100:.1f}%")
    if speed_mult > 1.0:
        parts.append(f"반응속도 ×{speed_mult}")
    bonus_desc = " | ".join(parts) if parts else "없음"

    return {"money": money, "exp": exp, "bonus_desc": bonus_desc}


# ─── 성공률 ───────────────────────────────────────────────────────

def calculate_success_rate(udata, reaction_ms):
    base = KIDNAP_BASE_SUCCESS_RATE

    tracking_lv = udata.get("skills", {}).get("tracking", 0)
    raw_skill_bonus = tracking_lv * SKILL_EFFECTS.get("tracking", {}).get("kidnap_success_bonus", 0.4)
    # ★ 스킬 성공률 보너스 캡 적용
    skill_bonus = min(raw_skill_bonus, MAX_SKILL_SUCCESS_BONUS)

    # ★ 변경: udata 직접 전달
    eq_stats = get_total_equipment_stats(udata)
    raw_equip_bonus = eq_stats.get("kidnap_bonus", 0) * 0.5
    # ★ 장비 납치 보너스 캡 적용
    equip_bonus = min(raw_equip_bonus, MAX_EQUIP_KIDNAP_BONUS)

    if reaction_ms <= REACTION_PERFECT_MS:
        reaction_bonus = REACTION_PERFECT_BONUS
    elif reaction_ms <= REACTION_GREAT_MS:
        reaction_bonus = REACTION_GREAT_BONUS
    elif reaction_ms <= REACTION_GOOD_MS:
        reaction_bonus = REACTION_GOOD_BONUS
    elif reaction_ms >= REACTION_TIMEOUT_MS:
        reaction_bonus = REACTION_TIMEOUT_PENALTY
    else:
        reaction_bonus = 0.0

    # ★ 반응속도 보너스 캡 적용 (마이너스는 제한 없음)
    if reaction_bonus > 0:
        reaction_bonus = min(reaction_bonus, MAX_REACTION_BONUS)

    total_pct = base + skill_bonus + equip_bonus + reaction_bonus
    total_pct = max(total_pct, KIDNAP_MIN_SUCCESS_RATE)
    # ★ 절대 상한 적용 (85%)
    total_pct = min(total_pct, MAX_SUCCESS_RATE_CAP)

    desc_parts = [f"기본 {base:.0f}%"]
    if skill_bonus > 0:
        desc_parts.append(f"스킬 +{skill_bonus:.1f}%")
    if equip_bonus > 0:
        desc_parts.append(f"장비 +{equip_bonus:.1f}%")
    if reaction_bonus != 0:
        sign = "+" if reaction_bonus > 0 else ""
        desc_parts.append(f"반응 {sign}{reaction_bonus:.1f}%")
    desc_parts.append(f"→ **{total_pct:.1f}%**")

    return total_pct / 100.0, " | ".join(desc_parts)


# ─── 냥이 등록 ────────────────────────────────────────────────────

def _normalize_cats_dict(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        converted = {}
        for c in raw:
            if isinstance(c, dict):
                # ★ "name"을 키로 사용
                cid = str(c.get("id", c.get("name", "unknown")))
                if cid in converted:
                    converted[cid]["count"] = converted[cid].get("count", 0) + 1
                else:
                    converted[cid] = {
                        "name": c.get("name", cid),
                        "rarity": str(_safe_rarity_str(c.get("rarity", "common"))),
                        "count": c.get("count", 1),
                        "first_caught": c.get("first_caught", datetime.utcnow().isoformat()),
                    }
            elif isinstance(c, str):
                if c not in converted:
                    converted[c] = {
                        "name": c, "rarity": "common", "count": 1,
                        "first_caught": datetime.utcnow().isoformat(),
                    }
                else:
                    converted[c]["count"] = converted[c].get("count", 0) + 1
        return converted
    return {}


def register_caught_cat(udata, cat):
    cat = _ensure_cat_dict(cat)

    # ★ "name"을 ID로 사용 (기존: "id" → "unknown")
    cat_id = str(cat.get("id", cat.get("name", "unknown")))
    rarity = _safe_rarity_str(cat.get("rarity", "common"))
    name = cat.get("name", cat_id)

    udata["cats"] = _normalize_cats_dict(udata.get("cats", {}))
    udata["catdex"] = _normalize_cats_dict(udata.get("catdex", {}))

    cats = udata["cats"]
    catdex = udata["catdex"]
    stats = udata.setdefault("stats", {})

    is_new = cat_id not in catdex

    if cat_id in cats:
        cats[cat_id]["count"] = cats[cat_id].get("count", 0) + 1
    else:
        cats[cat_id] = {
            "name": name, "rarity": str(rarity), "count": 1,
            "first_caught": datetime.utcnow().isoformat(),
        }

    if is_new:
        catdex[cat_id] = {
            "name": name, "rarity": str(rarity),
            "first_caught": datetime.utcnow().isoformat(),
        }

    stats["successful_kidnaps"] = stats.get("successful_kidnaps", 0) + 1
    caught_dict = stats.setdefault("cats_caught", {})
    caught_dict[rarity] = caught_dict.get(rarity, 0) + 1

    return is_new


# ─── 업적 ─────────────────────────────────────────────────────────

def check_achievements(udata):
    # ── 방어 코드: achievements 타입 통일 (dict 기준) ──
    raw = udata.get("achievements", {})
    
    # 리스트인 경우 → 딕셔너리로 변환
    if isinstance(raw, list):
        converted = {}
        for item in raw:
            if isinstance(item, str):
                converted[item] = {"achieved_at": datetime.utcnow().isoformat()}
            elif isinstance(item, dict) and "id" in item:
                converted[item["id"]] = item
        udata["achievements"] = converted
        raw = converted
    
    if not isinstance(raw, dict):
        raw = {}
        udata["achievements"] = raw

    earned = raw  # 이제 항상 딕셔너리

    new_achievements = []
    stats = udata.get("stats", {})
    catdex = udata.get("catdex", {})
    species_count = len(catdex) if isinstance(catdex, dict) else 0
    level = udata.get("level", 1)
    money = udata.get("money", 0)

    checks = {
        "first_catch": stats.get("successful_kidnaps", 0) >= 1,
        "collector_10": species_count >= 10,
        "collector_25": species_count >= 25,
        "collector_all": species_count >= 43,
        "battle_10": stats.get("battle_wins", 0) >= 10,
        "battle_100": stats.get("battle_wins", 0) >= 100,
        "labyrinth_10": stats.get("labyrinth_max_floor", 0) >= 10,
        "labyrinth_30": stats.get("labyrinth_max_floor", 0) >= 30,
        "labyrinth_50": stats.get("labyrinth_max_floor", 0) >= 50,
        "level_10": level >= 10,
        "level_25": level >= 25,
        "level_50": level >= 50,
        "level_70": level >= 70,
        "weekly_boss_first": stats.get("weekly_boss_first_kill", False),
        "rich_100k": money >= 100000,
        "rich_1m": money >= 1000000,
    }

    for ach_id, met in checks.items():
        if met and ach_id not in earned and ach_id in ACHIEVEMENTS:
            # ★ 딕셔너리 형태로 저장 (models/user.py와 동일한 포맷)
            earned[ach_id] = {"achieved_at": datetime.utcnow().isoformat()}
            new_achievements.append({"id": ach_id, **ACHIEVEMENTS[ach_id]})

    return new_achievements


# ─── 튜토리얼 ────────────────────────────────────────────────────

def advance_tutorial(udata, completed_step):
    current = udata.get("tutorial_step", "welcome")
    step_data = TUTORIAL_STEPS.get(current)
    if not step_data:
        return None
    if current != completed_step:
        return None

    reward_money = step_data.get("reward_money", 0)
    reward_exp = step_data.get("reward_exp", 0)
    if reward_money:
        udata["money"] = udata.get("money", 0) + reward_money
    if reward_exp:
        grant_exp(udata, reward_exp)

    next_step = step_data.get("next")
    udata["tutorial_step"] = next_step if next_step else "complete"
    return udata["tutorial_step"]


# ─── 쿨다운 ──────────────────────────────────────────────────────

def get_cooldown(udata):
    tracking_lv = udata.get("skills", {}).get("tracking", 0)
    reduction = tracking_lv * 0.3
    cd = KIDNAP_BASE_COOLDOWN - reduction
    # ★ 쿨다운 절대 하한 적용
    return max(cd, max(KIDNAP_MIN_COOLDOWN, MIN_COOLDOWN_FLOOR))

# ──────────────────────────────────────────────────────────────────
#  임베드
# ──────────────────────────────────────────────────────────────────

def build_search_embed(user, region=None):
    msg = random.choice(KIDNAP_SEARCHING_MESSAGES)
    embed = discord.Embed(
        title="🔍 냥이 탐색 중...",
        description=msg,
        color=COLOR_DEFAULT,
    )
    if region:
        embed.add_field(name="📍 지역", value=region, inline=True)
    embed.set_footer(
        text=f"{user.display_name} | {FOOTER_TEXT}",
        icon_url=user.display_avatar.url,
    )
    return embed


def build_found_embed(user, cat):
    cat = _ensure_cat_dict(cat)
    rarity = _safe_rarity_str(cat.get("rarity", "common"))
    tier = RARITY_TIERS.get(rarity, {})
    r_emoji = tier.get("emoji", "⬜")
    r_name = tier.get("name", rarity)
    r_color = tier.get("color", COLOR_DEFAULT)
    activation_msg = random.choice(KIDNAP_ACTIVATE_MESSAGES)

    embed = discord.Embed(
        title="🐱 야생의 냥이 발견!",
        description=(
            f"{r_emoji} **{cat.get('name', '???')}** ({r_name})\n\n"
            f"{activation_msg}\n\n"
            f"⚠️ **올바른 버튼을 눌러 납치하세요!**\n"
            f"함정 버튼을 누르면 실패합니다!"
        ),
        color=r_color,
    )
    if cat.get("image_url"):
        embed.set_thumbnail(url=cat["image_url"])
    embed.set_footer(
        text=f"{user.display_name} | 제한시간 20초",
        icon_url=user.display_avatar.url,
    )
    return embed


def build_success_embed(user, cat, rewards, rate_desc, reaction_ms, is_new, new_achs, leveled, new_level):
    cat = _ensure_cat_dict(cat)
    rarity = _safe_rarity_str(cat.get("rarity", "common"))
    tier = RARITY_TIERS.get(rarity, {})
    r_emoji = tier.get("emoji", "⬜")
    r_name = tier.get("name", rarity)
    r_color = tier.get("color", COLOR_SUCCESS)

    if reaction_ms <= REACTION_PERFECT_MS:
        speed_grade = "⚡ PERFECT!"
    elif reaction_ms <= REACTION_GREAT_MS:
        speed_grade = "🔥 GREAT!"
    elif reaction_ms <= REACTION_GOOD_MS:
        speed_grade = "👍 GOOD"
    else:
        speed_grade = "🐢 SLOW"

    embed = discord.Embed(
        title="✅ 납치 성공!",
        description=(
            f"{r_emoji} **{cat.get('name', '???')}** ({r_name})을(를) 잡았습니다!\n"
            f"{SEPARATOR}"
        ),
        color=r_color,
    )
    embed.add_field(
        name="💰 보상",
        value=f"돈: **+{rewards['money']:,}원**\nEXP: **+{rewards['exp']}**",
        inline=True,
    )
    embed.add_field(
        name="⏱️ 반응 속도",
        value=f"**{reaction_ms:.0f}ms** {speed_grade}",
        inline=True,
    )
    embed.add_field(name="📊 성공률", value=rate_desc, inline=False)

    if rewards.get("bonus_desc") and rewards["bonus_desc"] != "없음":
        embed.add_field(name="🎁 보너스", value=rewards["bonus_desc"], inline=False)
    if is_new:
        embed.add_field(
            name="📖 새로운 도감 등록!",
            value=f"**{cat.get('name', '???')}** 도감에 추가!",
            inline=False,
        )
    if leveled:
        embed.add_field(
            name="🎉 레벨 업!",
            value=f"**Lv.{new_level}** 달성!",
            inline=False,
        )
    if new_achs:
        ach_lines = [f"🏆 **{a.get('name', '?')}** — {a.get('desc', '')}" for a in new_achs]
        embed.add_field(name="🏆 업적 달성!", value="\n".join(ach_lines), inline=False)
    if tier.get("announcement", False):
        embed.add_field(
            name="📢",
            value="희귀 냥이 포획! 서버에 알림이 전송됩니다.",
            inline=False,
        )

    embed.set_footer(
        text=f"{user.display_name} | {FOOTER_TEXT}",
        icon_url=user.display_avatar.url,
    )
    return embed


def build_fail_embed(user, cat, rate_desc, reaction_ms):
    cat = _ensure_cat_dict(cat)
    rarity = _safe_rarity_str(cat.get("rarity", "common"))
    tier = RARITY_TIERS.get(rarity, {})
    r_emoji = tier.get("emoji", "⬜")
    r_name = tier.get("name", rarity)

    if reaction_ms <= REACTION_PERFECT_MS:
        speed_grade = "⚡ PERFECT!"
    elif reaction_ms <= REACTION_GREAT_MS:
        speed_grade = "🔥 GREAT!"
    elif reaction_ms <= REACTION_GOOD_MS:
        speed_grade = "👍 GOOD"
    else:
        speed_grade = "🐢 SLOW"

    embed = discord.Embed(
        title="❌ 납치 실패...",
        description=(
            f"{r_emoji} **{cat.get('name', '???')}** ({r_name})이(가) 도망갔습니다!\n"
            f"{SEPARATOR}\n"
            f"⏱️ 반응 속도: **{reaction_ms:.0f}ms** {speed_grade}\n"
            f"📊 성공률: {rate_desc}"
        ),
        color=COLOR_ERROR,
    )
    embed.set_footer(
        text=f"{user.display_name} | {FOOTER_TEXT}",
        icon_url=user.display_avatar.url,
    )
    return embed


def build_fake_embed(user):
    fake_msg = random.choice(KIDNAP_FAKE_MESSAGES)
    embed = discord.Embed(
        title="💥 함정이었다!",
        description=f"{fake_msg}\n\n냥이가 도망갔습니다...",
        color=COLOR_WARNING,
    )
    embed.set_footer(
        text=f"{user.display_name} | {FOOTER_TEXT}",
        icon_url=user.display_avatar.url,
    )
    return embed


def build_timeout_embed(user):
    embed = discord.Embed(
        title="⏰ 시간 초과!",
        description="너무 늦었습니다... 냥이가 도망갔습니다.",
        color=COLOR_ERROR,
    )
    try:
        embed.set_footer(
            text=f"{user.display_name}",
            icon_url=user.display_avatar.url,
        )
    except AttributeError:
        pass
    return embed


def build_cooldown_embed(user, remaining):
    embed = discord.Embed(
        title="⏳ 쿨다운",
        description=f"납치 쿨다운 중입니다. **{remaining:.1f}초** 후 다시 시도하세요.",
        color=COLOR_WARNING,
    )
    embed.set_footer(
        text=f"{user.display_name}",
        icon_url=user.display_avatar.url,
    )
    return embed


def get_kidnap_stats_embed(user, udata):
    stats = udata.get("stats", {})
    total = stats.get("total_kidnaps", 0)
    success = stats.get("successful_kidnaps", 0)
    rate = (success / total * 100) if total > 0 else 0
    cats_caught = stats.get("cats_caught", {})

    embed = discord.Embed(
        title=f"📊 {user.display_name}의 납치 통계",
        color=COLOR_DEFAULT,
    )
    embed.add_field(
        name="📈 전체 기록",
        value=(
            f"총 시도: **{total}회**\n"
            f"성공: **{success}회**\n"
            f"성공률: **{rate:.1f}%**"
        ),
        inline=True,
    )

    rarity_lines = []
    for r in RARITY_ORDER:
        cnt = cats_caught.get(r, 0)
        if cnt > 0:
            tier = RARITY_TIERS.get(r, {})
            rarity_lines.append(f"{tier.get('emoji', '⬜')} {tier.get('name', r)}: **{cnt}마리**")
    if rarity_lines:
        embed.add_field(
            name="🐱 등급별 포획",
            value="\n".join(rarity_lines),
            inline=True,
        )

    cats_data = udata.get("cats", {})
    if isinstance(cats_data, dict):
        total_owned = sum(c.get("count", 0) if isinstance(c, dict) else 0 for c in cats_data.values())
    elif isinstance(cats_data, list):
        total_owned = len(cats_data)
    else:
        total_owned = 0

    catdex_data = udata.get("catdex", {})
    species_count = len(catdex_data) if isinstance(catdex_data, dict) else 0

    embed.add_field(
        name="📖 도감",
        value=f"등록 종: **{species_count}종** / 총 보유: **{total_owned}마리**",
        inline=False,
    )

    cd = get_cooldown(udata)
    _, count, limit = _check_daily(udata, "kidnap")
    embed.add_field(
        name="⚙️ 현재 설정",
        value=f"쿨다운: **{cd:.1f}초** | 오늘 사용: **{count}/{limit}회**",
        inline=False,
    )
    embed.set_footer(text=FOOTER_TEXT, icon_url=BOT_ICON_URL)
    return embed

# ──────────────────────────────────────────────────────────────────
#  버튼 뷰
# ──────────────────────────────────────────────────────────────────

class KidnapButtonView(discord.ui.View):

    def __init__(self, owner_id, cat, udata, timeout=20.0):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.cat = _ensure_cat_dict(cat)
        self.udata = udata
        self.pressed = False
        self.start_time = time.monotonic()
        self.message = None
        self.is_real = False
        self._switching = True

    @discord.ui.button(
        label="준비 중...",
        style=discord.ButtonStyle.danger,
        custom_id="kidnap_btn",
        disabled=True,
    )
    async def catch_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "다른 사람의 납치에 개입할 수 없습니다!", ephemeral=True
            )
            return

        if self.pressed:
            return
        self.pressed = True
        self._switching = False
        self.stop()

        if self.is_real:
            await self._handle_real(interaction)
        else:
            await self._handle_fake(interaction)

    async def start_switching(self):
        await asyncio.sleep(0.5)

        schedule = []
        num_switches = random.randint(4, 7)
        for i in range(num_switches):
            is_real = (i % 2 == 1)
            duration = random.uniform(1.2, 3.0)
            schedule.append((duration, is_real))

        if not schedule[-1][1]:
            schedule.append((random.uniform(1.5, 3.0), True))
        if schedule[0][1]:
            schedule.insert(0, (random.uniform(1.0, 2.0), False))

        for duration, is_real in schedule:
            if self.pressed or not self._switching:
                return

            self.is_real = is_real

            if is_real:
                label = random.choice(KIDNAP_REAL_BUTTON_LABELS)
                self.start_time = time.monotonic()
            else:
                label = random.choice(KIDNAP_FAKE_BUTTON_LABELS)

            self.catch_button.label = label
            self.catch_button.disabled = False

            try:
                if self.message:
                    await self.message.edit(view=self)
            except Exception:
                return

            await asyncio.sleep(duration)

        if not self.pressed:
            self.catch_button.label = "시간 초과!"
            self.catch_button.disabled = True
            self._switching = False
            try:
                if self.message:
                    await self.message.edit(view=self)
            except Exception:
                pass

    # ── 진짜 버튼 처리 ──
    async def _handle_real(self, interaction: discord.Interaction):
        reaction_ms = (time.monotonic() - self.start_time) * 1000

        udata = load_user(interaction.user.id)
        udata["user_id"] = interaction.user.id

        if udata is None:
            await interaction.response.edit_message(
                embed=discord.Embed(title="❌ 오류", description="유저 데이터를 찾을 수 없습니다.", color=COLOR_ERROR),
                view=None,
            )
            return

        # ★ 유저 이름 자동 갱신
        if udata.get("username") in (None, "", "Unknown"):
            udata["username"] = interaction.user.name
            udata["display_name"] = interaction.user.display_name

        cat = self.cat

        ac_pass, ac_msg = _anticheat_check(udata, reaction_ms)
        if not ac_pass:
            embed = discord.Embed(
                title="🚫 안티치트 감지",
                description=ac_msg,
                color=COLOR_ERROR,
            )
            save_user(interaction.user.id, udata)
            await interaction.response.edit_message(embed=embed, view=None)
            return

        rate, rate_desc = calculate_success_rate(udata, reaction_ms)
        if ac_msg:
            rate_desc += f"\n{ac_msg}"

        success = random.random() <= rate

        if success:
            rewards = calculate_kidnap_rewards(udata, cat, reaction_ms)
            is_new = register_caught_cat(udata, cat)

            udata["money"] = udata.get("money", 0) + rewards["money"]
            actual_exp, leveled = grant_exp(udata, rewards["exp"])

            _increment_daily(udata, "kidnap")
            stats = udata.setdefault("stats", {})
            stats["total_kidnaps"] = stats.get("total_kidnaps", 0) + 1

            new_achs = check_achievements(udata)
            for ach in new_achs:
                if ach.get("reward_money"):
                    udata["money"] += ach["reward_money"]
                if ach.get("reward_exp"):
                    grant_exp(udata, ach["reward_exp"])

            tut_result = advance_tutorial(udata, "first_kidnap")
            if leveled:
                advance_tutorial(udata, "level_up")

            # ★ level_up 단계인데 이미 레벨 조건 충족한 경우 자동 완료
            if udata.get("tutorial_step") == "level_up" and udata.get("level", 1) >= 2:
                advance_tutorial(udata, "level_up")
            
            if leveled:
                advance_tutorial(udata, "level_up")

            save_user(interaction.user.id, udata)

            embed = build_success_embed(
                interaction.user, cat, rewards, rate_desc,
                reaction_ms, is_new, new_achs, leveled, udata["level"],
            )

            if tut_result and tut_result != "first_kidnap":
                step_data = TUTORIAL_STEPS.get("first_kidnap", {})
                parts = []
                if step_data.get("reward_money"):
                    parts.append(f"💰 +{step_data['reward_money']:,}원")
                if step_data.get("reward_exp"):
                    parts.append(f"✨ +{step_data['reward_exp']} EXP")
                if parts:
                    embed.add_field(
                        name="📚 튜토리얼 보상!",
                        value=" | ".join(parts),
                        inline=False,
                    )

            rarity = _safe_rarity_str(cat.get("rarity", "common"))
            tier = RARITY_TIERS.get(rarity, {})
            if tier.get("announcement", False):
                try:
                    await _send_rare_catch_webhook(interaction, cat, rarity)
                except Exception:
                    pass
        else:
            _increment_daily(udata, "kidnap")
            stats = udata.setdefault("stats", {})
            stats["total_kidnaps"] = stats.get("total_kidnaps", 0) + 1
            save_user(interaction.user.id, udata)

            embed = build_fail_embed(interaction.user, cat, rate_desc, reaction_ms)

        await interaction.response.edit_message(embed=embed, view=None)

    # ── 페이크 버튼 처리 ──
    async def _handle_fake(self, interaction: discord.Interaction):
        udata = load_user(interaction.user.id)
        udata["user_id"] = interaction.user.id

        if udata is None:
            await interaction.response.edit_message(
                embed=discord.Embed(title="❌ 오류", description="유저 데이터를 찾을 수 없습니다.", color=COLOR_ERROR),
                view=None,
            )
            return

        _increment_daily(udata, "kidnap")
        stats = udata.setdefault("stats", {})
        stats["total_kidnaps"] = stats.get("total_kidnaps", 0) + 1
        save_user(interaction.user.id, udata)

        embed = build_fake_embed(interaction.user)
        await interaction.response.edit_message(embed=embed, view=None)

    # ── 타임아웃 ──
    async def on_timeout(self):
        if self.pressed:
            return
        self.pressed = True
        self._switching = False

        if self.message:
            try:
                udata = load_user(self.owner_id)
                if udata is not None:
                    _increment_daily(udata, "kidnap")
                    stats = udata.setdefault("stats", {})
                    stats["total_kidnaps"] = stats.get("total_kidnaps", 0) + 1
                    save_user(self.owner_id, udata)
            except Exception:
                pass

            try:
                u = self.message.interaction.user if self.message.interaction else None
                embed = build_timeout_embed(u or discord.Object(id=self.owner_id))
                await self.message.edit(embed=embed, view=None)
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────
#  희귀 냥이 웹훅 알림
# ──────────────────────────────────────────────────────────────────

async def _send_rare_catch_webhook(interaction, cat, rarity):
    import aiohttp

    webhook_url = getattr(_cfg, "RARE_CATCH_WEBHOOK_URL", None)
    if not webhook_url:
        return

    cat = _ensure_cat_dict(cat)
    tier = RARITY_TIERS.get(rarity, {})
    payload = {
        "embeds": [
            {
                "title": f"{tier.get('emoji', '⭐')} 희귀 냥이 포획!",
                "description": (
                    f"**{interaction.user.display_name}**님이 "
                    f"**{cat.get('name', '???')}** ({tier.get('name', rarity)})을(를) 포획했습니다!"
                ),
                "color": tier.get("color", COLOR_SUCCESS),
                "footer": {
                    "text": f"서버: {interaction.guild.name}" if interaction.guild else "DM"
                },
            }
        ],
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(webhook_url, json=payload) as resp:
            pass


# ──────────────────────────────────────────────────────────────────
#  메인 시퀀스
# ──────────────────────────────────────────────────────────────────

_cooldowns: Dict[int, float] = {}

def auto_check_tutorial(udata):
    """현재 튜토리얼 단계의 조건을 이미 충족했으면 자동으로 다음 단계로 넘김"""
    changed = False
    for _ in range(10):
        cur = udata.get("tutorial_step", "complete")
        if cur in ("complete", None) or udata.get("tutorial_completed", False):
            break
        should_advance = False
        if cur == "first_kidnap":
            if udata.get("stats", {}).get("successful_kidnaps", 0) >= 1:
                should_advance = True
        elif cur == "level_up":
            if udata.get("level", 1) >= 2:
                should_advance = True
        elif cur == "check_inventory":
            if len(udata.get("cats", udata.get("owned_cats", {}))) > 0:
                should_advance = True
        elif cur == "visit_shop":
            should_advance = True  # 상점 방문은 별도 트리거
        if should_advance:
            result = advance_tutorial(udata, cur)
            if result:
                changed = True
                continue
        break
    return changed


async def run_kidnap_sequence(interaction: discord.Interaction, region: str = None):
    uid = interaction.user.id

    # ── ★ 동시 실행 방지 ──
    if not acquire_lock(uid, "kidnap"):
        embed = build_locked_embed(uid)
        # 아직 defer 전이므로 response 사용
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)
        return

    try:
        # ── ★ 미등록 유저 차단 ──
        if not is_registered(uid):
            embed = discord.Embed(
                title="❌ 미등록 유저",
                description="등록된 유저가 아닙니다.\n`/가입` 명령어로 먼저 가입해주세요!",
                color=COLOR_ERROR,
            )
            embed.set_footer(text=FOOTER_TEXT, icon_url=BOT_ICON_URL)
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
            return

        udata = load_user(uid)
        if udata is None:
            embed = discord.Embed(
                title="❌ 데이터 오류",
                description="유저 데이터를 불러올 수 없습니다.\n관리자에게 문의해주세요.",
                color=COLOR_ERROR,
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # ★ 유저 이름 자동 갱신
        if udata.get("username") in (None, "", "Unknown"):
            udata["username"] = interaction.user.name
            udata["display_name"] = interaction.user.display_name
            save_user(uid, udata)

        # ★ 유저의 현재 지역 사용
        if region is None:
            region = udata.get("current_region", "alley")

        # ★ 튜토리얼 자동 완료 체크
        if auto_check_tutorial(udata):
            save_user(uid, udata)

        # ── 일일 한도 체크 ──
        allowed, count, limit = _check_daily(udata, "kidnap")
        if not allowed:
            embed = discord.Embed(
                title="⏰ 일일 납치 한도 초과",
                description=(
                    f"오늘의 납치 한도(**{limit}회**)를 모두 사용했습니다.\n"
                    f"현재: {count}/{limit}\n"
                    f"내일 다시 도전하세요!"
                ),
                color=COLOR_ERROR,
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # ── 쿨다운 체크 ──
        now = time.monotonic()
        cd = get_cooldown(udata)
        last = _cooldowns.get(uid, 0)
        remaining = cd - (now - last)
        if remaining > 0:
            embed = build_cooldown_embed(interaction.user, remaining)
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
            return

        _cooldowns[uid] = now

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ★ 여기서 defer → 이후 모든 응답은 followup
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if not interaction.response.is_done():
            await interaction.response.defer()

        # ── 지역명 표시용 ──
        from models.region import REGIONS
        region_display = REGIONS.get(region, {}).get("name", region)

        # ── 탐색 임베드 전송 (followup) ──
        search_embed = build_search_embed(interaction.user, region_display)
        msg = await interaction.followup.send(embed=search_embed, wait=True)

        # ── 탐색 대기 (10~20초) ──
        await asyncio.sleep(random.uniform(10.0, 20.0))

        # ── 냥이 선택 & 발견 임베드 ──
        cat = select_kidnap_cat(udata, region)
        found_embed = build_found_embed(interaction.user, cat)

        # ── 버튼 뷰 생성 ──
        view = KidnapButtonView(uid, cat, udata, timeout=20.0)
        await msg.edit(embed=found_embed, view=view)
        view.message = msg

        # ── 버튼 전환 루프 시작 ──
        asyncio.create_task(view.start_switching())

        # ── 버튼 뷰 종료 대기 ──
        await view.wait()

    finally:
        release_lock(uid)
