# systems/gambling.py
# ──────────────────────────────────────────────────────────
#  도박 시스템 (가챠베팅, 총력전배치고사, 계정리세마라)
# ──────────────────────────────────────────────────────────

import asyncio
import random
from datetime import datetime

import discord

from config import (
    COLOR_DEFAULT, COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING,
    BOT_ICON_URL, DAILY_LIMITS,
)

FOOTER_TEXT = "카요코 봇"

# ═══════════════════════════════════════════════════════════
# 상수
# ═══════════════════════════════════════════════════════════

GAMBLE_MIN_BET = 1000
GAMBLE_MAX_BET = 50000

# ═══════════════════════════════════════════════════════════
# 가챠 데이터
# ═══════════════════════════════════════════════════════════

GACHA_DATA = {
    "3성": {
        "prob": 30.00,
        "multiplier": 2.0,
        "message": "🟪 축하드립니다! 3성 확정 가챠에 성공하여 베팅액의 2배를 획득했습니다!",
        "gif_url": "https://i.imgur.com/sSZYmYP.gif",
        "static_image_url": "https://i.imgur.com/RGap9LM.jpeg",
        "duration": 12.7,
        "color": 0xFF69B4,
    },
    "3성 변동": {
        "prob": 9.2,
        "multiplier": 3.0,
        "message": "✨🟪 2성? 그건 재미없잖아. 3성 변동 가챠에 성공하여 베팅액의 3배를 획득했습니다!",
        "gif_url": "https://i.imgur.com/XqQeide.gif",
        "static_image_url": "https://i.imgur.com/FxXTSDu.jpeg",
        "duration": 14.1,
        "color": 0xFF69B4,
    },
    "프라나의 3성 밑장빼기": {
        "prob": 1.8,
        "multiplier": 7.7,
        "message": "⬜ 프라나가 아로나 선배 몰래 3성 밑장빼기에 성공했습니다! 베팅액의 7.7배를 획득했습니다!",
        "gif_url": "https://cdn.discordapp.com/attachments/1182958084298113094/1418453851056509010/gacha__.gif",
        "static_image_url": "https://i.imgur.com/dd8Psom.jpeg",
        "duration": 8.1,
        "color": 0xFFFFFF,
        "source_url": "https://x.com/_N_sol_/status/1887327857812382055",
    },
    "2성 봉투": {
        "prob": 40.00,
        "multiplier": -2.0,
        "message": "🟨 1성 대신 2성 봉투를 얻었습니다. 베팅액의 2배를 잃었습니다.",
        "gif_url": "https://cdn.discordapp.com/attachments/1182958084298113094/1418453746979049513/e9d3de5ec7d10b16.gif",
        "static_image_url": "https://i.imgur.com/P9UMddQ.jpeg",
        "duration": 8.8,
        "color": 0xFFFF00,
    },
    "1성 봉투": {
        "prob": 16.00,
        "multiplier": -3.0,
        "message": "🟦 저런 1성 봉투네요. 베팅액의 3배를 잃었습니다.",
        "gif_url": "https://cdn.discordapp.com/attachments/1182958084298113094/1418453746979049513/e9d3de5ec7d10b16.gif",
        "static_image_url": "https://i.imgur.com/P9UMddQ.jpeg",
        "duration": 8.8,
        "color": 0xADD8E6,
    },
    "올블루": {
        "prob": 3.0,
        "multiplier": -5.0,
        "message": "🟦🟦 올블루라고 들어봤어?? 베팅액의 5배를 잃었습니다.",
        "gif_url": "https://cdn.discordapp.com/attachments/1182958084298113094/1418453746979049513/e9d3de5ec7d10b16.gif",
        "static_image_url": "https://i.imgur.com/aqmtxze.jpeg",
        "duration": 8.8,
        "color": 0x000000,
    },
}

# ═══════════════════════════════════════════════════════════
# 총력전 보스 데이터
# ═══════════════════════════════════════════════════════════

