# kayoko_ai/memory.py
"""
뉴럴 코어 — 단기 / 장기 / 집단 기억 (Tri-Tier Memory Architecture).

- 단기 기억: 유저별 최근 30개 메시지 쌍, 프롬프트에 최근 10개 직접 주입.
- 장기 기억: 10회 대화마다 요약 → 임베딩 → 벡터 저장.
  중복 유사도 ≥ 0.85는 저장하지 않음. 회상은 top-3, min_sim ≥ 0.55.
- 집단 기억: 채널별 최근 10개 메시지(다른 유저 포함) — 분위기 파악용.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from kayoko_ai.embedding import EmbeddingClient, cosine_similarity, top_k_similar
from config import (
    SHORT_TERM_FILE,
    LONG_TERM_FILE,
    AMBIENT_FILE,
    SHORT_TERM_MAX,
    SHORT_TERM_INJECT,
    LONG_TERM_FORM_EVERY,
    LONG_TERM_RECALL_TOP_K,
    LONG_TERM_RECALL_MIN_SIM,
    LONG_TERM_DEDUP_THRESHOLD,
    AMBIENT_CONTEXT_MAX,
)


# ─────────────────────────────────────────────────────
# 디스크 I/O 유틸 (비동기 안전)
# ─────────────────────────────────────────────────────

_io_lock = asyncio.Lock()


def _load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data: Any):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


# ═════════════════════════════════════════════════════
# 단기 기억
# ═════════════════════════════════════════════════════

class ShortTermMemory:
    """유저별 최근 대화 N개 보관."""

    def __init__(self):
        self.path = SHORT_TERM_FILE
        # { user_id: [ {"role": "user"|"model", "text": str, "ts": float}, ... ] }
        self.data: dict[str, list[dict]] = _load_json(self.path, {})

    def get_recent(self, user_id: int, n: int = SHORT_TERM_INJECT) -> list[dict]:
        uid = str(user_id)
        msgs = self.data.get(uid, [])
        return msgs[-n:]

    def append(self, user_id: int, role: str, text: str):
        uid = str(user_id)
        msgs = self.data.setdefault(uid, [])
        msgs.append({"role": role, "text": text, "ts": time.time()})
        # 최대 길이 초과 시 앞부분 삭제
        if len(msgs) > SHORT_TERM_MAX:
            self.data[uid] = msgs[-SHORT_TERM_MAX:]

    def count_user_turns(self, user_id: int) -> int:
        """유저의 메시지(role=user) 개수 — 장기기억 형성 트리거에 사용."""
        uid = str(user_id)
        return sum(1 for m in self.data.get(uid, []) if m["role"] == "user")

    async def save(self):
        async with _io_lock:
            await asyncio.to_thread(_save_json, self.path, self.data)


# ═════════════════════════════════════════════════════
# 장기 기억 (RAG)
# ═════════════════════════════════════════════════════

class LongTermMemory:
    """
    유저별 의미 단위 '에피소드' 저장 + 벡터 검색.
    구조: { user_id: [ {"text": 요약, "vector": [...], "ts": float}, ... ] }
    """

    def __init__(self, embed_client: EmbeddingClient):
        self.embed = embed_client
        self.path = LONG_TERM_FILE
        self.data: dict[str, list[dict]] = _load_json(self.path, {})

    async def save(self):
        async with _io_lock:
            await asyncio.to_thread(_save_json, self.path, self.data)

    async def recall(self, user_id: int, query: str) -> list[dict]:
        """질의와 관련된 장기 기억 상위 K개를 회상."""
        uid = str(user_id)
        episodes = self.data.get(uid, [])
        if not episodes:
            return []

        qvec = await self.embed.embed_query(query)
        if qvec is None:
            return []

        candidates = [
            (e["text"], e["vector"], {"ts": e.get("ts", 0)})
            for e in episodes
            if e.get("vector")
        ]
        hits = top_k_similar(
            qvec, candidates,
            k=LONG_TERM_RECALL_TOP_K,
            min_sim=LONG_TERM_RECALL_MIN_SIM,
        )
        return [{"sim": round(s, 3), "text": t, **m} for s, t, m in hits]

    async def _is_duplicate(self, user_id: int, vec: list[float]) -> bool:
        uid = str(user_id)
        for e in self.data.get(uid, []):
            if not e.get("vector"):
                continue
            if cosine_similarity(vec, e["vector"]) >= LONG_TERM_DEDUP_THRESHOLD:
                return True
        return False

    async def add_episode(self, user_id: int, summary_text: str):
        """요약 텍스트를 임베딩하여 에피소드로 저장. 중복 시 스킵."""
        summary_text = (summary_text or "").strip()
        if not summary_text:
            return False

        vec = await self.embed.embed_document(summary_text)
        if vec is None:
            return False

        if await self._is_duplicate(user_id, vec):
            return False

        uid = str(user_id)
        self.data.setdefault(uid, []).append({
            "text": summary_text,
            "vector": vec,
            "ts": time.time(),
        })
        await self.save()
        return True


# ═════════════════════════════════════════════════════
# 집단 기억 (채널 분위기)
# ═════════════════════════════════════════════════════

class AmbientMemory:
    """
    채널별 최근 메시지 (다른 유저 포함, 봇 메시지 제외).
    봇이 호출되었을 때 분위기 파악용으로 함께 주입.
    """

    def __init__(self):
        self.path = AMBIENT_FILE
        # { channel_id: [ {"author": str, "text": str, "ts": float}, ... ] }
        self.data: dict[str, list[dict]] = _load_json(self.path, {})

    def add(self, channel_id: int, author: str, text: str):
        cid = str(channel_id)
        msgs = self.data.setdefault(cid, [])
        msgs.append({"author": author, "text": text, "ts": time.time()})
        if len(msgs) > AMBIENT_CONTEXT_MAX:
            self.data[cid] = msgs[-AMBIENT_CONTEXT_MAX:]

    def get(self, channel_id: int) -> list[dict]:
        return self.data.get(str(channel_id), [])

    async def save(self):
        async with _io_lock:
            await asyncio.to_thread(_save_json, self.path, self.data)


# ═════════════════════════════════════════════════════
# 뉴럴 코어 (통합)
# ═════════════════════════════════════════════════════

class NeuralCore:
    def __init__(self, embed_client: EmbeddingClient):
        self.short = ShortTermMemory()
        self.long = LongTermMemory(embed_client)
        self.ambient = AmbientMemory()
        self._form_threshold = LONG_TERM_FORM_EVERY

    def should_form_long_term(self, user_id: int) -> bool:
        """유저 발화가 N의 배수에 도달하면 장기기억 형성."""
        n = self.short.count_user_turns(user_id)
        return n > 0 and n % self._form_threshold == 0

    async def persist(self):
        await self.short.save()
        await self.ambient.save()
