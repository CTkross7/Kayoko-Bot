# commands/gameplay.py
"""
게임플레이 커맨드 Cog - Balance v2
"""

import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import json
import os
import random
from datetime import datetime

import config as _cfg
from utils.cooldown_lock import acquire_lock, release_lock, build_locked_embed


# ── config 값 로딩 ──
COLOR_DEFAULT = _cfg.COLOR_DEFAULT
COLOR_PRIMARY = _cfg.COLOR_INFO
COLOR_INFO = _cfg.COLOR_INFO
COLOR_SUCCESS = _cfg.COLOR_SUCCESS
COLOR_ERROR = _cfg.COLOR_ERROR
COLOR_WARNING = _cfg.COLOR_WARNING

RARITY_TIERS = _cfg.RARITY_TIERS
SKILL_EFFECTS = _cfg.SKILL_EFFECTS
MAX_SKILL_LEVEL = _cfg.MAX_SKILL_LEVEL
MAX_LEVEL = _cfg.MAX_LEVEL
DAILY_LIMITS = _cfg.DAILY_LIMITS

BOT_ICON_URL = _cfg.BOT_ICON_URL
LOCATION_EMOJIS = _cfg.LOCATION_EMOJIS
CATS_FILE = _cfg.CATS_FILE
REGIONS_FILE = _cfg.REGIONS_FILE
USERS_DIR = _cfg.USERS_DIR

TUTORIAL_STEPS = _cfg.TUTORIAL_STEPS
TUTORIAL_COMPLETION_REWARD = _cfg.TUTORIAL_COMPLETION_REWARD
NEWBIE_PROTECTION_DAYS = _cfg.NEWBIE_PROTECTION_DAYS
KIDNAP_BASE_MONEY_REWARD = _cfg.KIDNAP_BASE_MONEY_REWARD
REPORT_WEBHOOK_URL = getattr(_cfg, "REPORT_WEBHOOK_URL", "")

from systems.kidnap import run_kidnap_sequence, get_kidnap_stats_embed,auto_check_tutorial
from models.region import REGIONS, get_region_list


# ============================================================
# 스킬 한글명 매핑
# ============================================================

SKILL_DISPLAY_NAMES = {
    "tracking": "🔍 추적술",
    "combat": "⚔️ 전투술",
    "trade": "💼 상술",
}

SKILL_EFFECT_DISPLAY_NAMES = {
    "kidnap_success_bonus": "납치 성공률 보너스",
    "rare_chance_bonus": "희귀 냥이 확률 보너스",
    "hint_accuracy_bonus": "힌트 정확도 보너스",
    "battle_power_bonus": "전투력 보너스",
    "battle_hp_bonus": "전투 HP 보너스",
    "skill_damage_bonus": "스킬 데미지 보너스",
    "sell_price_bonus": "판매가 보너스",
    "shop_discount": "상점 할인",
    "daily_bonus_money": "일일 보너스 골드",
}


# ============================================================
# rarity 안전 변환 헬퍼
# ============================================================

def _safe_rarity_str(raw_rarity) -> str:
    if isinstance(raw_rarity, str):
        low = raw_rarity.lower()
        if low in RARITY_TIERS:
            return low
        return low
    try:
        for rarity_key, tier_info in RARITY_TIERS.items():
            if isinstance(tier_info, dict):
                w = tier_info.get("weight", tier_info.get("probability", None))
                if w is not None and abs(float(w) - float(raw_rarity)) < 0.001:
                    return rarity_key
    except Exception:
        pass
    tier_map = {0: "common", 1: "uncommon", 2: "rare", 3: "epic", 4: "legendary", 5: "mythic"}
    if isinstance(raw_rarity, (int, float)) and int(raw_rarity) in tier_map:
        return tier_map[int(raw_rarity)]
    return "common"


# ============================================================
# 유저 데이터 I/O
# ============================================================

def _user_path(uid):
    return os.path.join(USERS_DIR, f"{uid}.json")


def load_user_data(uid):
    p = _user_path(uid)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    # ★ 스킬포인트 자동 보정
    if not data.get("_sp_fixed"):
        level = data.get("level", 1)
        total_should = (level - 1) * _cfg.SKILL_POINTS_PER_LEVEL
        skills = data.get("skills", {})
        invested = sum(skills.get(t, 0) for t in ("tracking", "combat", "trade"))
        remaining = data.get("skill_points", 0)
        missing = total_should - (invested + remaining)
        if missing > 0:
            data["skill_points"] = remaining + missing
        data["_sp_fixed"] = True
        # 보정 결과 즉시 저장
        try:
            save_user_data(uid, data)
        except Exception:
            pass

    return data