BOSS_DATA = {
    "그레고리오": {
        "prob": 33.33,
        "intro_gif_url": "https://i.imgur.com/b6qs984.gif",
        "intro_duration": 11.8,
        "outro_image_url": "https://i.imgur.com/ZzE1Uv5.jpeg",
        "tiers": {
            "플래티넘 상위 1%": {"prob": 1.0, "multiplier": 10.0, "color": 0xE0DBEF,
                "message": "💥 **[그레고리오]** 완벽한 디버프 조절과 크리티컬의 조화! 베팅액의 10배를 획득했습니다!"},
            "플래티넘": {"prob": 9.4, "multiplier": 3.0, "color": 0xE0DBEF,
                "message": "🏆 **[그레고리오]** 완벽한 디버프 누적으로 격퇴했습니다. 베팅액의 3배를 획득했습니다!"},
            "골드": {"prob": 30.0, "multiplier": 2.0, "color": 0xFFD700,
                "message": "🏅 **[그레고리오]** 성좌의 속삭임을 간신히 뚫고 골드 티어에 안착했습니다. 베팅액의 2배를 획득했습니다!"},
            "실버": {"prob": 40.0, "multiplier": -2.0, "color": 0xC0C0C0,
                "message": "🥉 **[그레고리오]** 엄격한 회개의 방해가 심했네요. 베팅액의 2배를 잃었습니다."},
            "브론즈": {"prob": 17.0, "multiplier": -3.0, "color": 0xCD7F32,
                "message": "🧱 **[그레고리오]** 엄격한 회개 기믹을 대처하지 못했습니다. 베팅액의 3배를 잃었습니다."},
            "순위권 도달 실패": {"prob": 3.0, "multiplier": -5.0, "color": 0x000000,
                "message": "**마에스트로:** 그러니 이번에도 갈채를 내려주길 바란다. 선생이여."},
        },
    },
    "비나": {
        "prob": 33.33,
        "intro_gif_url": "https://i.imgur.com/8tsctDn.gif",
        "intro_duration": 16.4,
        "outro_image_url": "https://i.imgur.com/eQU5rVk.jpeg",
        "tiers": {
            "플래티넘 상위 1%": {"prob": 1.0, "multiplier": 10.0, "color": 0xE0DBEF,
                "message": "💥 **[비나]** 완벽한 기믹회피와 당신의 압도적인 딜량! 베팅액의 10배를 획득했습니다!"},
            "플래티넘": {"prob": 9.4, "multiplier": 3.0, "color": 0xE0DBEF,
                "message": "🏆 **[비나]** 기절 효과를 적극 이용하여 플래티넘 달성! 베팅액의 3배를 획득했습니다!"},
            "골드": {"prob": 30.0, "multiplier": 2.0, "color": 0xFFD700,
                "message": "🏅 **[비나]** 미사일을 간신히 피해 골드 티어에 안착했습니다. 베팅액의 2배를 획득했습니다!"},
            "실버": {"prob": 40.0, "multiplier": -2.0, "color": 0xC0C0C0,
                "message": "🥉 **[비나]** 하늘에서 쏟아지는 폭격에 팀이 전멸했습니다. 베팅액의 2배를 잃었습니다."},
            "브론즈": {"prob": 17.0, "multiplier": -3.0, "color": 0xCD7F32,
                "message": "🧱 **[비나]** 레이저에 맞고 팀이 증발했습니다. 베팅액의 3배를 잃었습니다."},
            "순위권 도달 실패": {"prob": 3.0, "multiplier": -5.0, "color": 0x000000,
                "message": "❌ **[비나]** 접근조차 못하고 사라졌네요. 베팅액의 5배를 잃었습니다."},
        },
    },
    "카이텐져": {
        "prob": 33.34,
        "intro_gif_url": "https://i.imgur.com/8PpsToP.gif",
        "intro_duration": 10.4,
        "outro_image_url": "https://i.imgur.com/TRd0ijE.jpeg",
        "tiers": {
            "플래티넘 상위 1%": {"prob": 1.0, "multiplier": 10.0, "color": 0xE0DBEF,
                "message": "💥 **[카이텐져]** 카이텐저의 패배! 보호막 완벽 제거! 베팅액의 10배를 획득했습니다!"},
            "플래티넘": {"prob": 9.4, "multiplier": 3.0, "color": 0xE0DBEF,
                "message": "🏆 **[카이텐져]** 군중제어를 이용하여 플래티넘 달성! 베팅액의 3배를 획득했습니다!"},
            "골드": {"prob": 30.0, "multiplier": 2.0, "color": 0xFFD700,
                "message": "🏅 **[카이텐져]** 간신히 기믹을 회피하여 골드 티어에 안착했습니다. 베팅액의 2배를 획득했습니다!"},
            "실버": {"prob": 40.0, "multiplier": -2.0, "color": 0xC0C0C0,
                "message": "🥉 **[카이텐져]** 카이텐저의 강화스킬을 막지 못했습니다. 베팅액의 2배를 잃었습니다."},
            "브론즈": {"prob": 17.0, "multiplier": -3.0, "color": 0xCD7F32,
                "message": "🧱 **[카이텐져]** 어설픈 기믹 회피로 결국 패배했습니다. 베팅액의 3배를 잃었습니다."},
            "순위권 도달 실패": {"prob": 3.0, "multiplier": -5.0, "color": 0x000000,
                "message": "❌ **[카이텐져]** 예상치 못한 변수가! 리트확정이네요. 베팅액의 5배를 잃었습니다."},
        },
    },
}

