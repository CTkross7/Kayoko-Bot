# commands/notice.py
# ──────────────────────────────────────────────────────────
# 공지사항 작성 / 수정 / 삭제 (개발자 전용)
# 전송 대상: data/guilds/*/guild_config.json의 notice_channel_id
# ──────────────────────────────────────────────────────────

import discord
from discord import app_commands, ui
from discord.ext import commands
from datetime import datetime

from config import DEVELOPER_IDS, COLOR_SUCCESS, COLOR_ERROR, BOT_ICON_URL
from data_manager import get_guilds_with_notice_channel, load_guild_config, save_guild_config

FOOTER_TEXT = "카요코 봇"


def _is_developer(interaction: discord.Interaction) -> bool:
    return interaction.user.id in DEVELOPER_IDS


class AnnouncementModal(ui.Modal, title="📣 공지사항 작성"):
    title_input = ui.TextInput(
        label="제목", placeholder="공지 제목", style=discord.TextStyle.short
    )
    content_input = ui.TextInput(
        label="내용", placeholder="공지 내용 (마크다운 지원)",
        style=discord.TextStyle.paragraph, max_length=2000,
    )
    image_input = ui.TextInput(
        label="이미지 URL (쉼표 구분)", placeholder="이미지 링크", required=False
    )

    def __init__(self, mode: str, message_id: int = None):
        super().__init__(timeout=600)
        self.mode = mode
        self.message_id = message_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except discord.errors.NotFound:
            pass

        embed = discord.Embed(
            title=self.title_input.value,
            description=self.content_input.value,
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )
        embed.set_footer(text=f"개발자: {interaction.user.display_name}")

        image_urls = [u.strip() for u in self.image_input.value.split(",") if u.strip()]
        if image_urls:
            embed.set_image(url=image_urls[0])
            if len(image_urls) > 1:
                additional = "\n".join(
                    f"• [추가 이미지 {i+2}]({url})" for i, url in enumerate(image_urls[1:])
                )
                embed.add_field(name="🖼️ 추가 이미지", value=additional[:1024], inline=False)

        # ★ guild_config에서 공지 채널 목록 가져오기
        guilds_with_notice = get_guilds_with_notice_channel()
        success_msgs = []
        error_msgs = []

        for guild_id_str, config in guilds_with_notice:
            channel_id = config.get("notice_channel_id")
            guild_name = config.get("guild_name", guild_id_str)
            if not channel_id:
                continue

            try:
                channel = interaction.client.get_channel(channel_id)
                if not channel:
                    channel = await interaction.client.fetch_channel(channel_id)

                if self.mode == "create":
                    msg = await channel.send(embed=embed)
                    # 메시지 ID 기록 (나중에 수정/삭제용)
                    config.setdefault("notice_message_ids", []).append(msg.id)
                    save_guild_config(guild_id_str, config)
                    success_msgs.append(f"✅ {guild_name} / #{channel.name}")

                elif self.mode == "edit" and self.message_id:
                    try:
                        msg = await channel.fetch_message(self.message_id)
                        await msg.edit(embed=embed)
                        success_msgs.append(f"✅ {guild_name} / #{channel.name} 수정")
                    except discord.NotFound:
                        error_msgs.append(f"❌ {guild_name}: 메시지 미발견")

            except discord.Forbidden:
                error_msgs.append(f"❌ {guild_name}: 권한 없음")
            except Exception as e:
                error_msgs.append(f"❌ {guild_name}: {str(e)[:50]}")

        final = []
        if success_msgs:
            final.append("### ✅ 성공")
            final.extend(success_msgs)
        if error_msgs:
            final.append("### ❌ 오류")
            final.extend(error_msgs)
        if not final:
            final = ["⚠️ 공지 채널이 설정된 서버가 없습니다."]

        try:
            await interaction.edit_original_response(content="\n".join(final))
        except discord.errors.NotFound:
            await interaction.followup.send("\n".join(final), ephemeral=True)


class NoticeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="공지작성", description="[개발자] 공지사항을 작성하여 전체 서버에 전송합니다.")
    @app_commands.guild_only()
    async def create_notice(self, interaction: discord.Interaction):
        if not _is_developer(interaction):
            return await interaction.response.send_message("❌ 개발자만 사용 가능합니다.", ephemeral=True)
        await interaction.response.send_modal(AnnouncementModal(mode="create"))

    @app_commands.command(name="공지수정", description="[개발자] 기존 공지를 수정합니다.")
    @app_commands.describe(message_id="수정할 메시지 ID")
    @app_commands.guild_only()
    async def edit_notice(self, interaction: discord.Interaction, message_id: str):
        if not _is_developer(interaction):
            return await interaction.response.send_message("❌ 개발자만 사용 가능합니다.", ephemeral=True)
        try:
            mid = int(message_id)
        except ValueError:
            return await interaction.response.send_message("❌ 유효한 메시지 ID를 입력하세요.", ephemeral=True)
        await interaction.response.send_modal(AnnouncementModal(mode="edit", message_id=mid))

    @app_commands.command(name="공지삭제", description="[개발자] 기존 공지를 삭제합니다.")
    @app_commands.describe(message_id="삭제할 메시지 ID")
    @app_commands.guild_only()
    async def delete_notice(self, interaction: discord.Interaction, message_id: str):
        if not _is_developer(interaction):
            return await interaction.response.send_message("❌ 개발자만 사용 가능합니다.", ephemeral=True)
        try:
            mid = int(message_id)
        except ValueError:
            return await interaction.response.send_message("❌ 유효한 메시지 ID를 입력하세요.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        guilds_with_notice = get_guilds_with_notice_channel()
        deleted = False

        for guild_id_str, config in guilds_with_notice:
            channel_id = config.get("notice_channel_id")
            if not channel_id:
                continue
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                msg = await channel.fetch_message(mid)
                await msg.delete()
                # 기록에서 제거
                msg_ids = config.get("notice_message_ids", [])
                if mid in msg_ids:
                    msg_ids.remove(mid)
                    save_guild_config(guild_id_str, config)
                deleted = True
            except (discord.NotFound, discord.Forbidden):
                pass
            except Exception:
                pass

        if deleted:
            await interaction.followup.send("✅ 공지 삭제 완료.", ephemeral=True)
        else:
            await interaction.followup.send("❌ 해당 메시지를 찾을 수 없습니다.", ephemeral=True)

    @app_commands.command(name="공지채널리스트", description="[개발자] 공지 채널이 설정된 서버 목록을 확인합니다.")
    @app_commands.guild_only()
    async def list_notice_channels(self, interaction: discord.Interaction):
        if not _is_developer(interaction):
            return await interaction.response.send_message("❌ 개발자만 사용 가능합니다.", ephemeral=True)

        guilds = get_guilds_with_notice_channel()

        embed = discord.Embed(
            title="📜 공지 채널 등록 서버 목록",
            color=discord.Color.purple(),
        )

        if not guilds:
            embed.description = "공지 채널이 설정된 서버가 없습니다."
        else:
            for gid, config in guilds:
                embed.add_field(
                    name=f"🌐 {config.get('guild_name', gid)}",
                    value=(
                        f"채널: <#{config['notice_channel_id']}>\n"
                        f"서버 ID: `{gid}`"
                    ),
                    inline=False,
                )

        embed.set_footer(text=FOOTER_TEXT, icon_url=BOT_ICON_URL)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(NoticeCog(bot))
