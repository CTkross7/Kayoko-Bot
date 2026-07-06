# commands/welcome.py
# ──────────────────────────────────────────────────────────
# 공식 서버 가입 환영 메시지 (웹훅 전송)
# ──────────────────────────────────────────────────────────

import aiohttp
import discord
from discord import Embed, Webhook
from discord.ext import commands

# ★ 시크릿은 config.py(gitignore 보호)에서 로드 — 하드코딩 금지
from config import GUILD_ID, WELCOME_WEBHOOK_URL


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # 공식 서버가 아니면 무시
        if member.guild.id != GUILD_ID:
            return
        # 봇은 무시
        if member.bot:
            return

        embed = Embed(
            title=f"환영합니다, {member.name}님! 🎉",
            description=(
                "카요코 봇 공식서버(𝐏𝐫𝐨𝐛𝐥𝐞𝐦 𝐒𝐨𝐥𝐯𝐞𝐫 𝟔𝟖)에 오신 것을 환영합니다!\n"
                "아래 채널에서 인증을 통해 카요코 봇을 사용해보세요!\n"
                "🔗 **[인증채널 바로가기]** (https://discord.com/channels/1381422203161284618/1381802093119016961)\n"
                "🔗 **[규정채널 바로가기]** (https://discord.com/channels/1381422203161284618/1381882148788633630)\n"
            ),
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_image(
            url="https://img.onnada.com/2022/0119/thumb_991469724_c5226522_388_p0.jpg"
        )
        embed.set_footer(text="규정사항 숙지는 선택이 아닌 필수입니다.")

        async with aiohttp.ClientSession() as session:
            try:
                webhook = Webhook.from_url(WELCOME_WEBHOOK_URL, session=session)
                await webhook.send(embed=embed, username=member.name)
            except Exception as e:
                print(f"환영 웹훅 전송 실패: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
