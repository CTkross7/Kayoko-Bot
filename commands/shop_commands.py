"""
commands/shop_commands.py
─────────────────────────
상점 시스템 - 드롭다운 기반 장비 구매 / 판매 / 장착 / 인벤토리
"""

from __future__ import annotations

import json
import os
import random
import time
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

import config as _cfg

DATA_DIR = _cfg.DATA_DIR
USERS_DIR = _cfg.USERS_DIR
EQUIPMENT_FILE = _cfg.EQUIPMENT_FILE
COLOR_DEFAULT = _cfg.COLOR_DEFAULT
COLOR_SUCCESS = _cfg.COLOR_SUCCESS
COLOR_ERROR = _cfg.COLOR_ERROR
COLOR_WARNING = getattr(_cfg, "COLOR_WARNING", 0xFEE75C)
RARITY_TIERS = _cfg.RARITY_TIERS
DAILY_LIMITS = _cfg.DAILY_LIMITS
ICON_URL = _cfg.BOT_ICON_URL
EMBED_FOOTER_TEXT = getattr(_cfg, "EMBED_FOOTER_TEXT", "카요코 봇")
SEPARATOR = getattr(_cfg, "SEPARATOR", _cfg.EMBED_THIN_SEPARATOR)
RARITY_COLORS = getattr(_cfg, "RARITY_COLORS", {k: v["color"] for k, v in _cfg.RARITY_TIERS.items()})
RARITY_ORDER = getattr(_cfg, "RARITY_ORDER", ["common", "uncommon", "rare", "epic", "legendary", "mythic"])

CATEGORY_NAMES = {"weapon": "무기", "tool": "도구", "accessory": "악세서리"}
CATEGORY_EMOJIS = {"weapon": "⚔️", "tool": "🔧", "accessory": "💍"}
RARITY_EMOJI = {"common": "⚪", "uncommon": "🟢", "rare": "🔵", "epic": "🟣", "legendary": "🟡", "mythic": "🔴"}
STAT_DISPLAY = {"attack": ("공격력", "⚔️"), "hp_bonus": ("체력 보너스", "❤️"), "kidnap_bonus": ("납치 보너스", "🐱")}


def _safe_rarity_str(raw) -> str:
    if isinstance(raw, str):
        return raw.lower()
    if isinstance(raw, (int, float)):
        for name, tier in RARITY_TIERS.items():
            if isinstance(tier, dict) and abs(tier.get("weight", -1) - raw) < 1e-6:
                return name
        idx_map = {0: "common", 1: "uncommon", 2: "rare", 3: "epic", 4: "legendary", 5: "mythic"}
        return idx_map.get(int(raw), "common")
    return "common"


# ─── data loaders ─────────────────────────────────────────────────

