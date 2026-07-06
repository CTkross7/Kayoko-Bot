# commands/general.py
"""
일반 커맨드 Cog - Balance v2
- /가입: 약관 동의 + 가입 처리
- /캣맘정보: 유저 프로필 (본인/타인)
- /튜토리얼: 튜토리얼 진행 상태
- /일일보상: 매일 보상 수령
- /도움말: 카테고리별 도움말
- /가이드: 빠른 시작 가이드
- /규정: 약관 확인
- /유저정보: 디스코드 유저 정보
- /출석: 연속 출석 보상
"""

import discord
from discord import app_commands, Interaction, Embed, ui
from discord.ext import commands
from datetime import datetime, timedelta

from config import (
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING,
    BOT_ICON_URL, MAX_LEVEL, EXP_FOR_LEVEL,
    SKILL_TREE_TRACKING, SKILL_TREE_COMBAT, SKILL_TREE_TRADE,
    RARITY_TIERS, DAILY_LOGIN_REWARD,
    TUTORIAL_STEPS, TUTORIAL_COMPLETE_REWARD,
    NEWBIE_PROTECTION_DAYS, DAILY_LIMITS
)
from models.user import (
    load_user_data, save_user_data, create_user_data,
    add_exp, get_skill_effect, is_newbie, get_newbie_days_remaining,
    get_daily_counts_summary, advance_tutorial,
    calculate_catchup_bonus, get_active_buff_value
)
from systems.anticheat import run_anticheat_checks
from utils.checks import is_registered, is_not_banned


# ============================================================
# 밴/서버 차단 데이터 헬퍼
# ============================================================

import json
import os

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_BAN_FILE = os.path.join(_DATA_DIR, "user_ban.json")
_SERVER_BLOCK_FILE = os.path.join(_DATA_DIR, "server_block.json")


def _load_json(filepath: str) -> dict:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _is_user_banned(user_id: str) -> tuple[bool, str]:
    """유저 밴 여부 + 사유"""
    ban_data = _load_json(_BAN_FILE)
    entry = ban_data.get(user_id, {})
    if isinstance(entry, dict) and entry.get("banned", False):
        return True, entry.get("reason", "사유 없음")
    return False, ""

# ============================================================
# rarity 안전 변환 헬퍼
# ============================================================

def _safe_rarity_str(raw_rarity) -> str:
    if isinstance(raw_rarity, str):
        return raw_rarity
    try:
        for rarity_key, tier_info in RARITY_TIERS.items():
            if isinstance(tier_info, dict):
                w = tier_info.get("weight", tier_info.get("probability", None))
                if w is not None and abs(float(w) - float(raw_rarity)) < 0.001:
                    return rarity_key
            elif isinstance(tier_info, (int, float)):
                if abs(float(tier_info) - float(raw_rarity)) < 0.001:
                    return rarity_key
    except Exception:
        pass
    tier_map = {0: "common", 1: "uncommon", 2: "rare", 3: "epic", 4: "legendary", 5: "mythic"}
    if isinstance(raw_rarity, (int, float)) and int(raw_rarity) in tier_map:
        return tier_map[int(raw_rarity)]
    return "common"


# ============================================================
# 일일 보상 로직
# ============================================================

def claim_daily_reward(user_data: dict) -> tuple[bool, int, str]:
    today = datetime.now().strftime("%Y-%m-%d")
    last_daily = user_data.get("last_daily", "")

    if last_daily == today:
        return False, 0, "⏳ 오늘의 일일 보상은 이미 수령했습니다.\n내일 다시 방문해주세요!"

    streak = user_data.get("daily_streak", 0)
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    if last_daily == yesterday:
        streak += 1
    else:
        streak = 1

    base_reward = DAILY_LOGIN_REWARD
    streak_bonus = min(streak, 30) * 50
    total_reward = base_reward + streak_bonus

    tuna_bonus = 0
    if streak % 7 == 0:
        tuna_bonus = 1

    special_bonus = 0
    if streak % 30 == 0:
        special_bonus = 5000
        total_reward += special_bonus

    user_data["money"] = user_data.get("money", 0) + total_reward
    if tuna_bonus > 0:
        user_data["tuna_can"] = user_data.get("tuna_can", 0) + tuna_bonus
    user_data["last_daily"] = today
    user_data["daily_streak"] = streak

    msg_lines = [
        f"💰 **{base_reward:,}원** 지급!",
    ]
    if streak_bonus > 0:
        msg_lines.append(f"🔥 연속 출석 보너스: **+{streak_bonus:,}원** ({streak}일 연속)")
    if tuna_bonus > 0:
        msg_lines.append(f"🐟 7일 연속 보너스: **참치캔 {tuna_bonus}개** 추가!")
    if special_bonus > 0:
        msg_lines.append(f"🎉 30일 연속 특별 보너스: **+{special_bonus:,}원**!")

    msg_lines.append(f"\n총 지급: **{total_reward:,}원**")

    return True, total_reward, "\n".join(msg_lines)


