# utils/embeds.py
# ──────────────────────────────────────────────────────────
# 희귀도별 연출 임베드 빌더 및 공통 임베드 유틸리티
# ──────────────────────────────────────────────────────────

import os
import random
from datetime import datetime
from typing import Optional

import discord
from discord import Embed, File

from config import (
    KST, BOT_ICON, IMAGES_DIR,
    COLOR_DEFAULT, COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING, COLOR_INFO,
    RARITY_TIERS, get_rarity_tier,
)


# ═══════════════════════════════════════════════════════════
# 납치 성공 연출 (희귀도별 차등)
# ═══════════════════════════════════════════════════════════

# 등급별 연출 텍스트
_CATCH_EFFECTS = {
    "common": {
        "title_prefix": "",
        "description_extra": "",
        "footer_extra": "",
    },
    "uncommon": {
        "title_prefix": "✨ ",
        "description_extra": "\n*꽤 괜찮은 냥이를 발견했습니다!*",
        "footer_extra": "",
    },
    "rare": {
        "title_prefix": "💎 ",
        "description_extra": "\n**희귀한 냥이를 포획했습니다!**",
        "footer_extra": " | 희귀 등급 획득!",
    },
    "epic": {
        "title_prefix": "🌟 ",
        "description_extra": (
            "\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ **영웅급 냥이 포획!!** ⚡\n"
            "━━━━━━━━━━━━━━━━━━━━"
        ),
        "footer_extra": " | ⚡ 영웅 등급 획득!",
    },
    "legendary": {
        "title_prefix": "👑 ",
        "description_extra": (
            "\n\n"
            "╔══════════════════════════╗\n"
            "║  🏆 **전설의 냥이 포획!!!**  🏆  ║\n"
            "╚══════════════════════════╝\n"
            "\n*이 냥이는 전설 속에서만 존재한다던...*"
        ),
        "footer_extra": " | 👑 전설 등급 획득!!",
    },
    "mythic": {
        "title_prefix": "🔥 ",
        "description_extra": (
            "\n\n"
            "╔══════════════════════════════════╗\n"
            "║                                                              ║\n"
            "║   ✦ ✦ ✦  **신화급 냥이 포획!!!!**  ✦ ✦ ✦   ║\n"
            "║                                                              ║\n"
            "╚══════════════════════════════════╝\n"
            "\n"
            "```\n"
            "▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓\n"
            "  세계에서 가장 희귀한 냥이를 손에 넣었습니다\n"
            "▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓\n"
            "```"
        ),
        "footer_extra": " | 🔥🔥🔥 신화 등급 획득!!!",
    },
}

# 등급별 반응 메시지 (랜덤)
_CATCH_REACTIONS = {
    "common": [
        "평범한 냥이를 발견했어요.",
        "흔하디 흔한 길냥이네요.",
        "어디서나 볼 수 있는 냥이입니다.",
    ],
    "uncommon": [
        "오, 좀 특별한 녀석이네요!",
        "이 냥이 꽤 귀여운데요?",
        "흔하지 않은 냥이를 찾았어요!",
    ],
    "rare": [
        "희귀한 냥이를 발견했습니다!",
        "이런 냥이는 자주 볼 수 없어요!",
        "행운이 따랐네요! 희귀 냥이!",
    ],
    "epic": [
        "이건...!! 영웅급 냥이!!",
        "믿을 수 없어요! 영웅급이에요!",
        "대단한 발견입니다! 영웅급 냥이!",
    ],
    "legendary": [
        "전...전설의 냥이?! 꿈이 아닌가요?!",
        "전설이 현실이 되었습니다!!!",
        "이 냥이를 본 사람은 당신뿐입니다...!",
    ],
    "mythic": [
        "신화...이것은 신화입니다......!!!",
        "세계가 당신의 행운을 축복합니다!!!!",
        "이 순간을 영원히 기억하세요...신화급 포획!!!!",
    ],
}


