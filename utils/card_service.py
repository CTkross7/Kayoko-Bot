# utils/card_service.py
# ──────────────────────────────────────────────────────────
# 카드 이미지 생성 서비스 (커맨드/상점 공용)
#
#  · 유저 스탯 수집 + 랭킹 계산 + 아바타 로드 + 커스터마이징 적용을
#    한 곳에 모아 여러 커맨드가 재사용
#  · 읽기 전용 — 유저 데이터를 변경/저장하지 않음
#  · 커스터마이징 미적용 시 렌더러 기본 테마 자동 사용
# ──────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import io
import os
from datetime import datetime

import discord

from config import (
    MAX_LEVEL, EXP_FOR_LEVEL, KST, USERS_DIR,
    SKILL_TREE_TRACKING, SKILL_TREE_COMBAT, SKILL_TREE_TRADE,
)
from data_manager import load_json
from systems.customization import get_customization
from utils.profile_card import render_profile_card, render_stat_card


# ═══════════════════════════════════════════════════════════
# 공용 헬퍼
# ═══════════════════════════════════════════════════════════

async def fetch_avatar_image(user):
    """디스코드 아바타를 PIL 이미지로. 실패 시 None(카드가 기본 원형 처리)."""
    try:
        import aiohttp
        from PIL import Image
        asset = user.display_avatar.replace(size=256, format="png")
        async with aiohttp.ClientSession() as sess:
            async with sess.get(asset.url) as resp:
                if resp.status == 200:
                    return Image.open(io.BytesIO(await resp.read()))
    except Exception:
        pass
    return None


def compute_ranks(my_money: int, my_level: int, my_exp: int = 0) -> dict:
    """전체 유저 1회 스캔으로 소지금·레벨 순위 계산 (읽기 전용)."""
    try:
        money_higher = 0
        level_higher = 0
        for fn in os.listdir(USERS_DIR):
            if not fn.endswith(".json"):
                continue
            d = load_json(os.path.join(USERS_DIR, fn), {})
            if not isinstance(d, dict):
                continue
            if d.get("money", 0) > my_money:
                money_higher += 1
            lv = d.get("level", 1)
            if lv > my_level or (lv == my_level and d.get("exp", 0) > my_exp):
                level_higher += 1
        return {"money_rank": f"{money_higher + 1:,}위", "level_rank": f"{level_higher + 1:,}위"}
    except Exception:
        return {"money_rank": "-", "level_rank": "-"}


def _count_cats(user_data) -> int:
    owned = user_data.get("cats", user_data.get("owned_cats", {}))
    total = 0
    if isinstance(owned, dict):
        for v in owned.values():
            total += v.get("count", 0) if isinstance(v, dict) else int(v or 0)
    return total


def _skill_lv(user_data, tree) -> int:
    s = user_data.get("skills", {})
    return s.get(tree, 0) if isinstance(s, dict) else 0


def gather_profile_data(user_data: dict, display_name: str) -> dict:
    """유저 데이터 → 프로필 카드용 dict (읽기 전용)."""
    level = user_data.get("level", 1)
    exp = user_data.get("exp", 0)
    next_exp = EXP_FOR_LEVEL(level)
    money = user_data.get("money", 0)

    catdex = user_data.get("catdex", {})
    catdex_count = len(catdex) if isinstance(catdex, (dict, list)) else 0

    battle_stats = user_data.get("battle_stats", {}) or {}
    stats = user_data.get("stats", {}) or {}
    battle_wins = battle_stats.get("victories") or stats.get("battle_wins", 0)

    lab_stats = user_data.get("labyrinth_stats", {}) or {}
    best_floor = (lab_stats.get("highest_floor")
                  or stats.get("labyrinth_best_floor", 0)
                  or user_data.get("labyrinth_best_floor", 0))

    ach = user_data.get("achievements", {})
    if isinstance(ach, dict):
        ach_count = len([k for k, v in ach.items() if v])
    elif isinstance(ach, list):
        ach_count = len(ach)
    else:
        ach_count = 0

    ranks = compute_ranks(money, level, exp)

    return {
        "nickname": display_name,
        "title": user_data.get("equipped_title"),
        "level": level,
        "level_max": level >= MAX_LEVEL,
        "exp": exp,
        "next_exp": next_exp,
        "money": money,
        "tuna_can": user_data.get("tuna_can", 0),
        "money_rank": ranks["money_rank"],
        "level_rank": ranks["level_rank"],
        "streak": user_data.get("daily_streak", 0),
        "cats_owned": _count_cats(user_data),
        "catdex": catdex_count,
        "battle_wins": battle_wins,
        "best_floor": best_floor,
        "achievements": ach_count,
        "skill_track": _skill_lv(user_data, SKILL_TREE_TRACKING),
        "skill_combat": _skill_lv(user_data, SKILL_TREE_COMBAT),
        "skill_trade": _skill_lv(user_data, SKILL_TREE_TRADE),
        "footer_date": datetime.now(KST).strftime("%Y/%m/%d %H:%M"),
    }


# ═══════════════════════════════════════════════════════════
# 카드 파일 빌더
# ═══════════════════════════════════════════════════════════

async def build_profile_card_file(member, user_data: dict) -> discord.File:
    """프로필 카드 PNG를 discord.File로 반환. (커스터마이징 자동 적용)"""
    data = gather_profile_data(user_data, member.display_name)
    customization = get_customization(user_data) or None
    avatar = await fetch_avatar_image(member)
    buf = await asyncio.to_thread(render_profile_card, data, avatar, customization)
    return discord.File(buf, filename="profile.png")


async def build_stat_card_file(member, user_data: dict, title: str, subtitle,
                               sections, filename: str = "stat.png") -> discord.File:
    """
    범용 스탯 카드 PNG를 discord.File로 반환. (다른 커맨드 카드화용)
    sections: [(섹션명, [(이모지, 라벨, 값), ...]), ...]
    커스터마이징(배경/테두리/네온/색상)은 프로필 카드와 동일하게 적용.
    """
    customization = get_customization(user_data) or None
    avatar = await fetch_avatar_image(member)
    buf = await asyncio.to_thread(
        render_stat_card, member.display_name, title, subtitle, sections, avatar, customization
    )
    return discord.File(buf, filename=filename)
