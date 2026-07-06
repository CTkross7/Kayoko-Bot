"""
commands/raid_commands.py
시즌 총력전 / 대결전 커맨드
 - /총력전: 이번 시즌 보스 공격 (본인 로스터 기준 딜)
 - /총력전랭킹: 누적 딜 랭킹
 - /총력전보스: 보스 정보 + 내 기여
 - /총력전보상: 지난 시즌 백분위 보상 수령
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config as _cfg
from models.user import load_user_data, save_user_data
from models.element import defense_label, attack_label
from systems import raid as R

COLOR_DEFAULT = _cfg.COLOR_DEFAULT
COLOR_SUCCESS = _cfg.COLOR_SUCCESS
COLOR_ERROR = _cfg.COLOR_ERROR
COLOR_WARNING = _cfg.COLOR_WARNING
BOT_ICON_URL = _cfg.BOT_ICON_URL
ELIGMA = _cfg.ELIGMA_EMOJI


def _hp_bar(cur, mx, length=18):
    ratio = max(0.0, min(1.0, cur / mx)) if mx else 0
    filled = round(ratio * length)
    return "🟥" * filled + "⬛" * (length - filled)


class RaidCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="총력전", description="이번 시즌 총력전 보스를 공격합니다. (본인 로스터 기준)")
    async def raid_attack(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = load_user_data(interaction.user.id)
        if not data:
            await interaction.followup.send("❌ 먼저 `/가입` 해주세요.", ephemeral=True)
            return

        result = await R.attack(interaction.user.id, interaction.user.display_name, data)
        if not result["ok"]:
            await interaction.followup.send(result["msg"], ephemeral=True)
            return

        save_user_data(interaction.user.id, data)

        b = result["boss"]
        embed = discord.Embed(
            title=f"⚔️ 총력전 — {b['name']} (시즌 {b['season']})",
            color=COLOR_SUCCESS if not result["killed"] else 0xFFD700,
        )
        embed.add_field(
            name="가한 데미지",
            value=f"💥 **{result['damage']:,}**" + (f"  (내 누적: {result['my_total']:,})"),
            inline=False,
        )
        embed.add_field(name="보스 상태",
                        value=f"{_hp_bar(b['current_hp'], b['max_hp'])}\n**{b['current_hp']:,} / {b['max_hp']:,}**",
                        inline=False)
        embed.add_field(name="보스 속성",
                        value=f"{defense_label(b['defense_type'])} · 공격 {attack_label(b['attack_type'])} · 지형 {b.get('terrain','-')}",
                        inline=True)
        embed.add_field(name="보상", value=f"💰 +{result['reward_money']:,}원", inline=True)
        embed.set_footer(text=f"남은 공격 {result['attempts_left']}회 · 딜은 보유·강화 냥이로만 산정")

        if result["killed"]:
            embed.description = f"🎉 **{b['name']} 토벌 완료!** 전 서버가 힘을 합쳤습니다. `/총력전랭킹` 확인!"
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="총력전랭킹", description="이번 시즌 누적 딜 랭킹을 봅니다.")
    async def raid_ranking(self, interaction: discord.Interaction):
        await interaction.response.defer()
        r = R.get_ranking(limit=10)
        embed = discord.Embed(
            title=f"🏆 총력전 랭킹 — {r['boss']} (시즌 {r['season']})",
            color=COLOR_DEFAULT,
        )
        embed.add_field(name="보스 HP",
                        value=f"{_hp_bar(r['current_hp'], r['max_hp'])}\n**{r['current_hp']:,} / {r['max_hp']:,}**",
                        inline=False)
        if r["top"]:
            medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
            lines = [f"{medals[i]} **{i+1}.** {nm} — {dmg:,}" for i, (uid, dmg, nm) in enumerate(r["top"])]
            embed.add_field(name=f"누적 딜 TOP (참여 {r['total']}명)", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="랭킹", value="아직 참여자가 없습니다. `/총력전`으로 첫 공격을!", inline=False)

        mine = R.my_rank(interaction.user.id)
        if mine:
            tier = R.rank_reward_for(mine["percentile"])
            embed.add_field(
                name="내 순위",
                value=f"**{mine['rank']}/{mine['total']}위** · 누적 {mine['damage']:,} · 예상보상 {tier['label']}",
                inline=False,
            )
        embed.set_footer(text="시즌 종료 후 /총력전보상 으로 백분위 보상 수령", icon_url=BOT_ICON_URL)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="총력전보스", description="이번 시즌 보스 정보와 내 기여를 봅니다.")
    async def raid_boss_info(self, interaction: discord.Interaction):
        r = R.get_ranking(limit=0)
        embed = discord.Embed(title=f"👹 {r['boss']} — 시즌 {r['season']}", color=COLOR_WARNING)
        embed.add_field(name="HP", value=f"{_hp_bar(r['current_hp'], r['max_hp'])}\n**{r['current_hp']:,} / {r['max_hp']:,}**", inline=False)
        embed.add_field(name="방어 속성", value=defense_label(r["defense_type"]), inline=True)
        embed.add_field(name="공격 속성", value=attack_label(r["attack_type"]), inline=True)
        embed.add_field(name="지형", value=r.get("terrain", "-"), inline=True)
        # 공략 팁: 방어 속성에 유효한 공격 속성 안내
        counter = {"light": "🔥 폭발", "heavy": "🎯 관통", "special": "🔮 신비", "elastic": "💠 진동"}
        embed.add_field(name="💡 유효 공격 속성",
                        value=f"{counter.get(r['defense_type'],'-')} 냥이를 강화해 편성하면 딜이 크게 증가합니다.",
                        inline=False)
        embed.add_field(name="참여 조건", value=f"🔒 계정 레벨 **{_cfg.RAID_LEVEL_REQ}+** · 일일 **{_cfg.RAID_DAILY_ATTEMPTS}회**", inline=False)
        mine = R.my_rank(interaction.user.id)
        if mine:
            embed.add_field(name="내 기여", value=f"{mine['rank']}/{mine['total']}위 · 누적 {mine['damage']:,}", inline=False)
        embed.set_footer(text="딜은 남의 힘이 아닌 본인 보유·강화 냥이로만 산정됩니다.", icon_url=BOT_ICON_URL)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="총력전보상", description="지난 시즌 누적 딜 백분위 보상을 수령합니다.")
    async def raid_claim(self, interaction: discord.Interaction):
        data = load_user_data(interaction.user.id)
        if not data:
            await interaction.response.send_message("❌ 먼저 `/가입` 해주세요.", ephemeral=True)
            return
        ok, msg = R.claim_last_season(interaction.user.id, data)
        if ok:
            save_user_data(interaction.user.id, data)
            await interaction.response.send_message(embed=discord.Embed(title="🎁 시즌 보상", description=msg, color=COLOR_SUCCESS))
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(RaidCog(bot))
