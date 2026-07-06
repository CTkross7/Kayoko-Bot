# commands/gambling_commands.py
"""
도박 커맨드 Cog — 가챠베팅, 총력전배치고사, 계정리세마라
일일 한도 + 총 이익/손실 기록
"""

import time
import discord
from discord import app_commands
from discord.ext import commands

from utils.cooldown_lock import acquire_lock, release_lock, build_locked_embed
from systems.gambling import (
    run_gacha_sequence,
    run_assault_sequence,
    run_reroll_sequence,
    GAMBLE_MIN_BET,
    GAMBLE_MAX_BET,
)

import config as _cfg

COLOR_ERROR = _cfg.COLOR_ERROR
COLOR_WARNING = _cfg.COLOR_WARNING
COLOR_SUCCESS = _cfg.COLOR_SUCCESS
BOT_ICON_URL = _cfg.BOT_ICON_URL
DAILY_LIMITS = _cfg.DAILY_LIMITS
FOOTER_TEXT = getattr(_cfg, "EMBED_FOOTER_TEXT", "카요코 봇")

from models.user import load_user_data, save_user_data


def _is_registered(uid):
    import os
    return os.path.exists(os.path.join(_cfg.USERS_DIR, f"{uid}.json"))


def _check_daily(udata, action):
    today = time.strftime("%Y-%m-%d")
    daily = udata.setdefault("daily_actions", {})
    if daily.get("date") != today:
        udata["daily_actions"] = {"date": today}
        daily = udata["daily_actions"]
    count = daily.get(action, 0)
    limit = DAILY_LIMITS.get(action, 999)
    return count < limit, count, limit


def _increment_daily(udata, action):
    daily = udata.setdefault("daily_actions", {})
    daily[action] = daily.get(action, 0) + 1


def _record_gamble_stats(udata, game_type, result_name, winnings):
    """
    공통 도박 통계 기록.
    game_type: "gacha", "assault", "reroll"
    result_name: 결과 이름 (예: "3성", "플래티넘", "FES")
    winnings: 순이익/손실 금액 (음수 가능)
    """
    stats = udata.setdefault("stats", {})
    gamble = stats.setdefault("gamble", {})

    # 게임별 횟수
    count_key = f"{game_type}_count"
    gamble[count_key] = gamble.get(count_key, 0) + 1

    # 게임별 결과 분포
    results_key = f"{game_type}_results"
    gamble.setdefault(results_key, {})
    gamble[results_key][result_name] = gamble[results_key].get(result_name, 0) + 1

    # ★ 총 이익/손실 누적 (전체 합산)
    gamble["total_profit"] = gamble.get("total_profit", 0) + winnings

    # ★ 게임별 이익/손실 누적
    profit_key = f"{game_type}_profit"
    gamble[profit_key] = gamble.get(profit_key, 0) + winnings

    # ★ 총 베팅 횟수 (전체 합산)
    gamble["total_count"] = gamble.get("total_count", 0) + 1


