"""
commands/battle_commands.py
전투 커맨드 Cog — systems/battle.py 연동
"""

import discord
from discord import app_commands
from discord.ext import commands
from utils.cooldown_lock import acquire_lock, release_lock, build_locked_embed

from systems.battle import (
    run_battle_sequence,
    run_weekly_boss_sequence,
    load_user,
    get_player_stats,
    get_equipment_stats,
    check_achievements,
    _build_hp_bar,
    _get_current_weekly_boss_key,
    SKILL_EFFECTS,
    WEEKLY_BOSS_TEMPLATES,
    COLOR_DEFAULT,
    COLOR_SUCCESS,
    COLOR_ERROR,
    COLOR_WARNING,
    DAILY_LIMITS,
    FOOTER_TEXT,
    BOT_ICON_URL,
)

import config as _cfg

from data_manager import load_json, save_json, get_user_filepath
from models.cat import get_cat_by_name
from models.element import get_cat_types, type_badge, attack_label, defense_label


class BattleCommandsCog(commands.Cog):
    """전투 관련 명령어"""

    def __init__(self, bot):
        self.bot = bot

    # ─────────────────────────────────────────────
    # 선봉 냥이 편성 (/편성)
    # ─────────────────────────────────────────────
    async def _team_autocomplete(self, interaction: discord.Interaction, current: str):
        """보유 냥이 이름 자동완성."""
        fp = get_user_filepath(str(interaction.user.id))
        data = load_json(fp, None) or {}
        cats = data.get("cats") or {}
        names = list(cats.keys()) if isinstance(cats, dict) else []
        cur = (current or "").lower()
        filtered = [n for n in names if cur in n.lower()][:25]
        return [app_commands.Choice(name=n[:100], value=n) for n in filtered]

    @app_commands.command(
        name="편성",
        description="전투/주간보스에 나갈 선봉 냥이를 지정합니다. (속성 상성 결정)",
    )
    @app_commands.describe(냥이="선봉으로 세울 보유 냥이 이름 (비우면 현재 편성 확인)")
    @app_commands.autocomplete(냥이=_team_autocomplete)
    async def team_command(self, interaction: discord.Interaction, 냥이: str = None):
        fp = get_user_filepath(str(interaction.user.id))
        # ★ 순수 로드: 마이그레이션/기본값 주입 없이 원본 그대로 읽는다.
        data = load_json(fp, None)

        if data is None:
            await interaction.response.send_message(
                "❌ 아직 가입하지 않았습니다. `/가입` 후 이용해주세요.", ephemeral=True
            )
            return

        cats = data.get("cats") or {}
        owned = set(cats.keys()) if isinstance(cats, dict) else set()

        # ── 인자 없음: 현재 선봉 확인 ──
        if not 냥이:
            team = data.get("battle_team") or []
            lead = team[0] if isinstance(team, list) and team else None
            embed = discord.Embed(title="🎯 선봉 냥이 편성", color=COLOR_DEFAULT)
            if lead and lead in owned:
                cat_def = get_cat_by_name(lead)
                atk, dfn = get_cat_types(cat_def)
                embed.description = (
                    f"현재 선봉: **{lead}**\n"
                    f"{attack_label(atk)} / {defense_label(dfn)}"
                )
            else:
                embed.description = (
                    "현재 선봉이 **미편성** 상태입니다.\n"
                    "`/편성 [냥이]`로 선봉을 지정하면 전투에서 속성 상성이 적용됩니다."
                )
            embed.set_footer(text="선봉 냥이의 공격/방어 속성이 전투 상성을 결정합니다.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # ── 인자 있음: 편성 변경 ──
        if 냥이 not in owned:
            await interaction.response.send_message(
                f"❌ **{냥이}** 냥이를 보유하고 있지 않습니다. 이름을 정확히 입력해주세요.",
                ephemeral=True,
            )
            return

        # ★ battle_team 필드만 수정 — 그 외 유저 데이터는 절대 건드리지 않는다.
        data["battle_team"] = [냥이]
        save_json(fp, data)

        cat_def = get_cat_by_name(냥이)
        atk, dfn = get_cat_types(cat_def)
        embed = discord.Embed(
            title="✅ 선봉 편성 완료",
            description=f"선봉 냥이를 **{냥이}**(으)로 지정했습니다!\n{attack_label(atk)} / {defense_label(dfn)}",
            color=COLOR_SUCCESS,
        )
        embed.set_footer(text="이제 /전투 · /주간보스에서 이 냥이의 속성 상성이 적용됩니다.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="전투", description="야생의 적과 전투합니다!")
    async def battle_command(self, interaction):
        uid = interaction.user.id

        if not acquire_lock(uid, "battle"):
            await interaction.response.send_message(
                embed=build_locked_embed(uid), ephemeral=True
            )
            return

        try:
            await run_battle_sequence(interaction)
        except Exception as e:
            embed = discord.Embed(
                title="❌ 오류 발생",
                description=f"전투 중 오류가 발생했습니다.\n`{str(e)[:100]}`",
                color=COLOR_ERROR,
            )
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.response.send_message(embed=embed)
            except Exception:
                pass
        finally:
            release_lock(uid)

    @app_commands.command(name="주간보스", description="이번 주의 보스에 도전합니다!")
    async def weekly_boss_command(self, interaction):
        uid = interaction.user.id

        if not acquire_lock(uid, "weekly_boss"):
            await interaction.response.send_message(
                embed=build_locked_embed(uid), ephemeral=True
            )
            return

        try:
            await run_weekly_boss_sequence(interaction)
        except Exception as e:
            embed = discord.Embed(
                title="❌ 오류 발생",
                description=f"주간보스 중 오류가 발생했습니다.\n`{str(e)[:100]}`",
                color=COLOR_ERROR,
            )
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.response.send_message(embed=embed)
            except Exception:
                pass
        finally:
            release_lock(uid)

    @app_commands.command(name="전투정보", description="내 전투 스탯을 확인합니다.")
    async def battle_info_command(self, interaction):
        udata = load_user(interaction.user.id)
        player = get_player_stats(udata)
        stats = udata.get("stats", {})

        embed = discord.Embed(
            title=f"⚔️ {interaction.user.display_name}의 전투 정보",
            color=COLOR_DEFAULT,
        )

        hp_bar = _build_hp_bar(player["max_hp"], player["max_hp"])
        embed.add_field(
            name="📊 전투 스탯",
            value=(
                f"❤️ HP: {hp_bar} **{player['max_hp']}**\n"
                f"⚔️ 공격력: **{player['attack']}**\n"
                f"🛡️ 방어력: **{player['defense']}**"
            ),
            inline=False,
        )

        eq_stats = get_equipment_stats(udata)
        level = udata.get("level", 1)
        combat_lv = udata.get("skills", {}).get("combat", 0)
        combat_fx = SKILL_EFFECTS.get("combat", {})

        embed.add_field(
            name="📋 스탯 분해",
            value=(
                f"기본(Lv.{level}): ATK {10+(level-1)*3}"
                f" | HP {100+(level-1)*15}"
                f" | DEF {5+(level-1)*2}\n"
                f"전투 스킬(Lv.{combat_lv}):"
                f" ATK +{combat_lv*combat_fx.get('battle_power_bonus',2.5):.0f}"
                f" | HP +{combat_lv*combat_fx.get('battle_hp_bonus',8):.0f}\n"
                f"장비: ATK +{eq_stats.get('attack',0)}"
                f" | HP +{eq_stats.get('hp_bonus',0)}"
            ),
            inline=False,
        )

        embed.add_field(
            name="📈 전적",
            value=(
                f"승리: **{stats.get('battle_wins',0)}회**\n"
                f"패배: **{stats.get('battle_losses',0)}회**\n"
                f"주간 보스 처치: **{stats.get('weekly_boss_kills',0)}회**"
            ),
            inline=False,
        )

        boss_key = _get_current_weekly_boss_key()
        if boss_key:
            tmpl = WEEKLY_BOSS_TEMPLATES.get(boss_key, {})
            embed.add_field(
                name=f"💀 이번 주 보스: {tmpl.get('name','???')}",
                value=(
                    f"HP: {tmpl.get('hp','?')}"
                    f" | ATK: {tmpl.get('attack','?')}\n"
                    f"도전 가능: "
                    f"{'✅' if level >= _cfg.WEEKLY_BOSS_MIN_LEVEL else f'🔒 Lv.{_cfg.WEEKLY_BOSS_MIN_LEVEL} 필요'}"
                ),
                inline=False,
            )

        embed.set_footer(text=FOOTER_TEXT, icon_url=BOT_ICON_URL)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="전투기록", description="전투 기록을 확인합니다.")
    async def battle_record_command(self, interaction):
        udata = load_user(interaction.user.id)
        stats = udata.get("stats", {})

        wins = stats.get("battle_wins", 0)
        losses = stats.get("battle_losses", 0)
        total = wins + losses
        winrate = (wins / max(total, 1)) * 100

        embed = discord.Embed(
            title=f"⚔️ {interaction.user.display_name}의 전투 기록",
            color=COLOR_DEFAULT,
        )
        embed.add_field(
            name="📊 전적",
            value=(
                f"총 전투: **{total}회**\n"
                f"승리: **{wins}회** / 패배: **{losses}회**\n"
                f"승률: **{winrate:.1f}%**"
            ),
            inline=False,
        )

        daily = udata.get("daily_actions", {})
        battle_today = daily.get("battle", 0)
        battle_limit = DAILY_LIMITS.get("battle", 30)
        embed.add_field(
            name="📅 오늘 전투",
            value=f"**{battle_today}/{battle_limit}회**",
            inline=False,
        )

        embed.set_footer(text=FOOTER_TEXT, icon_url=BOT_ICON_URL)
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(BattleCommandsCog(bot))
