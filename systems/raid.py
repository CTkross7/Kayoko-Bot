# systems/raid.py
# ──────────────────────────────────────────────────────────
# 시즌 총력전 / 대결전 (전서버 공유 HP + 누적 딜 랭킹)
#
#  버스/무임승차 방지 설계:
#   · 계정 레벨 제한 (RAID_LEVEL_REQ)
#   · 딜은 **본인이 보유·강화한 냥이 로스터로만** 산정 → 남의 힘 못 씀
#   · 보상은 누적 딜 기여도(백분위) 기반 → 딜 0이면 보상 없음
#   · 일일 공격 횟수 제한
#
#  동시성: 전서버 공유 HP는 asyncio.Lock으로 직렬화(단일 프로세스 봇).
#  영속성: data/raid_boss.json 원자적 저장(재시작/에러에도 무손실).
# ──────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

import config as _cfg
from data_manager import load_json, save_json
from models.cat import get_cat_by_name
from models.element import calc_type_multiplier, defense_label, attack_label
from systems.enhancement import get_enhanced_stats

_lock = asyncio.Lock()

RAID_LEVEL_REQ = _cfg.RAID_LEVEL_REQ
DAILY = _cfg.RAID_DAILY_ATTEMPTS


# ═══════════════════════════════════════════════════════════
# 시즌 / 보스 상태
# ═══════════════════════════════════════════════════════════

def _current_season() -> int:
    days = (datetime.now(timezone.utc) - datetime(2024, 1, 1, tzinfo=timezone.utc)).days
    return days // _cfg.RAID_SEASON_DAYS


def _boss_for_season(season: int) -> dict:
    tpls = _cfg.RAID_BOSS_TEMPLATES
    return tpls[season % len(tpls)]


def _new_state(season: int) -> dict:
    b = _boss_for_season(season)
    # 시즌이 진행될수록 HP 완만 증가 (10시즌마다 순환하므로 라운드 반영)
    rounds = season // len(_cfg.RAID_BOSS_TEMPLATES)
    hp = int(b["base_hp"] * (1.0 + 0.15 * rounds))
    return {
        "season": season,
        "boss_key": b["key"], "name": b["name"],
        "defense_type": b["defense_type"], "attack_type": b["attack_type"],
        "terrain": b.get("terrain", ""),
        "max_hp": hp, "current_hp": hp,
        "participants": {},          # {uid: {"damage": n, "name": s}}
        "started_at": datetime.now(timezone.utc).isoformat(),
        "last_season": None,          # 직전 시즌 랭킹 스냅샷(보상 청구용)
    }


def _archive_ranking(state: dict) -> dict:
    parts = state.get("participants", {})
    ranking = sorted(
        [(uid, p.get("damage", 0), p.get("name", "?")) for uid, p in parts.items()],
        key=lambda x: -x[1],
    )
    return {"season": state.get("season"), "boss": state.get("name"),
            "total": len(ranking), "ranking": ranking}


def load_state() -> dict:
    """현재 시즌 보스 상태를 로드. 시즌 변경 시 롤오버(직전 랭킹 보관)."""
    season = _current_season()
    state = load_json(_cfg.RAID_STATE_FILE, None)
    if not isinstance(state, dict) or state.get("season") != season:
        prev_archive = _archive_ranking(state) if isinstance(state, dict) and state.get("participants") else None
        state = _new_state(season)
        state["last_season"] = prev_archive
        save_json(_cfg.RAID_STATE_FILE, state)
    return state


# ═══════════════════════════════════════════════════════════
# 딜 산정 (본인 로스터 기준 — 버스방지 핵심)
# ═══════════════════════════════════════════════════════════

def _regular_top_power(user_data: dict) -> int:
    cats = user_data.get("cats", {})
    powers = []
    if isinstance(cats, dict):
        for cid, info in cats.items():
            nm = info.get("name", cid) if isinstance(info, dict) else cid
            cd = get_cat_by_name(nm)
            if cd:
                powers.append(cd.get("base_power", 10))
    powers.sort(reverse=True)
    return sum(powers[:_cfg.RAID_TOP_ENHANCED_COUNT])


def compute_raid_damage(user_data: dict, state: dict) -> int:
    """
    본인 보유·강화 냥이 로스터로만 딜을 산정한다. (무임승차 불가)
    상위 강화 냥이 × 속성 상성 + 레벨 보정 + ±10% 변동.
    """
    d_type = state.get("defense_type", "none")
    enhanced = [i for i in user_data.get("enhanced_cats", []) if isinstance(i, dict)]
    stats = [get_enhanced_stats(i) for i in enhanced]
    stats.sort(key=lambda s: s["base_power"], reverse=True)
    top = stats[:_cfg.RAID_TOP_ENHANCED_COUNT]

    dmg = 0.0
    for s in top:
        mult = calc_type_multiplier(s["attack_type"], d_type)
        dmg += s["base_power"] * mult

    # 강화 냥이가 부족하면 일반 냥이가 소량만 기여 → 강화 육성 유도
    if len(top) < _cfg.RAID_TOP_ENHANCED_COUNT:
        dmg += _regular_top_power(user_data) * 0.25

    dmg *= (1 + user_data.get("level", 1) * 0.015)      # 레벨 보정
    dmg *= random.uniform(0.9, 1.1)                      # 변동
    return max(1, int(dmg * _cfg.RAID_DAMAGE_SCALE))


# ═══════════════════════════════════════════════════════════
# 공격
# ═══════════════════════════════════════════════════════════

def _today() -> str:
    return datetime.now(_cfg.KST).strftime("%Y-%m-%d")


