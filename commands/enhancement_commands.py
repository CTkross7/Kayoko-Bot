"""
commands/enhancement_commands.py
냥이 성작(星作)/초월 강화 + 엘리그마 커맨드
 - /강화등록: 일반 냥이 1마리를 강화 대상으로 승격
 - /강화: 강화 냥이 선택 → 성작/초월
 - /강화냥이: 강화 냥이 목록(분리 표기)
 - /엘리그마: 엘리그마 보유/일일 현황
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config as _cfg
from models.user import load_user_data, save_user_data
from systems import enhancement as E

COLOR_DEFAULT = _cfg.COLOR_DEFAULT
COLOR_SUCCESS = _cfg.COLOR_SUCCESS
COLOR_ERROR = _cfg.COLOR_ERROR
BOT_ICON_URL = _cfg.BOT_ICON_URL
ELIGMA = _cfg.ELIGMA_EMOJI


def _detail_embed(user_data: dict, iid: str) -> discord.Embed:
    inst = E.get_instance(user_data, iid)
    if not inst:
        return discord.Embed(title="❌ 오류", description="강화 냥이를 찾을 수 없습니다.", color=COLOR_ERROR)
    stats = E.get_enhanced_stats(inst)
    star = inst.get("star", 0)
    t = inst.get("transcend", 0)
    embed = discord.Embed(title=f"🔧 {inst['name']} 강화", color=COLOR_DEFAULT)
    embed.add_field(name="현재 등급", value=f"**{E.star_label(inst)}**  (스탯 x{stats['mult']})", inline=False)
    embed.add_field(name="실효 스탯",
                    value=f"⚔️ 공격 {stats['base_power']} · ❤️ HP {stats['hp']} · 🪙 코인 {stats['coin_power']}",
                    inline=False)
    if star < E.MAX_STAR:
        c = E.star_cost(inst["name"], star)
        fail = _cfg.STAR_FAIL_CHANCE.get(star, 0) * 100
        dest = _cfg.STAR_DESTROY_CHANCE.get(star, 0) * 100
        risk = f" · 실패 {fail:.0f}%" + (f" · 파괴 {dest:.0f}%" if dest else "") if fail else ""
        embed.add_field(name=f"성작 → {star+1}성",
                        value=f"{ELIGMA} {c['eligma']:,} · 💰 {c['gold']:,}원{risk}", inline=False)
    elif t < E.MAX_TRANSCEND:
        c = E.transcend_cost(inst["name"], t)
        fail = _cfg.TRANSCEND_FAIL_CHANCE.get(t, 0) * 100
        dest = _cfg.TRANSCEND_DESTROY_CHANCE.get(t, 0) * 100
        risk = f" · 실패 {fail:.0f}%" + (f" · 파괴 {dest:.0f}%" if dest else "")
        embed.add_field(name=f"초월 → 전무 {t+1}성",
                        value=f"{ELIGMA} {c['eligma']:,} · 💰 {c['gold']:,}원{risk}", inline=False)
    else:
        embed.add_field(name="최대 강화", value="✅ 5성 + 전무 3성 완성!", inline=False)
    embed.set_footer(text=f"보유: {ELIGMA} {user_data.get('eligma',0):,} · 💰 {user_data.get('money',0):,}원")
    return embed


class EnhanceActionView(discord.ui.View):
    def __init__(self, owner_id: int, iid: str):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.iid = iid

    async def _guard(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("본인만 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⭐ 성작", style=discord.ButtonStyle.success)
    async def star_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        data = load_user_data(self.owner_id)
        ok, msg = E.star_up(data, self.iid)
        if ok:
            save_user_data(self.owner_id, data)
        embed = _detail_embed(data, self.iid)
        embed.description = msg
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🌟 초월", style=discord.ButtonStyle.primary)
    async def transcend_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        data = load_user_data(self.owner_id)
        ok, msg = E.transcend(data, self.iid)
        if ok:
            save_user_data(self.owner_id, data)
        embed = _detail_embed(data, self.iid)
        embed.description = msg
        await interaction.response.edit_message(embed=embed, view=self)


class EnhanceSelect(discord.ui.Select):
    def __init__(self, owner_id: int, enhanced: list):
        self.owner_id = owner_id
        options = []
        for inst in enhanced[:25]:
            options.append(discord.SelectOption(
                label=f"{inst.get('name','?')} · {E.star_label(inst)}"[:100],
                value=inst.get("iid", ""),
            ))
        if not options:
            options = [discord.SelectOption(label="강화 냥이 없음", value="none")]
        super().__init__(placeholder="강화할 냥이를 선택하세요...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("본인만 조작할 수 있습니다.", ephemeral=True)
            return
        if self.values[0] == "none":
            await interaction.response.send_message(
                "강화할 냥이가 없습니다. `/강화등록 [냥이]`로 먼저 등록하세요.", ephemeral=True)
            return
        data = load_user_data(self.owner_id)
        iid = self.values[0]
        await interaction.response.edit_message(
            embed=_detail_embed(data, iid), view=_action_with_select(self.owner_id, data, iid))


def _action_with_select(owner_id, data, iid):
    view = EnhanceActionView(owner_id, iid)
    view.add_item(EnhanceSelect(owner_id, data.get("enhanced_cats", [])))
    return view


# ─── 장비 강화 ───────────────────────────────────────────────

def _equip_embed(user_data: dict, unique_id: str) -> discord.Embed:
    item = E._find_equipment(user_data, unique_id)
    if not item:
        return discord.Embed(title="❌ 오류", description="장비를 찾을 수 없습니다.", color=COLOR_ERROR)
    level = int(item.get("enhance_level", 0))
    rarity = item.get("grade", item.get("rarity", "common"))
    embed = discord.Embed(title=f"🛠️ {item.get('name','장비')} 강화", color=COLOR_DEFAULT)
    stats = item.get("stats", {})
    mult = 1.0 + level * _cfg.EQUIP_ENHANCE_STAT_MULT
    stat_txt = " · ".join(f"{k} +{int(v*mult)}" for k, v in stats.items()) or "-"
    embed.add_field(name=f"현재 +{level}", value=f"실효 스탯: {stat_txt} (x{mult:.2f})", inline=False)
    if level < _cfg.EQUIP_MAX_ENHANCE:
        c = E.equip_enhance_cost(rarity, level)
        fail = _cfg.EQUIP_FAIL_CHANCE.get(level, 0) * 100
        dest = _cfg.EQUIP_DESTROY_CHANCE.get(level, 0) * 100
        risk = (f" · 실패 {fail:.0f}%" + (f" · 파괴 {dest:.0f}%" if dest else "")) if fail else ""
        embed.add_field(name=f"강화 → +{level+1}",
                        value=f"💰 {c['gold']:,}원 · {ELIGMA} {c['eligma']:,}{risk}", inline=False)
    else:
        embed.add_field(name="최대 강화", value=f"✅ +{_cfg.EQUIP_MAX_ENHANCE} 달성", inline=False)
    embed.set_footer(text=f"보유: 💰 {user_data.get('money',0):,}원 · {ELIGMA} {user_data.get('eligma',0):,}")
    return embed


class EquipSelect(discord.ui.Select):
    def __init__(self, owner_id, items):
        self.owner_id = owner_id
        options = [discord.SelectOption(label=label[:100], value=uid)
                   for (uid, label, lv, rarity) in items[:25]]
        super().__init__(placeholder="강화할 장비를 선택하세요...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("본인만 조작할 수 있습니다.", ephemeral=True)
            return
        data = load_user_data(self.owner_id)
        uid = self.values[0]
        view = EquipEnhanceView(self.owner_id, E.list_enhanceable_equipment(data), selected=uid)
        await interaction.response.edit_message(embed=_equip_embed(data, uid), view=view)


class EquipEnhanceView(discord.ui.View):
    def __init__(self, owner_id, items, selected=None):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.selected = selected or (items[0][0] if items else None)
        if items:
            self.add_item(EquipSelect(owner_id, items))

    @discord.ui.button(label="🛠️ 강화", style=discord.ButtonStyle.success)
    async def enhance_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("본인만 조작할 수 있습니다.", ephemeral=True)
            return
        data = load_user_data(self.owner_id)
        ok, msg = E.equip_enhance(data, self.selected)
        if ok:
            save_user_data(self.owner_id, data)
        embed = _equip_embed(data, self.selected)
        embed.description = msg
        # 셀렉트 갱신
        view = EquipEnhanceView(self.owner_id, E.list_enhanceable_equipment(data), selected=self.selected)
        await interaction.response.edit_message(embed=embed, view=view)


class EnhancementCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _owned_regular_ac(self, interaction: discord.Interaction, current: str):
        data = load_user_data(interaction.user.id) or {}
        cats = data.get("cats", {})
        names = []
        if isinstance(cats, dict):
            for cid, info in cats.items():
                names.append(info.get("name", cid) if isinstance(info, dict) else cid)
        cur = (current or "").lower()
        return [app_commands.Choice(name=n[:100], value=n) for n in names if cur in n.lower()][:25]

    @app_commands.command(name="강화등록", description="일반 냥이 1마리를 강화 대상(0성)으로 등록합니다.")
    @app_commands.describe(냥이="강화 대상으로 만들 보유 냥이")
    @app_commands.autocomplete(냥이=_owned_regular_ac)
    async def register_command(self, interaction: discord.Interaction, 냥이: str):
        await interaction.response.defer(ephemeral=True)
        data = load_user_data(interaction.user.id)
        if not data:
            await interaction.followup.send("❌ 먼저 `/가입` 해주세요.", ephemeral=True)
            return
        ok, msg, inst = E.promote_to_enhanced(data, 냥이)
        if ok:
            save_user_data(interaction.user.id, data)
            embed = _detail_embed(data, inst["iid"])
            embed.description = msg + "\n\n`/강화`로 성작을 진행하세요."
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {msg}", ephemeral=True)

    @app_commands.command(name="강화", description="강화 냥이를 성작/초월합니다.")
    async def enhance_command(self, interaction: discord.Interaction):
        data = load_user_data(interaction.user.id)
        if not data:
            await interaction.response.send_message("❌ 먼저 `/가입` 해주세요.", ephemeral=True)
            return
        enhanced = data.get("enhanced_cats", [])
        if not enhanced:
            await interaction.response.send_message(
                "강화 냥이가 없습니다. `/강화등록 [냥이]`로 먼저 등록하세요.", ephemeral=True)
            return
        view = EnhanceActionView(interaction.user.id, enhanced[0].get("iid", ""))
        view.add_item(EnhanceSelect(interaction.user.id, enhanced))
        await interaction.response.send_message(
            embed=_detail_embed(data, enhanced[0].get("iid", "")), view=view, ephemeral=True)

    @app_commands.command(name="강화냥이", description="강화(성작/초월) 냥이 목록을 봅니다.")
    async def enhanced_list_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = load_user_data(interaction.user.id)
        if not data:
            await interaction.followup.send("❌ 먼저 `/가입` 해주세요.", ephemeral=True)
            return
        enhanced = data.get("enhanced_cats", [])
        rows = []
        for inst in enhanced[:12]:
            s = E.get_enhanced_stats(inst)
            rows.append(("⭐", inst.get("name", "?"), f"{E.star_label(inst)} · x{s['mult']}"))
        if not rows:
            rows = [("📭", "강화 냥이", "없음 — /강화등록")]
        st = E.eligma_status(data)
        sections = [("강화 냥이 (일반과 분리)", rows),
                    ("엘리그마", [(ELIGMA, "보유", f"{st['eligma']:,}"),
                                  ("📅", "오늘 획득", f"{st['today']}/{st['cap']}")])]
        try:
            from utils.card_service import build_stat_card_file
            file = await build_stat_card_file(
                interaction.user, data, title="강화 냥이",
                subtitle=f"{len(enhanced)}마리", sections=sections, filename="enhanced.png")
            await interaction.followup.send(file=file)
        except Exception:
            import traceback; traceback.print_exc()
            embed = discord.Embed(title="🔧 강화 냥이", color=COLOR_DEFAULT)
            embed.description = "\n".join(f"{r[1]} — {r[2]}" for r in rows)
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="장비강화", description="장비 티어를 강화합니다. (재료 + 실패/파괴)")
    async def equip_enhance_command(self, interaction: discord.Interaction):
        data = load_user_data(interaction.user.id)
        if not data:
            await interaction.response.send_message("❌ 먼저 `/가입` 해주세요.", ephemeral=True)
            return
        items = E.list_enhanceable_equipment(data)
        if not items:
            await interaction.response.send_message(
                "강화할 장비가 없습니다. `/상점`에서 장비를 구매하세요.", ephemeral=True)
            return
        view = EquipEnhanceView(interaction.user.id, items)
        await interaction.response.send_message(
            embed=_equip_embed(data, items[0][0]), view=view, ephemeral=True)

    @app_commands.command(name="엘리그마", description="엘리그마 보유량과 오늘 획득 현황을 봅니다.")
    async def eligma_command(self, interaction: discord.Interaction):
        data = load_user_data(interaction.user.id)
        if not data:
            await interaction.response.send_message("❌ 먼저 `/가입` 해주세요.", ephemeral=True)
            return
        st = E.eligma_status(data)
        embed = discord.Embed(
            title=f"{ELIGMA} 엘리그마",
            description=(f"보유: **{st['eligma']:,}**\n"
                        f"오늘 획득: **{st['today']}/{st['cap']}** (잔여 {st['remaining']})\n\n"
                        f"냥이를 `/냥이분양`하면 희귀할수록 높은 확률로 엘리그마가 드랍됩니다."),
            color=COLOR_DEFAULT,
        )
        embed.set_footer(text="엘리그마는 성작/초월 재료입니다.", icon_url=BOT_ICON_URL)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(EnhancementCog(bot))
