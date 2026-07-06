# models/element.py
# ──────────────────────────────────────────────────────────
# 속성 상성 시스템 (블루아카이브식 공격/방어 삼각형)
#
# 설계 원칙:
#   · 모든 상수/로직을 이 모듈에 self-contained. config.py는 건드리지 않음
#     (config.py에는 시크릿이 있어 저장소에서 제외되므로 의존하지 않는다)
#   · 속성 미지정("none")이면 배율 1.0 → 기존 밸런스 100% 보존
#   · 배율은 상수 테이블이라 밸런싱 시 숫자만 교체
# ──────────────────────────────────────────────────────────

from __future__ import annotations

# ── 공격 속성 ──
ATTACK_TYPES = {
    "explosive": {"name": "폭발", "emoji": "🔥"},
    "piercing":  {"name": "관통", "emoji": "🎯"},
    "mystic":    {"name": "신비", "emoji": "🔮"},
    "sonic":     {"name": "진동", "emoji": "💠"},
}

# ── 방어 속성 ──
DEFENSE_TYPES = {
    "light":   {"name": "경장갑",   "emoji": "🟢"},
    "heavy":   {"name": "중장갑",   "emoji": "🔵"},
    "special": {"name": "특수장갑", "emoji": "🟡"},
    "elastic": {"name": "탄력장갑", "emoji": "🟣"},
}

# ── 배율 튜닝 노브 ──
ELEM_EFFECTIVE = 1.5   # 유효(강): 데미지 증폭
ELEM_RESIST    = 0.75  # 저항(약): 데미지 감쇠
ELEM_NEUTRAL   = 1.0   # 보통

# ── 상성표 (공격 → 방어) ──
# 클래식 3각: 폭발▶경 / 관통▶중 / 신비▶특
# 탄력장갑: 폭발·관통·신비 전부 저항, 진동만 유효 (고난도 전용 방어구)
ELEMENT_MATRIX = {
    "explosive": {"light": ELEM_EFFECTIVE, "heavy": ELEM_RESIST,    "special": ELEM_NEUTRAL,   "elastic": ELEM_RESIST},
    "piercing":  {"light": ELEM_NEUTRAL,   "heavy": ELEM_EFFECTIVE, "special": ELEM_RESIST,    "elastic": ELEM_RESIST},
    "mystic":    {"light": ELEM_RESIST,    "heavy": ELEM_NEUTRAL,   "special": ELEM_EFFECTIVE, "elastic": ELEM_RESIST},
    "sonic":     {"light": ELEM_NEUTRAL,   "heavy": ELEM_NEUTRAL,   "special": ELEM_NEUTRAL,   "elastic": ELEM_EFFECTIVE},
}

NONE_TYPE = "none"


# ═══════════════════════════════════════════════════════════
# 핵심 계산
# ═══════════════════════════════════════════════════════════

def calc_type_multiplier(attack_type: str | None, defense_type: str | None) -> float:
    """
    공격 속성 vs 방어 속성의 데미지 배율을 반환합니다.

    어느 한쪽이라도 미지정/미정의 속성이면 1.0(보통)을 반환하여
    기존 밸런스를 그대로 보존합니다.
    """
    if not attack_type or not defense_type:
        return ELEM_NEUTRAL
    row = ELEMENT_MATRIX.get(attack_type)
    if not row:
        return ELEM_NEUTRAL
    return row.get(defense_type, ELEM_NEUTRAL)


def effectiveness_tag(multiplier: float) -> str:
    """배율에 대응하는 짧은 상성 태그 문자열."""
    if multiplier >= ELEM_EFFECTIVE:
        return "효과가 굉장했다!"
    if multiplier <= ELEM_RESIST:
        return "효과가 별로였다..."
    return ""


def effectiveness_symbol(multiplier: float) -> str:
    """임베드용 초간단 상성 기호."""
    if multiplier >= ELEM_EFFECTIVE:
        return "🔺유효"
    if multiplier <= ELEM_RESIST:
        return "🔻저항"
    return "▪️보통"


# ═══════════════════════════════════════════════════════════
# 라벨 헬퍼
# ═══════════════════════════════════════════════════════════

def attack_label(attack_type: str | None) -> str:
    info = ATTACK_TYPES.get(attack_type or "")
    if not info:
        return "❔ 무속성"
    return f"{info['emoji']} {info['name']}"


def defense_label(defense_type: str | None) -> str:
    info = DEFENSE_TYPES.get(defense_type or "")
    if not info:
        return "❔ 무장갑"
    return f"{info['emoji']} {info['name']}"


def type_badge(attack_type: str | None, defense_type: str | None) -> str:
    """냥이/유닛 옆에 붙일 `🔥폭발/🟢경장갑` 형태 배지."""
    return f"{attack_label(attack_type)} / {defense_label(defense_type)}"


# ═══════════════════════════════════════════════════════════
# 데이터 접근 (안전한 기본값 주입)
# ═══════════════════════════════════════════════════════════

def get_cat_types(cat_data: dict | None) -> tuple[str, str]:
    """
    냥이 데이터에서 (attack_type, defense_type)를 안전하게 추출합니다.
    필드가 없거나 잘못된 값이면 NONE_TYPE을 반환 → 배율 1.0.
    """
    if not isinstance(cat_data, dict):
        return NONE_TYPE, NONE_TYPE
    atk = cat_data.get("attack_type")
    dfn = cat_data.get("defense_type")
    atk = atk if atk in ATTACK_TYPES else NONE_TYPE
    dfn = dfn if dfn in DEFENSE_TYPES else NONE_TYPE
    return atk, dfn


def normalize_types_in_place(cat_data: dict) -> bool:
    """
    냥이 정의 dict에 속성 필드가 없으면 NONE_TYPE으로 채웁니다.
    반환: 변경이 발생했으면 True. (원본 유저 데이터는 건드리지 않는 정의 데이터 전용)
    """
    changed = False
    if cat_data.get("attack_type") not in ATTACK_TYPES:
        if cat_data.get("attack_type") is None:
            cat_data["attack_type"] = NONE_TYPE
            changed = True
    if cat_data.get("defense_type") not in DEFENSE_TYPES:
        if cat_data.get("defense_type") is None:
            cat_data["defense_type"] = NONE_TYPE
            changed = True
    return changed
