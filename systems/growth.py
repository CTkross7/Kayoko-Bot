# systems/growth.py
# ──────────────────────────────────────────────────────────
# 카요코 성장 시스템 / 스킬 투자 / 지역 이동·해금
# ──────────────────────────────────────────────────────────

from datetime import datetime
from typing import Optional

import discord
from discord import Embed

from config import (
    KST, COLOR_SUCCESS, COLOR_ERROR, COLOR_INFO, COLOR_WARNING,
    SKILL_TREE_TRACKING, SKILL_TREE_COMBAT, SKILL_TREE_TRADE,
    SKILL_EFFECTS, MAX_SKILL_LEVEL, MAX_LEVEL,
    get_exp_for_level, DAILY_LOGIN_REWARD,
    TUTORIAL_STEPS, TUTORIAL_COMPLETION_REWARD,
)
from models.user import (
    load_user_data, save_user_data, add_exp,
    allocate_skill_point, get_effective_kidnap_stats,
    get_skill_effect,
)
from models.region import (
    REGIONS, get_region, get_region_list, get_next_region,
)
from models.cat import get_cats_by_region, get_region_dex_percent


# ═══════════════════════════════════════════════════════════
# 스킬 정보 표시
# ═══════════════════════════════════════════════════════════

SKILL_DISPLAY = {
    SKILL_TREE_TRACKING: {
        "name": "🐾 추적",
        "desc": "납치 성공률, 희귀 냥이 확률, 힌트 정확도 향상",
        "effects_desc": [
            ("납치 성공률", "kidnap_success_bonus", "+{val:.1f}%"),
            ("희귀 냥이 확률", "rare_chance_bonus", "+{val:.1f}%"),
            ("힌트 정확도", "hint_accuracy_bonus", "+{val:.1f}%"),
        ],
    },
    SKILL_TREE_COMBAT: {
        "name": "⚔️ 전투",
        "desc": "전투력, 체력, 스킬 데미지 향상",
        "effects_desc": [
            ("전투력 보너스", "battle_power_bonus", "+{val:.0f}"),
            ("체력 보너스", "battle_hp_bonus", "+{val:.0f}"),
            ("스킬 데미지", "skill_damage_bonus", "+{val:.1f}%"),
        ],
    },
    SKILL_TREE_TRADE: {
        "name": "💰 거래",
        "desc": "분양가, 상점 할인, 일일 보너스 향상",
        "effects_desc": [
            ("분양가 보너스", "sell_price_bonus", "+{val:.1f}%"),
            ("상점 할인", "shop_discount", "+{val:.1f}%"),
            ("일일 보너스", "daily_bonus_money", "+{val:.0f}원"),
        ],
    },
}


def build_skill_info_embed(user_data: dict, display_name: str) -> Embed:
    """유저의 스킬 트리 현황 임베드를 생성합니다."""
    level = user_data.get("level", 1)
    exp = user_data.get("exp", 0)
    skill_points = user_data.get("skill_points", 0)
    skills = user_data.get("skills", {})

    next_exp = get_exp_for_level(level)

    embed = Embed(
        title=f"📊 {display_name}님의 성장 현황",
        color=COLOR_INFO,
    )

    # 레벨 정보
    if level >= MAX_LEVEL:
        level_text = f"**Lv.{level}** (MAX)\nEXP: {exp:,}"
    else:
        level_text = f"**Lv.{level}**\nEXP: {exp:,} / {next_exp:,}"

    embed.add_field(
        name="🎯 레벨",
        value=level_text,
        inline=True,
    )
    embed.add_field(
        name="✨ 스킬 포인트",
        value=f"**{skill_points}** 포인트",
        inline=True,
    )
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    # 각 스킬 트리 상세
    for tree_key, display in SKILL_DISPLAY.items():
        current_level = skills.get(tree_key, 0)
        tree_effects = SKILL_EFFECTS.get(tree_key, {})

        # 프로그레스 바 생성
        filled = current_level
        empty = MAX_SKILL_LEVEL - current_level
        bar = "█" * min(filled, 20) + "░" * min(empty, 20 - min(filled, 20))

        effects_text_lines = []
        for effect_label, effect_key, fmt in display["effects_desc"]:
            per_level = tree_effects.get(effect_key, 0)
            current_val = current_level * per_level
            effects_text_lines.append(
                f"  {effect_label}: {fmt.format(val=current_val)}"
            )

        field_value = (
            f"Lv.**{current_level}** / {MAX_SKILL_LEVEL}\n"
            f"`[{bar}]`\n"
            f"*{display['desc']}*\n"
            + "\n".join(effects_text_lines)
        )

        embed.add_field(
            name=f"{display['name']}",
            value=field_value,
            inline=False,
        )

    # 실효 납치 스탯
    stats = get_effective_kidnap_stats(user_data)
    embed.add_field(
        name="📋 현재 납치 실효 스탯",
        value=(
            f"성공률: **{stats['success_rate']:.1f}%** | "
            f"쿨타임: **{stats['cooldown']:.1f}초** | "
            f"보상 배율: **x{stats['money_multiplier']:.2f}** | "
            f"희귀 보너스: **+{stats['rare_bonus']:.1f}%**"
        ),
        inline=False,
    )

    embed.set_footer(text="💡 /스킬투자 명령어로 스킬 포인트를 투자할 수 있습니다.")
    return embed