# ═══════════════════════════════════════════════════════════
# 리세마라 데이터
# ═══════════════════════════════════════════════════════════

REROLL_DATA = {
    "FES": {
        "prob": 1.2,
        "gif_url": "https://cdn.discordapp.com/attachments/1182958084298113094/1418453851056509010/gacha__.gif",
        "duration": 8.1,
        "color": 0xFFFFFF,
        "message": "🎉 페스 인권 캐릭터 픽업 성공!",
        "students": [
            {"name": "호시노(수영복)", "multiplier": 7.0,
             "image_url": "https://cdn.discordapp.com/attachments/1267472211531530311/1419521524771328112/80k50hZpMAh6zv85nmYE4Fg4BSSTk5uH6JaPsNqog_MFFt7RhqqhlSHidwqdqVjGRYbUTKoCiIDAs2dqznv5WA.webp",
             "description": "수영복 차림의 호시노, 강력한 페스 캐릭터입니다. 베팅액의 7배를 획득했습니다."},
            {"name": "미카", "multiplier": 7.0,
             "image_url": "https://cdn.discordapp.com/attachments/1267472211531530311/1419521525278576680/images_4.jpg",
             "description": "최강의 총력전 딜러, 리세마라 졸업 1순위! 베팅액의 7배를 획득했습니다."},
            {"name": "시로코*테러", "multiplier": 7.0,
             "image_url": "https://cdn.discordapp.com/attachments/1267472211531530311/1419521525807317042/MfnmgT77eqRWySHarLjheaGDgLIgoT71_M7axTGdyZASQupcJEgVoLuYNi0Q6Z2A-Nr0kJ_OGGGAvst3SiSBpA.webp",
             "description": "총력전 필수 캐릭터, 리세마라 졸업 1순위! 베팅액의 7배를 획득했습니다."},
        ],
    },
    "INCY": {
        "prob": 4.0,
        "gif_url": "https://i.imgur.com/sSZYmYP.gif",
        "duration": 12.7,
        "color": 0xFF69B4,
        "message": "✨ 인권 캐릭터 픽업 성공!",
        "students": [
            {"name": "시로코(수영복)", "multiplier": 5.0,
             "image_url": "https://cdn.discordapp.com/attachments/1267472211531530311/1419521526297788416/om_yZxx8gANouhN-5mxRZuOUg4lKPKMfZNrGOCw77r-eh5YTx8fut28hX7QOarjO3FCt2oBs3zLQIyXu9a0qrQ.webp",
             "description": "수영복을 입은 시로코, 총력전에서 맹활약합니다. 베팅액의 5배를 획득했습니다."},
            {"name": "카요코(새해)", "multiplier": 5.0,
             "image_url": "https://cdn.discordapp.com/attachments/1267472211531530311/1419521526876868689/nKg0uuQtU5xcUCDRqlx-GCC-ifoLLcRmwKDZkF6_v9PmqEnMxyb1CykEcHSpNGjSi-Z576Xt1BRSP0U_nJWMXA.webp",
             "description": "최상의 신비 서포터. 베팅액의 5배를 획득했습니다."},
            {"name": "아코", "multiplier": 5.0,
             "image_url": "https://cdn.discordapp.com/attachments/1267472211531530311/1419521527434444852/nZQiHn2TpSEBKGyQ98TrrCnqCbzdTWV2xKS0wTBtVhTzUZ_MhQ02a3eBa1494pwY3Q8ujW-CHc3z5qfh4zn1cQ.webp",
             "description": "총력전 필수 서포터. 베팅액의 5배를 획득했습니다."},
        ],
    },
    "GOOD_3STAR": {
        "prob": 35.0,
        "gif_url": "https://i.imgur.com/sSZYmYP.gif",
        "duration": 12.7,
        "color": 0xFFFF00,
        "message": "🎉 3성 캐릭터 획득!",
        "students": [
            {"name": "아즈사", "multiplier": 2.0,
             "image_url": "https://cdn.discordapp.com/attachments/1267472211531530311/1419521527854006362/Bxj9LgFIKksir9N3mQT7Qn8KDmMzmztcVYPjCj-cOWHjlunT6QtoJnHiYGORDMhUKEWdU9xfJF66XDNPqAaVwA.webp",
             "description": "준수한 성능의 딜러입니다. 베팅액의 2배를 획득했습니다."},
            {"name": "이즈나", "multiplier": 2.0,
             "image_url": "https://cdn.discordapp.com/attachments/1267472211531530311/1419521528285888582/BXsIdr5KTzRZ1F04oIC9Ey_wsXaNcJvD_FAbkthnHgYqGC4vTVUK7Cy7MnWlHzUxRm34XUp5ED5VfGtq2atvkQ.webp",
             "description": "귀여운 닌자 학생. 베팅액의 2배를 획득했습니다."},
            {"name": "히비키", "multiplier": 2.0,
             "image_url": "https://cdn.discordapp.com/attachments/1267472211531530311/1419521528739008563/-MWICmidukQ7rOc_EL3nxjLfcGZ0dVhr5Bt1tItUT3F6_y_5f_ULdSXrbydEY64rKgkerdcLtc_QCYPsTG3dxg.webp",
             "description": "준수한 성능의 서포터. 베팅액의 2배를 획득했습니다."},
        ],
    },
    "FAIL_3STAR": {
        "prob": 50.8,
        "gif_url": "https://i.imgur.com/sSZYmYP.gif",
        "duration": 12.7,
        "color": 0xADD8E6,
        "message": "😞 3성이 나왔지만... 망했어요.",
        "students": [
            {"name": "히후미", "multiplier": -2.0,
             "image_url": "https://cdn.discordapp.com/attachments/1267472211531530311/1419521529103782041/images_5.jpg",
             "description": "리세마라로는 아쉽네요. 베팅액의 2배를 잃었습니다."},
            {"name": "마키", "multiplier": -2.0,
             "image_url": "https://cdn.discordapp.com/attachments/1267472211531530311/1419521562398163066/images_6.jpg",
             "description": "리세마라로 쓰기엔 아쉬운 3성. 베팅액의 2배를 잃었습니다."},
            {"name": "츠루기", "multiplier": -2.0,
             "image_url": "https://cdn.discordapp.com/attachments/1267472211531530311/1419521562045972521/C4k5_-g1zKSdtu0Zqa2Z1KKF4pgEuSlXa9mwDv8ZxdjNi-_y5wDGSpZS66Vv4_6e1tpOVizXYD-B6Cm5okmseg.webp",
             "description": "리세마라로는 아쉬운 픽. 베팅액의 2배를 잃었습니다."},
        ],
    },
    "RERUN": {
        "prob": 6.0,
        "gif_url": "https://i.imgur.com/sSZYmYP.gif",
        "duration": 12.7,
        "color": 0x000000,
        "message": "🔄 무한 리세마라에 빠지셨습니다.",
        "students": [
            {"name": "네트워크 에러", "multiplier": -5.0,
             "image_url": "https://i.imgur.com/P9UMddQ.jpeg",
             "description": "네트워크 오류로 서버 연결이 종료되었습니다. 베팅액의 5배를 잃었습니다."},
            {"name": "무지개는 떴지만...", "multiplier": -5.0,
             "image_url": "https://i.imgur.com/P9UMddQ.jpeg",
             "description": "아쉽게도 중복만 나왔네요. 베팅액의 5배를 잃었습니다."},
            {"name": "이건 좀...", "multiplier": -5.0,
             "image_url": "https://i.imgur.com/P9UMddQ.jpeg",
             "description": "운이 너무 없군요. 베팅액의 5배를 잃었습니다."},
        ],
    },
}


