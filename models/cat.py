# models/cat.py
# ──────────────────────────────────────────────────────────
# 냥이 데이터 모델 및 유틸리티
# ──────────────────────────────────────────────────────────

import random
from typing import Optional, List

from config import CATS_FILE, RARITY_TIERS, get_rarity_tier
from data_manager import load_json


# ═══════════════════════════════════════════════════════════
# 냥이 데이터 캐시
# ═══════════════════════════════════════════════════════════

_CAT_CACHE = {}           # {name: cat_data}
_CAT_LIST = []            # [cat_data, ...]
_REGION_CAT_MAP = {}      # {region_key: [cat_data, ...]}


def load_cats() -> list:
    """cats.json에서 냥이 데이터를 로드하고 캐시합니다."""
    global _CAT_CACHE, _CAT_LIST, _REGION_CAT_MAP
    raw = load_json(CATS_FILE, [])

    # ── 속성 상성 필드 안전 주입 ──
    # cats.json에 attack_type/defense_type가 없는 항목은 "none"으로 채워
    # 배율 1.0(보통) 처리되게 한다. (정의 데이터 전용 — 유저 데이터 무관)
    try:
        from models.element import normalize_types_in_place
        for cat in raw:
            if isinstance(cat, dict):
                normalize_types_in_place(cat)
    except Exception:
        pass

    _CAT_LIST = sorted(raw, key=lambda x: x.get("rarity", 100))
    _CAT_CACHE = {cat["name"]: cat for cat in _CAT_LIST}

    # 지역별 냥이 맵 구축
    _REGION_CAT_MAP = {}
    for cat in _CAT_LIST:
        region = cat.get("region", "alley")
        if region not in _REGION_CAT_MAP:
            _REGION_CAT_MAP[region] = []
        _REGION_CAT_MAP[region].append(cat)

    return _CAT_LIST


def get_all_cats() -> list:
    """전체 냥이 리스트를 반환합니다."""
    if not _CAT_LIST:
        load_cats()
    return _CAT_LIST


def get_cat_by_name(name: str) -> Optional[dict]:
    """이름으로 냥이 데이터를 조회합니다."""
    if not _CAT_CACHE:
        load_cats()
    return _CAT_CACHE.get(name)


def get_cats_by_region(region_key: str) -> list:
    """특정 지역에 출현하는 냥이 목록을 반환합니다."""
    if not _REGION_CAT_MAP:
        load_cats()
    return _REGION_CAT_MAP.get(region_key, [])


def get_region_total_cats(region_key: str) -> int:
    """특정 지역의 총 냥이 종류 수를 반환합니다."""
    return len(get_cats_by_region(region_key))


def get_region_dex_percent(user_data: dict, region_key: str) -> float:
    """유저의 특정 지역 도감 달성률을 계산합니다."""
    total = get_region_total_cats(region_key)
    if total == 0:
        return 0.0

    # 유저가 해당 지역의 냥이를 몇 종류 가지고 있는지 계산
    owned_cats = user_data.get("cats", {})
    region_cats = get_cats_by_region(region_key)
    collected = sum(1 for cat in region_cats if cat["name"] in owned_cats)

    return round((collected / total) * 100, 1)


def pick_cat_from_region(
    region_key: str,
    rarity_weights: dict,
    rare_bonus: float = 0.0
) -> Optional[dict]:
    """
    지역의 등급 가중치에 따라 냥이를 선택합니다.

    1단계: 등급 가중치에 따라 등급을 먼저 결정
    2단계: 해당 등급의 냥이 풀에서 rarity 값에 따른 가중치 뽑기

    rare_bonus: 희귀 이상 등급의 가중치를 증가시키는 보너스 (%)
    """
    region_cats = get_cats_by_region(region_key)
    if not region_cats:
        return None

    # 1단계: 등급 결정
    adjusted_weights = dict(rarity_weights)

    # rare_bonus 적용: rare 이상 등급에 보너스 가중치 추가
    if rare_bonus > 0:
        for tier_key in ["rare", "epic", "legendary", "mythic"]:
            if tier_key in adjusted_weights:
                adjusted_weights[tier_key] += rare_bonus

    tier_keys = list(adjusted_weights.keys())
    tier_weight_values = [adjusted_weights[k] for k in tier_keys]

    chosen_tier_key = random.choices(tier_keys, weights=tier_weight_values, k=1)[0]

    # 2단계: 해당 등급에 속하는 냥이 필터링
    tier_info = RARITY_TIERS.get(chosen_tier_key)
    if not tier_info:
        return random.choice(region_cats)

    # 등급 범위에 맞는 냥이 필터
    tier_min = tier_info["min_rarity"]

    # 다음 등급의 min_rarity를 찾아서 상한선 설정
    tier_order = ["mythic", "legendary", "epic", "rare", "uncommon", "common"]
    current_idx = tier_order.index(chosen_tier_key)
    if current_idx > 0:
        upper_tier = tier_order[current_idx - 1]
        tier_max = RARITY_TIERS[upper_tier]["min_rarity"]
    else:
        # mythic은 최하위이므로 상한 없음 (0 ~ min_rarity of legendary)
        tier_max = RARITY_TIERS["legendary"]["min_rarity"]

    # 해당 등급 범위의 냥이 필터링
    if chosen_tier_key == "mythic":
        # 신화: rarity < legendary의 min_rarity (0.01 미만)
        eligible = [c for c in region_cats if c["rarity"] < tier_max]
    elif chosen_tier_key == "common":
        # 일반: rarity >= common의 min_rarity
        eligible = [c for c in region_cats if c["rarity"] >= tier_min]
    else:
        # 그 외: tier_min <= rarity < tier_max
        eligible = [c for c in region_cats if tier_min <= c["rarity"] < tier_max]

    if not eligible:
        # 해당 등급에 냥이가 없으면 지역 전체에서 랜덤
        eligible = region_cats

    # 3단계: rarity 기반 가중치 뽑기 (rarity가 낮을수록 희귀 → 가중치도 낮게)
    weights = [cat["rarity"] for cat in eligible]
    chosen = random.choices(eligible, weights=weights, k=1)[0]

    return chosen