# ═══════════════════════════════════════════════════════════
# 지역 정보 표시
# ═══════════════════════════════════════════════════════════

def build_region_list_embed(user_data: dict, display_name: str) -> Embed:
    """지역 목록 및 해금 현황 임베드를 생성합니다."""
    unlocked = user_data.get("unlocked_regions", ["alley"])
    current = user_data.get("current_region", "alley")
    level = user_data.get("level", 1)

    embed = Embed(
        title=f"🗺️ {display_name}님의 지역 현황",
        description="각 지역을 탐험하며 다양한 냥이를 발견하세요!",
        color=COLOR_INFO,
    )

    for region_key, region_data in get_region_list():
        is_unlocked = region_key in unlocked
        is_current = region_key == current

        # 도감 달성률
        dex_percent = get_region_dex_percent(user_data, region_key)
        total_cats = len(get_cats_by_region(region_key))

        # 상태 표시
        if is_current:
            status = "📍 현재 위치"
        elif is_unlocked:
            status = "✅ 해금됨"
        else:
            status = "🔒 미해금"

        # 해금 조건
        req_level = region_data["required_level"]
        req_dex = region_data["required_prev_dex_percent"]
        prev_region = region_data.get("prev_region")

        if is_unlocked:
            condition_text = ""
        else:
            conditions = [f"Lv.{req_level} 필요 (현재 Lv.{level})"]
            if prev_region:
                prev_name = REGIONS.get(prev_region, {}).get("name", "???")
                prev_dex = get_region_dex_percent(user_data, prev_region)
                conditions.append(f"{prev_name} 도감 {req_dex}% 필요 (현재 {prev_dex:.1f}%)")
            condition_text = "\n".join(conditions)

        field_name = f"{region_data['emoji']} {region_data['name']} {status}"

        field_parts = [f"*{region_data['description']}*"]
        field_parts.append(f"냥이 종류: {total_cats}종 | 도감: {dex_percent:.1f}%")

        if condition_text:
            field_parts.append(f"**해금 조건:** {condition_text}")

        embed.add_field(
            name=field_name,
            value="\n".join(field_parts),
            inline=False,
        )

    embed.set_footer(text="💡 /지역이동 명령어로 다른 지역으로 이동할 수 있습니다.")
    return embed


