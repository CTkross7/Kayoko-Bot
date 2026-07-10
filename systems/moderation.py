# systems/moderation.py
# ──────────────────────────────────────────────────────────
# 카요코 AI 대화 모더레이션
#  · 로컬 키워드 pre-check → API 호출 최소화
#  · 부적절 발화 감지 시 랜덤 거부 문구 (템플릿 리스트 기반)
#  · 반복 위반 시 AI 호출 없이 고정 문구로 대화 중단
#  · 카테고리/키워드/템플릿은 kayoko_settings.json에서 관리 (gitignore 대상)
# ──────────────────────────────────────────────────────────

from __future__ import annotations

import json
import os
import random
import time
from typing import Any


DEFAULT_REFUSALS = [
    "...선생님, 그런 얘기는 하고 싶지 않아.",
    "...싫어. 다른 얘기 하자.",
    "그만... 그런 얘기는 불편해. 다른 얘기 해줘.",
    "...카요코는 그런 대화는 안 해. 미안.",
    "...선생님, 그건 좀 아닌 것 같아. 다른 걸로 얘기하자.",
]

DEFAULT_CONFIG = {
    "warning_threshold_no_api": 3,
    "warning_reset_hours": 24,
    "categories": {},
    "refusal_templates": DEFAULT_REFUSALS,
}


class ModerationEngine:
    """
    로컬 키워드 기반 pre-check로 API 호출 없이 부적절 발화를 감지하고,
    카요코 캐릭터 톤의 거부 문구로 대화를 중단시킨다.

    · fast_check(text) → 로컬 매칭 (0 API)
    · record_warning() → 유저별 위반 카운트 (메모리, 시간 기반 리셋)
    · should_skip_api() → 임계 넘으면 True → 파이프라인이 AI 호출 건너뜀
    · pick_refusal() → 템플릿 랜덤 선택
    · build_ai_refusal_prompt() → AI가 문구를 자연스럽게 재구성하도록 지시
    """

    def __init__(self, settings_file: str):
        self.settings_file = settings_file
        self._config_mtime: float = 0
        self._config: dict = dict(DEFAULT_CONFIG)
        # {user_id_int: [(timestamp, category), ...]}
        self._warnings: dict[int, list[tuple[float, str]]] = {}

    # ─── 설정 로드 (파일 변경 시 자동 리로드) ────────────────────
    def _reload(self) -> dict:
        try:
            mtime = os.path.getmtime(self.settings_file)
        except OSError:
            return self._config
        if mtime == self._config_mtime and self._config:
            return self._config
        try:
            with open(self.settings_file, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            return self._config
        mod = raw.get("moderation") or {}
        merged = dict(DEFAULT_CONFIG)
        merged.update(mod)
        # refusal_templates가 비어있으면 기본값 유지
        if not merged.get("refusal_templates"):
            merged["refusal_templates"] = list(DEFAULT_REFUSALS)
        self._config = merged
        self._config_mtime = mtime
        return self._config

    @property
    def threshold(self) -> int:
        try:
            return int(self._reload().get("warning_threshold_no_api", 3))
        except (ValueError, TypeError):
            return 3

    @property
    def reset_hours(self) -> float:
        try:
            return float(self._reload().get("warning_reset_hours", 24))
        except (ValueError, TypeError):
            return 24.0

    def _categories(self) -> dict:
        c = self._reload().get("categories")
        return c if isinstance(c, dict) else {}

    def _templates(self) -> list[str]:
        t = self._reload().get("refusal_templates")
        if isinstance(t, list) and t:
            return [x for x in t if isinstance(x, str) and x.strip()]
        return list(DEFAULT_REFUSALS)

    # ─── 카테고리 매칭 (로컬 · 0 API) ────────────────────────────
    def fast_check(self, text: str) -> tuple[bool, str | None, str | None]:
        """
        키워드 매칭으로 부적절 카테고리 판정.
        반환: (flagged, category_key, category_label)
        """
        if not text:
            return False, None, None
        low = text.lower()
        for cat_key, cat_data in self._categories().items():
            if not isinstance(cat_data, dict):
                continue
            keywords = cat_data.get("keywords") or []
            if not isinstance(keywords, list):
                continue
            for kw in keywords:
                if not isinstance(kw, str) or not kw.strip():
                    continue
                if kw.lower() in low:
                    label = cat_data.get("label") or cat_key
                    return True, cat_key, label
        return False, None, None

    # ─── 유저별 위반 카운트 ──────────────────────────────────────
    def _prune(self, user_id: int) -> None:
        cutoff = time.time() - self.reset_hours * 3600
        arr = [t for t in self._warnings.get(user_id, []) if t[0] >= cutoff]
        if arr:
            self._warnings[user_id] = arr
        else:
            self._warnings.pop(user_id, None)

    def warn_count(self, user_id: int) -> int:
        self._prune(user_id)
        return len(self._warnings.get(user_id, []))

    def record_warning(self, user_id: int, category: str | None) -> int:
        self._prune(user_id)
        self._warnings.setdefault(user_id, []).append((time.time(), category or "unknown"))
        return len(self._warnings[user_id])

    def should_skip_api(self, user_id: int) -> bool:
        """임계 N번까지는 AI로 거부 문구 생성, N+1번부터 고정 문구로 전환."""
        return self.warn_count(user_id) > self.threshold

    # ─── 응답 생성 ───────────────────────────────────────────────
    def pick_refusal(self) -> str:
        templates = self._templates()
        return random.choice(templates) if templates else "..."

    def build_ai_refusal_prompt(self, user_text: str, category_label: str) -> str:
        """
        AI가 상황에 맞게 조합·재구성하도록 지시하는 프롬프트.
        문구 후보를 직접 넘겨서 톤을 통일하고, 유해 내용을 인용하지 않도록 지시.
        """
        templates = self._templates()
        candidates = "\n".join(f"- {t}" for t in templates)
        return (
            f"사용자가 [{category_label}] 카테고리로 부적절한 발화를 했습니다. "
            "카요코 캐릭터로 짧고 단호하게 대화를 거부하세요. "
            "아래 문구 후보 중 하나를 골라 자연스럽게 이어붙이되, **1~2문장 안**으로 마무리하세요. "
            "절대 유해 내용을 인용하거나 반복하지 마세요. "
            "부드럽게 화제를 돌리는 여지는 남기지 말고, 단호하게 끝맺으세요.\n\n"
            f"문구 후보:\n{candidates}"
        )

    # ─── 안내용 부가 정보 ────────────────────────────────────────
    def warning_meta(self, user_id: int) -> tuple[int, int]:
        return self.warn_count(user_id), self.threshold