# ============================================================
# 튜토리얼 임베드 빌더
# ============================================================

def build_tutorial_embed(user_data: dict) -> Embed:
    current_step = user_data.get("tutorial_step", "complete")

    embed = Embed(
        title="📘 튜토리얼 진행 상태",
        color=COLOR_PRIMARY
    )

    if current_step == "complete" or user_data.get("tutorial_completed", False):
        embed.description = "🎉 **튜토리얼을 모두 완료했습니다!**\n자유롭게 게임을 즐겨주세요."
        embed.color = COLOR_SUCCESS
        return embed

    step_order = []
    step = "welcome"
    visited = set()
    while step and step != "complete" and step not in visited:
        visited.add(step)
        step_info = TUTORIAL_STEPS.get(step)
        if step_info:
            step_order.append((step, step_info))
            step = step_info.get("next")
        else:
            break

    current_index = -1
    for i, (step_key, _) in enumerate(step_order):
        if step_key == current_step:
            current_index = i
            break

    for i, (step_key, step_info) in enumerate(step_order):
        if i < current_index:
            status = "✅"
        elif i == current_index:
            status = "👉"
        else:
            status = "⬜"

        display_name = step_info.get("title", step_key)
        description = step_info.get("description", "")

        reward_parts = []
        if step_info.get("reward_money", 0) > 0:
            reward_parts.append(f"💰 {step_info['reward_money']:,}원")
        if step_info.get("reward_exp", 0) > 0:
            reward_parts.append(f"✨ {step_info['reward_exp']} EXP")
        reward_text = f"\n🎁 보상: {', '.join(reward_parts)}" if reward_parts else ""

        embed.add_field(
            name=f"{status} {display_name}",
            value=f"{description}{reward_text}" if description else f"다음 단계를 진행하세요!{reward_text}",
            inline=False
        )

    if current_index >= 0:
        _, current_info = step_order[current_index]
        embed.add_field(
            name="📌 현재 목표",
            value=current_info.get("description", "다음 단계를 진행하세요!"),
            inline=False
        )

    embed.set_footer(text="튜토리얼 완료 시 특별 보상이 지급됩니다!", icon_url=BOT_ICON_URL)
    return embed

# ============================================================
# 가입 동의 뷰
# ============================================================