def try_unlock_region(user_data: dict, region_key: str) -> tuple:
    """
    지역 해금을 시도합니다.
    반환: (성공여부: bool, 메시지: str)
    """
    region = get_region(region_key)
    if not region:
        return False, "존재하지 않는 지역입니다."

    unlocked = user_data.get("unlocked_regions", ["alley"])
    if region_key in unlocked:
        return False, "이미 해금된 지역입니다."

    # 레벨 체크
    level = user_data.get("level", 1)
    if level < region["required_level"]:
        return False, f"레벨이 부족합니다. (필요: Lv.{region['required_level']}, 현재: Lv.{level})"

    # 이전 지역 도감 달성률 체크
    prev_region_key = region.get("prev_region")
    if prev_region_key:
        if prev_region_key not in unlocked:
            prev_name = REGIONS.get(prev_region_key, {}).get("name", "???")
            return False, f"이전 지역({prev_name})이 해금되지 않았습니다."

        prev_dex = get_region_dex_percent(user_data, prev_region_key)
        required_dex = region["required_prev_dex_percent"]
        if prev_dex < required_dex:
            prev_name = REGIONS.get(prev_region_key, {}).get("name", "???")
            return False, (
                f"{prev_name} 도감 달성률이 부족합니다. "
                f"(필요: {required_dex}%, 현재: {prev_dex:.1f}%)"
            )

    # 해금 성공
    user_data.setdefault("unlocked_regions", ["alley"])
    if region_key not in user_data["unlocked_regions"]:
        user_data["unlocked_regions"].append(region_key)

    return True, f"**{region['emoji']} {region['name']}** 지역이 해금되었습니다!"


def move_to_region(user_data: dict, region_key: str) -> tuple:
    """
    지역을 이동합니다.
    반환: (성공여부: bool, 메시지: str)
    """
    region = get_region(region_key)
    if not region:
        return False, "존재하지 않는 지역입니다."

    unlocked = user_data.get("unlocked_regions", ["alley"])
    if region_key not in unlocked:
        return False, f"**{region['name']}** 지역이 아직 해금되지 않았습니다."

    current = user_data.get("current_region", "alley")
    if current == region_key:
        return False, f"이미 **{region['name']}**에 있습니다."

    user_data["current_region"] = region_key
    return True, f"**{region['emoji']} {region['name']}**(으)로 이동했습니다!"


# ═══════════════════════════════════════════════════════════
# 일일 보상
# ═══════════════════════════════════════════════════════════

def claim_daily_reward(user_data: dict) -> tuple:
    """
    일일 보상을 수령합니다.
    반환: (성공여부: bool, 보상금액: int, 메시지: str)
    """
    today = datetime.now(KST).strftime("%Y-%m-%d")
    last_daily = user_data.get("last_daily_reward")

    if last_daily == today:
        return False, 0, "오늘 이미 일일 보상을 수령했습니다. 내일 다시 오세요!"

    # 기본 보상 + 거래 스킬 보너스
    base_reward = DAILY_LOGIN_REWARD
    trade_bonus = get_skill_effect(user_data, SKILL_TREE_TRADE, "daily_bonus_money")
    total_reward = int(base_reward + trade_bonus)

    user_data["money"] = user_data.get("money", 0) + total_reward
    user_data["last_daily_reward"] = today

    bonus_text = ""
    if trade_bonus > 0:
        bonus_text = f" (기본 {base_reward:,} + 거래스킬 보너스 {int(trade_bonus):,})"

    return True, total_reward, f"💰 일일 보상 **{total_reward:,}원**을 수령했습니다!{bonus_text}"


# ═══════════════════════════════════════════════════════════
# 튜토리얼 시스템
# ═══════════════════════════════════════════════════════════

def get_current_tutorial_step(user_data: dict) -> dict | None:
    """현재 튜토리얼 단계 정보를 반환합니다. 완료 시 None."""
    if user_data.get("tutorial_completed", False):
        return None

    step_key = user_data.get("tutorial_step", "welcome")
    return TUTORIAL_STEPS.get(step_key)