def build_catch_embed(
    cat_data: dict,
    user_display_name: str,
    money_reward: int,
    exp_reward: int,
    region_name: str,
    reaction_bonus_text: str = "",
    level_up_info: Optional[dict] = None,
) -> tuple:
    """
    납치 성공 임베드를 생성합니다.
    반환: (embed: Embed, file: Optional[File])
    
    cat_data: cats.json의 냥이 데이터 dict
    """
    rarity = cat_data.get("rarity", 100.0)
    tier = get_rarity_tier(rarity)
    tier_key = tier["key"]
    tier_name = tier["name"]
    tier_emoji = tier["emoji"]
    tier_color = tier["color"]

    effect = _CATCH_EFFECTS.get(tier_key, _CATCH_EFFECTS["common"])
    reaction = random.choice(_CATCH_REACTIONS.get(tier_key, _CATCH_REACTIONS["common"]))

    cat_name = cat_data.get("name", "???")
    cat_desc = cat_data.get("desc", "")
    cat_age = cat_data.get("age", "???")
    cat_gender = cat_data.get("gender", "???")

    title = f"{effect['title_prefix']}납치 성공! {tier_emoji} {cat_name}"

    description_parts = [
        f"**{user_display_name}** 님이 **{region_name}**에서 냥이를 포획했습니다!",
        f"\n*\"{reaction}\"*",
        effect["description_extra"],
    ]

    if reaction_bonus_text:
        description_parts.append(f"\n{reaction_bonus_text}")

    description = "\n".join(description_parts)

    embed = Embed(
        title=title,
        description=description,
        color=tier_color,
    )

    # 냥이 정보 필드
    embed.add_field(name="등급", value=f"{tier_emoji} {tier_name}", inline=True)
    embed.add_field(name="희귀도", value=f"{rarity}%", inline=True)
    embed.add_field(name="나이", value=f"{cat_age}세", inline=True)
    embed.add_field(name="성별", value=cat_gender, inline=True)

    if cat_desc:
        embed.add_field(name="설명", value=cat_desc, inline=False)

    # 보상 필드
    reward_text = f"💰 {money_reward:,}원 | ✨ {exp_reward} EXP"
    embed.add_field(name="보상", value=reward_text, inline=False)

    # 레벨업 정보
    if level_up_info and level_up_info.get("leveled_up"):
        level_text = (
            f"🎉 **레벨 업!** Lv.{level_up_info['new_level']}에 도달했습니다!\n"
            f"스킬 포인트 +{level_up_info['skill_points_gained']}"
        )
        embed.add_field(name="🆙 레벨 업!", value=level_text, inline=False)

    footer_text = f"획득 확률: {rarity}%{effect['footer_extra']}"
    embed.set_footer(text=footer_text)

    # 이미지 처리
    image_name = cat_data.get("image", "")
    file_obj = None
    if image_name:
        image_path = os.path.join(IMAGES_DIR, image_name)
        if os.path.isfile(image_path):
            file_obj = File(image_path, filename=image_name)
            embed.set_image(url=f"attachment://{image_name}")

    return embed, file_obj


# ═══════════════════════════════════════════════════════════
# 납치 실패 임베드
# ═══════════════════════════════════════════════════════════

_FAIL_MESSAGES = [
    "냥이를 찾지 못했어요...",
    "냥이가 도망갔어요 🏃‍💨",
    "이번엔 빈손이네요.",
    "냥이가 숨어버렸습니다.",
    "근처에 냥이가 없는 것 같아요.",
    "발소리를 듣고 도망친 것 같습니다...",
    "풀숲이 바스락거렸지만... 바람이었어요.",
]


def build_fail_embed(user_display_name: str, region_name: str) -> Embed:
    """납치 실패 임베드를 생성합니다."""
    message = random.choice(_FAIL_MESSAGES)
    embed = Embed(
        title=f"❌ 납치 실패",
        description=f"**{user_display_name}** 님이 **{region_name}**에서 탐색했지만...\n\n*{message}*",
        color=COLOR_ERROR,
    )
    embed.set_footer(text="다음엔 성공할 거예요!")
    return embed