class GamblingCog(commands.Cog):
    """도박 관련 명령어 (일일 한도 + 이익/손실 추적)"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _validate_bet(self, interaction: discord.Interaction, bet_amount: int):
        uid = interaction.user.id

        if not _is_registered(uid):
            embed = discord.Embed(
                title="❌ 미등록 유저",
                description="`/가입` 명령어로 먼저 가입해주세요!",
                color=COLOR_ERROR,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return None, False

        if bet_amount < GAMBLE_MIN_BET:
            await interaction.followup.send(
                f"❌ 최소 베팅 금액은 **{GAMBLE_MIN_BET:,}원**입니다.", ephemeral=True
            )
            return None, False

        if bet_amount > GAMBLE_MAX_BET:
            await interaction.followup.send(
                f"❌ 최대 베팅 금액은 **{GAMBLE_MAX_BET:,}원**입니다.", ephemeral=True
            )
            return None, False

        udata = load_user_data(uid)
        if udata is None:
            await interaction.followup.send(
                "❌ 유저 데이터를 불러올 수 없습니다.", ephemeral=True
            )
            return None, False

        allowed, count, limit = _check_daily(udata, "gamble")
        if not allowed:
            embed = discord.Embed(
                title="⏰ 일일 도박 한도 초과",
                description=(
                    f"오늘의 도박 한도(**{limit}회**)를 모두 사용했습니다.\n"
                    f"현재: {count}/{limit}\n"
                    f"내일 다시 도전하세요!"
                ),
                color=COLOR_WARNING,
            )
            embed.set_footer(text=FOOTER_TEXT, icon_url=BOT_ICON_URL)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return None, False

        if udata.get("money", 0) < bet_amount:
            await interaction.followup.send(
                f"❌ 잔액이 부족합니다. (보유: {udata.get('money', 0):,}원)",
                ephemeral=True,
            )
            return None, False

        return udata, True

    # ── /가챠베팅 ──
    @app_commands.command(name="가챠베팅", description="베팅액에 따라 가챠를 진행합니다.")
    @app_commands.describe(bet_amount="베팅할 금액 (1,000원 ~ 50,000원)")
    async def gacha_command(self, interaction: discord.Interaction, bet_amount: int):
        uid = interaction.user.id

        if not acquire_lock(uid, "gacha"):
            await interaction.response.send_message(
                embed=build_locked_embed(uid), ephemeral=True
            )
            return

        try:
            await interaction.response.defer()
            udata, ok = await self._validate_bet(interaction, bet_amount)
            if not ok:
                return

            udata["money"] -= bet_amount
            result_name, winnings = await run_gacha_sequence(interaction, udata, bet_amount)

            _increment_daily(udata, "gamble")
            _record_gamble_stats(udata, "gacha", result_name, winnings)
            save_user_data(uid, udata)

        except Exception as e:
            try:
                embed = discord.Embed(
                    title="❌ 오류 발생",
                    description=f"가챠 중 오류가 발생했습니다.\n`{str(e)[:100]}`",
                    color=COLOR_ERROR,
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception:
                pass
        finally:
            release_lock(uid)

    # ── /총력전배치고사 ──
    @app_commands.command(name="총력전배치고사", description="총력전 티어에 베팅합니다.")
    @app_commands.describe(bet_amount="베팅할 금액 (1,000원 ~ 50,000원)")
    async def assault_command(self, interaction: discord.Interaction, bet_amount: int):
        uid = interaction.user.id

        if not acquire_lock(uid, "assault"):
            await interaction.response.send_message(
                embed=build_locked_embed(uid), ephemeral=True
            )
            return

        try:
            await interaction.response.defer()
            udata, ok = await self._validate_bet(interaction, bet_amount)
            if not ok:
                return

            udata["money"] -= bet_amount
            boss_name, tier_name, winnings = await run_assault_sequence(interaction, udata, bet_amount)

            _increment_daily(udata, "gamble")
            _record_gamble_stats(udata, "assault", tier_name, winnings)
            save_user_data(uid, udata)

        except Exception as e:
            try:
                embed = discord.Embed(
                    title="❌ 오류 발생",
                    description=f"총력전 중 오류가 발생했습니다.\n`{str(e)[:100]}`",
                    color=COLOR_ERROR,
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception:
                pass
        finally:
            release_lock(uid)

    # ── /계정리세마라 ──
    @app_commands.command(name="계정리세마라", description="가상 베팅액에 따라 계정 리세마라를 진행합니다.")
    @app_commands.describe(bet_amount="베팅할 금액 (1,000원 ~ 50,000원)")
    async def reroll_command(self, interaction: discord.Interaction, bet_amount: int):
        uid = interaction.user.id

        if not acquire_lock(uid, "reroll"):
            await interaction.response.send_message(
                embed=build_locked_embed(uid), ephemeral=True
            )
            return

        try:
            await interaction.response.defer()
            udata, ok = await self._validate_bet(interaction, bet_amount)
            if not ok:
                return

            udata["money"] -= bet_amount
            grade_name, student_name, winnings = await run_reroll_sequence(interaction, udata, bet_amount)

            _increment_daily(udata, "gamble")
            _record_gamble_stats(udata, "reroll", grade_name, winnings)
            save_user_data(uid, udata)

        except Exception as e:
            try:
                embed = discord.Embed(
                    title="❌ 오류 발생",
                    description=f"리세마라 중 오류가 발생했습니다.\n`{str(e)[:100]}`",
                    color=COLOR_ERROR,
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception:
                pass
        finally:
            release_lock(uid)

    # ── /도박현황 ──
    @app_commands.command(name="도박현황", description="도박 사용 현황과 총 수익을 확인합니다.")
    async def gamble_status_command(self, interaction: discord.Interaction):
        uid = interaction.user.id

        if not _is_registered(uid):
            await interaction.response.send_message("❌ 등록된 유저가 아닙니다.", ephemeral=True)
            return

        udata = load_user_data(uid)
        if udata is None:
            await interaction.response.send_message("❌ 유저 데이터를 불러올 수 없습니다.", ephemeral=True)
            return

        await interaction.response.defer()
        _, count, limit = _check_daily(udata, "gamble")
        gamble = udata.get("stats", {}).get("gamble", {})

        total_count = gamble.get("total_count", 0)
        total_profit = gamble.get("total_profit", 0)

        def fmt(val):
            sign = "+" if val > 0 else ""
            return f"{sign}{val:,}원"

        sections = [
            ("누적 손익", [
                ("💰", "총 손익", fmt(total_profit)),
                ("📅", "오늘 사용", f"{count}/{limit}회"),
                ("📊", "총 횟수", f"{total_count}회"),
                ("📐", "회당 평균", fmt(int(total_profit / total_count)) if total_count else "0원"),
            ]),
            ("게임별", [
                ("🎰", "가챠", f"{gamble.get('gacha_count',0)}회 · {fmt(gamble.get('gacha_profit',0))}"),
                ("⚔️", "총력전", f"{gamble.get('assault_count',0)}회 · {fmt(gamble.get('assault_profit',0))}"),
                ("🔄", "리세마라", f"{gamble.get('reroll_count',0)}회 · {fmt(gamble.get('reroll_profit',0))}"),
            ]),
        ]
        try:
            from utils.card_service import build_stat_card_file
            file = await build_stat_card_file(
                interaction.user, udata, title="도박 현황",
                subtitle=f"Lv.{udata.get('level',1)}", sections=sections, filename="gamble.png",
            )
            await interaction.followup.send(file=file)
        except Exception:
            import traceback
            traceback.print_exc()
            embed = discord.Embed(
                title=f"🎰 {interaction.user.display_name}의 도박 현황",
                description=f"총 손익 {fmt(total_profit)} · 총 {total_count}회 · 오늘 {count}/{limit}",
                color=COLOR_SUCCESS if total_profit >= 0 else COLOR_ERROR,
            )
            await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(GamblingCog(bot))
