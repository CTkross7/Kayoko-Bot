# models/region.py
# ──────────────────────────────────────────────────────────
# 지역 시스템 데이터 + cats.json 기반 도감 검증
# ──────────────────────────────────────────────────────────

from typing import Optional

# ═══════════════════════════════════════════════════════════
# 지역 정의
# ═══════════════════════════════════════════════════════════

REGIONS = {
    "alley": {
        "name": "골목길",
        "emoji": "🏙️",
        "description": "도시의 좁은 골목길. 흔한 길고양이들이 많이 돌아다닙니다.",
        "required_level": 1,
        "required_prev_dex_percent": 0,
        "prev_region": None,
        "order": 0,
        "rarity_weights": {
            "common": 60,
            "uncommon": 25,
            "rare": 10,
            "epic": 4,
            "legendary": 0.9,
            "mythic": 0.1,
        },
        "base_money_reward": 100,
        "base_exp_reward": 8,
        "location_themes": [
            ("🗑️", "쓰레기통 뒤"),
            ("📦", "박스 안"),
            ("🪜", "사다리 옆"),
        ],
    },
    "park": {
        "name": "공원",
        "emoji": "🌳",
        "description": "넓은 도시 공원. 풀숲에 숨어있는 냥이들을 찾아보세요.",
        "required_level": 10,
        "required_prev_dex_percent": 80,
        "prev_region": "alley",
        "order": 1,
        "rarity_weights": {
            "common": 45,
            "uncommon": 30,
            "rare": 15,
            "epic": 7,
            "legendary": 2.5,
            "mythic": 0.5,
        },
        "base_money_reward": 250,
        "base_exp_reward": 15,
        "location_themes": [
            ("🌿", "풀숲 속"),
            ("🌳", "나무 위"),
            ("⛲", "분수대 근처"),
        ],
    },
    "harbor": {
        "name": "항구",
        "emoji": "⚓",
        "description": "바다 냄새 가득한 항구. 물고기를 노리는 냥이들이 있습니다.",
        "required_level": 22,
        "required_prev_dex_percent": 80,
        "prev_region": "park",
        "order": 2,
        "rarity_weights": {
            "common": 35,
            "uncommon": 30,
            "rare": 20,
            "epic": 10,
            "legendary": 4,
            "mythic": 1,
        },
        "base_money_reward": 500,
        "base_exp_reward": 25,
        "location_themes": [
            ("🚢", "배 위"),
            ("🪨", "방파제 뒤"),
            ("🐟", "생선 가게 옆"),
        ],
    },
    "factory": {
        "name": "폐공장",
        "emoji": "🏚️",
        "description": "버려진 공장. 위험하지만 희귀한 냥이가 서식합니다.",
        "required_level": 35,
        "required_prev_dex_percent": 80,
        "prev_region": "harbor",
        "order": 3,
        "rarity_weights": {
            "common": 25,
            "uncommon": 28,
            "rare": 25,
            "epic": 14,
            "legendary": 6,
            "mythic": 2,
        },
        "base_money_reward": 800,
        "base_exp_reward": 40,
        "location_themes": [
            ("🏗️", "무너진 벽 뒤"),
            ("🛢️", "드럼통 안"),
            ("⚙️", "기계 사이"),
        ],
    },
    "underground": {
        "name": "지하도시",
        "emoji": "🌑",
        "description": "도시 지하에 펼쳐진 미지의 영역. 전설의 냥이가 목격됩니다.",
        "required_level": 50,
        "required_prev_dex_percent": 80,
        "prev_region": "factory",
        "order": 4,
        "rarity_weights": {
            "common": 15,
            "uncommon": 22,
            "rare": 28,
            "epic": 20,
            "legendary": 10,
            "mythic": 5,
        },
        "base_money_reward": 1500,
        "base_exp_reward": 60,
        "location_themes": [
            ("🕳️", "하수구 입구"),
            ("🔦", "어두운 터널"),
            ("🚇", "버려진 역사"),
        ],
    },
    "abyss": {
        "name": "심연",
        "emoji": "🌀",
        "description": "세계의 끝. 신화급 냥이가 존재한다는 소문이 있습니다.",
        "required_level": 65,
        "required_prev_dex_percent": 80,
        "prev_region": "underground",
        "order": 5,
        "rarity_weights": {
            "common": 5,
            "uncommon": 15,
            "rare": 25,
            "epic": 25,
            "legendary": 18,
            "mythic": 12,
        },
        "base_money_reward": 3000,
        "base_exp_reward": 100,
        "location_themes": [
            ("🌀", "차원의 틈"),
            ("🔮", "수정동굴"),
            ("👁️", "감시자의 눈 앞"),
        ],
    },
}