# ═══════════════════════════════════════════════════════════
# 확률 선택 유틸리티
# ═══════════════════════════════════════════════════════════

def _pick_by_probability(data_dict, key="prob"):
    """확률 기반 가중치 선택. data_dict의 각 값에 key로 지정된 확률이 있어야 함."""
    items = list(data_dict.items())
    weights = [v[key] for _, v in items]
    chosen_name, chosen_data = random.choices(items, weights=weights, k=1)[0]
    return chosen_name, chosen_data


def _pick_tier(tiers):
    """보스 티어 확률 선택."""
    return _pick_by_probability(tiers)


# ═══════════════════════════════════════════════════════════
# 가챠 실행
# ═══════════════════════════════════════════════════════════

async def run_gacha_sequence(interaction: discord.Interaction, udata: dict, bet_amount: int):
    """가챠 베팅 실행. interaction은 이미 defer된 상태여야 합니다."""
    result_name, result_data = _pick_by_probability(GACHA_DATA)

    # GIF 연출
    gacha_embed = discord.Embed(
        title=f"{interaction.user.display_name}님의 가챠 결과는...",
        color=COLOR_DEFAULT,
    )
    gacha_embed.set_image(url=result_data["gif_url"])
    await interaction.edit_original_response(embed=gacha_embed)
    await asyncio.sleep(result_data["duration"] + 0.2)

    # 결과 계산
    winnings = int(bet_amount * result_data["multiplier"])
    udata["money"] = udata.get("money", 0) + winnings

    # 결과 임베드
    result_embed = discord.Embed(
        title=f"{interaction.user.display_name}님의 가챠 결과",
        description=(
            f"{result_data['message']}\n\n"
            f"**확률**: {result_data['prob']}%"
        ),
        color=result_data["color"],
    )
    result_embed.add_field(name="베팅액", value=f"{bet_amount:,}원", inline=True)
    result_embed.add_field(name="획득/손실", value=f"{winnings:+,}원", inline=True)
    result_embed.add_field(name="현재 잔액", value=f"{udata['money']:,}원", inline=False)

    if result_name == "프라나의 3성 밑장빼기":
        source = result_data.get("source_url", "")
        if source:
            result_embed.description += f"\n\n[GIF 출처]({source})"

    result_embed.set_image(url=result_data["static_image_url"])
    result_embed.set_footer(text=FOOTER_TEXT, icon_url=BOT_ICON_URL)
    await interaction.edit_original_response(embed=result_embed)

    return result_name, winnings