class JoinAgreeView(ui.View):
    def __init__(self, discord_user_id: int, user_id_str: str, user_data: dict | None, discord_user: discord.User = None):
        super().__init__(timeout=300)
        self.discord_user_id = discord_user_id
        self.user_id_str = user_id_str
        self.user_data = user_data
        self.discord_user = discord_user

    @ui.button(label="동의하고 가입하기", style=discord.ButtonStyle.success, emoji="✅")
    async def agree_button(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id != self.discord_user_id:
            await interaction.response.send_message("❌ 이 버튼은 다른 사용자의 것입니다.", ephemeral=True)
            return

        if self.user_data is None or not self.user_data:
            self.user_data = create_user_data(self.user_id_str)

        self.user_data["agreement"] = True
        self.user_data["registered_at"] = datetime.now().isoformat()
        self.user_data["tutorial_step"] = "first_kidnap"

        # ★ 디스코드 실제 유저 정보 저장
        self.user_data["username"] = interaction.user.name
        self.user_data["display_name"] = interaction.user.display_name

        welcome_step = TUTORIAL_STEPS.get("welcome", {})
        reward_text = ""

        reward_money = welcome_step.get("reward_money", 0)
        reward_exp = welcome_step.get("reward_exp", 0)

        if reward_money > 0:
            self.user_data["money"] = self.user_data.get("money", 0) + reward_money
            reward_text += f"\n💰 가입 보상: **{reward_money:,}원**"
        if reward_exp > 0:
            add_exp(self.user_data, reward_exp)
            reward_text += f"\n✨ 경험치: **+{reward_exp} EXP**"

        save_user_data(self.user_id_str, self.user_data)

        result_text = (
            "✅ **가입이 완료되었습니다!**\n"
            "봇의 모든 기능을 사용할 수 있습니다."
            f"{reward_text}\n\n"
            f"🌱 **뉴비 보호** {NEWBIE_PROTECTION_DAYS}일 활성화!\n"
            "  경험치 +50%, 보상금 +30%, 패배 페널티 면제\n\n"
            "💡 `/튜토리얼`로 가이드 퀘스트를 확인하세요!\n"
            "💡 `/납치`로 첫 냥이를 잡아보세요!"
        )

        for item in self.children:
            item.disabled = True

        embed = Embed(
            title="🎉 가입 완료!",
            description=result_text,
            color=COLOR_SUCCESS
        )
        embed.set_footer(text="카요코봇을 사용해 주셔서 감사합니다!", icon_url=BOT_ICON_URL)

        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="취소", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id != self.discord_user_id:
            await interaction.response.send_message("❌ 이 버튼은 다른 사용자의 것입니다.", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True

        embed = Embed(
            title="↩️ 가입 취소",
            description="가입을 취소했습니다.\n게임을 시작하려면 `/가입`을 다시 사용해주세요.",
            color=COLOR_WARNING
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ============================================================
# 도움말 드롭다운
# ============================================================

HELP_CATEGORIES = {
    "🐾 납치 시스템": {
        "color": 0xF8A8C4,
        "fields": [
            ("📝 사용 방법", "`/납치` 명령어를 사용하면 냥이 수색이 시작됩니다.\n❗ 버튼이 나타나면 빠르게 눌러 포획하세요!\n❓ 버튼은 **페이크**입니다. 속지 마세요!"),
            ("💡 팁", "추적 스킬을 올리면 희귀 냥이 등장률이 증가하고,\n반응속도가 빠를수록 성공률 보너스를 받습니다.\n일일 납치 횟수: 최대 100회"),
        ],
    },
    "📊 성장 시스템": {
        "color": 0x57F287,
        "fields": [
            ("🎯 레벨업", f"납치/전투/미궁에서 경험치를 획득합니다.\n최대 레벨: Lv.{MAX_LEVEL}\n레벨업 시 스킬 포인트를 획득합니다."),
            ("🐾 스킬 트리", "**🔍 추적**: 납치 성공률, 희귀도 보너스\n**⚔️ 전투**: 전투력, 체력 보너스\n**💼 교역**: 상점 할인, 판매가 보너스\n`/스킬`로 확인, `/스킬투자`로 투자!"),
            ("🌱 뉴비 보호", f"가입 후 **{NEWBIE_PROTECTION_DAYS}일** 동안 뉴비 보호 활성\n경험치 +50%, 보상금 +30%, 패배 페널티 면제"),
        ],
    },
    "🗺️ 지역 시스템": {
        "color": 0x5865F2,
        "fields": [
            ("🌍 지역 탐험", "각 지역마다 다른 냥이가 출현합니다.\n새 지역을 해금하려면 레벨 + 돈이 필요합니다."),
            ("🔓 명령어", "`/지역목록` — 전체 지역 확인\n`/지역이동` — 해금된 지역으로 이동\n`/지역해금` — 새 지역 해금"),
        ],
    },
    "⚔️ 전투 시스템": {
        "color": 0xED4245,
        "fields": [
            ("🗡️ 전투 방법", f"`/전투`로 현재 지역의 적과 전투합니다.\n보유 냥이를 파티에 편성하여 전투!\n일일 전투 횟수: 최대 {DAILY_LIMITS.get('battle', 30)}회"),
            ("🏛️ 미궁", f"`/미궁`으로 무한 미궁에 도전합니다.\n층을 올라갈수록 보상이 커지지만 적도 강해집니다.\n일일 미궁 횟수: 최대 {DAILY_LIMITS.get('labyrinth', 5)}회"),
            ("👹 주간 보스", "`/주간보스`로 강력한 보스에 도전합니다.\n매주 월요일 초기화, 주당 3회 도전 가능"),
        ],
    },
    "🛒 상점 시스템": {
        "color": 0xFEE75C,
        "fields": [
            ("🏪 상점", "`/상점`으로 상점을 열어 다양한 아이템을 구매하세요.\n소모품, 장비, 랜덤 박스, 참치캔 상점, 도박장이 있습니다."),
            ("⚔️ 장비 시스템", "`/장비` — 장비 인벤토리 관리\n`/장착 [번호]` — 장비 장착\n`/장착해제 [슬롯]` — 장착 해제\n`/장비판매 [번호]` — 장비 판매\n장비 슬롯: 무기, 방어구, 장신구, 특수 (총 4개)\n스탯 총합 상한제가 적용됩니다."),
            ("🧪 소모품", "`/사용` — 보유 소모품 확인\n`/사용 [아이템이름]` — 소모품 사용\n`/인벤토리` — 소모품 인벤토리"),
        ],
    },
    "🐱 냥이 도감": {
        "color": 0xA8D8EA,
        "fields": [
            ("📖 도감/인벤토리", "`/냥이도감` — 전체 냥이 도감 (미발견 = ???)\n`/냥이인벤토리` — 보유 냥이 목록\n`/냥이분양 [이름]` — 냥이 판매"),
            ("💎 희귀도", "⬜ 일반 → 🟩 고급 → 🟦 희귀 → 🟪 영웅 → 🟨 전설 → ❤️ 신화\n높은 지역일수록 희귀한 냥이가 등장합니다."),
        ],
    },
    "📋 기타 기능": {
        "color": 0x99AAB5,
        "fields": [
            ("💰 경제", "`/송금 [유저] [금액]` — 다른 유저에게 송금 (수수료 5%)\n`/도박` — 동전 던지기 / 슬롯머신"),
            ("📊 랭킹/통계", "`/캣맘랭킹` — 냥이 보유 랭킹\n`/보유금랭킹` — 보유금 랭킹\n`/전투기록` — 전투 통계\n`/미궁기록` — 미궁 통계\n`/일일현황` — 오늘 활동 현황\n`/납치현황` — 현재 지역 납치 정보"),
            ("🚨 신고", "`/신고 [유저] [사유]` — 부적절한 유저 신고"),
        ],
    },
}


class HelpDropdown(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=cat_name, value=cat_name)
            for cat_name in HELP_CATEGORIES.keys()
        ]
        super().__init__(placeholder="📂 궁금한 카테고리를 선택하세요…", options=options)

    async def callback(self, interaction: Interaction):
        cat_name = self.values[0]
        data = HELP_CATEGORIES[cat_name]
        embed = Embed(title=cat_name, color=data["color"])
        for field_name, field_value in data["fields"]:
            embed.add_field(name=field_name, value=field_value, inline=False)
        embed.set_footer(text="📂 드롭다운에서 다른 카테고리를 선택하면 내용이 변경됩니다.")
        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpDropdownView(ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(HelpDropdown())

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

# ============================================================
# Cog 정의
# ============================================================

class GeneralCog(commands.Cog):
    """일반 명령어"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="가입", description="약관에 동의하고 게임을 시작합니다.")
    async def join_command(self, interaction: Interaction):

        banned, reason = _is_user_banned(str(interaction.user.id))
        if banned:
            embed = Embed(title="🚫 이용 제한", description=f"귀하의 계정은 이용이 제한되었습니다.\n**사유**: {reason}", color=COLOR_ERROR)
            await interaction.response.send_message(embed=embed, ephemeral=False)
            return

        user_id_str = str(interaction.user.id)
        user_data = load_user_data(user_id_str)

        if user_data and user_data.get("agreement", False):
            await interaction.response.send_message("❌ 이미 가입되어 있습니다.", ephemeral=True)
            return

        embed = Embed(title="📜 약관 및 규정 동의", description="이 봇을 이용하기 위해서는 약관에 동의해야 합니다.\n아래 내용을 확인하고 동의 버튼을 눌러주세요.", color=COLOR_PRIMARY)
        embed.add_field(name="[ 제 1 조 ] 저작권 및 기여자", value="`1항` 봇의 소스코드 및 텍스트의 저작권은 개발자 `CTkross`에게 있습니다.\n`2항` 타인 기여분의 저작권은 해당 기여자에게 있습니다.\n`3항` 기여자는 기여를 통해 `CTkross`에게 비상업적, 영구적 이용을 허락합니다.", inline=False)
        embed.add_field(name="[ 제 2 조 ] 개인정보의 수집 및 활용", value="`1항` 서비스 제공을 위해 `Discord User ID`와 `Play Date`를 수집하며, 카요코 봇 서버에 보관됩니다.", inline=False)
        embed.add_field(name="[ 제 3 조 ] 금지 행위 및 제재", value="**1항** 부정한 이익 취득(버그 악용), 정상 서비스 방해(매크로), 서비스 목적 훼손(비방/음란)은 금지되며 위반 시 경고 및 처벌이 적용됩니다.\n**2항** 경고 누적 시 영구 밴 및 데이터 초기화가 포함될 수 있습니다.\n**3항** 경고/처벌 우회 행위도 금지되며 즉시 영구 밴 처리됩니다.", inline=False)
        embed.add_field(name="[ 제 4 조 ] 약관의 효력 및 변경", value="**1항** 가입 시 약관에 동의한 것으로 간주합니다.\n**2항** 약관/공지 미숙지로 인한 손해는 책임지지 않습니다.\n**3항** 약관은 예고 없이 변경될 수 있고 변경 즉시 효력을 가집니다.", inline=False)
        embed.add_field(name="🔔 공식 서버", value="약관 및 공지는 [카요코 봇 공식 서버](https://discord.gg/6Xava2SkGR)에 게시됩니다.", inline=False)

        view = JoinAgreeView(interaction.user.id, user_id_str, user_data, discord_user=interaction.user)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="캣맘정보", description="캣맘 정보를 확인합니다.")
    @app_commands.describe(target="정보를 볼 유저 (미입력 시 본인)")
    @is_not_banned()
    async def catmom_info(self, interaction: Interaction, target: discord.User = None):
        await interaction.response.defer()
        if target is None:
            target = interaction.user
        user_id_str = str(target.id)
        user_data = load_user_data(user_id_str)
        if not user_data or not user_data.get("agreement", False):
            await interaction.followup.send(f"⚠️ **{target.display_name}**님은 아직 가입하지 않았습니다.", ephemeral=True)
            return

        # ★ username/display_name 자동 갱신
        updated = False
        if user_data.get("username") in (None, "", "Unknown"):
            user_data["username"] = target.name
            updated = True
        if user_data.get("display_name") in (None, "", "Unknown"):
            user_data["display_name"] = target.display_name
            updated = True
        if updated:
            save_user_data(user_id_str, user_data)

        level = user_data.get("level", 1)
        exp = user_data.get("exp", 0)
        next_exp = EXP_FOR_LEVEL(level)
        money = user_data.get("money", 0)
        tuna_can = user_data.get("tuna_can", 0)
        skill_points = user_data.get("skill_points", 0)
        skills = user_data.get("skills", {})
        current_region = user_data.get("current_region", "서울 뒷골목")

        if next_exp > 0:
            ratio = min(exp / next_exp, 1.0)
        else:
            ratio = 1.0
        bar_filled = int(ratio * 20)
        bar_empty = 20 - bar_filled
        exp_bar = "█" * bar_filled + "░" * bar_empty

        if level >= MAX_LEVEL:
            level_display = f"Lv.{level} **(MAX)**"
        else:
            level_display = f"Lv.{level}"

        owned_cats = user_data.get("cats", user_data.get("owned_cats", {}))
        total_cats = 0
        for v in owned_cats.values():
            if isinstance(v, dict):
                total_cats += v.get("count", 0)
            else:
                total_cats += int(v)
        catdex_count = len(user_data.get("catdex", {}))
        if isinstance(user_data.get("catdex"), list):
            catdex_count = len(user_data.get("catdex", []))

        stats = user_data.get("stats", {})
        battle_stats = user_data.get("battle_stats", {})
        labyrinth_stats = user_data.get("labyrinth_stats", {})

        # ★ 최상위 키가 0이면 stats 내부도 확인 (0은 falsy하므로 or 사용)
        total_kidnaps = (
            user_data.get("total_kidnaps")
            or stats.get("total_kidnaps", 0)
            or stats.get("successful_kidnaps", 0)
        )

        total_battles = (
            battle_stats.get("total_battles")
            or stats.get("total_battles", 0)
        )

        battle_wins = (
            battle_stats.get("victories")
            or stats.get("battle_wins", 0)
        )

        best_floor = (
            labyrinth_stats.get("highest_floor")
            or stats.get("labyrinth_best_floor", 0)
            or user_data.get("labyrinth_best_floor", 0)
        )

        rare_bonus = get_skill_effect(user_data, SKILL_TREE_TRACKING, "rare_chance_bonus")
        combat_power = get_skill_effect(user_data, SKILL_TREE_COMBAT, "battle_power_bonus")
        shop_discount = get_skill_effect(user_data, SKILL_TREE_TRADE, "shop_discount")

        equipped_title = user_data.get("equipped_title")
        title_display = f"『{equipped_title}』" if equipped_title else ""

        embed = Embed(title=f"💖 {target.display_name}의 캣맘 정보 {title_display}", color=COLOR_PRIMARY)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="📊 기본 정보", value=f"**{level_display}** | {exp:,}/{next_exp:,} EXP\n`{exp_bar}` ({ratio * 100:.1f}%)\n📍 {current_region}", inline=False)
        embed.add_field(name="💰 재화", value=f"💵 **{money:,}원**\n🐟 **{tuna_can}개**", inline=True)
        embed.add_field(name="🐱 냥이", value=f"보유: **{total_cats}마리**\n도감: **{catdex_count}종**", inline=True)
        embed.add_field(name=f"⭐ 스킬 (잔여 {skill_points}P)", value=f"🔍 추적술 Lv.{skills.get(SKILL_TREE_TRACKING, 0)} | ⚔️ 전투술 Lv.{skills.get(SKILL_TREE_COMBAT, 0)} | 💼 상술 Lv.{skills.get(SKILL_TREE_TRADE, 0)}", inline=False)

        effect_parts = []
        if rare_bonus > 0:
            effect_parts.append(f"희귀+{rare_bonus:.1f}%")
        if combat_power > 0:
            effect_parts.append(f"전투력+{combat_power:.1f}")
        if shop_discount > 0:
            effect_parts.append(f"할인-{shop_discount:.1f}%")
        if effect_parts:
            embed.add_field(name="🔧 스킬 효과", value=" | ".join(effect_parts), inline=False)

        embed.add_field(name="📈 활동 통계", value=f"🐾 납치: **{total_kidnaps}회** | ⚔️ 전투: **{total_battles}회** (승{battle_wins}) | 🏛️ 미궁 최고: **{best_floor}층**", inline=False)

        if is_newbie(user_data):
            remaining = get_newbie_days_remaining(user_data)
            embed.add_field(name="🌱 뉴비 보호", value=f"활성 중 (잔여 **{remaining}일**)", inline=True)

        catchup = calculate_catchup_bonus(user_data)
        if catchup > 0:
            embed.add_field(name="📈 캐치업 보너스", value=f"경험치 +**{catchup * 100:.0f}%**", inline=True)

        active_buffs = user_data.get("active_buffs", {})
        buff_parts = []
        for bk, bv in active_buffs.items():
            if isinstance(bv, dict) and bv.get("uses_remaining", 0) > 0:
                buff_parts.append(f"{bk}+{bv.get('value', 0)}%({bv['uses_remaining']}회)")
        if buff_parts:
            embed.add_field(name="🧪 활성 버프", value=" | ".join(buff_parts), inline=False)

        achievements = user_data.get("achievements", {})
        if isinstance(achievements, dict):
            completed = [k for k, v in achievements.items() if v]
        elif isinstance(achievements, list):
            completed = achievements
        else:
            completed = []
        if completed:
            embed.add_field(name="🏆 업적", value=f"달성: **{len(completed)}개**", inline=True)

        streak = user_data.get("daily_streak", 0)
        if streak > 0:
            embed.add_field(name="🔥 연속 출석", value=f"**{streak}일**", inline=True)

        embed.set_footer(text="카요코 봇", icon_url=BOT_ICON_URL)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="튜토리얼", description="현재 튜토리얼 진행 상태를 확인합니다.")
    @is_registered()
    @is_not_banned()
    async def tutorial_command(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        user_data = load_user_data(str(interaction.user.id))
        embed = build_tutorial_embed(user_data)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="일일보상", description="매일 한 번 보상을 수령합니다.")
    @is_registered()
    @is_not_banned()
    async def daily_reward_command(self, interaction: Interaction):
        await interaction.response.defer()
        user_id_str = str(interaction.user.id)
        user_data = load_user_data(user_id_str)
        success, amount, message = claim_daily_reward(user_data)

        if success:
            save_user_data(user_id_str, user_data)
            embed = Embed(title="🎁 일일 보상", description=message, color=COLOR_SUCCESS)
            embed.add_field(name="💰 현재 잔액", value=f"**{user_data.get('money', 0):,}원**", inline=True)
            embed.add_field(name="🔥 연속 출석", value=f"**{user_data.get('daily_streak', 0)}일**", inline=True)

            tutorial_step = user_data.get("tutorial_step", "complete")
            if tutorial_step == "daily_reward":
                advance_tutorial(user_data, "daily_reward")
                save_user_data(user_id_str, user_data)
                step_info = TUTORIAL_STEPS.get(user_data.get("tutorial_step", ""), {})
                if step_info:
                    tutorial_embed = Embed(title="📘 튜토리얼 진행!", description=step_info.get("description", "다음 단계로 진행합니다!"), color=COLOR_PRIMARY)
                    await interaction.followup.send(embed=tutorial_embed)
        else:
            embed = Embed(title="🎁 일일 보상", description=message, color=COLOR_WARNING)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="도움말", description="카요코 봇의 모든 기능을 안내합니다.")
    async def help_command(self, interaction: Interaction):
        embed = Embed(title="📖 카요코 봇 도움말", description="카요코 봇의 기능을 안내합니다!\n아래 드롭다운 메뉴에서 카테고리를 선택해 주세요.\n━━━━━━━━━━━━━━━━━━━━", color=COLOR_PRIMARY)
        embed.add_field(name="🐾 납치", value="지역을 탐험하며 냥이를 납치합니다.", inline=True)
        embed.add_field(name="📊 성장", value="레벨업하고 스킬을 투자합니다.", inline=True)
        embed.add_field(name="🗺️ 지역", value="다양한 지역을 해금하고 이동합니다.", inline=True)
        embed.add_field(name="⚔️ 전투", value="적과 전투하고 보상을 획득합니다.", inline=True)
        embed.add_field(name="🛒 상점", value="아이템 구매/장비 관리를 합니다.", inline=True)
        embed.add_field(name="🐱 도감", value="수집한 냥이를 확인합니다.", inline=True)
        embed.add_field(name="📋 기타", value="송금, 랭킹, 도박, 신고 등", inline=True)
        embed.add_field(name="\u200b", value="━━━━━━━━━━━━━━━━━━━━\n💡 **팁**: `/가이드` 명령어로 빠른 시작 가이드를 볼 수 있어요!", inline=False)
        embed.set_footer(text="⏱ 이 메뉴는 5분 후 자동으로 비활성화됩니다.")
        if BOT_ICON_URL:
            embed.set_thumbnail(url=BOT_ICON_URL)
        view = HelpDropdownView()
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="가이드", description="카요코 봇 빠른 시작 가이드입니다.")
    async def guide_command(self, interaction: Interaction):
        e1 = Embed(title="🚀 카요코 봇 빠른 시작 가이드", description="카요코 봇을 처음 사용하시나요?\n아래 단계를 따라 해 보세요!", color=COLOR_PRIMARY)
        e1.add_field(name="Step 1 │ 가입하기", value="`/가입` 명령어로 약관에 동의하고 시작하세요!\n가입 보상과 뉴비 보호가 적용됩니다.", inline=False)
        e1.add_field(name="Step 2 │ 첫 납치", value="`/납치` 명령어로 첫 냥이를 잡아보세요!\n❗ 버튼이 나타나면 빠르게 눌러 포획!\n⚠️ ❓ 버튼은 **페이크**입니다!", inline=False)
        e1.add_field(name="Step 3 │ 성장하기", value="납치/전투/미궁에서 경험치를 획득하여 레벨업!\n`/스킬`로 스킬 트리 확인, `/스킬투자`로 투자하세요.", inline=False)
        e1.add_field(name="Step 4 │ 지역 탐험", value="레벨이 오르면 새로운 지역을 해금할 수 있습니다.\n`/지역목록`으로 확인하고 `/지역해금`으로 해금!", inline=False)
        e1.add_field(name="Step 5 │ 전투와 미궁", value="`/전투`로 보상 획득, `/미궁`으로 무한 도전!\nLv.20 이상이면 `/주간보스`에도 도전 가능합니다.", inline=False)
        e1.add_field(name="Step 6 │ 일일 보상", value="`/일일보상` 명령어로 매일 보상을 받을 수 있어요!\n연속 출석 보너스와 7일/30일 특별 보상도 있습니다.", inline=False)
        if BOT_ICON_URL:
            e1.set_thumbnail(url=BOT_ICON_URL)

        e2 = Embed(title="❓ 자주 묻는 질문 (FAQ)", color=0xA8D8EA)
        e2.add_field(name="Q. 페이크 버튼이 뭔가요?", value="납치 시 ❓ 이모지의 가짜 버튼이 등장할 수 있습니다.\n가짜 버튼을 누르면 무조건 실패! ❗ 버튼이 진짜입니다.", inline=False)
        e2.add_field(name="Q. 반응속도가 중요한가요?", value="네! ❗ 버튼을 빨리 누를수록 성공률 보너스를 받습니다.\n500ms 이하: +15%, 1초: +10%, 5초 이상: -5%", inline=False)
        e2.add_field(name="Q. 뉴비 보호 기간은?", value=f"가입 후 **{NEWBIE_PROTECTION_DAYS}일** 동안 활성됩니다.\n경험치 +50%, 보상금 +30%, 전투 패배 페널티 면제!", inline=False)
        e2.add_field(name="Q. 매크로 사용하면 어떻게 되나요?", value="안티치트 시스템이 자동으로 비정상 플레이를 감지합니다.\n경고 누적 시 **자동 영구 차단** 처리됩니다.", inline=False)
        e2.set_footer(text="카요코 봇 공식 서버 참여를 적극 권장드립니다.")

        await interaction.response.send_message(embeds=[e1, e2])

    @app_commands.command(name="규정", description="봇의 약관 및 규정을 확인합니다.")
    async def regulation_command(self, interaction: Interaction):

        embed = Embed(title="📜 카요코 봇 이용 약관 및 규정", description="이 봇을 이용하는 모든 사용자는 아래 약관 및 규정에 동의한 것으로 간주합니다.", color=COLOR_PRIMARY)
        embed.add_field(name="[ 제 1 조 ] 저작권", value="봇의 소스코드 및 텍스트의 저작권은 개발자 `CTkross`에게 있습니다.", inline=False)
        embed.add_field(name="[ 제 2 조 ] 개인정보", value="서비스 제공을 위해 `Discord User ID`와 `Play Date`를 수집합니다.", inline=False)
        embed.add_field(name="[ 제 3 조 ] 금지행위", value="버그 악용, 매크로, 비방/음란 등은 금지됩니다.\n안티치트 시스템에 의해 자동 감지/경고/차단됩니다.", inline=False)
        embed.add_field(name="[ 제 4 조 ] 약관 효력", value="약관은 예고 없이 변경될 수 있고 변경 즉시 효력을 가집니다.", inline=False)
        embed.add_field(name="🔔 공식 서버", value="[카요코 봇 공식 서버](https://discord.gg/6Xava2SkGR)", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="유저정보", description="디스코드 유저 정보를 확인합니다.")
    @app_commands.describe(user="조회할 유저 (미입력 시 본인)")
    async def user_info_command(self, interaction: Interaction, user: discord.User = None):
        await interaction.response.defer()
        if user is None:
            user = interaction.user
        try:
            fetched_user = await interaction.client.fetch_user(user.id)
        except Exception:
            fetched_user = user
        member = interaction.guild.get_member(user.id) if interaction.guild else None
        embed = Embed(title=f"🔎 {fetched_user.display_name}의 정보", color=COLOR_PRIMARY)
        embed.set_thumbnail(url=fetched_user.display_avatar.url)
        embed.add_field(name="닉네임", value=fetched_user.display_name, inline=True)
        embed.add_field(name="사용자 ID", value=str(fetched_user.id), inline=True)
        embed.add_field(name="봇 여부", value="✅" if fetched_user.bot else "❌", inline=True)
        if member:
            status_map = {discord.Status.online: "🟢 온라인", discord.Status.idle: "🌙 자리 비움", discord.Status.dnd: "⛔ 방해 금지", discord.Status.offline: "⚪ 오프라인"}
            embed.add_field(name="상태", value=status_map.get(member.status, "알 수 없음"), inline=True)
            embed.add_field(name="최고 역할", value=member.top_role.mention if member.top_role else "없음", inline=True)
            if member.joined_at:
                embed.add_field(name="서버 가입일", value=member.joined_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
        embed.add_field(name="디스코드 가입일", value=fetched_user.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
        if fetched_user.banner:
            embed.set_image(url=fetched_user.banner.url)
        embed.set_footer(text="소스코드 제공: leeepv_ | 리팩토링: CTkross")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="출석", description="출석 체크합니다. (/일일보상과 동일)")
    @is_registered()
    @is_not_banned()
    async def attendance_command(self, interaction: Interaction):
        await self.daily_reward_command.callback(self, interaction)

    @app_commands.command(name="상성", description="속성 상성표를 확인합니다. (공격 vs 방어)")
    async def element_chart_command(self, interaction: Interaction):
        from models.element import (
            ATTACK_TYPES, DEFENSE_TYPES, ELEMENT_MATRIX,
            ELEM_EFFECTIVE, ELEM_RESIST,
        )
        embed = Embed(
            title="🔰 속성 상성표",
            description=(
                f"공격 속성이 방어 속성을 만났을 때의 데미지 배율입니다.\n"
                f"🔺 **유효** ×{ELEM_EFFECTIVE}　▪️ 보통 ×1.0　🔻 **저항** ×{ELEM_RESIST}\n"
                "선봉 냥이(`/편성`)의 속성이 전투 상성을 결정합니다."
            ),
            color=COLOR_PRIMARY,
        )

        def sym(m):
            if m >= ELEM_EFFECTIVE:
                return "🔺"
            if m <= ELEM_RESIST:
                return "🔻"
            return "▪️"

        for atk_key, atk_info in ATTACK_TYPES.items():
            row = ELEMENT_MATRIX.get(atk_key, {})
            parts = []
            for dfn_key, dfn_info in DEFENSE_TYPES.items():
                m = row.get(dfn_key, 1.0)
                parts.append(f"{sym(m)}{dfn_info['emoji']}{dfn_info['name']}")
            embed.add_field(
                name=f"{atk_info['emoji']} {atk_info['name']} 공격",
                value=" ".join(parts),
                inline=False,
            )

        embed.add_field(
            name="💡 핵심 3각 + 탄력",
            value=(
                "🔥폭발▶🟢경장갑　🎯관통▶🔵중장갑　🔮신비▶🟡특수장갑\n"
                "🟣탄력장갑은 폭발·관통·신비를 모두 버티고 💠**진동**에만 약합니다. (고난도 보스)"
            ),
            inline=False,
        )
        embed.set_footer(text=FOOTER_TEXT if 'FOOTER_TEXT' in globals() else "카요코 봇",
                         icon_url=BOT_ICON_URL)
        await interaction.response.send_message(embed=embed)


# ============================================================
# Cog 등록
# ============================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(GeneralCog(bot))
