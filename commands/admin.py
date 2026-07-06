# commands/admin.py
# ──────────────────────────────────────────────────────────
# 관리자 + 개발자 커맨드 Cog (병합본)
# ──────────────────────────────────────────────────────────

import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from datetime import datetime

from config import (
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING,
    BOT_ICON_URL, ADMIN_IDS, DEVELOPER_ID, USERS_DIR,
    ADMIN_WEBHOOK_URL, MAX_LEVEL, KST,
    DAILY_LIMITS, ANTICHEAT_MAX_WARNINGS
)
from models.user import (
    load_user_data, save_user_data,
    add_exp, is_newbie
)
from systems.anticheat import (
    get_anticheat_status, format_anticheat_embed,
    load_anticheat_data, save_anticheat_data,
    clear_warnings, remove_auto_ban
)
from utils.checks import is_admin
from utils.dishost_api import post_server_count
from data_manager import get_guilds_with_notice_channel

# ── config에서 EXP_FOR_LEVEL 안전하게 가져오기 ──
try:
    from config import EXP_FOR_LEVEL
except ImportError:
    try:
        from config import get_exp_for_level as EXP_FOR_LEVEL
    except ImportError:
        def EXP_FOR_LEVEL(level):
            return int(100 * (level ** 1.5))


# ============================================================
# 권한 확인 헬퍼
# ============================================================

def _is_admin(user_id: int) -> bool:
    """관리자 또는 개발자인지 확인"""
    return user_id in ADMIN_IDS or user_id == DEVELOPER_ID


def _is_developer(user_id: int) -> bool:
    """개발자 전용 확인"""
    return user_id == DEVELOPER_ID


def admin_only():
    """관리자(ADMIN_IDS) + 개발자 모두 사용 가능"""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not _is_admin(interaction.user.id):
            await interaction.response.send_message(
                embed=discord.Embed(title="⛔ 권한 없음", description="관리자 전용 명령어입니다.", color=COLOR_ERROR),
                ephemeral=True,
            )
            return False
        return True
    return app_commands.check(predicate)


def developer_only():
    """개발자(DEVELOPER_ID)만 사용 가능"""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not _is_developer(interaction.user.id):
            await interaction.response.send_message(
                embed=discord.Embed(title="⛔ 권한 없음", description="개발자 전용 명령어입니다.", color=COLOR_ERROR),
                ephemeral=True,
            )
            return False
        return True
    return app_commands.check(predicate)


# ============================================================
# 밴 데이터 관리
# ============================================================

BAN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "user_ban.json")


