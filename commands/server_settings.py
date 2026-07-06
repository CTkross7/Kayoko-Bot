# commands/server_settings.py
# ──────────────────────────────────────────────────────────
# 서버 관리자용 설정 커맨드
# ──────────────────────────────────────────────────────────

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

from config import (
    COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING, COLOR_PRIMARY,
    BOT_ICON_URL, DEVELOPER_IDS, KST,
)
from data_manager import load_guild_config, save_guild_config
from utils.checks import is_server_admin


FOOTER_TEXT = "카요코 봇"


class ServerSettingsCog(commands.Cog):
    """서버 관리자용 설정 명령어"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /서버설정 ──
    @app_commands.command(name="서버설정", description="[관리자] 이 서버의 봇 설정을 확인합니다.")
    @app_commands.guild_only()
    @is_server_admin()
    async def server_config_command(self, interaction: discord.Interaction):
        config = load_guild_config(interaction.guild.id)

        notice_ch = config.get("notice_channel_id")
        notice_display = f"<#{notice_ch}>" if notice_ch else "미설정"

        welcome_ch = config.get("welcome_channel_id")
        welcome_display = f"<#{welcome_ch}>" if welcome_ch else "미설정"

        bot_enabled = config.get("bot_enabled", True)

        embed = discord.Embed(
            title=f"⚙️ {interaction.guild.name} 서버 설정",
            color=COLOR_PRIMARY,
        )
        embed.add_field(
            name="📢 공지 수신 채널",
            value=notice_display,
            inline=True,
        )
        embed.add_field(
            name="👋 환영 메시지 채널",
            value=welcome_display,
            inline=True,
        )
        embed.add_field(
            name="🤖 봇 활성화",
            value="✅ 활성" if bot_enabled else "❌ 비활성",
            inline=True,
        )
        embed.set_footer(text=FOOTER_TEXT, icon_url=BOT_ICON_URL)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /공지채널설정 (서버 관리자용) ──
    @app_commands.command(
        name="공지채널설정",
        description="[관리자] 이 서버의 공지 수신 채널을 설정합니다.",
    )
    @app_commands.guild_only()
    @app_commands.describe(channel="공지를 수신할 채널")
    @is_server_admin()
    async def set_notice_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        guild_id = interaction.guild.id
        config = load_guild_config(guild_id)

        config["notice_channel_id"] = channel.id
        config["notice_channel_name"] = channel.name
        config["guild_name"] = interaction.guild.name
        if not config.get("created_at"):
            config["created_at"] = datetime.now(KST).isoformat()

        save_guild_config(guild_id, config)

        embed = discord.Embed(
            title="✅ 공지 채널 설정 완료",
            description=(
                f"이 서버의 공지 수신 채널이 {channel.mention}으로 설정되었습니다.\n"
                f"개발자가 공지를 작성하면 이 채널에 자동으로 전송됩니다."
            ),
            color=COLOR_SUCCESS,
        )
        embed.set_footer(text=FOOTER_TEXT, icon_url=BOT_ICON_URL)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /공지채널삭제 (서버 관리자용 — 자기 서버만) ──
    @app_commands.command(
        name="공지채널삭제",
        description="[관리자] 이 서버의 공지 수신 채널을 해제합니다.",
    )
    @app_commands.guild_only()
    @is_server_admin()
    async def remove_notice_channel(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        config = load_guild_config(guild_id)

        if not config.get("notice_channel_id"):
            await interaction.response.send_message(
                "❌ 이 서버에 설정된 공지 채널이 없습니다.", ephemeral=True
            )
            return

        old_channel_id = config["notice_channel_id"]
        config["notice_channel_id"] = None
        config["notice_channel_name"] = None
        save_guild_config(guild_id, config)

        embed = discord.Embed(
            title="✅ 공지 채널 해제 완료",
            description=f"공지 수신 채널(<#{old_channel_id}>)이 해제되었습니다.",
            color=COLOR_SUCCESS,
        )
        embed.set_footer(text=FOOTER_TEXT, icon_url=BOT_ICON_URL)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /봇토글 (서버 관리자용) ──
    @app_commands.command(
        name="봇토글",
        description="[관리자] 이 서버에서 봇 기능을 활성화/비활성화합니다.",
    )
    @app_commands.guild_only()
    @is_server_admin()
    async def toggle_bot(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        config = load_guild_config(guild_id)

        current = config.get("bot_enabled", True)
        config["bot_enabled"] = not current
        save_guild_config(guild_id, config)

        if config["bot_enabled"]:
            embed = discord.Embed(
                title="✅ 봇 활성화",
                description="이 서버에서 봇 기능이 활성화되었습니다.",
                color=COLOR_SUCCESS,
            )
        else:
            embed = discord.Embed(
                title="❌ 봇 비활성화",
                description=(
                    "이 서버에서 봇 기능이 비활성화되었습니다.\n"
                    "게임 커맨드가 작동하지 않습니다.\n"
                    "`/봇토글`로 다시 활성화할 수 있습니다."
                ),
                color=COLOR_WARNING,
            )

        embed.set_footer(text=FOOTER_TEXT, icon_url=BOT_ICON_URL)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerSettingsCog(bot))