def save_user_data(uid, data):
    os.makedirs(USERS_DIR, exist_ok=True)
    with open(_user_path(uid), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# 데이터 로드 헬퍼
# ============================================================

def load_cats_data() -> list:
    try:
        with open(CATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                if "cats" in data:
                    return data["cats"]
                return list(data.values())
            return data if isinstance(data, list) else []
    except Exception:
        return []


def get_cat_by_id(cats_data: list, cat_id: str):
    for cat in cats_data:
        if isinstance(cat, dict):
            if str(cat.get("id", cat.get("name", ""))) == str(cat_id):
                return cat
    return None

# ============================================================
# 유저 헬퍼 함수들
# ============================================================

def is_newbie(user_data):
    created = user_data.get("created_at")
    if not created:
        return False
    try:
        age = (datetime.utcnow() - datetime.fromisoformat(created)).days
        return age <= NEWBIE_PROTECTION_DAYS
    except Exception:
        return False


def get_newbie_days_remaining(user_data):
    created = user_data.get("created_at")
    if not created:
        return 0
    try:
        age = (datetime.utcnow() - datetime.fromisoformat(created)).days
        return max(0, NEWBIE_PROTECTION_DAYS - age)
    except Exception:
        return 0


def get_skill_effect(user_data, tree, effect_name):
    lv = user_data.get("skills", {}).get(tree, 0)
    per_level = SKILL_EFFECTS.get(tree, {}).get(effect_name, 0)
    return lv * per_level


def allocate_skill_point(user_data, skill_name):
    sp = user_data.get("skill_points", 0)
    if sp <= 0:
        return "❌ 스킬 포인트가 부족합니다."
    skills = user_data.setdefault("skills", {})
    current = skills.get(skill_name, 0)
    if current >= MAX_SKILL_LEVEL:
        return f"❌ 이미 최대 레벨({MAX_SKILL_LEVEL})입니다."
    skills[skill_name] = current + 1
    user_data["skill_points"] = sp - 1
    display_name = SKILL_DISPLAY_NAMES.get(skill_name, skill_name)
    return f"✅ **{display_name}** 스킬이 Lv.{current + 1}이 되었습니다!"


def advance_tutorial(user_data, completed_step):
    current = user_data.get("tutorial_step", "welcome")
    step_data = TUTORIAL_STEPS.get(current)
    if not step_data or current != completed_step:
        return False
    reward_money = step_data.get("reward_money", 0)
    reward_exp = step_data.get("reward_exp", 0)
    if reward_money:
        user_data["money"] = user_data.get("money", 0) + reward_money
    if reward_exp:
        user_data["exp"] = user_data.get("exp", 0) + reward_exp
    next_step = step_data.get("next")
    user_data["tutorial_step"] = next_step if next_step else "complete"
    return True


def get_daily_counts_summary(user_data):
    daily = user_data.get("daily_actions", {})
    dc = user_data.get("daily_counts", {})

    # ★ 두 소스 중 더 큰 값 사용 (동기화 누락 방지)
    summary = {}
    for key, limit in DAILY_LIMITS.items():
        from_actions = daily.get(key, 0) if key != "date" else 0
        from_counts = dc.get(key, 0)
        current = max(from_actions, from_counts)
        summary[key] = {"current": current, "max": limit, "remaining": max(0, limit - current)}
    return summary

def calculate_catchup_bonus(user_data):
    created = user_data.get("created_at")
    if not created:
        return 0
    try:
        age = (datetime.utcnow() - datetime.fromisoformat(created)).days
        if age <= NEWBIE_PROTECTION_DAYS:
            return (1.0 - age / NEWBIE_PROTECTION_DAYS) * _cfg.CATCHUP_EXP_BONUS_MAX
    except Exception:
        pass
    return 0


def _owned_cats_to_list(raw_cats) -> list:
    """유저의 cats 데이터를 항상 리스트로 변환"""
    if isinstance(raw_cats, list):
        return raw_cats
    if isinstance(raw_cats, dict):
        result = []
        for cid, info in raw_cats.items():
            if isinstance(info, dict):
                result.append({
                    "id": cid,
                    "name": info.get("name", cid),
                    "rarity": info.get("rarity", "common"),
                    "count": info.get("count", 1),
                    "first_caught": info.get("first_caught", ""),
                })
            else:
                result.append({
                    "id": cid, "name": cid,
                    "rarity": "common", "count": int(info) if info else 1,
                })
        return result
    return []


def _count_total_cats(raw_cats) -> int:
    if isinstance(raw_cats, dict):
        total = 0
        for v in raw_cats.values():
            if isinstance(v, dict):
                total += v.get("count", 1)
            else:
                total += int(v) if v else 1
        return total
    if isinstance(raw_cats, list):
        return len(raw_cats)
    return 0

# ============================================================
# 임베드 빌더
# ============================================================

def build_profile_embed(member: discord.Member, user_data: dict) -> discord.Embed:
    level = user_data.get("level", 1)
    exp = user_data.get("exp", 0)
    needed = _cfg.get_exp_for_level(level)
    money = user_data.get("money", 0)
    tuna = user_data.get("tuna_can", 0)

    ratio = min(exp / needed, 1.0) if needed > 0 else 1.0
    bar_filled = int(ratio * 20)
    exp_bar = "█" * bar_filled + "░" * (20 - bar_filled)

    embed = discord.Embed(title=f"📋 {member.display_name}의 프로필", color=COLOR_PRIMARY)
    embed.add_field(
        name="📊 기본 정보",
        value=(
            f"**레벨**: Lv.{level} / {MAX_LEVEL}\n"
            f"**경험치**: {exp:,} / {needed:,}\n"
            f"`{exp_bar}` ({ratio * 100:.1f}%)"
        ),
        inline=False,
    )
    embed.add_field(name="💰 재화", value=f"💵 **{money:,}원**\n🐟 **참치캔 {tuna:,}개**", inline=True)

    raw_cats = user_data.get("cats", {})
    total_cats = _count_total_cats(raw_cats)
    catdex = user_data.get("catdex", {})
    species = len(catdex) if isinstance(catdex, dict) else 0
    embed.add_field(name="🐱 냥이", value=f"보유: **{total_cats}마리**\n도감: **{species}종**", inline=True)

    skills = user_data.get("skills", {})
    skill_points = user_data.get("skill_points", 0)
    embed.add_field(
        name="⭐ 스킬",
        value=(
            f"잔여 포인트: **{skill_points}P**\n"
            f"🔍 추적술 Lv.{skills.get('tracking', 0)} | "
            f"⚔️ 전투술 Lv.{skills.get('combat', 0)} | "
            f"💼 상술 Lv.{skills.get('trade', 0)}"
        ),
        inline=False,
    )

    if is_newbie(user_data):
        remaining = get_newbie_days_remaining(user_data)
        embed.add_field(name="🌱 뉴비 보호", value=f"뉴비 보너스 활성 중 (잔여 **{remaining}일**)", inline=False)

    stats = user_data.get("stats", {})
    embed.add_field(
        name="📈 통계",
        value=(
            f"총 납치: **{stats.get('total_kidnaps', 0)}회**\n"
            f"총 전투: **{stats.get('battle_wins', 0) + stats.get('battle_losses', 0)}회**"
        ),
        inline=True,
    )

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="카요코 봇", icon_url=BOT_ICON_URL)
    return embed


def build_skill_tree_embed(member: discord.Member, user_data: dict) -> discord.Embed:
    skills = user_data.get("skills", {})
    skill_points = user_data.get("skill_points", 0)
    embed = discord.Embed(
        title=f"⭐ {member.display_name}의 스킬 트리",
        description=f"잔여 스킬 포인트: **{skill_points}P**",
        color=COLOR_PRIMARY,
    )
    skill_info = {
        "tracking": {"name": "🔍 추적술", "effects": SKILL_EFFECTS.get("tracking", {})},
        "combat": {"name": "⚔️ 전투술", "effects": SKILL_EFFECTS.get("combat", {})},
        "trade": {"name": "💼 상술", "effects": SKILL_EFFECTS.get("trade", {})},
    }
    for tree_key, info in skill_info.items():
        current_lv = skills.get(tree_key, 0)
        bar_filled = "█" * current_lv
        bar_empty = "░" * (MAX_SKILL_LEVEL - current_lv)
        lines = [
            f"현재 레벨: **{current_lv}/{MAX_SKILL_LEVEL}**",
            f"`{bar_filled}{bar_empty}`",
        ]
        if current_lv < MAX_SKILL_LEVEL:
            for effect_name, per_level in info["effects"].items():
                effect_display = SKILL_EFFECT_DISPLAY_NAMES.get(effect_name, effect_name)
                lines.append(f"  {effect_display}: {current_lv * per_level:.1f} → {(current_lv + 1) * per_level:.1f}")
        else:
            lines.append("  ✅ MAX 달성!")
        embed.add_field(name=info["name"], value="\n".join(lines), inline=False)

    embed.set_footer(text="'/스킬투자 [스킬명]'으로 포인트를 투자하세요!", icon_url=BOT_ICON_URL)
    return embed


def build_daily_summary_embed(member: discord.Member, user_data: dict) -> discord.Embed:
    summary = get_daily_counts_summary(user_data)
    embed = discord.Embed(title=f"📅 {member.display_name}의 오늘의 활동 현황", color=COLOR_PRIMARY)
    activity_names = {
        "kidnap": "🐱 납치", "battle": "⚔️ 전투", "labyrinth": "🏛️ 미궁",
        "gamble": "🎰 도박", "equipment_buy": "🛡️ 장비 구매",
    }
    for key, info in summary.items():
        display_name = activity_names.get(key, key)
        current = info["current"]
        max_count = info["max"]
        remaining = info["remaining"]
        ratio = min(current / max_count, 1.0) if max_count > 0 else 0
        filled = int(ratio * 15)
        bar = "█" * filled + "░" * (15 - filled)
        embed.add_field(name=display_name, value=f"`{bar}` **{current}/{max_count}** (잔여: {remaining})", inline=False)

    catchup = calculate_catchup_bonus(user_data)
    if catchup > 0:
        embed.add_field(name="🌱 캐치업 보너스", value=f"경험치 +**{catchup * 100:.0f}%** 추가 적용 중", inline=False)

    embed.set_footer(text="매일 자정(KST)에 초기화됩니다.", icon_url=BOT_ICON_URL)
    return embed

# ============================================================
# 냥이 인벤토리 뷰
# ============================================================

class CatInventoryView(discord.ui.View):
    def __init__(self, user, owned_cats_list, cats_data, per_page=10):
        super().__init__(timeout=120)
        self.user = user
        self.owned = owned_cats_list
        self.cats_data = cats_data
        self.per_page = per_page
        self.page = 0
        self.max_page = max((len(self.owned) - 1) // per_page, 0)

    def build_page(self):
        start = self.page * self.per_page
        end = start + self.per_page
        page_cats = self.owned[start:end]
        lines = []
        for i, cat in enumerate(page_cats, start=start + 1):
            if isinstance(cat, dict):
                name = cat.get("name", "???")
                rarity = _safe_rarity_str(cat.get("rarity", "common"))
                count = cat.get("count", 1)
            else:
                name = str(cat)
                rarity = "common"
                count = 1
            tier = RARITY_TIERS.get(rarity, RARITY_TIERS.get("common", {}))
            emoji = tier.get("emoji", "⬜")
            r_name = tier.get("name", rarity)
            count_str = f" ×{count}" if count > 1 else ""
            badge = ""
            try:
                from models.cat import get_cat_by_name
                from models.element import get_cat_types, ATTACK_TYPES, DEFENSE_TYPES
                a, d = get_cat_types(get_cat_by_name(name))
                ai = ATTACK_TYPES.get(a); di = DEFENSE_TYPES.get(d)
                if ai and di:
                    badge = f" {ai['emoji']}{di['emoji']}"
            except Exception:
                pass
            lines.append(f"`{i}.` {emoji} **{name}** ({r_name}){count_str}{badge}")
        embed = discord.Embed(
            title=f"🐱 냥이 인벤토리 ({len(self.owned)}종)",
            description="\n".join(lines) if lines else "비어있음",
            color=COLOR_DEFAULT,
        )
        embed.set_footer(text=f"{self.user.display_name} | {self.page + 1}/{self.max_page + 1}페이지 | 카요코 봇", icon_url=BOT_ICON_URL)
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("본인만 조작할 수 있습니다.", ephemeral=True)
            return
        if self.page > 0:
            self.page -= 1
        await interaction.response.edit_message(embed=self.build_page(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("본인만 조작할 수 있습니다.", ephemeral=True)
            return
        if self.page < self.max_page:
            self.page += 1
        await interaction.response.edit_message(embed=self.build_page(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ============================================================
# 냥이 도감 뷰
# ============================================================

class CatdexView(discord.ui.View):
    def __init__(self, member, cats_data, user_data, page=0):
        super().__init__(timeout=120)
        self.member = member
        self.cats_data = cats_data if isinstance(cats_data, list) else []
        self.user_data = user_data
        self.page = page
        self.per_page = 15
        self.max_page = max(0, (len(self.cats_data) - 1) // self.per_page)
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.max_page

    def build_page(self):
        catdex = self.user_data.get("catdex", {})
        if isinstance(catdex, list):
            catdex_ids = {str(c.get("id", "")) for c in catdex if isinstance(c, dict)}
        elif isinstance(catdex, dict):
            catdex_ids = set(catdex.keys())
        else:
            catdex_ids = set()
        # 이름 기반으로도 체크
        catdex_names = set()
        for k, v in (catdex.items() if isinstance(catdex, dict) else []):
            if isinstance(v, dict):
                catdex_names.add(v.get("name", k))
            else:
                catdex_names.add(k)

        total_cats = len(self.cats_data)
        discovered = len(catdex_ids | catdex_names)
        embed = discord.Embed(
            title=f"📖 {self.member.display_name}의 냥이 도감",
            description=f"발견: **{discovered}/{total_cats}종** ({discovered / max(total_cats, 1) * 100:.1f}%)",
            color=COLOR_PRIMARY,
        )
        start = self.page * self.per_page
        end = min(start + self.per_page, total_cats)
        lines = []
        for i, cat in enumerate(self.cats_data[start:end], start=start + 1):
            if not isinstance(cat, dict):
                continue
            cat_id = str(cat.get("id", cat.get("name", "")))
            cat_name = cat.get("name", "???")
            rarity = _safe_rarity_str(cat.get("rarity", "common"))
            tier = RARITY_TIERS.get(rarity, RARITY_TIERS.get("common", {}))
            emoji = tier.get("emoji", "⬜")
            if cat_id in catdex_ids or cat_name in catdex_ids or cat_name in catdex_names:
                lines.append(f"`{i:03d}` {emoji} **{cat_name}** ({tier.get('name', rarity)})")
            else:
                lines.append(f"`{i:03d}` ❓ **???**")
        embed.add_field(name="목록", value="\n".join(lines) if lines else "데이터 없음", inline=False)
        embed.set_footer(text=f"페이지 {self.page + 1}/{self.max_page + 1} | 카요코 봇", icon_url=BOT_ICON_URL)
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("본인만 조작 가능합니다.", ephemeral=True)
            return
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_page(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("본인만 조작 가능합니다.", ephemeral=True)
            return
        self.page = min(self.max_page, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_page(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ============================================================
# 분양 확인 뷰
# ============================================================

class AdoptConfirmView(discord.ui.View):
    def __init__(self, user, cat_id, cat_name, rarity, sell_price):
        super().__init__(timeout=30)
        self.user = user
        self.cat_id = str(cat_id)
        self.cat_name = cat_name
        self.rarity = rarity
        self.sell_price = sell_price

    @discord.ui.button(label="✅ 분양하기", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("본인만 사용 가능합니다.", ephemeral=True)
            return
        user_data = load_user_data(self.user.id)
        if not user_data:
            await interaction.response.edit_message(embed=discord.Embed(title="❌ 오류", description="유저 데이터를 찾을 수 없습니다.", color=COLOR_ERROR), view=None)
            return
        cats = user_data.get("cats", {})
        if not isinstance(cats, dict) or self.cat_id not in cats:
            await interaction.response.edit_message(embed=discord.Embed(title="❌ 오류", description="해당 냥이를 보유하고 있지 않습니다.", color=COLOR_ERROR), view=None)
            return
        info = cats[self.cat_id]
        count = info.get("count", 1) if isinstance(info, dict) else 1
        if count <= 1:
            del cats[self.cat_id]
        else:
            if isinstance(info, dict):
                info["count"] = count - 1
        user_data["money"] = user_data.get("money", 0) + self.sell_price
        save_user_data(self.user.id, user_data)
        embed = discord.Embed(title="✅ 분양 완료!", description=f"**{self.cat_name}**을(를) 분양했습니다.\n💰 **+{self.sell_price:,}원** 획득!", color=COLOR_SUCCESS)
        embed.set_footer(text="카요코 봇", icon_url=BOT_ICON_URL)
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="❌ 취소", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("본인만 사용 가능합니다.", ephemeral=True)
            return
        embed = discord.Embed(title="↩️ 분양 취소", description="분양이 취소되었습니다.", color=COLOR_WARNING)
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

# ═══════════════════════════════════════════════════════════
#  COG 클래스
# ═══════════════════════════════════════════════════════════

class GameplayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---- /납치 ----
    @app_commands.command(name="납치", description="고양이를 납치합니다")
    async def kidnap_command(self, interaction: discord.Interaction):
        await run_kidnap_sequence(interaction)

    # ---- /프로필 ----
    @app_commands.command(name="프로필", description="내 프로필을 확인합니다.")
    async def profile_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_data = load_user_data(interaction.user.id)
        if not user_data:
            await interaction.followup.send("❌ 등록된 유저가 아닙니다. `/가입`을 먼저 입력해주세요.", ephemeral=True)
            return
        try:
            from utils.card_service import build_profile_card_file
            file = await build_profile_card_file(interaction.user, user_data)
            await interaction.followup.send(file=file)
        except Exception:
            import traceback; traceback.print_exc()
            await interaction.followup.send(embed=build_profile_embed(interaction.user, user_data))

    # ---- /일일현황 ----
    @app_commands.command(name="일일현황", description="오늘의 활동 현황을 확인합니다.")
    async def daily_summary_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_data = load_user_data(interaction.user.id)
        if not user_data:
            await interaction.followup.send("❌ 등록된 유저가 아닙니다.", ephemeral=True)
            return
        summary = get_daily_counts_summary(user_data)
        act = {"kidnap": ("🐱", "납치"), "battle": ("⚔️", "전투"), "labyrinth": ("🏛️", "미궁"),
               "gamble": ("🎰", "도박"), "equipment_buy": ("🛡️", "장비 구매")}
        rows = []
        for key, info in summary.items():
            em, nm = act.get(key, ("•", key))
            rows.append((em, nm, f"{info['current']}/{info['max']} (잔여 {info['remaining']})"))
        sections = [("오늘의 활동 (자정 초기화)", rows)]
        catchup = calculate_catchup_bonus(user_data)
        if catchup > 0:
            sections.append(("보너스", [("🌱", "캐치업", f"경험치 +{catchup*100:.0f}%")]))
        try:
            from utils.card_service import build_stat_card_file
            file = await build_stat_card_file(
                interaction.user, user_data, title="일일 현황",
                subtitle=f"Lv.{user_data.get('level',1)}", sections=sections, filename="daily.png")
            await interaction.followup.send(file=file)
        except Exception:
            import traceback; traceback.print_exc()
            await interaction.followup.send(embed=build_daily_summary_embed(interaction.user, user_data))

    # ---- /스킬 ----
    @app_commands.command(name="스킬", description="스킬 트리를 확인합니다.")
    async def skill_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_data = load_user_data(interaction.user.id)
        if not user_data:
            await interaction.followup.send("❌ 등록된 유저가 아닙니다.", ephemeral=True)
            return
        skills = user_data.get("skills", {})
        sp = user_data.get("skill_points", 0)
        rows = [
            ("🔍", "추적술", f"Lv.{skills.get('tracking',0)}/{MAX_SKILL_LEVEL}"),
            ("⚔️", "전투술", f"Lv.{skills.get('combat',0)}/{MAX_SKILL_LEVEL}"),
            ("💼", "상술", f"Lv.{skills.get('trade',0)}/{MAX_SKILL_LEVEL}"),
            ("⭐", "잔여 포인트", f"{sp}P"),
        ]
        sections = [("스킬 트리", rows)]
        try:
            from utils.card_service import build_stat_card_file
            file = await build_stat_card_file(
                interaction.user, user_data, title="스킬 트리",
                subtitle=f"잔여 {sp}P", sections=sections, filename="skill.png")
            await interaction.followup.send(file=file)
        except Exception:
            import traceback; traceback.print_exc()
            await interaction.followup.send(embed=build_skill_tree_embed(interaction.user, user_data))

    # ---- /스킬투자 ----
    @app_commands.command(name="스킬투자", description="스킬 포인트를 투자합니다.")
    @app_commands.describe(skill_name="투자할 스킬 이름")
    @app_commands.choices(skill_name=[
        app_commands.Choice(name="추적술 (납치 성공률 ↑)", value="tracking"),
        app_commands.Choice(name="전투술 (전투 능력 ↑)", value="combat"),
        app_commands.Choice(name="상술 (거래 보너스 ↑)", value="trade"),
    ])
    async def skill_invest_command(self, interaction: discord.Interaction, skill_name: str):
        await interaction.response.defer()
        user_data = load_user_data(interaction.user.id)
        if not user_data:
            await interaction.followup.send("❌ 등록된 유저가 아닙니다.", ephemeral=True)
            return
        result_msg = allocate_skill_point(user_data, skill_name)
        save_user_data(interaction.user.id, user_data)
        embed = discord.Embed(title="🎯 스킬 투자", description=result_msg, color=COLOR_SUCCESS)
        embed.set_footer(text="카요코 봇", icon_url=BOT_ICON_URL)
        await interaction.followup.send(embed=embed)

    # ---- /지역목록 (models/region.py REGIONS 기반으로 수정) ----
    @app_commands.command(name="지역목록", description="이동 가능한 지역 목록을 봅니다.")
    async def region_list_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_data = load_user_data(interaction.user.id)
        if not user_data:
            await interaction.followup.send("❌ 등록된 유저가 아닙니다.", ephemeral=True)
            return

        unlocked = user_data.get("unlocked_regions", ["alley"])
        current = user_data.get("current_region", "alley")

        # cats.json에서 지역별 냥이 수 계산
        all_cats = load_cats_data()
        region_cat_counts = {}
        for cat in all_cats:
            if isinstance(cat, dict):
                r = cat.get("region", "alley")
                region_cat_counts[r] = region_cat_counts.get(r, 0) + 1

        desc_lines = []
        for region_key, region_data in get_region_list():
            name = region_data.get("name", "???")
            emoji = region_data.get("emoji", "📍")
            req_level = region_data.get("required_level", 1)
            is_current = region_key == current
            is_unlocked = region_key in unlocked
            cat_count = region_cat_counts.get(region_key, 0)

            if is_current:
                status = "📌 현재 위치"
            elif is_unlocked:
                status = "✅ 해금됨"
            else:
                status = f"🔒 Lv.{req_level} 필요"

            desc_lines.append(f"{emoji} **{name}** — {status} (냥이 {cat_count}종)")

        embed = discord.Embed(
            title="🗺️ 지역 목록",
            description="\n".join(desc_lines) if desc_lines else "지역 없음",
            color=COLOR_INFO
        )
        embed.set_footer(text="카요코 봇", icon_url=BOT_ICON_URL)
        await interaction.followup.send(embed=embed)

    # ---- /지역이동 ----
    @app_commands.command(name="지역이동", description="다른 지역으로 이동합니다.")
    @app_commands.describe(region_name="이동할 지역 이름")
    @app_commands.choices(region_name=[
        app_commands.Choice(name="골목길", value="alley"),
        app_commands.Choice(name="공원", value="park"),
        app_commands.Choice(name="항구", value="harbor"),
        app_commands.Choice(name="폐공장", value="factory"),
        app_commands.Choice(name="지하도시", value="underground"),
        app_commands.Choice(name="심연", value="abyss"),
    ])
    async def region_move_command(self, interaction: discord.Interaction, region_name: str):
        await interaction.response.defer()
        user_data = load_user_data(interaction.user.id)
        if not user_data:
            await interaction.followup.send("❌ 등록된 유저가 아닙니다.", ephemeral=True)
            return
        unlocked = user_data.get("unlocked_regions", ["alley"])
        if region_name not in unlocked:
            region_display = REGIONS.get(region_name, {}).get("name", region_name)
            await interaction.followup.send(f"❌ **{region_display}** 지역은 아직 해금되지 않았습니다.", ephemeral=True)
            return
        user_data["current_region"] = region_name
        save_user_data(interaction.user.id, user_data)
        region_display = REGIONS.get(region_name, {}).get("name", region_name)
        region_emoji = REGIONS.get(region_name, {}).get("emoji", "📍")
        embed = discord.Embed(title="🚶 지역 이동 완료", description=f"{region_emoji} **{region_display}**(으)로 이동했습니다!", color=COLOR_SUCCESS)
        embed.set_footer(text="카요코 봇", icon_url=BOT_ICON_URL)
        await interaction.followup.send(embed=embed)

    # ---- /지역해금 ----
    @app_commands.command(name="지역해금", description="새로운 지역을 해금합니다.")
    @app_commands.describe(region_name="해금할 지역 이름")
    @app_commands.choices(region_name=[
        app_commands.Choice(name="공원", value="park"),
        app_commands.Choice(name="항구", value="harbor"),
        app_commands.Choice(name="폐공장", value="factory"),
        app_commands.Choice(name="지하도시", value="underground"),
        app_commands.Choice(name="심연", value="abyss"),
    ])
    async def region_unlock_command(self, interaction: discord.Interaction, region_name: str):
        await interaction.response.defer()
        user_data = load_user_data(interaction.user.id)
        if not user_data:
            await interaction.followup.send("❌ 등록된 유저가 아닙니다.", ephemeral=True)
            return

        from models.region import check_region_unlock
        can_unlock, reason = check_region_unlock(user_data, region_name)

        if not can_unlock:
            await interaction.followup.send(f"❌ {reason}", ephemeral=True)
            return

        # 해금 처리
        unlocked = user_data.setdefault("unlocked_regions", ["alley"])
        if region_name not in unlocked:
            unlocked.append(region_name)
        save_user_data(interaction.user.id, user_data)

        region_data = REGIONS.get(region_name, {})
        region_display = region_data.get("name", region_name)
        region_emoji = region_data.get("emoji", "📍")
        embed = discord.Embed(title="🔓 지역 해금 완료!", description=f"{region_emoji} **{region_display}** 해금!", color=COLOR_SUCCESS)
        embed.set_footer(text="카요코 봇", icon_url=BOT_ICON_URL)
        await interaction.followup.send(embed=embed)

    # ---- /냥이인벤토리 ----
    @app_commands.command(name="냥이인벤토리", description="보유 중인 냥이 목록을 봅니다.")
    async def cat_inventory_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_data = load_user_data(interaction.user.id)
        if not user_data:
            await interaction.followup.send("❌ 등록된 유저가 아닙니다.", ephemeral=True)
            return
        cats_data = load_cats_data()
        raw_cats = user_data.get("cats", {})
        owned = _owned_cats_to_list(raw_cats)

        tutorial_reward_text = None
        if user_data.get("tutorial_step") == "check_inventory":
            step_data = TUTORIAL_STEPS.get("check_inventory", {})
            if advance_tutorial(user_data, "check_inventory"):
                save_user_data(interaction.user.id, user_data)
                parts = []
                if step_data.get("reward_money"):
                    parts.append(f"💰 +{step_data['reward_money']:,}원")
                if step_data.get("reward_exp"):
                    parts.append(f"✨ +{step_data['reward_exp']} EXP")
                if parts:
                    tutorial_reward_text = " | ".join(parts)

        if not owned:
            embed = discord.Embed(title="🐱 냥이 인벤토리", description="보유 중인 냥이가 없습니다.\n`/납치`로 냥이를 잡아보세요!", color=COLOR_WARNING)
            if tutorial_reward_text:
                embed.add_field(name="📚 튜토리얼 완료 — 인벤토리 확인!", value=tutorial_reward_text, inline=False)
            embed.set_footer(text="카요코 봇", icon_url=BOT_ICON_URL)
            await interaction.followup.send(embed=embed)
            return

        view = CatInventoryView(interaction.user, owned, cats_data)
        embed = view.build_page()
        if tutorial_reward_text:
            embed.add_field(name="📚 튜토리얼 완료 — 인벤토리 확인!", value=tutorial_reward_text, inline=False)
        await interaction.followup.send(embed=embed, view=view)

    # ---- /냥이도감 ----
    @app_commands.command(name="냥이도감", description="냥이 도감을 확인합니다.")
    async def catdex_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_data = load_user_data(interaction.user.id)
        if not user_data:
            await interaction.followup.send("❌ 등록된 유저가 아닙니다.", ephemeral=True)
            return
        cats_data = load_cats_data()
        view = CatdexView(interaction.user, cats_data, user_data)
        embed = view.build_page()
        await interaction.followup.send(embed=embed, view=view)

    # ---- /냥이분양 ----
    @app_commands.command(name="냥이분양", description="보유한 냥이를 분양(판매)합니다.")
    @app_commands.describe(cat_name="분양할 냥이 이름")
    async def adopt_command(self, interaction: discord.Interaction, cat_name: str):
        await interaction.response.defer()
        user_data = load_user_data(interaction.user.id)
        if not user_data:
            await interaction.followup.send("❌ 등록된 유저가 아닙니다.", ephemeral=True)
            return
        cats = user_data.get("cats", {})
        if not isinstance(cats, dict):
            await interaction.followup.send("❌ 인벤토리 데이터 오류입니다.", ephemeral=True)
            return
        target_id = None
        target_info = None
        for cid, info in cats.items():
            check_name = info.get("name", cid) if isinstance(info, dict) else cid
            if check_name.lower() == cat_name.lower():
                target_id = cid
                target_info = info if isinstance(info, dict) else {"name": cid, "rarity": "common", "count": 1}
                break
        if not target_id:
            await interaction.followup.send(f"❌ **{cat_name}** 냥이를 보유하고 있지 않습니다.", ephemeral=True)
            return
        rarity = _safe_rarity_str(target_info.get("rarity", "common"))
        tier = RARITY_TIERS.get(rarity, RARITY_TIERS.get("common", {}))
        base_price = tier.get("sell_price_range", (300, 1000))
        if isinstance(base_price, tuple):
            base_price = (base_price[0] + base_price[1]) // 2
        sell_bonus = get_skill_effect(user_data, "trade", "sell_price_bonus")
        final_price = int(base_price * (1 + sell_bonus / 100))

        view = AdoptConfirmView(interaction.user, target_id, target_info.get("name", cat_name), rarity, final_price)
        embed = discord.Embed(
            title="🐱 냥이 분양 확인",
            description=(
                f"**{target_info.get('name', cat_name)}** ({tier.get('name', rarity)})\n"
                f"보유: **{target_info.get('count', 1)}마리**\n"
                f"💰 판매가: **{final_price:,}원** (1마리)"
            ),
            color=tier.get("color", COLOR_DEFAULT),
        )
        embed.set_footer(text="카요코 봇", icon_url=BOT_ICON_URL)
        await interaction.followup.send(embed=embed, view=view)

    # ---- /송금 ----
    @app_commands.command(name="송금", description="다른 유저에게 돈을 송금합니다.")
    @app_commands.describe(target="송금 대상", amount="금액")
    async def transfer_command(self, interaction: discord.Interaction, target: discord.Member, amount: int):
        await interaction.response.defer()
        if target.id == interaction.user.id:
            await interaction.followup.send("❌ 자기 자신에게 송금할 수 없습니다.", ephemeral=True)
            return
        if target.bot:
            await interaction.followup.send("❌ 봇에게 송금할 수 없습니다.", ephemeral=True)
            return
        if amount <= 0:
            await interaction.followup.send("❌ 1원 이상 송금해주세요.", ephemeral=True)
            return
        sender_data = load_user_data(interaction.user.id)
        receiver_data = load_user_data(target.id)
        if not sender_data:
            await interaction.followup.send("❌ 등록된 유저가 아닙니다.", ephemeral=True)
            return
        if not receiver_data:
            await interaction.followup.send("❌ 상대방이 등록된 유저가 아닙니다.", ephemeral=True)
            return
        if sender_data.get("money", 0) < amount:
            await interaction.followup.send(f"❌ 잔액이 부족합니다. (보유: {sender_data.get('money',0):,}원)", ephemeral=True)
            return
        sender_data["money"] -= amount
        receiver_data["money"] = receiver_data.get("money", 0) + amount
        save_user_data(interaction.user.id, sender_data)
        save_user_data(target.id, receiver_data)
        embed = discord.Embed(title="💸 송금 완료", description=f"**{interaction.user.display_name}** → **{target.display_name}**\n💰 **{amount:,}원** 송금!", color=COLOR_SUCCESS)
        embed.set_footer(text="카요코 봇", icon_url=BOT_ICON_URL)
        await interaction.followup.send(embed=embed)

    # ---- /캣맘랭킹 ----
    @app_commands.command(name="캣맘랭킹", description="냥이 보유 수 TOP 10 랭킹")
    async def cat_ranking_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        ranking = []
        if os.path.isdir(USERS_DIR):
            for fname in os.listdir(USERS_DIR):
                if fname.endswith(".json"):
                    uid = fname.replace(".json", "")
                    try:
                        data = load_user_data(uid)
                        if data:
                            count = _count_total_cats(data.get("cats", {}))
                            # JSON에 저장된 닉네임 우선 시도
                            nick = data.get("nickname") or data.get("display_name") or data.get("username")
                            # JSON에 없으면 봇 캐시에서 디스코드 유저 정보 가져오기
                            if not nick:
                                try:
                                    discord_user = self.bot.get_user(int(uid))
                                    if discord_user:
                                        nick = discord_user.display_name
                                except (ValueError, Exception):
                                    pass
                            # 그래도 없으면 fetch 시도
                            if not nick:
                                try:
                                    discord_user = await self.bot.fetch_user(int(uid))
                                    if discord_user:
                                        nick = discord_user.display_name
                                except (ValueError, discord.NotFound, discord.HTTPException, Exception):
                                    nick = f"유저#{uid[-4:]}"
                            ranking.append((uid, nick, count))
                    except Exception:
                        continue
        ranking.sort(key=lambda x: x[2], reverse=True)
        top10 = ranking[:10]
        medals = ["🥇", "🥈", "🥉"]
        desc_lines = []
        for i, (uid, name, count) in enumerate(top10):
            prefix = medals[i] if i < 3 else f"**{i+1}.**"
            desc_lines.append(f"{prefix} {name} — 🐱 {count}마리")
        embed = discord.Embed(title="🏆 캣맘 랭킹 TOP 10", description="\n".join(desc_lines) if desc_lines else "아직 데이터가 없습니다.", color=COLOR_PRIMARY)
        embed.set_footer(text="카요코 봇", icon_url=BOT_ICON_URL)
        await interaction.followup.send(embed=embed)

    # ---- /보유금랭킹 ----
    @app_commands.command(name="보유금랭킹", description="보유금 TOP 10 랭킹")
    async def money_ranking_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        ranking = []
        if os.path.isdir(USERS_DIR):
            for fname in os.listdir(USERS_DIR):
                if fname.endswith(".json"):
                    uid = fname.replace(".json", "")
                    try:
                        data = load_user_data(uid)
                        if data:
                            money = data.get("money", 0)
                            # JSON에 저장된 닉네임 우선 시도
                            nick = data.get("nickname") or data.get("display_name") or data.get("username")
                            # JSON에 없으면 봇 캐시에서 디스코드 유저 정보 가져오기
                            if not nick:
                                try:
                                    discord_user = self.bot.get_user(int(uid))
                                    if discord_user:
                                        nick = discord_user.display_name
                                except (ValueError, Exception):
                                    pass
                            # 그래도 없으면 fetch 시도
                            if not nick:
                                try:
                                    discord_user = await self.bot.fetch_user(int(uid))
                                    if discord_user:
                                        nick = discord_user.display_name
                                except (ValueError, discord.NotFound, discord.HTTPException, Exception):
                                    nick = f"유저#{uid[-4:]}"
                            ranking.append((uid, nick, money))
                    except Exception:
                        continue
        ranking.sort(key=lambda x: x[2], reverse=True)
        top10 = ranking[:10]
        medals = ["🥇", "🥈", "🥉"]
        desc_lines = []
        for i, (uid, name, money) in enumerate(top10):
            prefix = medals[i] if i < 3 else f"**{i+1}.**"
            desc_lines.append(f"{prefix} {name} — 💰 {money:,}원")
        embed = discord.Embed(title="🏆 보유금 랭킹 TOP 10", description="\n".join(desc_lines) if desc_lines else "아직 데이터가 없습니다.", color=COLOR_PRIMARY)
        embed.set_footer(text="카요코 봇", icon_url=BOT_ICON_URL)
        await interaction.followup.send(embed=embed)

    # ---- /신고 ----
    @app_commands.command(name="신고", description="부정행위 유저를 신고합니다.")
    @app_commands.describe(target="신고 대상", reason="신고 사유")
    async def report_command(self, interaction: discord.Interaction, target: discord.Member, reason: str):
        await interaction.response.defer(ephemeral=True)
        if target.id == interaction.user.id:
            await interaction.followup.send("❌ 자기 자신을 신고할 수 없습니다.", ephemeral=True)
            return
        if REPORT_WEBHOOK_URL:
            try:
                import aiohttp
                report_data = {
                    "embeds": [{
                        "title": "🚨 유저 신고 접수",
                        "color": COLOR_ERROR,
                        "fields": [
                            {"name": "신고자", "value": f"{interaction.user} ({interaction.user.id})", "inline": True},
                            {"name": "대상", "value": f"{target} ({target.id})", "inline": True},
                            {"name": "사유", "value": reason[:1000], "inline": False},
                            {"name": "서버", "value": f"{interaction.guild.name}" if interaction.guild else "DM", "inline": True},
                        ],
                    }],
                }
                async with aiohttp.ClientSession() as session:
                    await session.post(REPORT_WEBHOOK_URL, json=report_data)
            except Exception:
                pass
        embed = discord.Embed(title="✅ 신고 접수 완료", description=f"**{target.display_name}**에 대한 신고가 접수되었습니다.", color=COLOR_SUCCESS)
        embed.set_footer(text="카요코 봇", icon_url=BOT_ICON_URL)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ---- /납치현황 ----
    @app_commands.command(name="납치현황", description="납치 통계를 확인합니다.")
    async def kidnap_status_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_data = load_user_data(interaction.user.id)
        if not user_data:
            await interaction.followup.send("❌ 등록된 유저가 아닙니다.", ephemeral=True)
            return

        stats = user_data.get("stats", {})
        total = stats.get("total_kidnaps", 0)
        success = stats.get("successful_kidnaps", 0)
        rate = (success / total * 100) if total > 0 else 0
        cats_data = user_data.get("cats", {})
        total_owned = sum(c.get("count", 0) if isinstance(c, dict) else 0 for c in cats_data.values()) if isinstance(cats_data, dict) else 0
        species = len(user_data.get("catdex", {})) if isinstance(user_data.get("catdex"), dict) else 0

        sections = [
            ("전체 기록", [
                ("🐾", "총 시도", f"{total}회"),
                ("✅", "성공", f"{success}회"),
                ("📈", "성공률", f"{rate:.1f}%"),
                ("📖", "도감", f"{species}종 / {total_owned}마리"),
            ]),
        ]
        # 등급별 포획 (이모지는 행 아이콘으로만 사용 → 값엔 텍스트만)
        cats_caught = stats.get("cats_caught", {})
        rarity_rows = []
        for r in RARITY_ORDER:
            cnt = cats_caught.get(r, 0)
            if cnt > 0:
                tier = RARITY_TIERS.get(r, {})
                rarity_rows.append((tier.get("emoji", "⬜"), tier.get("name", r), f"{cnt}마리"))
        if rarity_rows:
            sections.append(("등급별 포획", rarity_rows))

        try:
            from utils.card_service import build_stat_card_file
            file = await build_stat_card_file(
                interaction.user, user_data, title="납치 통계",
                subtitle=f"Lv.{user_data.get('level',1)}", sections=sections, filename="kidnap.png")
            await interaction.followup.send(file=file)
        except Exception:
            import traceback; traceback.print_exc()
            await interaction.followup.send(embed=get_kidnap_stats_embed(interaction.user, user_data))


# ═══════════════════════════════════════════════════════════
#  SETUP
# ═══════════════════════════════════════════════════════════

async def setup(bot: commands.Bot):
    await bot.add_cog(GameplayCog(bot))
