# utils/checks.py
# ──────────────────────────────────────────────────────────
# 권한 체크, 서버 차단, 유저 밴 확인 유틸리티
# ──────────────────────────────────────────────────────────

import json
import os
from datetime import datetime, timezone, timedelta

import discord
from discord import Interaction, Embed, app_commands

from config import (
    DEVELOPER_ID, ALLOWED_ADMIN_IDS, GUILD_ID,
    BLOCKLIST_FILE, BAN_FILE, KST, COLOR_ERROR,
)
from data_manager import load_json, save_json
from models.user import load_user_data

# ============================================================
# 밴 데이터 경로
# ============================================================

BAN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "user_ban.json")
ANTICHEAT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "anticheat_data.json")


def _load_json(filepath: str) -> dict:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ============================================================
# 등록 확인
# ============================================================

def is_registered():
    """유저가 등록되어 있는지 확인하는 체크"""
    async def predicate(interaction: discord.Interaction) -> bool:
        from models.user import load_user_data
        user_data = load_user_data(str(interaction.user.id))

        if not user_data:
            embed = discord.Embed(
                title="❌ 미등록 유저",
                description=(
                    "아직 등록되지 않은 유저입니다!\n"
                    "`/시작`으로 게임을 시작해주세요."
                ),
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        return True

    return app_commands.check(predicate)


# ============================================================
# 차단 확인 (관리자 차단 + 안티치트 자동 차단)
# ============================================================

def is_not_banned():
    """유저가 차단되지 않았는지 확인하는 체크"""
    async def predicate(interaction: discord.Interaction) -> bool:
        user_id = str(interaction.user.id)

        # 관리자 차단 확인
        ban_data = _load_json(BAN_FILE)
        user_ban = ban_data.get(user_id, {})

        if isinstance(user_ban, dict) and user_ban.get("banned", False):
            reason = user_ban.get("reason", "사유 없음")
            embed = discord.Embed(
                title="🚫 이용 제한",
                description=(
                    "귀하의 계정은 이용이 제한되었습니다.\n\n"
                    f"**사유**: {reason}\n\n"
                    "이의가 있는 경우 관리자에게 문의해주세요."
                ),
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False

        # 안티치트 자동 차단 확인
        ac_data = _load_json(ANTICHEAT_FILE)
        user_ac = ac_data.get(user_id, {})

        if isinstance(user_ac, dict) and user_ac.get("auto_banned", False):
            embed = discord.Embed(
                title="🚫 이용 제한 (자동 감지)",
                description=(
                    "비정상적인 플레이가 감지되어 자동으로 이용이 제한되었습니다.\n\n"
                    "이의가 있는 경우 관리자에게 문의해주세요."
                ),
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False

        return True

    return app_commands.check(predicate)
    
# ═══════════════════════════════════════════════════════════
# ★ 추가: 서버 내 전용 체크 (DM 방지)
# ═══════════════════════════════════════════════════════════

# utils/checks.py

# 봇 토글 체크에서 제외할 커맨드 목록
TOGGLE_EXEMPT_COMMANDS = {"봇토글", "서버설정", "서버정보"}

async def check_guild_only(interaction: discord.Interaction) -> bool:
    """서버 전용 + 봇 활성화 체크 (토글 관련 커맨드는 예외)"""
    if interaction.guild is None:
        embed = discord.Embed(
            title="⚠️ 서버 전용",
            description="이 명령어는 서버에서만 사용할 수 있습니다.",
            color=COLOR_ERROR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False

    # 봇토글 등 예외 커맨드는 토글 체크 건너뛰기
    command_name = interaction.command.name if interaction.command else ""
    if command_name in TOGGLE_EXEMPT_COMMANDS:
        return True

    # 길드 설정 로드 후 봇 활성화 여부 확인
    from data_manager import load_guild_config
    guild_config = load_guild_config(str(interaction.guild.id))

    if not guild_config.get("bot_enabled", True):
        embed = discord.Embed(
            title="🔒 봇 비활성화",
            description="이 서버에서 봇이 비활성화되어 있습니다.\n서버 관리자가 `/봇토글` 명령어로 활성화할 수 있습니다.",
            color=COLOR_ERROR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False

    return True

# ═══════════════════════════════════════════════════════════
# ★ 추가: 서버 관리자 권한 체크
# ═══════════════════════════════════════════════════════════

async def check_server_admin(interaction) -> bool:
    """서버 관리자(manage_guild 권한) 여부를 확인합니다."""
    if interaction.guild is None:
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ 이 명령어는 서버 내에서만 사용할 수 있습니다.",
                ephemeral=True,
            )
        return False

    member = interaction.guild.get_member(interaction.user.id)
    if member is None:
        return False

    if member.guild_permissions.manage_guild or member.guild_permissions.administrator:
        return True

    # 개발자는 항상 통과
    from config import DEVELOPER_IDS
    if interaction.user.id in DEVELOPER_IDS:
        return True

    if not interaction.response.is_done():
        await interaction.response.send_message(
            "❌ 이 명령어는 서버 관리자(`서버 관리` 권한)만 사용할 수 있습니다.",
            ephemeral=True,
        )
    return False


def is_server_admin():
    """서버 관리자 체크 데코레이터"""
    from discord import app_commands

    async def predicate(interaction) -> bool:
        return await check_server_admin(interaction)

    return app_commands.check(predicate)    

# ═══════════════════════════════════════════════════════════
# 약관 동의 체크
# ═══════════════════════════════════════════════════════════

async def check_agreement(interaction: Interaction) -> bool:
    """
    유저가 약관에 동의했는지 확인합니다.
    동의하지 않았으면 False를 반환하고 안내 메시지를 보냅니다.
    """
    user_data = load_user_data(str(interaction.user.id), interaction.user.name)
    if not user_data.get("agreement", False):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "⚠️ `/가입`으로 약관 동의가 필요합니다.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                "⚠️ `/가입`으로 약관 동의가 필요합니다.", ephemeral=True
            )
        return False
    return True


# ═══════════════════════════════════════════════════════════
# 서버 차단 체크
# ═══════════════════════════════════════════════════════════

def load_blocked_servers() -> dict:
    """차단된 서버 목록을 로드합니다."""
    return load_json(BLOCKLIST_FILE, {})


def save_blocked_servers(data: dict):
    """차단된 서버 목록을 저장합니다."""
    save_json(BLOCKLIST_FILE, data)


def is_server_blocked(server_id: str) -> dict | None:
    """
    서버가 차단되어 있는지 확인합니다.
    차단되어 있으면 차단 정보 dict를, 아니면 None을 반환합니다.
    """
    blocked = load_blocked_servers()
    if server_id not in blocked:
        return None

    block_info = blocked[server_id]
    try:
        end = datetime.fromisoformat(block_info["end_time"])
    except (ValueError, KeyError):
        return None

    if datetime.now(KST) < end:
        return block_info
    else:
        del blocked[server_id]
        save_blocked_servers(blocked)
        return None


async def check_server_block(interaction: Interaction) -> bool:
    """
    서버가 차단되어 있는지 확인합니다.
    차단되어 있으면 True를 반환하고 안내 메시지를 보냅니다.
    """
    if interaction.guild is None:
        return False

    server_id = str(interaction.guild.id)
    block_info = is_server_blocked(server_id)

    if not block_info:
        return False

    try:
        start_time = datetime.fromisoformat(block_info["start_time"]).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, KeyError):
        start_time = "알 수 없음"

    try:
        end_time_obj = datetime.fromisoformat(block_info["end_time"])
        end_time = (
            "영구 차단"
            if end_time_obj.year >= 9999
            else end_time_obj.strftime("%Y-%m-%d %H:%M:%S")
        )
    except (ValueError, KeyError):
        end_time = "알 수 없음"

    embed = Embed(
        title="🚫 서버 차단 상태",
        description="이 서버는 현재 차단 상태입니다.",
        color=COLOR_ERROR,
    )
    embed.add_field(name="서버 이름", value=interaction.guild.name, inline=False)
    embed.add_field(name="서버 ID", value=server_id, inline=False)
    embed.add_field(name="차단 시작", value=start_time, inline=True)
    embed.add_field(name="차단 종료", value=end_time, inline=True)
    embed.add_field(name="사유", value=block_info.get("reason", "없음"), inline=False)
    embed.set_footer(text="차단 관련 문의는 공식 서버를 이용해주세요.")

    if not interaction.response.is_done():
        await interaction.response.send_message(embed=embed, ephemeral=False)
    else:
        await interaction.followup.send(embed=embed, ephemeral=False)
    return True


# ═══════════════════════════════════════════════════════════
# 유저 밴 체크
# ═══════════════════════════════════════════════════════════

def load_bans() -> dict:
    """밴 목록을 로드합니다."""
    return load_json(BAN_FILE, {})


def save_bans(data: dict):
    """밴 목록을 저장합니다."""
    save_json(BAN_FILE, data)


def is_banned(user_id: int) -> tuple:
    """
    유저가 밴되어 있는지 확인합니다.
    반환: (밴여부: bool, 밴정보: dict | None)
    """
    bans = load_bans()
    str_id = str(user_id)

    if str_id not in bans:
        return False, None

    ban_info = bans[str_id]
    expire_at = ban_info.get("expire_at", 0)

    if expire_at == 0:
        return True, ban_info

    if datetime.now(timezone.utc).timestamp() < expire_at:
        return True, ban_info

    bans.pop(str_id)
    save_bans(bans)
    return False, None


async def check_ban(interaction: Interaction) -> bool:
    """
    유저가 밴되어 있는지 확인합니다.
    밴되어 있으면 True를 반환하고 안내 메시지를 보냅니다.
    """
    banned, info = is_banned(interaction.user.id)
    if not banned:
        return False

    embed = Embed(
        title="🚫 접근 차단됨",
        color=COLOR_ERROR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="사유", value=info.get("reason", "없음"), inline=False)

    expire_at = info.get("expire_at", 0)
    if expire_at == 0:
        embed.add_field(name="만료", value="영구 차단", inline=False)
    else:
        expire_time = datetime.fromtimestamp(expire_at, tz=timezone.utc)
        embed.add_field(name="만료", value=expire_time.strftime("%Y-%m-%d %H:%M:%S UTC"), inline=False)

    if not interaction.response.is_done():
        await interaction.response.send_message(embed=embed, ephemeral=False)
    else:
        await interaction.followup.send(embed=embed, ephemeral=False)
    return True


# ═══════════════════════════════════════════════════════════
# 통합 체크 함수 (자주 사용되는 조합)
# ═══════════════════════════════════════════════════════════

async def standard_checks(interaction: Interaction) -> bool:
    """
    대부분의 커맨드에서 사용하는 표준 체크 조합입니다.
    모든 체크를 통과하면 True, 하나라도 실패하면 False를 반환합니다.

    체크 순서:
    1. 공식 서버 여부(delete)
    2. 약관 동의 여부
    3. 서버 차단 여부
    4. 유저 밴 여부
    """

    if not await check_agreement(interaction):
        return False
    if await check_server_block(interaction):
        return False
    if await check_ban(interaction):
        return False
    return True

# ============================================================
# 관리자 확인
# ============================================================

def is_admin():
    """관리자인지 확인하는 체크"""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id not in ADMIN_IDS:
            embed = discord.Embed(
                title="❌ 권한 없음",
                description="관리자 전용 명령어입니다.",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        return True

    return app_commands.check(predicate)


# ============================================================
# 추가 유틸리티
# ============================================================

def is_auto_banned(user_id: str) -> bool:
    """안티치트 자동 차단 여부 확인 (동기)"""
    ac_data = _load_json(ANTICHEAT_FILE)
    user_ac = ac_data.get(user_id, {})
    if isinstance(user_ac, dict) and user_ac.get("auto_banned", False):
        return True

    ban_data = _load_json(BAN_FILE)
    user_ban = ban_data.get(user_id, {})
    if isinstance(user_ban, dict) and user_ban.get("banned", False):
        return True

    return False


def get_ban_reason(user_id: str) -> str | None:
    """차단 사유 조회"""
    ban_data = _load_json(BAN_FILE)
    user_ban = ban_data.get(user_id, {})
    if isinstance(user_ban, dict) and user_ban.get("banned", False):
        return user_ban.get("reason", "사유 없음")

    ac_data = _load_json(ANTICHEAT_FILE)
    user_ac = ac_data.get(user_id, {})
    if isinstance(user_ac, dict) and user_ac.get("auto_banned", False):
        return "[자동] 안티치트 경고 누적"

    return None

def is_developer_user(interaction: Interaction) -> bool:
    """개발자인지 확인합니다."""
    return interaction.user.id == DEVELOPER_ID


def is_admin_user(interaction: Interaction) -> bool:
    """관리자인지 확인합니다."""
    return interaction.user.id in ALLOWED_ADMIN_IDS
