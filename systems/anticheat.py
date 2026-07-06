# systems/anticheat.py
# ──────────────────────────────────────────────────────────
# 매크로/자동화 탐지 시스템 v2
# - 인간 한계 반응속도 판정
# - 평균 반응속도 이상 탐지
# - 표준편차 기반 기계적 패턴 탐지
# - 등차수열 패턴 탐지 (일정한 증감)
# - 주기 패턴 탐지 (번갈아 반복)
# - 커맨드/납치 빈도 탐지
# - 경고 누적 → 자동 영구차단
# - JSON 파일 기반 영구 저장
# - 웹훅 알림
# ──────────────────────────────────────────────────────────

import os
import time
import math
import asyncio
import statistics
from datetime import datetime, timezone, timedelta
from typing import Optional
from collections import deque

import discord
import aiohttp

from config import (
    KST, ANTICHEAT_ENABLED,
    ANTICHEAT_COMMANDS_PER_MINUTE, ANTICHEAT_KIDNAPS_PER_HOUR,
    ANTICHEAT_MAX_WARNINGS, ANTICHEAT_WARNING_DECAY_DAYS,
    ANTICHEAT_WEBHOOK_URL, COLOR_ERROR, COLOR_WARNING,
    BASE_DIR,
)
from data_manager import load_json, save_json

# ═══════════════════════════════════════════════════════════
# 파일 경로
# ═══════════════════════════════════════════════════════════

ANTICHEAT_DATA_FILE = os.path.join(BASE_DIR, "anticheat_data.json")

# ═══════════════════════════════════════════════════════════
# ★ 반응속도 탐지 기준 상수
# ═══════════════════════════════════════════════════════════

# ── 1. 인간 한계 반응속도 (개별 판정) ──
HUMAN_MIN_REACTION_MS = 80
INHUMAN_STREAK_THRESHOLD = 3

# ── 2. 평균 반응속도 이상 탐지 ──
SUSPICIOUS_AVG_MS = 120
AVG_CHECK_WINDOW = 8

# ── 3. 표준편차 이상 탐지 (기계적으로 일정한 패턴) ──
MIN_STDDEV_MS = 15
STDDEV_CHECK_WINDOW = 6

# ── 4. 등차수열 패턴 탐지 (일정한 증감) ──
DIFF_STDDEV_THRESHOLD = 5
DIFF_CHECK_WINDOW = 5

# ── 5. 주기 패턴 탐지 (두 값 번갈아 반복) ──
PERIOD_STDDEV_THRESHOLD = 10
PERIOD_CHECK_WINDOW = 8

# ── 기록 보관 ──
HISTORY_MAX_SIZE = 30

# ═══════════════════════════════════════════════════════════
# 인메모리 트래킹
# ═══════════════════════════════════════════════════════════

_command_timestamps: dict[int, deque] = {}
_kidnap_timestamps: dict[int, deque] = {}
_reaction_history: dict[int, deque] = {}

# ═══════════════════════════════════════════════════════════
# 영구 데이터 로드/저장
# ═══════════════════════════════════════════════════════════

def _load_anticheat_data() -> dict:
    default = {
        "warnings": {},
        "auto_bans": {},
    }
    data = load_json(ANTICHEAT_DATA_FILE, default)
    if "warnings" not in data:
        data["warnings"] = {}
    if "auto_bans" not in data:
        data["auto_bans"] = {}
    return data

# 하위 호환 별칭
load_anticheat_data = _load_anticheat_data


def _save_anticheat_data(data: dict):
    save_json(ANTICHEAT_DATA_FILE, data)

save_anticheat_data = _save_anticheat_data


# ═══════════════════════════════════════════════════════════
# 경고 관리
# ═══════════════════════════════════════════════════════════