# ═══════════════════════════════════════════════════════════
# 총력전배치고사 실행
# ═══════════════════════════════════════════════════════════

async def run_assault_sequence(interaction: discord.Interaction, udata: dict, bet_amount: int):
    """총력전 배치고사 실행. interaction은 이미 defer된 상태여야 합니다."""
    boss_name = random.choice(list(BOSS_DATA.keys()))
    boss = BOSS_DATA[boss_name]

    # 보스 컷씬
    boss_embed = discord.Embed(
        title=f"🚨 총력전 보스 - {boss_name} 등장!",
        description="이제 당신의 랭킹을 가늠할 시간입니다!",
        color=COLOR_ERROR,
    )
    boss_embed.set_image(url=boss["intro_gif_url"])
    await interaction.edit_original_response(embed=boss_embed)
    await asyncio.sleep(boss["intro_duration"] + 0.2)

    # 티어 결정
    tier_name, tier_data = _pick_tier(boss["tiers"])
    winnings = int(bet_amount * tier_data["multiplier"])
    udata["money"] = udata.get("money", 0) + winnings

    # 결과 임베드
    result_embed = discord.Embed(
        title=f"✨ 최종 결과 - {tier_name}",
        description=tier_data["message"],
        color=tier_data["color"],
    )
    result_embed.add_field(name="베팅액", value=f"{bet_amount:,}원", inline=True)
    result_embed.add_field(name="획득/손실", value=f"{winnings:+,}원", inline=True)
    result_embed.add_field(name="현재 잔액", value=f"{udata['money']:,}원", inline=False)
    result_embed.add_field(
        name="보스별 티어 확률",
        value=f"총력전 보스: {boss_name}\n**{tier_name} 확률**: {tier_data['prob']}%",
        inline=False,
    )
    result_embed.set_image(url=boss["outro_image_url"])
    result_embed.set_footer(text=FOOTER_TEXT, icon_url=BOT_ICON_URL)
    await interaction.edit_original_response(embed=result_embed)

    return boss_name, tier_name, winnings