# ═══════════════════════════════════════════════════════════
# 기본 조회 함수
# ═══════════════════════════════════════════════════════════

def get_region(region_key: str) -> Optional[dict]:
    """지역 키로 지역 데이터를 조회합니다."""
    return REGIONS.get(region_key)


def get_region_list() -> list:
    """순서대로 정렬된 지역 목록(튜플 리스트)을 반환합니다."""
    return sorted(REGIONS.items(), key=lambda x: x[1]["order"])


def get_next_region(current_region_key: str) -> Optional[str]:
    """현재 지역의 다음 지역 키를 반환합니다. 없으면 None."""
    current = REGIONS.get(current_region_key)
    if not current:
        return None

    current_order = current["order"]
    for key, data in REGIONS.items():
        if data["order"] == current_order + 1:
            return key
    return None


# ═══════════════════════════════════════════════════════════
# cats.json 연동 도감 검증 함수
# ═══════════════════════════════════════════════════════════
# 아래 함수들은 models.cat 모듈의 함수를 사용합니다.
# region.py ↔ cat.py 사이의 순환 임포트를 방지하기 위해
# 함수 내부에서 지연 임포트(lazy import) 방식을 사용합니다.
# ═══════════════════════════════════════════════════════════

def get_region_total_cat_count(region_key: str) -> int:
    """
    cats.json에서 해당 지역에 등록된 총 냥이 종류 수를 반환합니다.
    cats.json이 로드되지 않았으면 0을 반환합니다.
    """
    from models.cat import get_cats_by_region
    return len(get_cats_by_region(region_key))


def get_user_region_collected_count(user_data: dict, region_key: str) -> int:
    """
    유저가 해당 지역의 냥이를 몇 종류 수집했는지 cats.json 기준으로 정확히 계산합니다.

    user_data["cats"]의 키(냥이 이름)와 cats.json의 해당 지역 냥이 이름을
    실제로 대조하여 정확한 수집 수를 반환합니다.
    """
    from models.cat import get_cats_by_region

    region_cats = get_cats_by_region(region_key)
    if not region_cats:
        return 0

    owned_cat_names = set(user_data.get("cats", {}).keys())
    region_cat_names = {cat["name"] for cat in region_cats}

    return len(owned_cat_names & region_cat_names)


def get_user_region_dex_percent(user_data: dict, region_key: str) -> float:
    """
    유저의 특정 지역 도감 달성률(%)을 cats.json 기준으로 정확히 계산합니다.

    get_region_total_cat_count로 지역 전체 냥이 수를 구하고,
    get_user_region_collected_count로 유저의 수집 수를 구해서
    백분율을 반환합니다.
    """
    total = get_region_total_cat_count(region_key)
    if total == 0:
        return 0.0

    collected = get_user_region_collected_count(user_data, region_key)
    return round((collected / total) * 100, 1)


# ═══════════════════════════════════════════════════════════
# 지역 해금 검증 (cats.json 실데이터 기반)
# ═══════════════════════════════════════════════════════════

