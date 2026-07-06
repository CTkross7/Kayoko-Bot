# kayoko_ai/knowledge_base.py
"""
블루 아카이브 세계관 지식베이스 (RAG).

- data/kayoko_knowledge.json에서 텍스트 엔트리를 로드
- 첫 실행 시 모든 엔트리를 임베딩하여 벡터 캐시(.vec.json) 생성
- 이후 실행은 캐시를 재사용 (요금 0원 전제 — 1회 색인 후 재사용)
- 질의 시 코사인 유사도 상위 K개 반환
"""

from __future__ import annotations

import json
import os
from typing import Any

from kayoko_ai.embedding import EmbeddingClient, top_k_similar
from config import (
    KNOWLEDGE_FILE,
    KNOWLEDGE_RECALL_TOP_K,
    KNOWLEDGE_MIN_SIM,
)


class KnowledgeBase:
    def __init__(self, embed_client: EmbeddingClient):
        self.embed = embed_client
        self.path = KNOWLEDGE_FILE
        self.cache_path = KNOWLEDGE_FILE.replace(".json", ".vec.json")
        # entries: [{"id": str, "category": str, "text": str, "vector": [...]}]
        self.entries: list[dict[str, Any]] = []
        self.ready = False

    # ─────────────────────────────────────────────
    # 로딩 / 색인
    # ─────────────────────────────────────────────

    def _load_raw(self) -> list[dict[str, Any]]:
        if not os.path.exists(self.path):
            print(f"[KB] 지식 파일 없음: {self.path}")
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("entries", [])
        return data

    def _load_cache(self) -> list[dict[str, Any]] | None:
        if not os.path.exists(self.cache_path):
            return None
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[KB] 캐시 로드 실패: {e}")
            return None

    def _save_cache(self):
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.entries, f, ensure_ascii=False)
        except Exception as e:
            print(f"[KB] 캐시 저장 실패: {e}")

    async def build_index(self, force: bool = False):
        """
        지식베이스를 색인합니다.
        - 캐시가 있고 항목 수가 일치하면 캐시 재사용
        - 그렇지 않으면 전체 재임베딩 (force=True도 동일)
        """
        raw = self._load_raw()
        if not raw:
            print("[KB] 지식 엔트리 0개 — 색인 스킵")
            self.ready = True
            return

        if not force:
            cache = self._load_cache()
            if cache and len(cache) == len(raw):
                # 텍스트 일치 검증 (간단)
                same = all(
                    c.get("text") == r.get("text") for c, r in zip(cache, raw)
                )
                if same:
                    self.entries = cache
                    self.ready = True
                    print(f"[KB] 캐시에서 {len(cache)}개 엔트리 로드")
                    return

        print(f"[KB] 지식 {len(raw)}개 임베딩 시작...")
        texts = [e["text"] for e in raw]
        vectors = await self.embed.embed_batch_documents(texts, concurrency=4)

        self.entries = []
        miss = 0
        for entry, vec in zip(raw, vectors):
            if vec is None:
                miss += 1
                continue
            self.entries.append({
                "id": entry.get("id", ""),
                "category": entry.get("category", ""),
                "text": entry["text"],
                "vector": vec,
            })

        self._save_cache()
        self.ready = True
        print(f"[KB] 색인 완료: {len(self.entries)}개 (실패 {miss}개)")

    # ─────────────────────────────────────────────
    # 검색
    # ─────────────────────────────────────────────

    async def search(
        self,
        query: str,
        top_k: int = KNOWLEDGE_RECALL_TOP_K,
        min_sim: float = KNOWLEDGE_MIN_SIM,
    ) -> list[dict[str, Any]]:
        """질의와 관련된 지식 상위 K개 반환."""
        if not self.entries:
            return []
        qvec = await self.embed.embed_query(query)
        if qvec is None:
            return []

        candidates = [
            (e["text"], e["vector"], {"id": e.get("id"), "category": e.get("category")})
            for e in self.entries
        ]
        hits = top_k_similar(qvec, candidates, k=top_k, min_sim=min_sim)
        return [
            {"sim": round(sim, 3), "text": text, **meta}
            for sim, text, meta in hits
        ]