def load_equipment_data() -> Dict[str, List[Dict]]:
    path = EQUIPMENT_FILE if os.path.isabs(EQUIPMENT_FILE) else os.path.join(DATA_DIR, "equipment.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"weapons": [], "tools": [], "accessories": []}


def _get_all_items() -> List[Dict]:
    data = load_equipment_data()
    items = []
    for cat_key in ("weapons", "tools", "accessories"):
        for item in data.get(cat_key, []):
            items.append(item)
    return items


def _find_item(item_id: str) -> Optional[Dict]:
    for item in _get_all_items():
        if item["id"] == item_id:
            return item
    return None


def _items_by_category(category: str) -> List[Dict]:
    return [i for i in _get_all_items() if i.get("category") == category]


# ─── user data helpers ────────────────────────────────────────────

def _user_path(user_id: int) -> str:
    return os.path.join(USERS_DIR, f"{user_id}.json")


def load_user(user_id: int) -> Dict[str, Any]:
    path = _user_path(user_id)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_user(user_id: int, data: Dict[str, Any]) -> None:
    path = _user_path(user_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _ensure_inventory(udata: Dict) -> Dict:
    udata.setdefault("inventory", {"weapons": [], "tools": [], "accessories": []})
    udata.setdefault("equipped", {"weapon": None, "tool": None, "accessory": None})
    udata.setdefault("money", 0)
    udata.setdefault("level", 1)
    return udata


def _inv_category_key(category: str) -> str:
    return {"weapon": "weapons", "tool": "tools", "accessory": "accessories"}.get(category, category)

# ─── 장비 구매 드롭다운 ───────────────────────────────────────────

class ItemBuySelect(discord.ui.Select):
    """카테고리 내 장비를 드롭다운으로 선택하여 구매"""

    def __init__(self, items: List[Dict], user_level: int, user_money: int):
        self.item_map: Dict[str, Dict] = {}
        options = []
        for item in items:
            rarity = _safe_rarity_str(item.get("rarity", "common"))
            r_emoji_str = RARITY_EMOJI.get(rarity, "⚪")
            lvl_req = item.get("level_required", 1)
            price = item.get("price", 0)

            # 상태 표시
            if user_level < lvl_req:
                status = f"🔒 Lv.{lvl_req} 필요"
            elif user_money < price:
                status = "💰 잔액 부족"
            else:
                status = f"✅ {price:,}원"

            # 스탯 한줄 요약
            stat_parts = []
            for sk, (sl, si) in STAT_DISPLAY.items():
                v = item.get("stats", {}).get(sk)
                if v:
                    stat_parts.append(f"{sl}+{v}")
            stat_text = " / ".join(stat_parts) if stat_parts else "효과 없음"

            label = f"{item['name']} ({rarity.upper()})"
            desc = f"{stat_text} | {status}"

            # discord SelectOption description 100자 제한
            if len(desc) > 100:
                desc = desc[:97] + "..."
            if len(label) > 100:
                label = label[:97] + "..."

            self.item_map[item["id"]] = item
            options.append(discord.SelectOption(
                label=label,
                value=item["id"],
                description=desc,
                emoji=r_emoji_str,
            ))

        if not options:
            options.append(discord.SelectOption(label="구매 가능한 장비 없음", value="none"))

        super().__init__(placeholder="구매할 장비를 선택하세요", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        selected_id = self.values[0]
        if selected_id == "none":
            await interaction.response.send_message("구매 가능한 장비가 없습니다.", ephemeral=True)
            return

        item = self.item_map.get(selected_id)
        if not item:
            await interaction.response.send_message("장비를 찾을 수 없습니다.", ephemeral=True)
            return

        udata = load_user(interaction.user.id)
        _ensure_inventory(udata)

        price = item.get("price", 0)
        lvl_req = item.get("level_required", 1)
        category = item.get("category", "weapon")
        inv_key = _inv_category_key(category)

        # 체크
        if udata.get("level", 1) < lvl_req:
            embed = discord.Embed(title="🔒 레벨 부족", description=f"**Lv.{lvl_req}** 이상이어야 구매할 수 있습니다.\n현재: **Lv.{udata.get('level', 1)}**", color=COLOR_ERROR)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if udata.get("money", 0) < price:
            embed = discord.Embed(title="💰 잔액 부족", description=f"필요: **{price:,}원** | 보유: **{udata.get('money', 0):,}원**", color=COLOR_ERROR)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if item["id"] in udata["inventory"].get(inv_key, []):
            embed = discord.Embed(title="📦 이미 보유 중", description=f"**{item['name']}**은(는) 이미 보유 중입니다.", color=COLOR_WARNING)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 일일 한도
        today = time.strftime("%Y-%m-%d")
        daily = udata.get("daily_actions", {})
        if daily.get("date") != today:
            daily = {"date": today}
        buy_count = daily.get("equipment_buy", 0)
        limit = DAILY_LIMITS.get("equipment_buy", 10)
        if buy_count >= limit:
            embed = discord.Embed(title="⏰ 일일 구매 한도 초과", description=f"오늘의 장비 구매 한도(**{limit}회**)를 모두 사용했습니다.", color=COLOR_ERROR)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 구매 실행
        udata["money"] -= price
        udata["inventory"][inv_key].append(item["id"])
        daily["equipment_buy"] = buy_count + 1
        udata["daily_actions"] = daily
        save_user(interaction.user.id, udata)

        rarity = _safe_rarity_str(item.get("rarity", "common"))
        r_emoji = RARITY_EMOJI.get(rarity, "⚪")

        stat_parts = []
        for sk, (sl, si) in STAT_DISPLAY.items():
            v = item.get("stats", {}).get(sk)
            if v:
                stat_parts.append(f"{si} {sl} **+{v}**")
        stat_line = "\n".join(stat_parts) if stat_parts else ""

        embed = discord.Embed(
            title="✅ 구매 완료!",
            description=(
                f"{r_emoji} **{item['name']}** ({rarity.upper()}) 구매!\n\n"
                f"{stat_line}\n\n"
                f"💰 지불: **{price:,}원**\n"
                f"💰 잔액: **{udata['money']:,}원**\n\n"
                f"📌 `/장착`으로 장비를 장착하세요!"
            ),
            color=COLOR_SUCCESS,
        )
        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=ICON_URL)
        await interaction.response.send_message(embed=embed)


class ShopCategorySelect(discord.ui.Select):
    """카테고리 선택 → 해당 카테고리의 장비 구매 드롭다운 표시"""

    def __init__(self):
        options = [
            discord.SelectOption(label="무기", value="weapon", emoji="⚔️", description="공격력을 올려주는 장비"),
            discord.SelectOption(label="도구", value="tool", emoji="🔧", description="납치 보너스를 올려주는 장비"),
            discord.SelectOption(label="악세서리", value="accessory", emoji="💍", description="체력 보너스를 올려주는 장비"),
        ]
        super().__init__(placeholder="카테고리를 선택하세요", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        udata = load_user(interaction.user.id)
        _ensure_inventory(udata)
        user_level = udata.get("level", 1)
        user_money = udata.get("money", 0)

        items = _items_by_category(category)
        items.sort(key=lambda i: i.get("level_required", 1))

        cat_name = CATEGORY_NAMES.get(category, category)
        cat_emoji = CATEGORY_EMOJIS.get(category, "📦")

        # 장비 목록 임베드
        embed = discord.Embed(
            title=f"{cat_emoji} 냥이 상점 — {cat_name}",
            description=f"💰 보유 금액: **{user_money:,}원**\n아래 드롭다운에서 구매할 장비를 선택하세요!",
            color=COLOR_DEFAULT,
        )

        for item in items:
            rarity = _safe_rarity_str(item.get("rarity", "common"))
            r_emoji = RARITY_EMOJI.get(rarity, "⚪")
            lvl_req = item.get("level_required", 1)
            price = item.get("price", 0)

            stat_parts = []
            for sk, (sl, si) in STAT_DISPLAY.items():
                v = item.get("stats", {}).get(sk)
                if v:
                    stat_parts.append(f"{si} {sl} +{v}")
            stat_line = " | ".join(stat_parts) if stat_parts else "효과 없음"

            can_buy = user_level >= lvl_req and user_money >= price
            owned = item["id"] in udata["inventory"].get(_inv_category_key(category), [])

            if owned:
                status = "📦 보유 중"
            elif user_level < lvl_req:
                status = f"🔒 Lv.{lvl_req} 필요"
            elif user_money < price:
                status = "💰 잔액 부족"
            else:
                status = "✅ 구매 가능"

            embed.add_field(
                name=f"{r_emoji} {item['name']} ({rarity.upper()})",
                value=f"> {item.get('description', '')}\n> {stat_line}\n> 💰 **{price:,}원** | {status}",
                inline=False,
            )

        # 구매 드롭다운 뷰
        buy_view = ShopBuyView(interaction.user.id, items, user_level, user_money)
        await interaction.response.edit_message(embed=embed, view=buy_view)


class ShopBuyView(discord.ui.View):
    """카테고리 선택 후 장비 구매 드롭다운"""

    def __init__(self, user_id: int, items: List[Dict], user_level: int, user_money: int, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        if items:
            self.add_item(ItemBuySelect(items, user_level, user_money))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사람의 상점은 조작할 수 없습니다!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class ShopView(discord.ui.View):
    """메인 상점 뷰 — 카테고리 선택"""

    def __init__(self, user_id: int, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.add_item(ShopCategorySelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("다른 사람의 상점은 조작할 수 없습니다!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ─── 장착 드롭다운 ───────────────────────────────────────────────

class EquipSelect(discord.ui.Select):
    """보유 장비 중 장착할 것을 선택"""

    def __init__(self, udata: Dict, category: str):
        self.category = category
        inv_key = _inv_category_key(category)
        item_ids = udata.get("inventory", {}).get(inv_key, [])
        equipped_id = udata.get("equipped", {}).get(category)

        options = []
        for iid in item_ids:
            item = _find_item(iid)
            if not item:
                continue
            rarity = _safe_rarity_str(item.get("rarity", "common"))
            is_eq = "⭐ " if iid == equipped_id else ""
            stat_parts = []
            for sk, (sl, si) in STAT_DISPLAY.items():
                v = item.get("stats", {}).get(sk)
                if v:
                    stat_parts.append(f"{sl}+{v}")
            stat_text = " / ".join(stat_parts) if stat_parts else ""
            label = f"{is_eq}{item['name']}"
            if len(label) > 100:
                label = label[:97] + "..."

            options.append(discord.SelectOption(
                label=label,
                value=iid,
                description=stat_text[:100] if stat_text else "스탯 없음",
                emoji=RARITY_EMOJI.get(rarity, "⚪"),
            ))

        if not options:
            options.append(discord.SelectOption(label="보유 장비 없음", value="none"))

        super().__init__(placeholder="장착할 장비를 선택하세요", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_id = self.values[0]
        if selected_id == "none":
            await interaction.response.send_message("보유한 장비가 없습니다.", ephemeral=True)
            return

        item = _find_item(selected_id)
        if not item:
            await interaction.response.send_message("장비를 찾을 수 없습니다.", ephemeral=True)
            return

        udata = load_user(interaction.user.id)
        _ensure_inventory(udata)

        category = item.get("category", "weapon")
        inv_key = _inv_category_key(category)

        if selected_id not in udata["inventory"].get(inv_key, []):
            await interaction.response.send_message("보유하지 않은 장비입니다.", ephemeral=True)
            return

        if udata["equipped"].get(category) == selected_id:
            await interaction.response.send_message(f"**{item['name']}**은(는) 이미 장착 중입니다.", ephemeral=True)
            return

        old_id = udata["equipped"].get(category)
        udata["equipped"][category] = selected_id
        save_user(interaction.user.id, udata)

        rarity = _safe_rarity_str(item.get("rarity", "common"))
        r_emoji = RARITY_EMOJI.get(rarity, "⚪")
        cat_emoji = CATEGORY_EMOJIS.get(category, "📦")

        desc = f"{cat_emoji} {r_emoji} **{item['name']}** ({rarity.upper()}) 장착 완료!"
        if old_id:
            old_item = _find_item(old_id)
            if old_item:
                desc += f"\n기존 장비 **{old_item['name']}** 해제됨."

        stat_lines = []
        for sk, (sl, si) in STAT_DISPLAY.items():
            new_val = item.get("stats", {}).get(sk, 0)
            old_val = 0
            if old_id:
                old_item_data = _find_item(old_id)
                if old_item_data:
                    old_val = old_item_data.get("stats", {}).get(sk, 0)
            if new_val or old_val:
                diff = new_val - old_val
                sign = "+" if diff >= 0 else ""
                stat_lines.append(f"{si} {sl}: {old_val} → **{new_val}** ({sign}{diff})")
        if stat_lines:
            desc += f"\n\n{SEPARATOR}\n" + "\n".join(stat_lines)

        embed = discord.Embed(title="⭐ 장착 완료!", description=desc, color=COLOR_SUCCESS)
        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=ICON_URL)
        await interaction.response.send_message(embed=embed)

# ─── 커스터마이징 상점 ─────────────────────────────────────────────

from data_manager import load_json as _load_json_dm, save_json as _save_json_dm, get_user_filepath
from systems import customization as _customize


class CustomizeSelect(discord.ui.Select):
    """커스터마이징 항목을 드롭다운으로 구매 → 즉시 적용 + 결과 안내 + 미리보기."""

    def __init__(self, owner_id: int, owned: list):
        self.owner_id = owner_id
        options = []
        for item_id, item in _customize.CUSTOMIZATION_ITEMS.items():
            price = item.get("price", 0)
            price_txt = "무료" if price == 0 else f"{price:,}원"
            owned_mark = " ✓보유" if item_id in owned else ""
            options.append(discord.SelectOption(
                label=f"{item['name']}{owned_mark}"[:100],
                description=f"{price_txt} · {item.get('desc','')}"[:100],
                value=item_id,
                emoji=item.get("emoji"),
            ))
        super().__init__(placeholder="커스터마이징 항목을 선택하세요...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("본인만 조작할 수 있습니다.", ephemeral=True)
            return

        item_id = self.values[0]
        fp = get_user_filepath(str(self.owner_id))

        # ★ 원자적 저장 대상 원본을 그대로 로드 (마이그레이션/기본값 주입 없음)
        data = _load_json_dm(fp, None)
        if data is None:
            await interaction.response.send_message("❌ 먼저 `/가입` 해주세요.", ephemeral=True)
            return

        ok, msg = _customize.purchase(data, item_id)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return

        # 구매 성공 → 원자적 저장 (재시작/에러에도 무손실)
        try:
            _save_json_dm(fp, data)
        except Exception:
            await interaction.response.send_message(
                "❌ 저장 중 오류가 발생했습니다. 변경사항이 적용되지 않았습니다.", ephemeral=True
            )
            return

        # 실시간 미리보기 카드
        embed = discord.Embed(title="🎨 커스터마이징 적용 완료", description=msg, color=COLOR_SUCCESS)
        try:
            from utils.card_service import build_profile_card_file
            file = await build_profile_card_file(interaction.user, data)
            await interaction.response.send_message(embed=embed, file=file, ephemeral=True)
        except Exception:
            await interaction.response.send_message(embed=embed, ephemeral=True)


class CustomizeView(discord.ui.View):
    def __init__(self, owner_id: int, owned: list):
        super().__init__(timeout=120)
        self.add_item(CustomizeSelect(owner_id, owned))


# ─── Cog ──────────────────────────────────────────────────────────

class ShopCog(commands.Cog):
    """상점 관련 슬래시 커맨드 모음."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="커스터마이징", description="프로필 카드 디자인을 구매/변경합니다.")
    async def customize_command(self, interaction: discord.Interaction):
        fp = get_user_filepath(str(interaction.user.id))
        data = _load_json_dm(fp, None)
        if data is None:
            await interaction.response.send_message("❌ 먼저 `/가입` 해주세요.", ephemeral=True)
            return

        owned = _customize.get_owned(data)
        money = data.get("money", 0)

        lines = [f"💰 보유 금액: **{money:,}원**\n"]
        for item_id, item in _customize.CUSTOMIZATION_ITEMS.items():
            price = item.get("price", 0)
            price_txt = "무료" if price == 0 else f"{price:,}원"
            mark = " ✓" if item_id in owned else ""
            lines.append(f"{item.get('emoji','•')} **{item['name']}**{mark} — {price_txt}\n　{item.get('desc','')}")

        embed = discord.Embed(
            title="🎨 프로필 카드 커스터마이징",
            description="\n".join(lines),
            color=COLOR_DEFAULT,
        )
        embed.set_footer(text="랜덤 색상 항목은 구매 시 결과 헥사코드를 알려드립니다. · 재구매로 색 리롤 가능")
        await interaction.response.send_message(
            embed=embed, view=CustomizeView(interaction.user.id, owned), ephemeral=True
        )

    @app_commands.command(name="상점", description="냥이 상점을 엽니다.")
    async def shop_command(self, interaction: discord.Interaction):
        udata = load_user(interaction.user.id)
        _ensure_inventory(udata)

        # 튜토리얼: visit_shop
        tutorial_reward_text = None
        if udata.get("tutorial_step") == "visit_shop":
            step_data = _cfg.TUTORIAL_STEPS.get("visit_shop", {})
            reward_money = step_data.get("reward_money", 0)
            reward_exp = step_data.get("reward_exp", 0)
            if reward_money:
                udata["money"] = udata.get("money", 0) + reward_money
            if reward_exp:
                udata["exp"] = udata.get("exp", 0) + reward_exp
            udata["tutorial_step"] = step_data.get("next", "complete")
            save_user(interaction.user.id, udata)
            parts = []
            if reward_money:
                parts.append(f"💰 +{reward_money:,}원")
            if reward_exp:
                parts.append(f"✨ +{reward_exp} EXP")
            if parts:
                tutorial_reward_text = " | ".join(parts)

        embed = discord.Embed(
            title="🏪 냥이 상점",
            description=(
                f"어서오세요! 장비를 구매하여 납치 성공률과 전투력을 올려보세요.\n\n"
                f"💰 보유 금액: **{udata.get('money', 0):,}원**\n"
                f"📊 현재 레벨: **Lv.{udata.get('level', 1)}**\n\n"
                f"아래 드롭다운에서 카테고리를 선택하세요!"
            ),
            color=COLOR_DEFAULT,
        )
        embed.add_field(name="⚔️ 무기", value="공격력 증가 → 전투에서 유리", inline=True)
        embed.add_field(name="🔧 도구", value="납치 보너스 증가 → 성공률 UP", inline=True)
        embed.add_field(name="💍 악세서리", value="체력 보너스 증가 → 생존력 UP", inline=True)

        if tutorial_reward_text:
            embed.add_field(name="📚 튜토리얼 완료 — 상점 방문!", value=tutorial_reward_text, inline=False)

        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=ICON_URL)
        view = ShopView(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="장착", description="보유한 장비를 장착합니다.")
    @app_commands.describe(slot="장착할 슬롯")
    @app_commands.choices(slot=[
        app_commands.Choice(name="⚔️ 무기", value="weapon"),
        app_commands.Choice(name="🔧 도구", value="tool"),
        app_commands.Choice(name="💍 악세서리", value="accessory"),
    ])
    async def equip_command(self, interaction: discord.Interaction, slot: str):
        udata = load_user(interaction.user.id)
        _ensure_inventory(udata)

        inv_key = _inv_category_key(slot)
        item_ids = udata["inventory"].get(inv_key, [])

        if not item_ids:
            cat_name = CATEGORY_NAMES.get(slot, slot)
            embed = discord.Embed(title="📦 장비 없음", description=f"**{cat_name}** 카테고리에 보유한 장비가 없습니다.\n`/상점`에서 먼저 구매하세요!", color=COLOR_WARNING)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        view = discord.ui.View(timeout=60)
        view.add_item(EquipSelect(udata, slot))
        cat_name = CATEGORY_NAMES.get(slot, slot)
        embed = discord.Embed(title=f"⭐ {cat_name} 장착", description="아래 드롭다운에서 장착할 장비를 선택하세요.", color=COLOR_DEFAULT)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="장착해제", description="장착 중인 장비를 해제합니다.")
    @app_commands.describe(slot="해제할 슬롯")
    @app_commands.choices(slot=[
        app_commands.Choice(name="무기", value="weapon"),
        app_commands.Choice(name="도구", value="tool"),
        app_commands.Choice(name="악세서리", value="accessory"),
    ])
    async def unequip_command(self, interaction: discord.Interaction, slot: str):
        udata = load_user(interaction.user.id)
        _ensure_inventory(udata)
        current = udata["equipped"].get(slot)
        if not current:
            cat_name = CATEGORY_NAMES.get(slot, slot)
            embed = discord.Embed(title="❌ 장착된 장비 없음", description=f"**{cat_name}** 슬롯에 장착된 장비가 없습니다.", color=COLOR_ERROR)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        item = _find_item(current)
        udata["equipped"][slot] = None
        save_user(interaction.user.id, udata)
        name = item["name"] if item else current
        embed = discord.Embed(title="🔄 장착 해제", description=f"**{name}**을(를) 장착 해제했습니다.", color=COLOR_DEFAULT)
        embed.set_footer(text=EMBED_FOOTER_TEXT, icon_url=ICON_URL)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="장비인벤토리", description="보유한 장비 목록을 확인합니다.")
    async def equipment_inventory_command(self, interaction: discord.Interaction):
        udata = load_user(interaction.user.id)
        _ensure_inventory(udata)
        inv = udata["inventory"]
        equipped = udata["equipped"]

        embed = discord.Embed(
            title=f"🎒 {interaction.user.display_name}의 장비 인벤토리",
            description=f"💰 보유 금액: **{udata.get('money', 0):,}원** | 레벨: **Lv.{udata.get('level', 1)}**\n{SEPARATOR}",
            color=COLOR_DEFAULT,
        )

        for cat, cat_key in [("weapon", "weapons"), ("tool", "tools"), ("accessory", "accessories")]:
            cat_emoji = CATEGORY_EMOJIS.get(cat, "📦")
            cat_name = CATEGORY_NAMES.get(cat, cat)
            equipped_id = equipped.get(cat)
            item_ids = inv.get(cat_key, [])

            if not item_ids:
                embed.add_field(name=f"{cat_emoji} {cat_name}", value="> 장비 없음", inline=False)
                continue

            lines = []
            for iid in item_ids:
                item = _find_item(iid)
                if not item:
                    continue
                rarity = _safe_rarity_str(item.get("rarity", "common"))
                r_emoji = RARITY_EMOJI.get(rarity, "⚪")
                is_eq = "⭐" if iid == equipped_id else "  "
                primary = ""
                for sk, (sl, si) in STAT_DISPLAY.items():
                    v = item.get("stats", {}).get(sk)
                    if v:
                        primary = f"{si}+{v}"
                        break
                lines.append(f"> {is_eq} {r_emoji} **{item['name']}** — {primary}")

            embed.add_field(name=f"{cat_emoji} {cat_name} ({len(item_ids)}개)", value="\n".join(lines) if lines else "> 장비 없음", inline=False)

        embed.set_footer(text=f"{EMBED_FOOTER_TEXT} | /장착 으로 장비 장착", icon_url=ICON_URL)
        await interaction.response.send_message(embed=embed)


# ─── stats helper ────────────────────────────────────────

def get_equipment_stats(user_id: int) -> Dict[str, int]:
    udata = load_user(user_id)
    _ensure_inventory(udata)
    equipped = udata.get("equipped", {})
    totals: Dict[str, int] = {}
    for slot in ("weapon", "tool", "accessory"):
        item_id = equipped.get(slot)
        if not item_id:
            continue
        item = _find_item(item_id)
        if not item:
            continue
        for stat_key, val in item.get("stats", {}).items():
            totals[stat_key] = totals.get(stat_key, 0) + val
    return totals


async def setup(bot: commands.Bot):
    await bot.add_cog(ShopCog(bot))
