# commands/verification.py
# ──────────────────────────────────────────────────────────
# 역할 인증 시스템 (보안 코드 + 즉시 지급)
# ──────────────────────────────────────────────────────────

import os
import json
import string
import random
import asyncio
from datetime import datetime, timedelta

import discord
from discord import app_commands, ui
from discord.ext import commands

import pytz

# ═══════════════════════════════════════════════════════════
# 상수 및 파일 경로
# ═══════════════════════════════════════════════════════════

CONFIG_FILE = "verification_config.json"
ATTEMPTS_FILE = "user_attempts.json"
CODE_EXPIRATION_SECONDS = 300  # 인증 코드 유효 시간 (5분)
KST_TZ = pytz.timezone("Asia/Seoul")

# 개발자 ID 목록
DEV_USER_IDS = [1138279240589127750]

# ═══════════════════════════════════════════════════════════
# 전역 상태
# ═══════════════════════════════════════════════════════════

VERIFICATION_CONFIG = {}
USER_ATTEMPTS = {}
VERIFICATION_PERSISTENT_VIEW = None  # on_ready에서 초기화


# ═══════════════════════════════════════════════════════════
# 유틸리티 함수
# ═══════════════════════════════════════════════════════════

def generate_random_code(length=6):
    characters = string.ascii_uppercase + string.digits
    return "".join(random.choice(characters) for _ in range(length))


def load_verification_config():
    global VERIFICATION_CONFIG
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                VERIFICATION_CONFIG = {int(k): v for k, v in data.items()}
        except (json.JSONDecodeError, Exception):
            VERIFICATION_CONFIG = {}
    else:
        VERIFICATION_CONFIG = {}
    return VERIFICATION_CONFIG


def save_verification_config_force():
    global VERIFICATION_CONFIG
    data_to_save = {str(k): v for k, v in VERIFICATION_CONFIG.items()}
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"❌ 인증 설정 파일 저장 오류: {e}")


def save_verification_config(channel_id, config_data):
    global VERIFICATION_CONFIG
    if channel_id in VERIFICATION_CONFIG:
        VERIFICATION_CONFIG[channel_id].update(config_data)
    else:
        VERIFICATION_CONFIG[channel_id] = config_data
    save_verification_config_force()