def check_region_unlock(user_data: dict, region_key: str) -> tuple:
    """
    유저가 해당 지역을 해금할 수 있는지 cats.json 실데이터 기반으로 검증합니다.

    반환: (가능여부: bool, 사유: str)

    검증 항목:
    1. 지역 존재 여부
    2. 이미 해금 여부
    3. 유저 레벨 >= 필요 레벨
    4. 이전 지역 해금 여부
    5. 이전 지역 도감 달성률 >= 필요 달성률 (cats.json 기반)
    """
    region = REGIONS.get(region_key)
    if not region:
        return False, "존재하지 않는 지역입니다."

    unlocked_regions = user_data.get("unlocked_regions", [])
    if region_key in unlocked_regions:
        return False, "이미 해금된 지역입니다."

    # 레벨 체크
    user_level = user_data.get("level", 1)
    required_level = region["required_level"]
    if user_level < required_level:
        return False, (
            f"레벨이 부족합니다. "
            f"(필요: Lv.{required_level}, 현재: Lv.{user_level})"
        )

    # 이전 지역 체크
    prev_region_key = region.get("prev_region")
    if prev_region_key:
        # 이전 지역이 해금되어 있는지
        if prev_region_key not in unlocked_regions:
            prev_region_data = REGIONS.get(prev_region_key, {})
            prev_name = prev_region_data.get("name", "???")
            return False, f"이전 지역({prev_name})이 해금되지 않았습니다."

        # 이전 지역 도감 달성률 체크 (cats.json 실데이터 기반)
        required_dex_percent = region["required_prev_dex_percent"]
        actual_dex_percent = get_user_region_dex_percent(user_data, prev_region_key)

        if actual_dex_percent < required_dex_percent:
            prev_region_data = REGIONS.get(prev_region_key, {})
            prev_name = prev_region_data.get("name", "???")
            total_cats = get_region_total_cat_count(prev_region_key)
            collected = get_user_region_collected_count(user_data, prev_region_key)
            return False, (
                f"{prev_name} 도감 달성률이 부족합니다.\n"
                f"필요: {required_dex_percent}% | 현재: {actual_dex_percent:.1f}% "
                f"({collected}/{total_cats}종)"
            )

    return True, "해금 가능"


# ═══════════════════════════════════════════════════════════
# 데이터 무결성 검증 유틸리티
# ═══════════════════════════════════════════════════════════

def validate_cats_region_mapping() -> dict:
    """
    cats.json의 모든 냥이가 유효한 지역에 소속되어 있는지 검증합니다.
    봇 시작 시 호출하여 데이터 무결성을 확인하는 용도입니다.

    반환:
    {
        "valid": bool,
        "total_cats": int,
        "region_counts": {"alley": 8, "park": 6, ...},
        "orphaned_cats": ["이름1", "이름2"],  # 유효하지 않은 지역에 속한 냥이
        "empty_regions": ["regionkey1"],       # 냥이가 0마리인 지역
        "errors": ["에러 메시지1", ...]
    }
    """
    from models.cat import get_all_cats

    all_cats = get_all_cats()
    valid_region_keys = set(REGIONS.keys())

    result = {
        "valid": True,
        "total_cats": len(all_cats),
        "region_counts": {key: 0 for key in valid_region_keys},
        "orphaned_cats": [],
        "empty_regions": [],
        "errors": [],
    }

    for cat in all_cats:
        cat_name = cat.get("name", "???")
        cat_region = cat.get("region", "")

        if not cat_region:
            result["orphaned_cats"].append(cat_name)
            result["errors"].append(f"'{cat_name}': region 필드가 비어있음")
            result["valid"] = False
            continue

        if cat_region not in valid_region_keys:
            result["orphaned_cats"].append(cat_name)
            result["errors"].append(
                f"'{cat_name}': region '{cat_region}'은 REGIONS에 정의되지 않은 지역"
            )
            result["valid"] = False
            continue

        result["region_counts"][cat_region] += 1

    for region_key in valid_region_keys:
        if result["region_counts"][region_key] == 0:
            result["empty_regions"].append(region_key)
            result["errors"].append(
                f"지역 '{region_key}' ({REGIONS[region_key]['name']})에 소속된 냥이가 0마리"
            )
            result["valid"] = False

    return result