def get_user_warnings(user_id: int) -> list:
    data = _load_anticheat_data()
    uid_str = str(user_id)
    warnings = data.get("warnings", {}).get(uid_str, [])
    if not warnings:
        return []

    now = datetime.now(timezone.utc)
    decay_delta = timedelta(days=ANTICHEAT_WARNING_DECAY_DAYS)
    valid_warnings = []
    for w in warnings:
        try:
            warn_time = datetime.fromisoformat(w["timestamp"])
            if now - warn_time < decay_delta:
                valid_warnings.append(w)
        except (ValueError, KeyError):
            continue

    if len(valid_warnings) != len(warnings):
        data.setdefault("warnings", {})[uid_str] = valid_warnings
        _save_anticheat_data(data)

    return valid_warnings


def get_warning_count(user_id: int) -> int:
    return len(get_user_warnings(user_id))


def is_auto_banned(user_id: int) -> bool:
    data = _load_anticheat_data()
    return str(user_id) in data.get("auto_bans", {})


def add_warning(user_id: int, reason: str, details: dict | None = None) -> tuple[int, bool]:
    data = _load_anticheat_data()
    uid_str = str(user_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    if uid_str in data.get("auto_bans", {}):
        return -1, True

    warnings_list = data.setdefault("warnings", {}).setdefault(uid_str, [])
    warnings_list.append({
        "reason": reason,
        "timestamp": now_iso,
        "details": details or {},
    })

    now = datetime.now(timezone.utc)
    decay_delta = timedelta(days=ANTICHEAT_WARNING_DECAY_DAYS)
    valid = [
        w for w in warnings_list
        if now - datetime.fromisoformat(w["timestamp"]) < decay_delta
    ]
    data["warnings"][uid_str] = valid

    current_count = len(valid)
    auto_banned = False

    if current_count >= ANTICHEAT_MAX_WARNINGS:
        data.setdefault("auto_bans", {})[uid_str] = {
            "banned_at": now_iso,
            "reason": f"안티치트 경고 {current_count}회 누적 (자동 영구차단)",
            "total_warnings": current_count,
            "last_warning_reason": reason,
        }
        auto_banned = True

    _save_anticheat_data(data)
    return current_count, auto_banned


def clear_warnings(user_id: int):
    data = _load_anticheat_data()
    uid_str = str(user_id)
    if uid_str in data.get("warnings", {}):
        del data["warnings"][uid_str]
    _save_anticheat_data(data)


def remove_auto_ban(user_id: int):
    data = _load_anticheat_data()
    uid_str = str(user_id)
    if uid_str in data.get("auto_bans", {}):
        del data["auto_bans"][uid_str]
    if uid_str in data.get("warnings", {}):
        del data["warnings"][uid_str]
    _save_anticheat_data(data)


# ═══════════════════════════════════════════════════════════
# 인메모리 트래킹 기록
# ═══════════════════════════════════════════════════════════

def record_command(user_id: int):
    if user_id not in _command_timestamps:
        _command_timestamps[user_id] = deque(maxlen=200)
    _command_timestamps[user_id].append(time.time())


def record_kidnap(user_id: int):
    if user_id not in _kidnap_timestamps:
        _kidnap_timestamps[user_id] = deque(maxlen=200)
    _kidnap_timestamps[user_id].append(time.time())


def record_reaction(user_id: int, reaction_ms: float):
    if user_id not in _reaction_history:
        _reaction_history[user_id] = deque(maxlen=HISTORY_MAX_SIZE)
    _reaction_history[user_id].append(round(reaction_ms, 1))


# ═══════════════════════════════════════════════════════════
# ★ 반응속도 복합 분석 (v2 핵심)
# ═══════════════════════════════════════════════════════════

def analyze_reaction_pattern(user_id: int, reaction_ms: float) -> list[str]:
    """
    반응속도를 기록하고 복합적으로 분석합니다.
    
    반환: 탐지된 사유 문자열 리스트 (빈 리스트 = 정상)
    """
    record_reaction(user_id, reaction_ms)

    history = _reaction_history.get(user_id)
    if not history:
        return []

    reactions = list(history)
    detected = []

    # ── 1. 단일 반응속도: 인간 한계 미만 ──
    if reaction_ms < HUMAN_MIN_REACTION_MS:
        detected.append(
            f"인간 한계 미만 반응속도 ({reaction_ms:.0f}ms < {HUMAN_MIN_REACTION_MS}ms)"
        )

    # ── 2. 연속 인간 한계 미만 ──
    if len(reactions) >= INHUMAN_STREAK_THRESHOLD:
        recent = reactions[-INHUMAN_STREAK_THRESHOLD:]
        if all(r < HUMAN_MIN_REACTION_MS for r in recent):
            avg = statistics.mean(recent)
            detected.append(
                f"연속 {INHUMAN_STREAK_THRESHOLD}회 인간 한계 미만 "
                f"(평균 {avg:.0f}ms)"
            )

    # ── 3. 평균 반응속도 비정상 ──
    if len(reactions) >= AVG_CHECK_WINDOW:
        recent_avg = statistics.mean(reactions[-AVG_CHECK_WINDOW:])
        if recent_avg < SUSPICIOUS_AVG_MS:
            detected.append(
                f"최근 {AVG_CHECK_WINDOW}회 평균 {recent_avg:.0f}ms "
                f"(기준: {SUSPICIOUS_AVG_MS}ms 미만)"
            )

    # ── 4. 표준편차 비정상 (기계적으로 일정한 반응) ──
    if len(reactions) >= STDDEV_CHECK_WINDOW:
        recent_std = statistics.stdev(reactions[-STDDEV_CHECK_WINDOW:])
        if recent_std < MIN_STDDEV_MS:
            detected.append(
                f"최근 {STDDEV_CHECK_WINDOW}회 표준편차 {recent_std:.1f}ms "
                f"(기준: {MIN_STDDEV_MS}ms 미만 → 기계적 패턴)"
            )

    # ── 5. 등차수열 패턴 (일정한 증감) ──
    if len(reactions) >= DIFF_CHECK_WINDOW:
        recent = reactions[-DIFF_CHECK_WINDOW:]
        diffs = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
        if len(diffs) >= 3:
            diff_std = statistics.stdev(diffs)
            if diff_std < DIFF_STDDEV_THRESHOLD:
                avg_diff = statistics.mean(diffs)
                detected.append(
                    f"등차 패턴 감지 (차이값 표준편차 {diff_std:.1f}ms, "
                    f"평균 증감 {avg_diff:+.1f}ms)"
                )

    # ── 6. 주기 패턴 (두 값 번갈아 반복) ──
    if len(reactions) >= PERIOD_CHECK_WINDOW:
        recent = reactions[-PERIOD_CHECK_WINDOW:]
        even_group = [recent[i] for i in range(0, len(recent), 2)]
        odd_group = [recent[i] for i in range(1, len(recent), 2)]
        if len(even_group) >= 3 and len(odd_group) >= 3:
            even_std = statistics.stdev(even_group)
            odd_std = statistics.stdev(odd_group)
            if even_std < PERIOD_STDDEV_THRESHOLD and odd_std < PERIOD_STDDEV_THRESHOLD:
                even_avg = statistics.mean(even_group)
                odd_avg = statistics.mean(odd_group)
                if abs(even_avg - odd_avg) > 30:
                    detected.append(
                        f"주기 패턴 감지 (A={even_avg:.0f}ms ±{even_std:.1f}, "
                        f"B={odd_avg:.0f}ms ±{odd_std:.1f})"
                    )

    return detected


# ═══════════════════════════════════════════════════════════
# 빈도 탐지 (기존 유지)
# ═══════════════════════════════════════════════════════════

def check_command_frequency(user_id: int) -> tuple[bool, str]:
    if not ANTICHEAT_ENABLED:
        return False, ""
    timestamps = _command_timestamps.get(user_id)
    if not timestamps:
        return False, ""
    now = time.time()
    recent_count = sum(1 for ts in timestamps if ts > now - 60)
    if recent_count >= ANTICHEAT_COMMANDS_PER_MINUTE:
        return True, (
            f"커맨드 빈도 초과: 최근 1분간 {recent_count}회 "
            f"(제한: {ANTICHEAT_COMMANDS_PER_MINUTE}회/분)"
        )
    return False, ""


def check_kidnap_frequency(user_id: int) -> tuple[bool, str]:
    if not ANTICHEAT_ENABLED:
        return False, ""
    timestamps = _kidnap_timestamps.get(user_id)
    if not timestamps:
        return False, ""
    now = time.time()
    recent_count = sum(1 for ts in timestamps if ts > now - 3600)
    if recent_count >= ANTICHEAT_KIDNAPS_PER_HOUR:
        return True, (
            f"시간당 납치 빈도 초과: 최근 1시간 {recent_count}회 "
            f"(제한: {ANTICHEAT_KIDNAPS_PER_HOUR}회/시간)"
        )
    return False, ""


# ═══════════════════════════════════════════════════════════
# ★ 종합 검사 (v2 — 반응속도 복합 분석 통합)
# ═══════════════════════════════════════════════════════════

async def run_anticheat_checks(
    user_id: int,
    username: str,
    interaction: discord.Interaction | None = None,
    check_type: str = "command",
    reaction_ms: float | None = None,
) -> tuple[bool, str | None]:
    """
    종합 안티치트 검사를 수행합니다.

    반환: (통과 여부, 차단 사유 또는 None)
    """
    if not ANTICHEAT_ENABLED:
        return True, None

    if is_auto_banned(user_id):
        return False, "안티치트에 의해 자동 차단된 계정입니다."

    record_command(user_id)

    if check_type == "kidnap":
        record_kidnap(user_id)

    # ── 탐지 결과 수집 ──
    detections: list[tuple[str, str]] = []

    # 1. ★ 반응속도 복합 분석 (v2)
    if reaction_ms is not None:
        reaction_flags = analyze_reaction_pattern(user_id, reaction_ms)
        for flag in reaction_flags:
            detections.append(("reaction_pattern", flag))

    # 2. 커맨드 빈도
    suspicious, reason = check_command_frequency(user_id)
    if suspicious:
        detections.append(("command_frequency", reason))

    # 3. 납치 빈도
    if check_type == "kidnap":
        suspicious, reason = check_kidnap_frequency(user_id)
        if suspicious:
            detections.append(("kidnap_frequency", reason))

    if not detections:
        return True, None

    # ── 경고 처리 (중복 방지 포함) ──
    data = _load_anticheat_data()
    uid_str = str(user_id)
    existing_warnings = data.get("warnings", {}).get(uid_str, [])
    now = datetime.now(timezone.utc)

    warnings_added = 0

    for detect_type, detect_reason in detections:
        # 최근 1분 내 같은 종류 경고 중복 방지
        duplicate = False
        for w in existing_warnings:
            try:
                w_time = datetime.fromisoformat(w["timestamp"])
                w_type = w.get("details", {}).get("type", "")
                if w_type == detect_type and (now - w_time).total_seconds() < 60:
                    duplicate = True
                    break
            except (ValueError, KeyError):
                continue

        if duplicate:
            continue

        details = {
            "type": detect_type,
            "guild_id": str(interaction.guild_id) if interaction and interaction.guild else "DM",
            "guild_name": interaction.guild.name if interaction and interaction.guild else "DM",
            "channel_id": str(interaction.channel_id) if interaction else "unknown",
            "channel_name": (
                interaction.channel.name
                if interaction and hasattr(interaction.channel, "name")
                else "unknown"
            ),
        }

        warning_count, auto_banned = add_warning(user_id, detect_reason, details)

        if warning_count < 0:
            return False, "안티치트에 의해 자동 차단된 계정입니다."

        warnings_added += 1

        # 웹훅 전송
        asyncio.create_task(
            _send_anticheat_webhook(
                user_id=user_id,
                username=username,
                reason=detect_reason,
                warning_count=warning_count,
                auto_banned=auto_banned,
                details=details,
            )
        )

        if auto_banned:
            await _apply_auto_ban(user_id, username, detect_reason, warning_count)
            return False, (
                f"매크로/자동화 의심으로 자동 영구차단되었습니다. "
                f"(경고 {warning_count}회 누적)"
            )

    # 경고가 추가되었으면 유저에게 알림
    if warnings_added > 0 and interaction:
        current_count = get_warning_count(user_id)
        try:
            warning_embed = discord.Embed(
                title="⚠️ 비정상 플레이 감지",
                description=(
                    f"비정상적인 플레이 패턴이 감지되었습니다.\n"
                    f"현재 경고: **{current_count}회** / {ANTICHEAT_MAX_WARNINGS}회\n\n"
                    f"경고가 **{ANTICHEAT_MAX_WARNINGS}회** 누적되면 자동으로 영구차단됩니다.\n"
                    f"경고는 {ANTICHEAT_WARNING_DECAY_DAYS}일 후 자동으로 감소합니다.\n\n"
                    f"감지 사유: {detections[0][1]}"
                ),
                color=COLOR_WARNING,
            )
            warning_embed.set_footer(text="정상적인 플레이를 부탁드립니다.")

            if interaction.response.is_done():
                await interaction.followup.send(embed=warning_embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=warning_embed, ephemeral=True)
        except Exception:
            pass

    return True, None


# ═══════════════════════════════════════════════════════════
# kidnap.py 호환 래퍼
# ═══════════════════════════════════════════════════════════

def check_reaction_for_kidnap(udata: dict, reaction_ms: float) -> tuple[bool, str]:
    """
    kidnap.py의 _anticheat_check 대체 함수.
    udata의 user_id를 사용하여 반응속도 패턴을 분석합니다.

    반환: (통과 여부, 메시지)
    - (True, "")       → 정상
    - (True, "⚠️ ...") → 경고 (플레이 허용)
    - (False, "🚫 ...") → 차단 (플레이 거부)
    """
    if not ANTICHEAT_ENABLED:
        return True, ""

    user_id = udata.get("user_id", 0)
    if not user_id:
        return True, ""

    # 이미 자동차단된 유저
    if is_auto_banned(user_id):
        return False, "🚫 안티치트에 의해 차단된 계정입니다."

    # 반응속도 복합 분석
    flags = analyze_reaction_pattern(user_id, reaction_ms)

    if not flags:
        return True, ""

    # 경고 추가 (중복 방지: 1분 내 같은 유형)
    data = _load_anticheat_data()
    uid_str = str(user_id)
    existing = data.get("warnings", {}).get(uid_str, [])
    now = datetime.now(timezone.utc)

    actually_added = 0
    for flag in flags:
        duplicate = False
        for w in existing:
            try:
                w_time = datetime.fromisoformat(w["timestamp"])
                if (now - w_time).total_seconds() < 60 and "reaction" in w.get("details", {}).get("type", ""):
                    duplicate = True
                    break
            except (ValueError, KeyError):
                continue
        if not duplicate:
            warning_count, auto_banned = add_warning(
                user_id, flag, {"type": "reaction_pattern"}
            )
            actually_added += 1

            if auto_banned:
                return False, (
                    f"🚫 **매크로 사용이 감지되어 자동 차단되었습니다.**\n"
                    f"감지 사유: {flag}\n"
                    f"누적 경고: {warning_count}/{ANTICHEAT_MAX_WARNINGS}"
                )

    if actually_added == 0:
        return True, ""

    current_count = get_warning_count(user_id)
    return True, (
        f"⚠️ 비정상 플레이 패턴 감지 "
        f"({current_count}/{ANTICHEAT_MAX_WARNINGS})\n"
        f"사유: {flags[0]}"
    )


# ═══════════════════════════════════════════════════════════
# 웹훅 전송
# ═══════════════════════════════════════════════════════════

async def _send_anticheat_webhook(
    user_id: int,
    username: str,
    reason: str,
    warning_count: int,
    auto_banned: bool,
    details: dict,
):
    if not ANTICHEAT_WEBHOOK_URL:
        return

    now_kst = datetime.now(KST)
    time_str = now_kst.strftime("%Y-%m-%d %H:%M:%S KST")

    if auto_banned:
        title = "🚨 안티치트 자동 영구차단"
        color = COLOR_ERROR
        status_text = f"**🔴 자동 영구차단 (경고 {warning_count}회 누적)**"
    else:
        title = "⚠️ 안티치트 경고 발생"
        color = COLOR_WARNING
        status_text = f"**🟡 경고 {warning_count}회 / {ANTICHEAT_MAX_WARNINGS}회**"

    embed = discord.Embed(
        title=title, description=status_text,
        color=color, timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="👤 유저 정보",
        value=f"닉네임: **{username}**\nID: `{user_id}`",
        inline=False,
    )
    embed.add_field(
        name="📍 발생 위치",
        value=(
            f"서버: **{details.get('guild_name', '???')}**\n"
            f"채널: **{details.get('channel_name', '???')}**"
        ),
        inline=False,
    )
    embed.add_field(name="🔍 탐지 사유", value=reason, inline=False)
    embed.add_field(name="🕐 탐지 시각", value=time_str, inline=True)
    embed.add_field(
        name="📊 경고 현황",
        value=f"{warning_count} / {ANTICHEAT_MAX_WARNINGS}",
        inline=True,
    )

    try:
        async with aiohttp.ClientSession() as session:
            webhook = discord.Webhook.from_url(ANTICHEAT_WEBHOOK_URL, session=session)
            await webhook.send(embed=embed, username="🛡️ 안티치트 시스템", wait=True)
    except Exception as e:
        print(f"[ANTICHEAT] 웹훅 전송 실패: {e}")


# ═══════════════════════════════════════════════════════════
# 자동 차단 적용
# ═══════════════════════════════════════════════════════════

async def _apply_auto_ban(user_id: int, username: str, reason: str, warning_count: int):
    from utils.checks import load_bans, save_bans

    bans = load_bans()
    uid_str = str(user_id)
    if uid_str in bans:
        return

    bans[uid_str] = {
        "user": username,
        "reason": f"[안티치트 자동차단] 경고 {warning_count}회 누적 — {reason}",
        "banned_by": "AntiCheat System",
        "banned_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "expire_at": 0,
    }
    save_bans(bans)


# ═══════════════════════════════════════════════════════════
# 유틸리티 (관리자 조회용)
# ═══════════════════════════════════════════════════════════

def get_anticheat_status(user_id: int) -> dict:
    warnings = get_user_warnings(user_id)
    banned = is_auto_banned(user_id)

    now = time.time()
    cmd_ts = _command_timestamps.get(user_id, deque())
    cmds_last_min = sum(1 for ts in cmd_ts if ts > now - 60)

    kidnap_ts = _kidnap_timestamps.get(user_id, deque())
    kidnaps_last_hour = sum(1 for ts in kidnap_ts if ts > now - 3600)

    reaction_hist = list(_reaction_history.get(user_id, deque()))
    recent_reactions = reaction_hist[-10:] if reaction_hist else []

    # ★ 통계 정보 추가
    stats_info = {}
    if len(recent_reactions) >= 3:
        stats_info["avg_ms"] = round(statistics.mean(recent_reactions), 1)
        stats_info["stddev_ms"] = round(statistics.stdev(recent_reactions), 1)
        stats_info["min_ms"] = min(recent_reactions)
        stats_info["max_ms"] = max(recent_reactions)

    return {
        "user_id": user_id,
        "warning_count": len(warnings),
        "warnings": warnings,
        "auto_banned": banned,
        "commands_last_minute": cmds_last_min,
        "kidnaps_last_hour": kidnaps_last_hour,
        "recent_reactions_ms": recent_reactions,
        "reaction_stats": stats_info,
    }


def format_anticheat_embed(member_or_id, status_or_username=None) -> discord.Embed:
    if isinstance(member_or_id, (discord.Member, discord.User)):
        user_id = member_or_id.id
        username = member_or_id.display_name
        status = status_or_username if isinstance(status_or_username, dict) else get_anticheat_status(user_id)
    elif isinstance(member_or_id, int):
        user_id = member_or_id
        username = status_or_username if isinstance(status_or_username, str) else str(member_or_id)
        status = get_anticheat_status(user_id)
    else:
        user_id = int(member_or_id) if str(member_or_id).isdigit() else 0
        username = str(status_or_username) if status_or_username else str(member_or_id)
        status = get_anticheat_status(user_id)

    if status["auto_banned"]:
        embed = discord.Embed(
            title=f"🛡️ 안티치트 상태 — {username}",
            description="**🔴 자동 영구차단 상태**",
            color=COLOR_ERROR,
        )
    elif status["warning_count"] > 0:
        embed = discord.Embed(
            title=f"🛡️ 안티치트 상태 — {username}",
            description=f"**🟡 경고 {status['warning_count']}회 / {ANTICHEAT_MAX_WARNINGS}회**",
            color=COLOR_WARNING,
        )
    else:
        embed = discord.Embed(
            title=f"🛡️ 안티치트 상태 — {username}",
            description="**🟢 정상**",
            color=0x57F287,
        )

    embed.add_field(
        name="📊 실시간 활동",
        value=(
            f"최근 1분 커맨드: **{status['commands_last_minute']}회** / {ANTICHEAT_COMMANDS_PER_MINUTE}\n"
            f"최근 1시간 납치: **{status['kidnaps_last_hour']}회** / {ANTICHEAT_KIDNAPS_PER_HOUR}"
        ),
        inline=False,
    )

    if status["recent_reactions_ms"]:
        reactions_str = ", ".join([f"{ms}ms" for ms in status["recent_reactions_ms"]])
        embed.add_field(name="⏱️ 최근 반응속도", value=f"`{reactions_str}`", inline=False)

        # ★ 통계 표시
        rs = status.get("reaction_stats", {})
        if rs:
            embed.add_field(
                name="📈 반응속도 통계",
                value=(
                    f"평균: **{rs.get('avg_ms', '?')}ms** | "
                    f"표준편차: **{rs.get('stddev_ms', '?')}ms**\n"
                    f"최소: **{rs.get('min_ms', '?')}ms** | "
                    f"최대: **{rs.get('max_ms', '?')}ms**"
                ),
                inline=False,
            )

    if status["warnings"]:
        warn_lines = []
        for i, w in enumerate(status["warnings"][-5:], 1):
            try:
                w_time = datetime.fromisoformat(w["timestamp"]).astimezone(KST)
                time_str = w_time.strftime("%m/%d %H:%M")
            except (ValueError, KeyError):
                time_str = "???"
            warn_lines.append(f"`{i}.` [{time_str}] {w.get('reason', '???')[:60]}")
        embed.add_field(
            name="⚠️ 최근 경고 (최대 5개)",
            value="\n".join(warn_lines),
            inline=False,
        )

    embed.set_footer(
        text=f"경고는 {ANTICHEAT_WARNING_DECAY_DAYS}일 후 자동 감소 | ID: {user_id}"
    )
    return embed