# ═══════════════════════════════════════════════════════════
# 탐색 장소 선택 임베드
# ═══════════════════════════════════════════════════════════

def build_location_select_embed(
    user_display_name: str,
    region_name: str,
    region_emoji: str,
    locations: list,
    hints: list,
) -> Embed:
    """
    탐색 장소 선택 임베드를 생성합니다.
    locations: [(emoji, name), ...]
    hints: [str, ...]  각 장소에 대한 힌트
    """
    embed = Embed(
        title=f"{region_emoji} {region_name} - 탐색 장소 선택",
        description=(
            f"**{user_display_name}** 님, 어디를 탐색할까요?\n"
            f"장소에 따라 발견되는 냥이가 달라질 수 있습니다.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        ),
        color=COLOR_INFO,
    )

    for i, ((emoji, name), hint) in enumerate(zip(locations, hints)):
        embed.add_field(
            name=f"{emoji} {name}",
            value=f"*{hint}*",
            inline=True,
        )

    embed.set_footer(text="💡 힌트를 잘 살펴보세요! 추적 스킬이 높을수록 정확한 힌트를 얻습니다.")
    return embed


# ═══════════════════════════════════════════════════════════
# 반응속도 테스트 임베드
# ═══════════════════════════════════════════════════════════

def build_reaction_wait_embed() -> Embed:
    """반응속도 테스트 대기 임베드"""
    embed = Embed(
        title="🔍 냥이를 추적하는 중...",
        description="잠시 기다려주세요... 곧 포획 기회가 옵니다!",
        color=0x95A5A6,
    )
    return embed


def build_reaction_now_embed() -> Embed:
    """반응속도 테스트 '지금!' 임베드"""
    embed = Embed(
        title="❗ 지금이다! 잡아!!",
        description="**아래 버튼을 최대한 빨리 누르세요!**",
        color=0xFF0000,
    )
    return embed


def build_reaction_result_embed(reaction_ms: int, bonus: float) -> Embed:
    """반응속도 결과 임베드"""
    if reaction_ms <= 500:
        grade = "⚡ PERFECT!"
        grade_color = 0xFFD700
    elif reaction_ms <= 1500:
        grade = "✨ GREAT!"
        grade_color = 0x00FF00
    elif reaction_ms <= 3000:
        grade = "👍 GOOD"
        grade_color = 0x3498DB
    else:
        grade = "😅 SLOW..."
        grade_color = 0x95A5A6

    bonus_text = f"+{bonus:.1f}%" if bonus >= 0 else f"{bonus:.1f}%"

    embed = Embed(
        title=grade,
        description=(
            f"반응 속도: **{reaction_ms:,}ms**\n"
            f"성공률 보정: **{bonus_text}**"
        ),
        color=grade_color,
    )
    return embed


# ═══════════════════════════════════════════════════════════
# 공통 유틸리티 임베드
# ═══════════════════════════════════════════════════════════

def build_level_up_embed(user_display_name: str, new_level: int, skill_points: int) -> Embed:
    """레벨업 알림 임베드"""
    embed = Embed(
        title=f"🎉 레벨 업! Lv.{new_level}",
        description=(
            f"**{user_display_name}** 님이 **Lv.{new_level}**에 도달했습니다!\n\n"
            f"🔹 스킬 포인트 **+{skill_points}** 획득\n"
            f"💡 `/스킬` 명령어로 스킬 포인트를 투자하세요!"
        ),
        color=COLOR_SUCCESS,
    )
    return embed


def build_error_embed(title: str = "오류 발생", description: str = "") -> Embed:
    """에러 임베드"""
    return Embed(title=f"❌ {title}", description=description, color=COLOR_ERROR)


def build_info_embed(title: str, description: str = "") -> Embed:
    """정보 임베드"""
    return Embed(title=title, description=description, color=COLOR_INFO)