async def attack(user_id: int, name: str, user_data: dict) -> dict:
    """
    총력전 공격. user_data(공격횟수/보상)와 전역 보스 상태를 갱신.
    반환 dict: {ok, msg, damage?, boss?, killed?, reward?}
    데이터 안전: 사전 체크 실패 시 user_data 무변경.
    """
    level = user_data.get("level", 1)
    if level < RAID_LEVEL_REQ:
        return {"ok": False, "msg": f"🔒 계정 레벨 **{RAID_LEVEL_REQ}** 이상만 참여할 수 있습니다. (현재 Lv.{level})"}

    # 일일 공격 횟수
    if user_data.get("raid_attempts_date") != _today():
        user_data["raid_attempts"] = 0
        user_data["raid_attempts_date"] = _today()
    if user_data.get("raid_attempts", 0) >= DAILY:
        return {"ok": False, "msg": f"오늘 총력전 공격을 모두 사용했습니다. ({DAILY}/{DAILY})"}

    # 본인 로스터 확인 (강화 냥이 없고 일반도 없으면 참여 불가 = 무임승차 차단)
    if not user_data.get("enhanced_cats") and not user_data.get("cats"):
        return {"ok": False, "msg": "냥이가 없어 참여할 수 없습니다. 냥이를 모으고 `/강화`하세요."}

    # ── 전역 공유 HP 갱신 (직렬화) ──
    async with _lock:
        state = load_state()
        if state["current_hp"] <= 0:
            return {"ok": False, "msg": f"이번 시즌 **{state['name']}**은(는) 이미 토벌되었습니다! 다음 시즌을 기다려주세요."}

        raw = compute_raid_damage(user_data, state)
        dealt = min(raw, state["current_hp"])
        state["current_hp"] -= dealt
        p = state["participants"].setdefault(str(user_id), {"damage": 0, "name": name})
        p["damage"] = p.get("damage", 0) + dealt
        p["name"] = name
        killed = state["current_hp"] <= 0
        save_json(_cfg.RAID_STATE_FILE, state)
        boss_snapshot = {k: state[k] for k in ("name", "max_hp", "current_hp", "defense_type", "attack_type", "terrain", "season")}
        my_total = p["damage"]

    # ── 즉시 보상 (기여도 비례 — 무임승차 방지) ──
    user_data["raid_attempts"] = user_data.get("raid_attempts", 0) + 1
    reward_money = 3000 + int(dealt * 0.02)
    reward_money = min(reward_money, 50000)
    user_data["money"] = user_data.get("money", 0) + reward_money

    return {
        "ok": True, "damage": dealt, "raw": raw, "killed": killed,
        "boss": boss_snapshot, "my_total": my_total, "reward_money": reward_money,
        "attempts_left": DAILY - user_data["raid_attempts"],
    }


# ═══════════════════════════════════════════════════════════
# 랭킹 / 조회
# ═══════════════════════════════════════════════════════════

def get_ranking(limit: int = 10) -> dict:
    state = load_state()
    parts = state.get("participants", {})
    ranking = sorted(
        [(uid, p.get("damage", 0), p.get("name", "?")) for uid, p in parts.items()],
        key=lambda x: -x[1],
    )
    return {
        "boss": state.get("name"), "season": state.get("season"),
        "max_hp": state.get("max_hp"), "current_hp": state.get("current_hp"),
        "defense_type": state.get("defense_type"), "attack_type": state.get("attack_type"),
        "terrain": state.get("terrain"),
        "total": len(ranking), "top": ranking[:limit], "ranking": ranking,
    }


def my_rank(user_id: int) -> dict | None:
    r = get_ranking(limit=0)
    for i, (uid, dmg, nm) in enumerate(r["ranking"]):
        if uid == str(user_id):
            pct = (i + 1) / max(1, r["total"])
            return {"rank": i + 1, "damage": dmg, "total": r["total"], "percentile": pct}
    return None


def rank_reward_for(percentile: float) -> dict:
    for tier in _cfg.RAID_RANK_REWARDS:
        if percentile <= tier["top"]:
            return tier
    return _cfg.RAID_RANK_REWARDS[-1]


# ═══════════════════════════════════════════════════════════
# 직전 시즌 보상 청구 (누적 딜 백분위)
# ═══════════════════════════════════════════════════════════

def claim_last_season(user_id: int, user_data: dict) -> tuple[bool, str]:
    """직전 시즌 랭킹 기준 백분위 보상 1회 지급."""
    state = load_state()
    arch = state.get("last_season")
    if not arch or not arch.get("ranking"):
        return False, "청구할 지난 시즌 보상이 없습니다."

    season = arch.get("season")
    if user_data.get("raid_claimed_season") == season:
        return False, "이미 지난 시즌 보상을 받았습니다."

    ranking = arch["ranking"]
    total = max(1, arch.get("total", len(ranking)))
    idx = next((i for i, (uid, d, n) in enumerate(ranking) if uid == str(user_id)), None)
    if idx is None:
        return False, "지난 시즌에 참여 기록이 없습니다."

    pct = (idx + 1) / total
    tier = rank_reward_for(pct)
    user_data["money"] = user_data.get("money", 0) + tier["money"]
    user_data["eligma"] = user_data.get("eligma", 0) + tier["eligma"]
    if tier.get("tuna_can"):
        user_data["tuna_can"] = user_data.get("tuna_can", 0) + tier["tuna_can"]
    user_data["raid_claimed_season"] = season

    return True, (f"🎁 지난 시즌 **{arch.get('boss')}** 보상 수령! ({tier['label']}, {idx+1}/{total}위)\n"
                  f"💰 {tier['money']:,}원 · {_cfg.ELIGMA_EMOJI} {tier['eligma']} · 🐟 {tier.get('tuna_can',0)}")