def advance_tutorial(user_data: dict, completed_action: str) -> tuple:
    """
    튜토리얼을 진행합니다.
    completed_action: 유저가 수행한 액션 (예: "first_kidnap", "check_inventory" 등)

    반환: (진행됨여부: bool, 보상정보: dict | None, 메시지: str)
    """
    if user_data.get("tutorial_completed", False):
        return False, None, ""

    current_key = user_data.get("tutorial_step", "welcome")
    current_step = TUTORIAL_STEPS.get(current_key)

    if not current_step:
        return False, None, ""

    # 현재 단계의 next가 completed_action과 일치하는지 확인
    # (welcome 단계는 가입 시 자동으로 넘어감)
    if current_key == "welcome" and completed_action == "welcome":
        pass  # welcome은 가입 시 자동 진행
    elif current_step.get("next") != completed_action and current_key != completed_action:
        # 현재 단계가 완료되지 않았으면 무시
        return False, None, ""

    # 다음 단계로 진행
    next_key = current_step.get("next")

    # 보상 지급
    reward_money = current_step.get("reward_money", 0)
    reward_exp = current_step.get("reward_exp", 0)

    user_data["money"] = user_data.get("money", 0) + reward_money

    level_up_result = None
    if reward_exp > 0:
        level_up_result = add_exp(user_data, reward_exp)

    reward_info = {
        "money": reward_money,
        "exp": reward_exp,
        "level_up": level_up_result,
        "step_title": current_step.get("title", ""),
    }

    if next_key is None or next_key == "complete":
        # 마지막 단계 완료
        # complete 단계의 보상도 지급
        complete_step = TUTORIAL_STEPS.get("complete")
        if complete_step and current_key != "complete":
            user_data["money"] = user_data.get("money", 0) + complete_step.get("reward_money", 0)
            if complete_step.get("reward_exp", 0) > 0:
                level_up_result = add_exp(user_data, complete_step["reward_exp"])
            reward_info["money"] += complete_step.get("reward_money", 0)
            reward_info["exp"] += complete_step.get("reward_exp", 0)

        user_data["tutorial_completed"] = True
        user_data["tutorial_step"] = "complete"
        return True, reward_info, "🎉 튜토리얼을 완료했습니다! 이제 자유롭게 모험을 즐기세요!"

    # 다음 단계 설정
    user_data["tutorial_step"] = next_key
    next_step = TUTORIAL_STEPS.get(next_key, {})

    return True, reward_info, (
        f"✅ **{current_step['title']}** 완료!\n"
        f"다음 목표: **{next_step.get('title', '???')}** — {next_step.get('description', '')}"
    )


def build_tutorial_embed(user_data: dict) -> Embed:
    """현재 튜토리얼 상태 임베드를 생성합니다."""
    if user_data.get("tutorial_completed", False):
        embed = Embed(
            title="📖 튜토리얼 완료!",
            description="모든 튜토리얼을 완료했습니다. 자유롭게 모험을 즐기세요!",
            color=COLOR_SUCCESS,
        )
        return embed

    current_key = user_data.get("tutorial_step", "welcome")
    current_step = TUTORIAL_STEPS.get(current_key)

    if not current_step:
        return Embed(title="❌ 튜토리얼 오류", color=COLOR_ERROR)

    # 전체 진행도 계산
    all_steps = list(TUTORIAL_STEPS.keys())
    current_index = all_steps.index(current_key) if current_key in all_steps else 0
    total_steps = len(all_steps)
    progress = current_index / total_steps * 100

    bar_filled = int(progress / 5)
    bar_empty = 20 - bar_filled
    progress_bar = "█" * bar_filled + "░" * bar_empty

    embed = Embed(
        title=f"📖 튜토리얼 — {current_step['title']}",
        description=current_step["description"],
        color=COLOR_INFO,
    )

    embed.add_field(
        name="진행도",
        value=f"`[{progress_bar}]` {progress:.0f}% ({current_index}/{total_steps})",
        inline=False,
    )

    # 보상 미리보기
    reward_parts = []
    if current_step.get("reward_money", 0) > 0:
        reward_parts.append(f"💰 {current_step['reward_money']:,}원")
    if current_step.get("reward_exp", 0) > 0:
        reward_parts.append(f"✨ {current_step['reward_exp']} EXP")

    if reward_parts:
        embed.add_field(
            name="🎁 완료 보상",
            value=" | ".join(reward_parts),
            inline=False,
        )

    embed.set_footer(text="목표를 달성하면 자동으로 다음 단계로 넘어갑니다!")
    return embed