def validate_user_region_data(user_data: dict) -> dict:
    """
    유저 데이터의 지역 관련 필드가 유효한지 검증합니다.

    검증 항목:
    1. current_region이 유효한 지역 키인지
    2. current_region이 해금된 지역 목록에 포함되는지
    3. unlocked_regions의 모든 항목이 유효한 지역 키인지
    4. region_dex_progress의 키들이 유효한 지역 키인지

    반환:
    {
        "valid": bool,
        "fixed": bool,       # 자동 수정이 이루어졌는지
        "errors": ["에러1", ...],
        "fixes": ["수정1", ...]
    }
    """
    valid_region_keys = set(REGIONS.keys())

    result = {
        "valid": True,
        "fixed": False,
        "errors": [],
        "fixes": [],
    }

    # 1. current_region 검증
    current = user_data.get("current_region", "")
    if current not in valid_region_keys:
        result["errors"].append(
            f"current_region '{current}'이 유효하지 않음 → 'alley'로 수정"
        )
        user_data["current_region"] = "alley"
        result["fixed"] = True
        result["fixes"].append("current_region → alley")
        result["valid"] = False

    # 2. unlocked_regions 검증
    unlocked = user_data.get("unlocked_regions", [])
    if not isinstance(unlocked, list):
        user_data["unlocked_regions"] = ["alley"]
        result["errors"].append("unlocked_regions가 리스트가 아님 → ['alley']로 수정")
        result["fixed"] = True
        result["fixes"].append("unlocked_regions → ['alley']")
        result["valid"] = False
        unlocked = user_data["unlocked_regions"]

    # alley는 항상 해금 상태여야 함
    if "alley" not in unlocked:
        unlocked.insert(0, "alley")
        result["fixes"].append("unlocked_regions에 'alley' 추가")
        result["fixed"] = True

    # 유효하지 않은 지역 키 제거
    invalid_keys = [k for k in unlocked if k not in valid_region_keys]
    if invalid_keys:
        for k in invalid_keys:
            unlocked.remove(k)
        result["errors"].append(f"unlocked_regions에서 유효하지 않은 키 제거: {invalid_keys}")
        result["fixed"] = True
        result["fixes"].append(f"제거된 키: {invalid_keys}")
        result["valid"] = False

    # 3. current_region이 해금 목록에 있는지
    if user_data["current_region"] not in unlocked:
        unlocked.append(user_data["current_region"])
        result["fixes"].append(
            f"current_region '{user_data['current_region']}'을 unlocked_regions에 추가"
        )
        result["fixed"] = True

    # 4. region_dex_progress 검증 및 cats.json 기반 실수치로 동기화
    dex_progress = user_data.get("region_dex_progress", {})
    if not isinstance(dex_progress, dict):
        user_data["region_dex_progress"] = {}
        result["errors"].append("region_dex_progress가 딕셔너리가 아님 → {} 로 수정")
        result["fixed"] = True
        result["valid"] = False
        dex_progress = user_data["region_dex_progress"]

    # 유효하지 않은 지역 키 제거
    invalid_dex_keys = [k for k in dex_progress if k not in valid_region_keys]
    if invalid_dex_keys:
        for k in invalid_dex_keys:
            del dex_progress[k]
        result["errors"].append(f"region_dex_progress에서 유효하지 않은 키 제거: {invalid_dex_keys}")
        result["fixed"] = True
        result["fixes"].append(f"dex에서 제거된 키: {invalid_dex_keys}")
        result["valid"] = False

    # 해금된 지역의 도감 수치를 cats.json 실데이터와 동기화
    for region_key in unlocked:
        actual_collected = get_user_region_collected_count(user_data, region_key)
        stored_collected = dex_progress.get(region_key, -1)

        if stored_collected != actual_collected:
            old_val = stored_collected if stored_collected != -1 else "(없음)"
            dex_progress[region_key] = actual_collected
            result["fixes"].append(
                f"{region_key} 도감 수치 동기화: {old_val} → {actual_collected}"
            )
            result["fixed"] = True

    user_data["region_dex_progress"] = dex_progress

    return result
