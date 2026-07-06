# kayoko_ai/embedding.py
"""
Gemini 임베딩 API 래퍼 + 순수 파이썬 코사인 유사도.

- text-embedding-004 (무료 티어 사용 가능, 768차원)
- 기존 GeminiKeyRotator의 API 키 풀을 공유하여 임베딩 호출에도 로테이션 적용
- numpy 의존성 없이 순수 파이썬 math.sqrt + zip으로 코사인 유사도 계산
"""

from __future__ import annotations

import asyncio
import math
from typing import Sequence

import google.generativeai as genai

from config import EMBEDDING_MODEL, EMBEDDING_DIM


# ─────────────────────────────────────────────────────
# 코사인 유사도 (순수 파이썬)
# ─────────────────────────────────────────────────────

def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """두 벡터의 코사인 유사도. 빈/길이 불일치 벡터는 0 반환."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def top_k_similar(
    query_vec: Sequence[float],
    candidates: list[tuple[str, list[float], dict]],
    k: int = 3,
    min_sim: float = 0.0,
) -> list[tuple[float, str, dict]]:
    """
    후보 리스트 [(text, vector, meta), ...] 중에서
    쿼리 벡터와 가장 유사한 상위 k개를 반환.
    반환: [(similarity, text, meta), ...] (내림차순)
    """
    scored: list[tuple[float, str, dict]] = []
    for text, vec, meta in candidates:
        sim = cosine_similarity(query_vec, vec)
        if sim >= min_sim:
            scored.append((sim, text, meta))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:k]


# ─────────────────────────────────────────────────────
# 임베딩 클라이언트 (키 로테이터 공유)
# ─────────────────────────────────────────────────────

class EmbeddingClient:
    """
    Gemini 임베딩 API 래퍼.

    - main.py의 GeminiKeyRotator를 주입받아 API 키를 공유합니다.
    - 호출 직전에 rotator의 현재 키로 genai.configure를 갱신합니다.
      (생성 모델과 임베딩이 같은 키 풀을 쓰므로 안전)
    - 실패 시 다음 활성 키로 자동 로테이션.
    """

    def __init__(self, rotator):
        self.rotator = rotator
        self.model = EMBEDDING_MODEL
        self.dim = EMBEDDING_DIM

    def _embed_sync(self, text: str, task_type: str) -> list[float] | None:
        """동기 임베딩 호출."""
        text = (text or "").strip()
        if not text:
            return None

        # 현재 로테이터 키로 갱신
        try:
            key = self.rotator.api_keys[self.rotator.current_index]
            genai.configure(api_key=key)
        except Exception:
            return None

        try:
            result = genai.embed_content(
                model=self.model,
                content=text[:8000],  # 안전한 길이 제한
                task_type=task_type,
            )
            # 반환 형식: {"embedding": [...]}
            vec = result.get("embedding") if isinstance(result, dict) else None
            if vec is None:
                # 일부 SDK 버전은 객체로 반환
                vec = getattr(result, "embedding", None)
            return list(vec) if vec else None
        except Exception as e:
            # 키 문제일 가능성 → 로테이터에 보고
            try:
                self.rotator._handle_api_error(e)
                self.rotator._rotate_to_next_key()
            except Exception:
                pass
            return None

    async def embed_query(self, text: str) -> list[float] | None:
        """질의용 임베딩 (RAG 검색 시 사용)."""
        return await asyncio.to_thread(
            self._embed_sync, text, "RETRIEVAL_QUERY"
        )

    async def embed_document(self, text: str) -> list[float] | None:
        """저장용 임베딩 (지식/기억 저장 시 사용)."""
        return await asyncio.to_thread(
            self._embed_sync, text, "RETRIEVAL_DOCUMENT"
        )

    async def embed_batch_documents(
        self, texts: list[str], concurrency: int = 4
    ) -> list[list[float] | None]:
        """
        다수 문서를 병렬 임베딩. 지식베이스 초기 색인용.
        세마포어로 동시성 제한.
        """
        sem = asyncio.Semaphore(concurrency)

        async def _one(t: str):
            async with sem:
                return await self.embed_document(t)

        return await asyncio.gather(*[_one(t) for t in texts])
