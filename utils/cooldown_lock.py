# utils/cooldown_lock.py
"""
글로벌 커맨드 동시 실행 방지 (유저당 1개 커맨드만 실행 가능)
자동 만료 기능 포함 — 잠금 후 일정 시간 경과 시 자동 해제
"""

import time
import discord
from config import COLOR_WARNING, BOT_ICON_URL

# ── 유저별 현재 실행 중인 커맨드 {user_id: (command_name, timestamp)} ──
_active_commands: dict[int, tuple[str, float]] = {}

# ── 잠금 자동 만료 시간 (초) ──
LOCK_TIMEOUT = 120  # 2분 — 납치 탐색(20초) + 버튼 대기(20초) + 여유

# ── 커맨드 한글명 매핑 ──
COMMAND_DISPLAY_NAMES = {
    "kidnap": "납치",
    "battle": "전투",
    "weekly_boss": "주간보스",
    "labyrinth": "미궁",
    "gamble": "도박",
    "shop": "상점",
    "skill_invest": "스킬투자",
    "region_move": "지역이동",
    "region_unlock": "지역해금",
    "adopt": "냥이분양",
    "transfer": "송금",
}


def _cleanup_expired():
    """만료된 잠금 자동 제거"""
    now = time.monotonic()
    expired = [
        uid for uid, (cmd, ts) in _active_commands.items()
        if now - ts > LOCK_TIMEOUT
    ]
    for uid in expired:
        _active_commands.pop(uid, None)


def is_locked(user_id: int) -> bool:
    """유저가 현재 다른 커맨드를 실행 중인지 확인"""
    _cleanup_expired()
    return user_id in _active_commands


def get_active_command(user_id: int) -> str | None:
    """현재 실행 중인 커맨드명 반환"""
    _cleanup_expired()
    entry = _active_commands.get(user_id)
    return entry[0] if entry else None


def acquire_lock(user_id: int, command_name: str) -> bool:
    """
    잠금 획득 시도.
    성공하면 True, 이미 다른 커맨드 실행 중이면 False.
    만료된 잠금은 자동 해제 후 재시도.
    """
    _cleanup_expired()
    if user_id in _active_commands:
        return False
    _active_commands[user_id] = (command_name, time.monotonic())
    return True


def release_lock(user_id: int):
    """잠금 해제"""
    _active_commands.pop(user_id, None)


def build_locked_embed(user_id: int) -> discord.Embed:
    """이미 실행 중일 때 보여줄 임베드 생성"""
    _cleanup_expired()
    entry = _active_commands.get(user_id)
    if entry:
        active = entry[0]
        elapsed = time.monotonic() - entry[1]
        remaining = max(0, LOCK_TIMEOUT - elapsed)
    else:
        active = "알 수 없음"
        remaining = 0

    display = COMMAND_DISPLAY_NAMES.get(active, active)
    embed = discord.Embed(
        title="⏳ 다른 작업 진행 중",
        description=(
            f"현재 **{display}** 진행 중입니다.\n"
            f"완료될 때까지 다른 커맨드를 사용할 수 없습니다.\n"
            f"자동 해제까지 약 **{remaining:.0f}초**"
        ),
        color=COLOR_WARNING,
    )
    embed.set_footer(text="카요코 봇", icon_url=BOT_ICON_URL)
    return embed
