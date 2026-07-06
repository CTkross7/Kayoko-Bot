"""
엠비언트 플로우:
- 기본적으로 직접 호출/멘션/reply에만 안정적으로 반응
- 엠비언트 반응은 매우 제한적으로만 허용
- 일반 채팅 전체를 먹지 않도록 채널/유저/메시지 조건을 강하게 검사

어댑티브 리플렉스:
- 진행 중인 응답이 있을 때 새 직접 호출이 들어오면 이전 응답 취소
- 일반 엠비언트 메시지로는 과도하게 취소하지 않도록 pipeline에서 호출 조건을 제어
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field

import discord

from config import (
    KAYOKO_TRIGGERS,
    AMBIENT_SESSION_TIMEOUT,
    REFLEX_INTERRUPT_GRACE,
)


# ─────────────────────────────────────────────────────
# 튜닝 상수
# ─────────────────────────────────────────────────────

# 직접 호출 후 이 시간 안에서만 엠비언트 후보 허용
# 기존 AMBIENT_SESSION_TIMEOUT이 300초라면 너무 깁니다.
# 여기서 한 번 더 짧게 제한합니다.
AMBIENT_SOFT_TIMEOUT = min(AMBIENT_SESSION_TIMEOUT, 45)

# 봇 답변 직후 너무 짧은 메시지는 무시
MIN_AMBIENT_CONTENT_LEN = 4

# 엠비언트 반응은 마지막 봇 답변 후 너무 오래 지나면 차단
MAX_SECONDS_AFTER_BOT_REPLY = 35

# 같은 유저가 너무 빠르게 이어 말하면 AI 호출하지 않고 무시
MIN_SECONDS_BETWEEN_USER_AMBIENT = 4

# 질문/대화 연결로 볼 수 있는 패턴
QUESTION_HINTS = (
    "?",
    "？",
    "뭐",
    "왜",
    "어떻게",
    "어케",
    "언제",
    "누구",
    "어디",
    "가능",
    "알아",
    "맞아",
    "아니",
    "그럼",
    "근데",
    "그러면",
)

# 너무 짧거나 의미 없는 리액션성 메시지 차단
LOW_SIGNAL_PATTERNS = (
    r"^ㅋ+$",
    r"^ㅎ+$",
    r"^ㅠ+$",
    r"^ㅜ+$",
    r"^ㅇㅇ$",
    r"^ㄴㄴ$",
    r"^ㄱㄱ$",
    r"^ㄷㄷ$",
    r"^ㅁㅊ$",
    r"^헐$",
    r"^와$",
    r"^오$",
)


# ─────────────────────────────────────────────────────
# 세션
# ─────────────────────────────────────────────────────

@dataclass
class Session:
    user_id: int
    channel_id: int

    # 직접 트리거가 발생한 시각
    last_activity: float = 0.0

    # 마지막 봇 메시지
    last_bot_message_id: int | None = None
    last_bot_reply_at: float = 0.0

    # 마지막 유저 엠비언트 처리 시각
    last_user_ambient_at: float = 0.0

    # 진행 중인 응답 태스크
    active_task: asyncio.Task | None = None

    def is_active(self, now: float | None = None) -> bool:
        now = now or time.time()
        if self.last_activity <= 0:
            return False
        return (now - self.last_activity) < AMBIENT_SESSION_TIMEOUT

    def is_soft_active(self, now: float | None = None) -> bool:
        now = now or time.time()
        if self.last_activity <= 0:
            return False
        return (now - self.last_activity) < AMBIENT_SOFT_TIMEOUT

    def touch(self):
        self.last_activity = time.time()

    def mark_bot_reply(self, message_id: int | None):
        self.last_bot_message_id = message_id
        self.last_bot_reply_at = time.time()


class SessionManager:
    """(user_id, channel_id) → Session"""

    def __init__(self):
        self._sessions: dict[tuple[int, int], Session] = {}

    def get(self, user_id: int, channel_id: int) -> Session:
        key = (user_id, channel_id)
        if key not in self._sessions:
            self._sessions[key] = Session(user_id=user_id, channel_id=channel_id)
        return self._sessions[key]

    def cleanup(self):
        now = time.time()
        expired = [k for k, s in self._sessions.items() if not s.is_active(now)]
        for k in expired:
            del self._sessions[k]


# ─────────────────────────────────────────────────────
# 내부 유틸
# ─────────────────────────────────────────────────────

def _normalize_trigger_text(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _strip_bot_mentions(content: str, bot_user_id: int) -> str:
    content = content.replace(f"<@{bot_user_id}>", "")
    content = content.replace(f"<@!{bot_user_id}>", "")
    return content.strip()


def _is_low_signal_message(content: str) -> bool:
    compact = re.sub(r"\s+", "", content.strip().lower())
    if not compact:
        return True

    for pattern in LOW_SIGNAL_PATTERNS:
        if re.fullmatch(pattern, compact):
            return True

    # 같은 문자 반복만 있는 경우
    if len(set(compact)) <= 2 and len(compact) <= 6:
        return True

    return False


def _has_question_or_continuation_hint(content: str) -> bool:
    compact = content.strip().lower()
    if not compact:
        return False

    if compact.endswith("?") or compact.endswith("？"):
        return True

    return any(hint in compact for hint in QUESTION_HINTS)


def _is_reply_to_bot(message: discord.Message, bot_user_id: int) -> bool:
    ref = message.reference
    if ref is None:
        return False

    resolved = getattr(ref, "resolved", None)
    if isinstance(resolved, discord.Message):
        return bool(resolved.author and resolved.author.id == bot_user_id)

    # resolved가 비어있어도 멘션이 같이 있으면 직접 호출로 인정
    return any(u.id == bot_user_id for u in message.mentions)


# ─────────────────────────────────────────────────────
# 트리거 판별
# ─────────────────────────────────────────────────────

def detect_trigger(message: discord.Message, bot_user_id: int) -> tuple[bool, str]:
    """
    반환: (직접 트리거 여부, 정제된 쿼리)

    직접 트리거:
      1. 봇 멘션
      2. 봇 메시지에 reply
      3. KAYOKO_TRIGGERS로 시작
    """
    content = (message.content or "").strip()
    if not content:
        return False, ""

    # 1) 봇 멘션
    if any(u.id == bot_user_id for u in message.mentions):
        query = _strip_bot_mentions(content, bot_user_id)
        return True, query or content

    # 2) 봇에 대한 reply
    if _is_reply_to_bot(message, bot_user_id):
        return True, content

    # 3) 키워드 트리거
    normalized_content = _normalize_trigger_text(content)

    for kw in KAYOKO_TRIGGERS:
        kw_raw = str(kw).strip()
        if not kw_raw:
            continue

        # 원문 startswith
        if content.startswith(kw_raw):
            query = content[len(kw_raw):].strip()
            return True, query

        # 공백 제거/소문자 기준 startswith
        normalized_kw = _normalize_trigger_text(kw_raw)
        if normalized_kw and normalized_content.startswith(normalized_kw):
            # 이 경우는 정확한 slice가 애매하므로 원문에서 첫 공백 뒤를 우선 사용
            parts = content.split(maxsplit=1)
            query = parts[1].strip() if len(parts) > 1 else ""
            return True, query

    return False, ""


def is_ambient_trigger(
    message: discord.Message,
    session: Session,
    bot_user_id: int,
) -> bool:
    """
    간접 엠비언트 트리거.

    매우 제한적으로만 True:
      - 이미 직접 호출로 열린 세션이어야 함
      - 마지막 봇 답변이 있어야 함
      - 마지막 봇 답변 후 짧은 시간 안이어야 함
      - 너무 짧은 리액션/잡담은 무시
      - 질문/대화 연결 힌트가 있어야 함
      - 유저 엠비언트 쿨타임 통과
    """
    if message.author.bot:
        return False

    content = (message.content or "").strip()
    if len(content) < MIN_AMBIENT_CONTENT_LEN:
        return False

    if _is_low_signal_message(content):
        return False

    now = time.time()

    # 직접 호출로 열린 세션이 아니면 차단
    if not session.is_soft_active(now):
        return False

    # 카요코가 이 세션에서 말한 적 없으면 차단
    if session.last_bot_message_id is None:
        return False

    # 마지막 봇 답변 이후 너무 오래 지나면 차단
    if session.last_bot_reply_at <= 0:
        return False

    if now - session.last_bot_reply_at > MAX_SECONDS_AFTER_BOT_REPLY:
        return False

    # 같은 유저의 엠비언트 과다 반응 차단
    if now - session.last_user_ambient_at < MIN_SECONDS_BETWEEN_USER_AMBIENT:
        return False

    # 질문/연결 힌트 없으면 차단
    if not _has_question_or_continuation_hint(content):
        return False

    session.last_user_ambient_at = now
    return True


# ─────────────────────────────────────────────────────
# 어댑티브 리플렉스
# ─────────────────────────────────────────────────────

class AdaptiveReflex:
    """
    진행 중인 응답 태스크 취소.
    pipeline에서 직접 호출일 때만 주로 interrupt하도록 쓰는 것을 권장.
    """

    @staticmethod
    async def interrupt(session: Session):
        task = session.active_task
        if task and not task.done():
            await asyncio.sleep(REFLEX_INTERRUPT_GRACE)
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

    @staticmethod
    def attach(session: Session, task: asyncio.Task):
        session.active_task = task