def load_ban_data() -> dict:
    try:
        with open(BAN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_ban_data(data: dict):
    os.makedirs(os.path.dirname(BAN_FILE), exist_ok=True)
    with open(BAN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# 웹훅 전송 헬퍼
# ============================================================

async def send_admin_webhook(embed_data: dict):
    if not ADMIN_WEBHOOK_URL:
        return
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            await session.post(ADMIN_WEBHOOK_URL, json={"embeds": [embed_data]})
    except Exception:
        pass


# ============================================================
# Cog 정의
# ============================================================

class AdminCog(commands.Cog):
    """관리자 + 개발자 명령어"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ================================================================
    #  관리자 커맨드 (ADMIN_IDS + DEVELOPER_ID)
    # ================================================================

    # ---- /공지 ----
    @app_commands.command(name="공지", description="[관리자] 현재 채널에 공지를 전송합니다.")
    @app_commands.describe(내용="공지 내용")
    @admin_only()
    async def announce_command(self, interaction: discord.Interaction, 내용: str):
        await interaction.response.defer()

        embed = discord.Embed(
            title="📢 공지사항",
            description=내용,
            color=COLOR_PRIMARY,
            timestamp=datetime.now(KST),
        )
        embed.set_footer(text=f"관리자: {interaction.user.display_name}", icon_url=BOT_ICON_URL)

        await interaction.channel.send(embed=embed)
        await interaction.followup.send("✅ 공지가 전송되었습니다.", ephemeral=True)

    # ---- /지급 ----
    @app_commands.command(name="지급", description="[관리자] 유저에게 재화를 지급합니다.")
    @app_commands.describe(대상="지급할 유저", 종류="재화 종류", 수량="지급 수량")
    @app_commands.choices(종류=[
        app_commands.Choice(name="💵 돈", value="money"),
        app_commands.Choice(name="🐟 참치캔", value="tuna_can"),
        app_commands.Choice(name="✨ 경험치", value="exp"),
        app_commands.Choice(name="⭐ 스킬포인트", value="skill_points"),
    ])
    @admin_only()
    async def give_command(self, interaction: discord.Interaction, 대상: discord.Member, 종류: str, 수량: int):
        await interaction.response.defer(ephemeral=True)

        if 수량 <= 0:
            await interaction.followup.send("❌ 수량은 1 이상이어야 합니다.", ephemeral=True)
            return

        user_data = load_user_data(str(대상.id))
        if not user_data:
            await interaction.followup.send("❌ 등록되지 않은 유저입니다.", ephemeral=True)
            return

        if 종류 == "exp":
            exp_result = add_exp(user_data, 수량)
            save_user_data(str(대상.id), user_data)
            result_text = f"✨ {수량:,} EXP 지급"
            if exp_result.get("leveled_up"):
                result_text += f" (Lv.{exp_result['old_level']} → Lv.{exp_result['new_level']})"
        else:
            user_data[종류] = user_data.get(종류, 0) + 수량
            save_user_data(str(대상.id), user_data)
            names = {"money": "💵 돈", "tuna_can": "🐟 참치캔", "skill_points": "⭐ 스킬포인트"}
            result_text = f"{names.get(종류, 종류)} {수량:,} 지급"

        embed = discord.Embed(
            title="✅ 지급 완료",
            description=f"**{대상.display_name}**에게 {result_text}",
            color=COLOR_SUCCESS,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        await send_admin_webhook({
            "title": "🔧 관리자 지급",
            "color": COLOR_SUCCESS,
            "fields": [
                {"name": "관리자", "value": f"{interaction.user} ({interaction.user.id})", "inline": True},
                {"name": "대상", "value": f"{대상} ({대상.id})", "inline": True},
                {"name": "지급 내용", "value": result_text, "inline": False},
                {"name": "시간 (KST)", "value": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"), "inline": False},
            ],
        })

# ---- /차단 ----
    @app_commands.command(name="차단", description="[관리자] 유저를 봇 + Discord 서버에서 벤합니다.")
    @app_commands.describe(대상="차단할 유저", 사유="차단 사유")
    @admin_only()
    async def ban_command(self, interaction: discord.Interaction, 대상: discord.Member, 사유: str = "관리자 차단"):
        await interaction.response.defer(ephemeral=True)

        # 봇 내부 차단 기록
        ban_data = load_ban_data()
        ban_data[str(대상.id)] = {
            "banned": True,
            "reason": 사유,
            "banned_by": str(interaction.user.id),
            "banned_at": datetime.now(KST).isoformat(),
        }
        save_ban_data(ban_data)

        # Discord 서버 실제 벤 실행
        try:
            await interaction.guild.ban(
                대상,
                reason=f"[관리자 차단] {사유} | by {interaction.user} ({interaction.user.id})",
                delete_message_days=0,
            )
            discord_ban_ok = True
        except discord.Forbidden:
            discord_ban_ok = False
            discord_ban_error = "봇에게 Ban Members 권한이 없습니다."
        except discord.HTTPException as e:
            discord_ban_ok = False
            discord_ban_error = str(e)

        if discord_ban_ok:
            embed = discord.Embed(
                title="🚫 차단 완료",
                description=f"**{대상.display_name}** ({대상.id}) 차단됨\n사유: {사유}",
                color=COLOR_ERROR,
            )
        else:
            embed = discord.Embed(
                title="⚠️ 차단 부분 완료",
                description=(
                    f"**{대상.display_name}** ({대상.id})\n"
                    f"봇 내부 차단: ✅\n"
                    f"Discord 서버 벤: ❌ ({discord_ban_error})\n"
                    f"사유: {사유}"
                ),
                color=COLOR_WARNING,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

        await send_admin_webhook({
            "title": "🚫 유저 차단",
            "color": COLOR_ERROR,
            "fields": [
                {"name": "관리자", "value": f"{interaction.user} ({interaction.user.id})", "inline": True},
                {"name": "대상", "value": f"{대상} ({대상.id})", "inline": True},
                {"name": "Discord 벤", "value": "✅ 완료" if discord_ban_ok else f"❌ 실패", "inline": True},
                {"name": "사유", "value": 사유, "inline": False},
                {"name": "시간 (KST)", "value": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"), "inline": False},
            ],
        })
        
    # ---- /차단해제 ----
    @app_commands.command(name="차단해제", description="[관리자] 유저의 차단을 해제합니다.")
    @app_commands.describe(대상="차단 해제할 유저")
    @admin_only()
    async def unban_command(self, interaction: discord.Interaction, 대상: discord.Member):
        await interaction.response.defer(ephemeral=True)

        ban_data = load_ban_data()
        if str(대상.id) in ban_data:
            del ban_data[str(대상.id)]
            save_ban_data(ban_data)

        embed = discord.Embed(
            title="✅ 차단 해제",
            description=f"**{대상.display_name}** ({대상.id}) 차단이 해제되었습니다.",
            color=COLOR_SUCCESS,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ---- /안티치트조회 ----
    @app_commands.command(name="안티치트조회", description="[관리자] 유저의 안티치트 경고 현황을 조회합니다.")
    @app_commands.describe(대상="조회할 유저")
    @admin_only()
    async def anticheat_check_command(self, interaction: discord.Interaction, 대상: discord.Member):
        await interaction.response.defer(ephemeral=True)

        status = get_anticheat_status(대상.id)
        embed = format_anticheat_embed(대상, status)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ---- /안티치트해제 ----
    @app_commands.command(name="안티치트해제", description="[관리자] 유저의 안티치트 경고를 초기화합니다.")
    @app_commands.describe(대상="초기화할 유저")
    @admin_only()
    async def anticheat_clear_command(self, interaction: discord.Interaction, 대상: discord.Member):
        await interaction.response.defer(ephemeral=True)

        clear_warnings(대상.id)
        remove_auto_ban(대상.id)

        ban_data = load_ban_data()
        user_ban = ban_data.get(str(대상.id), {})
        reason = user_ban.get("reason", "")
        if "안티치트" in reason or "[자동]" in reason or "AntiCheat" in reason:
            del ban_data[str(대상.id)]
            save_ban_data(ban_data)

        embed = discord.Embed(
            title="✅ 안티치트 초기화",
            description=(
                f"**{대상.display_name}** ({대상.id})의\n"
                f"안티치트 경고가 초기화되었습니다.\n"
                f"자동 차단도 해제되었습니다."
            ),
            color=COLOR_SUCCESS,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        await send_admin_webhook({
            "title": "🔓 안티치트 초기화",
            "color": COLOR_SUCCESS,
            "fields": [
                {"name": "관리자", "value": f"{interaction.user} ({interaction.user.id})", "inline": True},
                {"name": "대상", "value": f"{대상} ({대상.id})", "inline": True},
                {"name": "시간 (KST)", "value": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"), "inline": False},
            ],
        })

    # ---- /안티치트로그 ----
    @app_commands.command(name="안티치트로그", description="[관리자] 최근 안티치트 감지 로그를 조회합니다.")
    @app_commands.describe(대상="조회할 유저", 갯수="표시할 로그 수 (기본 10)")
    @admin_only()
    async def anticheat_log_command(self, interaction: discord.Interaction, 대상: discord.Member, 갯수: int = 10):
        await interaction.response.defer(ephemeral=True)

        status = get_anticheat_status(대상.id)
        warnings = status.get("warnings", [])

        if not warnings:
            await interaction.followup.send(
                f"✅ **{대상.display_name}**에 대한 안티치트 경고 기록이 없습니다.",
                ephemeral=True,
            )
            return

        recent = warnings[-갯수:]

        embed = discord.Embed(
            title=f"🛡️ {대상.display_name}의 안티치트 로그",
            description=f"총 경고: **{len(warnings)}회** / {ANTICHEAT_MAX_WARNINGS}회\n최근 {len(recent)}건 표시",
            color=COLOR_WARNING,
        )

        for i, w in enumerate(recent, 1):
            try:
                w_time = datetime.fromisoformat(w["timestamp"]).astimezone(KST)
                time_str = w_time.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, KeyError):
                time_str = w.get("timestamp", "???")

            reason = w.get("reason", "알 수 없음")
            details = w.get("details", {})
            detect_type = details.get("type", "unknown")
            location = f"{details.get('guild_name', '?')} / {details.get('channel_name', '?')}"

            embed.add_field(
                name=f"#{i} [{time_str}]",
                value=(
                    f"**유형**: {detect_type}\n"
                    f"**사유**: {reason[:80]}\n"
                    f"**위치**: {location}"
                ),
                inline=False,
            )

        reaction_stats = status.get("reaction_stats", {})
        if reaction_stats:
            embed.add_field(
                name="📈 반응속도 통계 (최근)",
                value=(
                    f"평균: **{reaction_stats.get('avg_ms', '?')}ms** | "
                    f"표준편차: **{reaction_stats.get('stddev_ms', '?')}ms**\n"
                    f"최소: **{reaction_stats.get('min_ms', '?')}ms** | "
                    f"최대: **{reaction_stats.get('max_ms', '?')}ms**"
                ),
                inline=False,
            )

        recent_reactions = status.get("recent_reactions_ms", [])
        if recent_reactions:
            reactions_str = ", ".join([f"{ms}ms" for ms in recent_reactions[-10:]])
            embed.add_field(
                name="⏱️ 최근 반응속도 기록",
                value=f"`{reactions_str}`",
                inline=False,
            )

        embed.set_thumbnail(url=대상.display_avatar.url)
        embed.set_footer(text=f"ID: {대상.id}", icon_url=BOT_ICON_URL)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ---- /유저상세정보 ----
    @app_commands.command(name="유저상세정보", description="[관리자] 유저의 상세 정보를 조회합니다.")
    @app_commands.describe(대상="조회할 유저")
    @admin_only()
    async def user_info_command(self, interaction: discord.Interaction, 대상: discord.Member):
        await interaction.response.defer(ephemeral=True)

        user_data = load_user_data(str(대상.id))
        if not user_data:
            await interaction.followup.send("❌ 등록되지 않은 유저입니다.", ephemeral=True)
            return

        level = user_data.get("level", 1)
        exp = user_data.get("exp", 0)
        money = user_data.get("money", 0)
        tuna = user_data.get("tuna_can", 0)
        skill_points = user_data.get("skill_points", 0)
        skills = user_data.get("skills", {})
        stats = user_data.get("stats", {})
        daily = user_data.get("daily_counts", {})

        try:
            needed_exp = EXP_FOR_LEVEL(level)
        except Exception:
            needed_exp = "?"

        embed = discord.Embed(
            title=f"🔍 {대상.display_name}의 상세 정보",
            color=COLOR_PRIMARY,
        )

        embed.add_field(
            name="📊 기본",
            value=(
                f"Lv.**{level}** | EXP: {exp:,}/{needed_exp:,}\n"
                f"💵 {money:,}원 | 🐟 {tuna}개\n"
                f"⭐ SP: {skill_points}P\n"
                f"지역: {user_data.get('current_region', 'N/A')}\n"
                f"튜토리얼: {user_data.get('tutorial_step', 'N/A')}"
            ),
            inline=False,
        )

        embed.add_field(
            name="🔧 스킬",
            value=(
                f"추적: Lv.{skills.get('tracking', 0)} | "
                f"전투: Lv.{skills.get('combat', 0)} | "
                f"교역: Lv.{skills.get('trade', 0)}"
            ),
            inline=True,
        )

        owned = user_data.get("cats", user_data.get("owned_cats", {}))
        if isinstance(owned, dict):
            total_cats = sum(
                v.get("count", 1) if isinstance(v, dict) else 1
                for v in owned.values()
            )
        elif isinstance(owned, list):
            total_cats = len(owned)
        else:
            total_cats = 0

        catdex = user_data.get("catdex", {})
        catdex_count = len(catdex) if isinstance(catdex, dict) else 0

        embed.add_field(
            name="🐱 냥이",
            value=f"보유: {total_cats}마리 | 도감: {catdex_count}종",
            inline=True,
        )

        embed.add_field(
            name="📈 통계",
            value=(
                f"납치: {stats.get('total_kidnaps', 0)} | "
                f"전투: {stats.get('total_battles', 0)} (승{stats.get('battle_wins', 0)}) | "
                f"미궁: {stats.get('labyrinth_runs', 0)} (최고{stats.get('labyrinth_best_floor', 0)}층)"
            ),
            inline=False,
        )

        daily_items = [(k, v) for k, v in daily.items() if k not in ("date", "daily_counts_date")]
        if daily_items:
            daily_text = " | ".join([f"{k}: {v}" for k, v in daily_items])
            embed.add_field(name="📅 오늘 활동", value=daily_text, inline=False)

        ac_status = get_anticheat_status(대상.id)
        ac_warnings = ac_status.get("warnings", [])
        embed.add_field(
            name="🛡️ 안티치트",
            value=f"경고: **{len(ac_warnings)}/{ANTICHEAT_MAX_WARNINGS}** | 밴: {'🔴' if ac_status.get('auto_banned', False) else '🟢'}",
            inline=True,
        )

        embed.add_field(
            name="🌱 뉴비",
            value=f"{'활성' if is_newbie(user_data) else '만료'}",
            inline=True,
        )

        registered_at = user_data.get("created_at", user_data.get("registered_at", "N/A"))
        embed.add_field(
            name="📅 가입일",
            value=registered_at[:10] if isinstance(registered_at, str) and len(registered_at) > 10 else str(registered_at),
            inline=True,
        )

        # 투표 정보 표시
        vote_data = user_data.get("vote", {})
        if vote_data:
            embed.add_field(
                name="🗳️ 투표",
                value=(
                    f"누적: {vote_data.get('total_count', 0)}회 | "
                    f"연속: {vote_data.get('streak', 0)}일 | "
                    f"총 보상: {vote_data.get('total_reward', 0):,}G"
                ),
                inline=False,
            )

        embed.set_thumbnail(url=대상.display_avatar.url)
        embed.set_footer(text="관리자 전용 정보", icon_url=BOT_ICON_URL)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ---- /서버상태 ----
    @app_commands.command(name="서버상태", description="[관리자] 전체 유저 통계를 확인합니다.")
    @admin_only()
    async def server_status_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        total_users = 0
        total_money = 0
        total_tuna = 0
        level_dist = {}
        active_today = 0

        today = datetime.now(KST).strftime("%Y-%m-%d")

        if os.path.exists(USERS_DIR):
            for filename in os.listdir(USERS_DIR):
                if not filename.endswith(".json"):
                    continue
                try:
                    user_id = filename.replace(".json", "")
                    data = load_user_data(user_id)
                    if not data:
                        continue

                    total_users += 1
                    total_money += data.get("money", 0)
                    total_tuna += data.get("tuna_can", 0)

                    level = data.get("level", 1)
                    bracket = f"{(level - 1) // 10 * 10 + 1}-{(level - 1) // 10 * 10 + 10}"
                    level_dist[bracket] = level_dist.get(bracket, 0) + 1

                    daily_date = data.get("daily_counts_date", data.get("daily_counts", {}).get("date", ""))
                    if daily_date == today:
                        active_today += 1

                except Exception:
                    continue

        embed = discord.Embed(
            title="📊 전체 유저 통계",
            color=COLOR_PRIMARY,
            timestamp=datetime.now(KST),
        )

        embed.add_field(
            name="👥 유저",
            value=f"총 등록: **{total_users}명**\n오늘 활동: **{active_today}명**",
            inline=True,
        )

        embed.add_field(
            name="💰 경제",
            value=f"총 유통 금액: **{total_money:,}원**\n총 참치캔: **{total_tuna:,}개**",
            inline=True,
        )

        if level_dist:
            sorted_dist = sorted(level_dist.items())
            dist_text = "\n".join([f"Lv.{k}: **{v}명**" for k, v in sorted_dist])
            embed.add_field(name="📈 레벨 분포", value=dist_text, inline=False)

        ac_data = load_anticheat_data()
        ac_warnings = ac_data.get("warnings", {})
        ac_bans = ac_data.get("auto_bans", {})
        warned_users = sum(1 for v in ac_warnings.values() if isinstance(v, list) and len(v) > 0)
        banned_users = len(ac_bans)

        embed.add_field(
            name="🛡️ 안티치트",
            value=f"경고 유저: **{warned_users}명**\n자동 차단: **{banned_users}명**",
            inline=True,
        )

        embed.set_footer(text="관리자 전용", icon_url=BOT_ICON_URL)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ================================================================
    #  개발자 전용 커맨드 (DEVELOPER_ID만)
    # ================================================================

    # ---- /봇상태 ----
    @app_commands.command(name="봇상태", description="[개발자] 봇 인프라 상태를 확인합니다.")
    @app_commands.default_permissions(administrator=True)
    @developer_only()
    async def checkk_bot_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_count = len(self.bot.guilds)
        total_members = sum(g.member_count or 0 for g in self.bot.guilds)
        user_files = len([f for f in os.listdir(USERS_DIR) if f.endswith(".json")]) if os.path.isdir(USERS_DIR) else 0
        latency_ms = round(self.bot.latency * 1000, 1)

        embed = discord.Embed(
            title="🖥️ 봇 인프라 상태",
            color=COLOR_SUCCESS,
            timestamp=datetime.now(KST),
        )
        embed.add_field(name="서버 수", value=f"`{guild_count}`개", inline=True)
        embed.add_field(name="총 멤버", value=f"`{total_members:,}`명", inline=True)
        embed.add_field(name="등록 유저", value=f"`{user_files}`명", inline=True)
        embed.add_field(name="핑", value=f"`{latency_ms}ms`", inline=True)
        embed.set_footer(text="Developer Only", icon_url=BOT_ICON_URL)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ---- /서버목록 ----
    @app_commands.command(name="서버목록", description="[개발자] 봇이 참여 중인 서버 목록을 확인합니다.")
    @app_commands.default_permissions(administrator=True)
    @developer_only()
    async def server_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guilds_sorted = sorted(self.bot.guilds, key=lambda g: g.member_count or 0, reverse=True)
        lines = []
        for i, g in enumerate(guilds_sorted[:20], 1):
            lines.append(f"`{i}.` **{g.name}** — {g.member_count or 0}명 (`{g.id}`)")

        desc = "\n".join(lines) if lines else "서버 없음"
        if len(guilds_sorted) > 20:
            desc += f"\n\n... 외 {len(guilds_sorted) - 20}개 서버"

        embed = discord.Embed(
            title=f"📋 서버 목록 ({len(self.bot.guilds)}개)",
            description=desc,
            color=COLOR_SUCCESS,
            timestamp=datetime.now(KST),
        )
        embed.set_footer(text="Developer Only", icon_url=BOT_ICON_URL)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ---- /통계전송 ----
    @app_commands.command(name="통계전송", description="[개발자] 디스호스트에 서버 수를 수동 전송합니다.")
    @app_commands.default_permissions(administrator=True)
    @developer_only()
    async def manual_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        count = len(self.bot.guilds)
        result = await post_server_count(count)

        if result:
            embed = discord.Embed(
                title="✅ 통계 전송 완료",
                description=(
                    f"서버 수 **{count}**개를 디스호스트에 전송했습니다.\n"
                    f"인증 상태: `{result.get('isCertified', 'N/A')}`"
                ),
                color=COLOR_SUCCESS,
            )
        else:
            embed = discord.Embed(
                title="❌ 전송 실패",
                description="디스호스트 API 요청에 실패했습니다. 콘솔 로그를 확인하세요.",
                color=COLOR_ERROR,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ---- /전체공지 ----
    @app_commands.command(name="전체공지", description="[개발자] 모든 서버의 공지 채널에 메시지를 전송합니다.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(제목="공지 제목", 내용="공지 내용")
    @developer_only()
    async def broadcast(self, interaction: discord.Interaction, 제목: str, 내용: str):
        await interaction.response.defer(ephemeral=True)

        targets = get_guilds_with_notice_channel()
        success, fail = 0, 0

        embed = discord.Embed(
            title=f"📢 {제목}",
            description=내용,
            color=COLOR_WARNING,
            timestamp=datetime.now(KST),
        )
        embed.set_footer(text="오니카타 카요코 공식 공지", icon_url=BOT_ICON_URL)

        for guild_id, channel_id in targets.items():
            try:
                ch = self.bot.get_channel(int(channel_id))
                if ch:
                    await ch.send(embed=embed)
                    success += 1
                else:
                    fail += 1
            except Exception:
                fail += 1

        result_embed = discord.Embed(
            title="📨 전체 공지 전송 완료",
            description=f"성공: `{success}`개 서버 / 실패: `{fail}`개 서버",
            color=COLOR_SUCCESS,
        )
        await interaction.followup.send(embed=result_embed, ephemeral=True)

# ---- /서버벤 ----
    @app_commands.command(name="서버벤", description="[개발자] 특정 서버에서 유저를 영구 벤합니다.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(서버아이디="벤을 실행할 서버 ID", 유저아이디="벤할 유저 ID", 사유="벤 사유")
    @developer_only()
    async def dev_guild_ban(self, interaction: discord.Interaction, 서버아이디: str, 유저아이디: str, 사유: str = "개발자 벤"):
        await interaction.response.defer(ephemeral=True)

        # 서버 ID 유효성 검사
        try:
            guild_id_int = int(서버아이디)
        except ValueError:
            await interaction.followup.send("❌ 서버 ID가 유효하지 않습니다.", ephemeral=True)
            return

        # 유저 ID 유효성 검사
        try:
            user_id_int = int(유저아이디)
        except ValueError:
            await interaction.followup.send("❌ 유저 ID가 유효하지 않습니다.", ephemeral=True)
            return

        # 봇이 해당 서버에 있는지 확인
        guild = self.bot.get_guild(guild_id_int)
        if guild is None:
            await interaction.followup.send("❌ 해당 서버를 찾을 수 없습니다. 봇이 참여 중인 서버인지 확인하세요.", ephemeral=True)
            return

        # 벤 실행 전 확인 UI
        confirm_embed = discord.Embed(
            title="⚠️ 서버 벤 확인",
            description=(
                f"**서버**: {guild.name} (`{guild.id}`)\n"
                f"**유저 ID**: `{user_id_int}`\n"
                f"**사유**: {사유}\n\n"
                "정말로 이 유저를 해당 서버에서 벤하시겠습니까?"
            ),
            color=COLOR_WARNING,
        )
        confirm_embed.set_footer(text="아래 버튼으로 선택하세요.", icon_url=BOT_ICON_URL)

        class ConfirmView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=30)
                self.value: bool | None = None

            @discord.ui.button(label="✅ 벤 실행", style=discord.ButtonStyle.danger)
            async def confirm(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                if btn_interaction.user.id != interaction.user.id:
                    await btn_interaction.response.send_message("❌ 명령어를 실행한 개발자만 선택할 수 있습니다.", ephemeral=True)
                    return
                self.value = True
                self.stop()
                await btn_interaction.response.defer()

            @discord.ui.button(label="❌ 취소", style=discord.ButtonStyle.secondary)
            async def cancel(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                if btn_interaction.user.id != interaction.user.id:
                    await btn_interaction.response.send_message("❌ 명령어를 실행한 개발자만 선택할 수 있습니다.", ephemeral=True)
                    return
                self.value = False
                self.stop()
                await btn_interaction.response.defer()

        view = ConfirmView()
        await interaction.followup.send(embed=confirm_embed, view=view, ephemeral=True)

        # 30초 타임아웃 대기
        await view.wait()

        if view.value is None:
            await interaction.edit_original_response(
                embed=discord.Embed(title="⏰ 시간 초과", description="선택 시간이 초과되어 취소되었습니다.", color=COLOR_ERROR),
                view=None,
            )
            return

        if not view.value:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 취소됨", description="벤이 취소되었습니다.", color=COLOR_WARNING),
                view=None,
            )
            return

        # 실제 Discord 서버 벤 실행
        # guild.ban()은 유저가 서버 멤버가 아니어도 Object로 처리 가능 (discord.py 공식 지원)
        try:
            await guild.ban(
                discord.Object(id=user_id_int),
                reason=f"[개발자 벤] {사유} | by {interaction.user} ({interaction.user.id})",
                delete_message_days=0,
            )
        except discord.Forbidden:
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="❌ 권한 부족",
                    description="해당 서버에서 봇에게 Ban Members 권한이 없습니다.",
                    color=COLOR_ERROR,
                ),
                view=None,
            )
            return
        except discord.HTTPException as e:
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="❌ 벤 실패",
                    description=f"Discord API 오류: `{e}`",
                    color=COLOR_ERROR,
                ),
                view=None,
            )
            return

        result_embed = discord.Embed(
            title="🔨 서버 벤 완료",
            description=(
                f"**서버**: {guild.name} (`{guild.id}`)\n"
                f"**유저 ID**: `{user_id_int}`\n"
                f"**사유**: {사유}"
            ),
            color=COLOR_ERROR,
            timestamp=datetime.now(KST),
        )
        result_embed.set_footer(text="Developer Only", icon_url=BOT_ICON_URL)
        await interaction.edit_original_response(embed=result_embed, view=None)

        await send_admin_webhook({
            "title": "🔨 서버 벤",
            "color": COLOR_ERROR,
            "fields": [
                {"name": "개발자", "value": f"{interaction.user} ({interaction.user.id})", "inline": True},
                {"name": "대상 유저 ID", "value": str(user_id_int), "inline": True},
                {"name": "서버", "value": f"{guild.name} ({guild.id})", "inline": False},
                {"name": "사유", "value": 사유, "inline": False},
                {"name": "시간 (KST)", "value": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"), "inline": False},
            ],
        })

# ---- /서버킥 ----
    @app_commands.command(name="서버킥", description="[개발자] 특정 서버에서 유저를 킥합니다.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(서버아이디="킥을 실행할 서버 ID", 유저아이디="킥할 유저 ID", 사유="킥 사유")
    @developer_only()
    async def dev_guild_kick(self, interaction: discord.Interaction, 서버아이디: str, 유저아이디: str, 사유: str = "개발자 킥"):
        await interaction.response.defer(ephemeral=True)

        try:
            guild_id_int = int(서버아이디)
        except ValueError:
            await interaction.followup.send("❌ 서버 ID가 유효하지 않습니다.", ephemeral=True)
            return

        try:
            user_id_int = int(유저아이디)
        except ValueError:
            await interaction.followup.send("❌ 유저 ID가 유효하지 않습니다.", ephemeral=True)
            return

        guild = self.bot.get_guild(guild_id_int)
        if guild is None:
            await interaction.followup.send("❌ 해당 서버를 찾을 수 없습니다.", ephemeral=True)
            return

        # 킥은 서버 멤버여야만 가능 — fetch_member로 실제 확인
        try:
            member = guild.get_member(user_id_int) or await guild.fetch_member(user_id_int)
        except discord.NotFound:
            await interaction.followup.send("❌ 해당 유저가 서버에 없습니다. 킥은 현재 서버 멤버만 가능합니다.", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ 유저 조회 실패: `{e}`", ephemeral=True)
            return

        confirm_embed = discord.Embed(
            title="⚠️ 서버 킥 확인",
            description=(
                f"**서버**: {guild.name} (`{guild.id}`)\n"
                f"**유저**: {member.display_name} (`{member.id}`)\n"
                f"**사유**: {사유}\n\n"
                "킥 후 재입장 가능합니다. 계속하시겠습니까?"
            ),
            color=COLOR_WARNING,
        )

        class KickConfirmView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=30)
                self.value: bool | None = None

            @discord.ui.button(label="✅ 킥 실행", style=discord.ButtonStyle.danger)
            async def confirm(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                if btn_interaction.user.id != interaction.user.id:
                    await btn_interaction.response.send_message("❌ 명령어를 실행한 개발자만 선택할 수 있습니다.", ephemeral=True)
                    return
                self.value = True
                self.stop()
                await btn_interaction.response.defer()

            @discord.ui.button(label="❌ 취소", style=discord.ButtonStyle.secondary)
            async def cancel(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                if btn_interaction.user.id != interaction.user.id:
                    await btn_interaction.response.send_message("❌ 명령어를 실행한 개발자만 선택할 수 있습니다.", ephemeral=True)
                    return
                self.value = False
                self.stop()
                await btn_interaction.response.defer()

        view = KickConfirmView()
        await interaction.followup.send(embed=confirm_embed, view=view, ephemeral=True)
        await view.wait()

        if view.value is None:
            await interaction.edit_original_response(
                embed=discord.Embed(title="⏰ 시간 초과", description="취소되었습니다.", color=COLOR_ERROR), view=None)
            return
        if not view.value:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 취소됨", description="킥이 취소되었습니다.", color=COLOR_WARNING), view=None)
            return

        try:
            await guild.kick(
                member,
                reason=f"[개발자 킥] {사유} | by {interaction.user} ({interaction.user.id})",
            )
        except discord.Forbidden:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 권한 부족", description="봇에게 Kick Members 권한이 없습니다.", color=COLOR_ERROR), view=None)
            return
        except discord.HTTPException as e:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 킥 실패", description=f"Discord API 오류: `{e}`", color=COLOR_ERROR), view=None)
            return

        result_embed = discord.Embed(
            title="👢 서버 킥 완료",
            description=(
                f"**서버**: {guild.name} (`{guild.id}`)\n"
                f"**유저**: {member.display_name} (`{member.id}`)\n"
                f"**사유**: {사유}"
            ),
            color=COLOR_WARNING,
            timestamp=datetime.now(KST),
        )
        result_embed.set_footer(text="Developer Only", icon_url=BOT_ICON_URL)
        await interaction.edit_original_response(embed=result_embed, view=None)

        await send_admin_webhook({
            "title": "👢 개발자 서버 킥",
            "color": COLOR_WARNING,
            "fields": [
                {"name": "개발자", "value": f"{interaction.user} ({interaction.user.id})", "inline": True},
                {"name": "대상", "value": f"{member} ({member.id})", "inline": True},
                {"name": "서버", "value": f"{guild.name} ({guild.id})", "inline": False},
                {"name": "사유", "value": 사유, "inline": False},
                {"name": "시간 (KST)", "value": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"), "inline": False},
            ],
        })
        
# ---- /서버타임아웃 ----
    @app_commands.command(name="서버타임아웃", description="[개발자] 특정 서버에서 유저에게 타임아웃을 부여합니다.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        서버아이디="타임아웃을 실행할 서버 ID",
        유저아이디="타임아웃할 유저 ID",
        분="타임아웃 시간 (분, 최대 40320 = 28일)",
        사유="타임아웃 사유",
    )
    @developer_only()
    async def dev_guild_timeout(self, interaction: discord.Interaction, 서버아이디: str, 유저아이디: str, 분: int, 사유: str = "개발자 타임아웃"):
        await interaction.response.defer(ephemeral=True)

        # Discord 타임아웃 최대 28일 = 40320분
        if not (1 <= 분 <= 40320):
            await interaction.followup.send("❌ 타임아웃 시간은 1분 ~ 40320분(28일) 사이여야 합니다.", ephemeral=True)
            return

        try:
            guild_id_int = int(서버아이디)
        except ValueError:
            await interaction.followup.send("❌ 서버 ID가 유효하지 않습니다.", ephemeral=True)
            return

        try:
            user_id_int = int(유저아이디)
        except ValueError:
            await interaction.followup.send("❌ 유저 ID가 유효하지 않습니다.", ephemeral=True)
            return

        guild = self.bot.get_guild(guild_id_int)
        if guild is None:
            await interaction.followup.send("❌ 해당 서버를 찾을 수 없습니다.", ephemeral=True)
            return

        # 타임아웃은 서버 멤버여야만 가능
        try:
            member = guild.get_member(user_id_int) or await guild.fetch_member(user_id_int)
        except discord.NotFound:
            await interaction.followup.send("❌ 해당 유저가 서버에 없습니다. 타임아웃은 현재 서버 멤버만 가능합니다.", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ 유저 조회 실패: `{e}`", ephemeral=True)
            return

        # 시간 표시 문자열
        if 분 < 60:
            duration_str = f"{분}분"
        elif 분 < 1440:
            duration_str = f"{분 // 60}시간 {분 % 60}분" if 분 % 60 else f"{분 // 60}시간"
        else:
            duration_str = f"{분 // 1440}일 {(분 % 1440) // 60}시간" if (분 % 1440) else f"{분 // 1440}일"

        confirm_embed = discord.Embed(
            title="⚠️ 서버 타임아웃 확인",
            description=(
                f"**서버**: {guild.name} (`{guild.id}`)\n"
                f"**유저**: {member.display_name} (`{member.id}`)\n"
                f"**시간**: {duration_str}\n"
                f"**사유**: {사유}\n\n"
                "계속하시겠습니까?"
            ),
            color=COLOR_WARNING,
        )

        class TimeoutConfirmView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=30)
                self.value: bool | None = None

            @discord.ui.button(label="✅ 타임아웃 실행", style=discord.ButtonStyle.danger)
            async def confirm(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                if btn_interaction.user.id != interaction.user.id:
                    await btn_interaction.response.send_message("❌ 명령어를 실행한 개발자만 선택할 수 있습니다.", ephemeral=True)
                    return
                self.value = True
                self.stop()
                await btn_interaction.response.defer()

            @discord.ui.button(label="❌ 취소", style=discord.ButtonStyle.secondary)
            async def cancel(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                if btn_interaction.user.id != interaction.user.id:
                    await btn_interaction.response.send_message("❌ 명령어를 실행한 개발자만 선택할 수 있습니다.", ephemeral=True)
                    return
                self.value = False
                self.stop()
                await btn_interaction.response.defer()

        view = TimeoutConfirmView()
        await interaction.followup.send(embed=confirm_embed, view=view, ephemeral=True)
        await view.wait()

        if view.value is None:
            await interaction.edit_original_response(
                embed=discord.Embed(title="⏰ 시간 초과", description="취소되었습니다.", color=COLOR_ERROR), view=None)
            return
        if not view.value:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 취소됨", description="타임아웃이 취소되었습니다.", color=COLOR_WARNING), view=None)
            return

        from datetime import timedelta
        try:
            await member.timeout(
                timedelta(minutes=분),
                reason=f"[개발자 타임아웃] {사유} | by {interaction.user} ({interaction.user.id})",
            )
        except discord.Forbidden:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 권한 부족", description="봇에게 Moderate Members 권한이 없거나 대상이 봇보다 높은 역할을 가지고 있습니다.", color=COLOR_ERROR), view=None)
            return
        except discord.HTTPException as e:
            await interaction.edit_original_response(
                embed=discord.Embed(title="❌ 타임아웃 실패", description=f"Discord API 오류: `{e}`", color=COLOR_ERROR), view=None)
            return

        result_embed = discord.Embed(
            title="🔇 타임아웃 완료",
            description=(
                f"**서버**: {guild.name} (`{guild.id}`)\n"
                f"**유저**: {member.display_name} (`{member.id}`)\n"
                f"**시간**: {duration_str}\n"
                f"**사유**: {사유}"
            ),
            color=COLOR_WARNING,
            timestamp=datetime.now(KST),
        )
        result_embed.set_footer(text="Developer Only", icon_url=BOT_ICON_URL)
        await interaction.edit_original_response(embed=result_embed, view=None)

        await send_admin_webhook({
            "title": "🔇 개발자 타임아웃",
            "color": COLOR_WARNING,
            "fields": [
                {"name": "개발자", "value": f"{interaction.user} ({interaction.user.id})", "inline": True},
                {"name": "대상", "value": f"{member} ({member.id})", "inline": True},
                {"name": "서버", "value": f"{guild.name} ({guild.id})", "inline": False},
                {"name": "시간", "value": duration_str, "inline": True},
                {"name": "사유", "value": 사유, "inline": False},
                {"name": "시간 (KST)", "value": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"), "inline": False},
            ],
        })        
# ============================================================
# Cog 등록
# ============================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
