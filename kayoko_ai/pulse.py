# kayoko_ai/pulse.py
"""
다이나믹 펄스 — 자연스러운 분할 송신.

- 응답을 문장 단위로 나누고, 길면 추가 분할
- 각 청크 사이에 (길이/속도 기반) 자연스러운 지연
- typing 인디케이터 표시
- 어댑티브 리플렉스에 의한 취소(CancelledError) 안전하게 전파
"""

from __future__ import annotations

import asyncio
import random
import re

import discord

from config import (
    PULSE_CHARS_PER_SEC,
    PULSE_MIN_DELAY,
    PULSE_MAX_DELAY,
    PULSE_SPLIT_MAX_LEN,
)


_SENT_SPLIT = re.compile(r"(?<=[\.!?。…\?！])\s+|(?<=[\n])")


def split_into_chunks(text: str, max_len: int = PULSE_SPLIT_MAX_LEN) -> list[str]:
    """
    응답을 자연스러운 청크로 분할.
    1) 문장 부호 기준 1차 분할
    2) 길이 초과 시 공백 기준 2차 분할 (단어 보존)
    3) 빈 청크 제거
    """
    text = text.strip()
    if not text:
        return []

    primary = [p.strip() for p in _SENT_SPLIT.split(text) if p and p.strip()]
    if not primary:
        primary = [text]

    chunks: list[str] = []
    for sent in primary:
        if len(sent) <= max_len:
            chunks.append(sent)
            continue
        # 너무 긴 문장 → 어절 단위 잘라붙임
        buf = ""
        for word in sent.split(" "):
            if not word:
                continue
            cand = (buf + " " + word).strip() if buf else word
            if len(cand) > max_len and buf:
                chunks.append(buf)
                buf = word
            else:
                buf = cand
        if buf:
            chunks.append(buf)
    return chunks


def estimate_delay(chunk: str) -> float:
    """청크 길이 기반 자연스러운 지연 시간."""
    base = len(chunk) / max(PULSE_CHARS_PER_SEC, 1)
    # 약간의 랜덤성 (±15%)
    jitter = base * random.uniform(-0.15, 0.15)
    delay = max(PULSE_MIN_DELAY, min(PULSE_MAX_DELAY, base + jitter))
    return delay


async def send_with_pulse(
    channel: discord.abc.Messageable,
    full_text: str,
    reply_to: discord.Message | None = None,
) -> list[discord.Message]:
    """
    다이나믹 펄스로 메시지 전송. 마지막 전송 메시지 리스트 반환.
    asyncio.CancelledError가 전파되면 중단 (어댑티브 리플렉스).
    """
    chunks = split_into_chunks(full_text)
    if not chunks:
        return []

    sent: list[discord.Message] = []
    first = True

    for chunk in chunks:
        # typing 표시 + 지연
        try:
            async with channel.typing():
                await asyncio.sleep(estimate_delay(chunk))
        except asyncio.CancelledError:
            raise
        except Exception:
            # typing 실패는 무시
            await asyncio.sleep(estimate_delay(chunk))

        try:
            if first and reply_to is not None:
                msg = await reply_to.reply(chunk, mention_author=False)
            else:
                msg = await channel.send(chunk)
            sent.append(msg)
            first = False
        except asyncio.CancelledError:
            raise
        except discord.HTTPException as e:
            print(f"[Pulse] 전송 실패: {e}")
            break

    return sent