def load_user_attempts():
    global USER_ATTEMPTS
    if os.path.exists(ATTEMPTS_FILE):
        try:
            with open(ATTEMPTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                loaded = {}
                for k, v in data.items():
                    user_id = int(k)
                    if "code_time" in v and isinstance(v["code_time"], str):
                        try:
                            v["code_time"] = datetime.fromisoformat(v["code_time"])
                        except ValueError:
                            v["code_time"] = 0
                    loaded[user_id] = v
                USER_ATTEMPTS = loaded
        except (json.JSONDecodeError, Exception):
            USER_ATTEMPTS = {}
    else:
        USER_ATTEMPTS = {}
    return USER_ATTEMPTS


def save_user_attempts():
    global USER_ATTEMPTS
    data_to_save = {}
    for user_id, attempt_data in USER_ATTEMPTS.items():
        data = attempt_data.copy()
        if "code_time" in data and isinstance(data["code_time"], datetime):
            data["code_time"] = data["code_time"].isoformat()
        data_to_save[str(user_id)] = data
    try:
        with open(ATTEMPTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"❌ 인증 시도 기록 저장 오류: {e}")


# ═══════════════════════════════════════════════════════════
# 모달: 보안 코드 입력
# ═══════════════════════════════════════════════════════════

class VerificationSecurityModal(ui.Modal, title="보안 인증 코드 입력"):
    security_check = ui.TextInput(
        label="인증 코드를 정확히 입력하세요:",
        style=discord.TextStyle.short,
        placeholder="인증 코드를 입력하세요.",
        max_length=6,
        required=True,
    )

    def __init__(self, role_id: int, member: discord.Member, channel_id: int, code: str):
        super().__init__(timeout=300, title=f"보안 인증 코드 입력: 🔑 {code}")
        self.reward_role_id = role_id
        self.member = member
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        user_id = self.member.id
        attempt_data = USER_ATTEMPTS.get(user_id)

        if not attempt_data or attempt_data.get("config_channel_id") != self.channel_id:
            await interaction.followup.send(
                "⚠️ 인증 코드가 유효하지 않습니다. 버튼을 다시 눌러 코드를 발급받으세요.",
                ephemeral=True,
            )
            return

        correct_code = attempt_data["code"]
        config = load_verification_config().get(self.channel_id)

        if not config:
            await interaction.followup.send("❌ 해당 인증 설정이 유효하지 않습니다.", ephemeral=True)
            USER_ATTEMPTS.pop(user_id, None)
            save_user_attempts()
            return

        max_fails = config.get("kick_fail_count", 99)
        current_fails = attempt_data.get("fails", 0)

        if self.security_check.value.strip() == correct_code:
            role = self.member.guild.get_role(self.reward_role_id)
            if role and role not in self.member.roles:
                try:
                    await self.member.add_roles(role)
                    await interaction.followup.send(
                        f"✅ 인증 성공! **{role.name}** 역할이 지급되었습니다.",
                        ephemeral=True,
                    )
                    USER_ATTEMPTS.pop(user_id, None)
                    save_user_attempts()
                except discord.Forbidden:
                    await interaction.followup.send(
                        "❌ 역할 지급 실패: 봇에게 권한이 없습니다.", ephemeral=True
                    )
            elif role and role in self.member.roles:
                await interaction.followup.send(
                    f"이미 **{role.name}** 역할을 가지고 있습니다.", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"❌ 역할 ID({self.reward_role_id})를 찾을 수 없습니다.", ephemeral=True
                )
        else:
            current_fails += 1
            USER_ATTEMPTS[user_id]["fails"] = current_fails
            remaining_fails = max_fails - current_fails

            if current_fails >= max_fails and max_fails > 0:
                try:
                    await self.member.kick(reason=f"인증 실패 횟수({max_fails}회) 초과")
                    await interaction.followup.send(
                        "🚨 코드 입력 실패 횟수 초과로 **서버에서 강퇴**되었습니다.",
                        ephemeral=True,
                    )
                except discord.Forbidden:
                    await interaction.followup.send(
                        f"⚠️ 인증 코드 불일치! ({current_fails}회 실패) - **(강퇴 실패: 봇 권한 부족)**",
                        ephemeral=True,
                    )
                USER_ATTEMPTS.pop(user_id, None)
                save_user_attempts()
            else:
                await interaction.followup.send(
                    f"❌ 인증 코드 불일치! **남은 기회: {remaining_fails}회**",
                    ephemeral=True,
                )
                save_user_attempts()


# ═══════════════════════════════════════════════════════════
# 모달: 인증 안내 메시지 작성
# ═══════════════════════════════════════════════════════════

class VerificationMessageModal(ui.Modal, title="인증 안내 메세지 입력"):
    message_body = ui.TextInput(
        label="인증 안내 메세지 (긴 텍스트)",
        style=discord.TextStyle.long,
        placeholder="인증을 위해 사용자들이 알아야 할 내용을 작성해주세요.",
        max_length=2000,
        required=True,
    )

    def __init__(
        self,
        target_channel: discord.TextChannel,
        security_enabled: bool,
        reward_role: discord.Role,
        button_emoji: str,
        kick_fail_count: int,
    ):
        super().__init__()
        self.target_channel = target_channel
        self.security_enabled = security_enabled
        self.reward_role = reward_role
        self.button_emoji = button_emoji
        self.kick_fail_count = kick_fail_count

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        title_text = "🔒 역할 인증 센터"
        security_text = "❌ 비활성화됨 (즉시 역할 지급)"

        if self.security_enabled:
            title_text += " (2단계 보안 인증 활성화)"
            security_text = "✅ 활성화됨 (버튼 클릭 시 코드가 표시된 모달 창에 코드 입력 필요)"

        embed = discord.Embed(
            title=title_text,
            description=self.message_body.value,
            color=discord.Color.blue(),
        )
        embed.add_field(name="인증 방식", value=security_text, inline=False)
        embed.add_field(name="지급 역할", value=f"{self.reward_role.mention}", inline=True)

        if self.kick_fail_count > 0 and self.security_enabled:
            embed.add_field(
                name="인증 실패 시",
                value=f"코드 **{self.kick_fail_count}회 실패 시 강퇴**",
                inline=True,
            )
        elif self.security_enabled:
            embed.add_field(name="인증 실패 시", value="실패 횟수 제한 없음", inline=True)

        embed.set_footer(
            text=f"{self.button_emoji} 버튼을 클릭하여 인증을 시작하세요."
        )

        global VERIFICATION_PERSISTENT_VIEW
        if VERIFICATION_PERSISTENT_VIEW is None:
            VERIFICATION_PERSISTENT_VIEW = VerificationView()

        config_data = {
            "reward_role_id": self.reward_role.id,
            "security_enabled": self.security_enabled,
            "emoji": self.button_emoji,
            "kick_fail_count": self.kick_fail_count,
        }
        save_verification_config(self.target_channel.id, config_data)
        VERIFICATION_PERSISTENT_VIEW.load_buttons_from_config()

        try:
            verification_message = await self.target_channel.send(
                embed=embed, view=VERIFICATION_PERSISTENT_VIEW
            )
            VERIFICATION_CONFIG[self.target_channel.id]["message_id"] = (
                verification_message.id
            )
            save_verification_config_force()
            await interaction.followup.send(
                f"✅ 역할 인증 메시지가 {self.target_channel.mention}에 설정되었습니다.",
                ephemeral=True,
            )
        except discord.Forbidden:
            VERIFICATION_CONFIG.pop(self.target_channel.id, None)
            save_verification_config_force()
            await interaction.followup.send(
                "❌ 메시지를 보낼 권한이 없습니다.", ephemeral=True
            )


# ═══════════════════════════════════════════════════════════
# 영구 View: 인증 버튼
# ═══════════════════════════════════════════════════════════

class VerificationView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.load_buttons_from_config()

    def load_buttons_from_config(self):
        config = load_verification_config()
        self.clear_items()
        for channel_id, data in config.items():
            button_id = f"verify_{channel_id}"
            button = ui.Button(
                label="인증하기",
                emoji=data.get("emoji"),
                style=discord.ButtonStyle.success,
                custom_id=button_id,
            )
            button.callback = self.verify_callback
            self.add_item(button)

    async def verify_callback(self, interaction: discord.Interaction):
        channel_id = int(interaction.data["custom_id"].split("_")[1])
        config = load_verification_config().get(channel_id)

        if not config:
            await interaction.response.send_message(
                "❌ 이 인증 설정은 더 이상 유효하지 않습니다.", ephemeral=True
            )
            return

        reward_role_id = config["reward_role_id"]
        security_enabled = config["security_enabled"]
        member = interaction.user
        user_id = member.id

        role = member.guild.get_role(reward_role_id)
        if role and role in member.roles:
            await interaction.response.send_message(
                f"이미 **{role.name}** 역할을 가지고 있습니다.", ephemeral=True
            )
            return

        # 보안 비활성화 → 즉시 역할 지급
        if not security_enabled:
            await interaction.response.defer(ephemeral=True, thinking=True)
            if role:
                try:
                    await member.add_roles(role)
                    await interaction.followup.send(
                        f"✅ 인증 성공! **{role.name}** 역할이 즉시 지급되었습니다.",
                        ephemeral=True,
                    )
                except discord.Forbidden:
                    await interaction.followup.send(
                        "❌ 역할 지급 실패: 봇에게 권한이 없습니다.", ephemeral=True
                    )
            else:
                await interaction.followup.send(
                    f"❌ 역할 ID({reward_role_id})를 찾을 수 없습니다.", ephemeral=True
                )
            return

        # 보안 활성화 → 모달
        new_code = generate_random_code()
        USER_ATTEMPTS[user_id] = {
            "config_channel_id": channel_id,
            "fails": 0,
            "code": new_code,
            "code_time": datetime.now(KST_TZ),
        }
        save_user_attempts()

        modal = VerificationSecurityModal(reward_role_id, member, channel_id, new_code)
        await interaction.response.send_modal(modal)


# ═══════════════════════════════════════════════════════════
# 만료 코드 정리 태스크
# ═══════════════════════════════════════════════════════════

async def periodic_code_cleanup():
    expiration_delta = timedelta(seconds=CODE_EXPIRATION_SECONDS)
    while True:
        await asyncio.sleep(60)
        now = datetime.now(KST_TZ)
        expired_users = []
        for user_id, attempt_data in list(USER_ATTEMPTS.items()):
            code_time = attempt_data.get("code_time")
            if isinstance(code_time, datetime) and (now - code_time) > expiration_delta:
                expired_users.append(user_id)
            elif not isinstance(code_time, datetime) and code_time != 0:
                expired_users.append(user_id)
        if expired_users:
            for user_id in expired_users:
                USER_ATTEMPTS.pop(user_id, None)
            save_user_attempts()


# ═══════════════════════════════════════════════════════════
# 개발자 체크 데코레이터
# ═══════════════════════════════════════════════════════════

def is_dev_user():
    async def predicate(interaction: discord.Interaction):
        if interaction.user.id in DEV_USER_IDS:
            return True
        await interaction.response.send_message(
            "❌ 이 명령어는 지정된 개발자만 사용할 수 있습니다.", ephemeral=True
        )
        return False
    return app_commands.check(predicate)


# ═══════════════════════════════════════════════════════════
# Cog 정의
# ═══════════════════════════════════════════════════════════

class VerificationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        """Cog 로드 시 인증 시스템 초기화"""
        global VERIFICATION_PERSISTENT_VIEW

        load_verification_config()
        load_user_attempts()

        VERIFICATION_PERSISTENT_VIEW = VerificationView()
        self.bot.add_view(VERIFICATION_PERSISTENT_VIEW)

        # 만료 코드 정리 태스크 시작
        self.bot.loop.create_task(periodic_code_cleanup())

        print("[인증 시스템] 로드 완료")

    @app_commands.command(
        name="역할인증설정",
        description="[개발자 전용] 채널에 역할 인증 시스템을 설정합니다.",
    )
    @app_commands.describe(
        target_channel="인증 메시지를 보낼 채널",
        security_enabled="랜덤 코드 인증을 추가할지 여부",
        reward_role="인증 성공 시 지급할 역할",
        button_emoji="인증 버튼에 표시할 이모지",
        kick_fail_count="인증 코드 몇 회 실패 시 강퇴 (0=비활성)",
    )
    @is_dev_user()
    async def setup_verification(
        self,
        interaction: discord.Interaction,
        target_channel: discord.TextChannel,
        security_enabled: bool,
        reward_role: discord.Role,
        button_emoji: str,
        kick_fail_count: int,
    ):
        if reward_role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "❌ 봇 역할보다 높거나 같은 역할을 지급할 수 없습니다.", ephemeral=True
            )
            return

        if (
            kick_fail_count > 0
            and security_enabled
            and not interaction.guild.me.guild_permissions.kick_members
        ):
            await interaction.response.send_message(
                "⚠️ 강퇴 기능을 활성화했지만 봇에게 '멤버 추방' 권한이 없습니다.",
                ephemeral=True,
            )
            return

        modal = VerificationMessageModal(
            target_channel, security_enabled, reward_role, button_emoji, kick_fail_count
        )
        await interaction.response.send_modal(modal)


async def setup(bot: commands.Bot):
    await bot.add_cog(VerificationCog(bot))