# ═══════════════════════════════════════════════════════════
# 리세마라 실행
# ═══════════════════════════════════════════════════════════

async def run_reroll_sequence(interaction: discord.Interaction, udata: dict, bet_amount: int):
    """계정 리세마라 실행. interaction은 이미 defer된 상태여야 합니다."""
    grade_name, grade_data = _pick_by_probability(REROLL_DATA)
    student = random.choice(grade_data["students"])

    # GIF 연출
    reroll_embed = discord.Embed(
        title=f"{interaction.user.display_name}님의 리세마라 결과는...",
        color=COLOR_DEFAULT,
    )
    reroll_embed.set_image(url=grade_data["gif_url"])
    await interaction.edit_original_response(embed=reroll_embed)
    await asyncio.sleep(grade_data["duration"] + 0.2)

    # 결과 계산
    winnings = int(bet_amount * student["multiplier"])
    udata["money"] = udata.get("money", 0) + winnings

    # 결과 임베드
    result_embed = discord.Embed(
        title=f"🎉 리세마라 성공! {student['name']} 획득!",
        description=f"{grade_data['message']}\n\n**{student['name']}**: {student['description']}",
        color=grade_data["color"],
    )
    result_embed.add_field(name="등급", value=f"**{grade_name}**", inline=True)
    result_embed.add_field(name="확률", value=f"**{grade_data['prob']}%**", inline=True)
    result_embed.add_field(name="베팅액", value=f"{bet_amount:,}원", inline=False)
    result_embed.add_field(name="획득/손실", value=f"{winnings:+,}원", inline=True)
    result_embed.add_field(name="현재 잔액", value=f"{udata['money']:,}원", inline=True)
    result_embed.set_image(url=student["image_url"])
    result_embed.set_footer(text=FOOTER_TEXT, icon_url=BOT_ICON_URL)
    await interaction.edit_original_response(embed=result_embed)

    return grade_name, student["name"], winnings
