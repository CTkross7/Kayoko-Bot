# systems/customization.py
# ──────────────────────────────────────────────────────────
# 프로필 카드 커스터마이징 (상점 연동)
#
#  · 구매 즉시 user_data["card_customization"]에 반영 → 다음 카드에 실시간 적용
#  · 랜덤 색상 아이템은 지정된 헥사값을 결과 메시지로 안내
#  · 순수 함수: user_data(dict)만 변경하고 저장은 호출측(원자적 save)이 담당
#  · 기존 시스템과 충돌 없음: 신규 필드 "card_customization"만 사용
# ──────────────────────────────────────────────────────────

from __future__ import annotations

from utils.profile_card import random_hex

# 커스터마이징 상태가 저장되는 유저 데이터 필드
FIELD = "card_customization"

# ── 아이템 카탈로그 ──
# repeatable=True 인 항목은 재구매로 리롤(재랜덤) 가능
CUSTOMIZATION_ITEMS = {
    "nickname_color": {
        "name": "닉네임 색상 (랜덤)", "emoji": "🎨", "price": 50_000,
        "desc": "닉네임 색을 랜덤 헥사코드로 지정", "repeatable": True,
    },
    "nickname_neon": {
        "name": "닉네임 네온 효과", "emoji": "✨", "price": 150_000,
        "desc": "닉네임에 발광 네온 효과", "repeatable": False,
    },
    "border_solid": {
        "name": "프로필 테두리 (랜덤 단색)", "emoji": "🖼️", "price": 80_000,
        "desc": "카드 테두리를 랜덤 단색으로", "repeatable": True,
    },
    "border_gradient": {
        "name": "프로필 테두리 (랜덤 그라데이션)", "emoji": "🌈", "price": 200_000,
        "desc": "카드 테두리를 랜덤 2색 그라데이션으로", "repeatable": True,
    },
    "bg_gradient": {
        "name": "배경 (랜덤 그라데이션)", "emoji": "🖌️", "price": 300_000,
        "desc": "카드 배경을 랜덤 그라데이션으로", "repeatable": True,
    },
    "reset": {
        "name": "모든 디자인 초기화", "emoji": "♻️", "price": 0,
        "desc": "커스터마이징을 기본값으로 되돌림", "repeatable": True,
    },
}

# 구매 없이도 유지되는 토글 성격 항목(중복 소유 방지 대상)
_ONE_TIME = {"nickname_neon"}


def get_customization(user_data: dict) -> dict:
    """저장된 커스터마이징(dict) 반환. 없으면 빈 dict → 렌더러가 기본값 사용."""
    cz = user_data.get(FIELD)
    return cz if isinstance(cz, dict) else {}


def get_owned(user_data: dict) -> list:
    """보유(적용 중)한 커스터마이징 항목 id 목록."""
    cz = get_customization(user_data)
    owned = []
    if cz.get("nickname_color"):
        owned.append("nickname_color")
    if cz.get("nickname_neon"):
        owned.append("nickname_neon")
    border = cz.get("border") or {}
    if border.get("type") == "solid":
        owned.append("border_solid")
    elif border.get("type") == "gradient":
        owned.append("border_gradient")
    if (cz.get("bg") or {}).get("type") == "gradient":
        owned.append("bg_gradient")
    return owned


def _apply(item_id: str, cz: dict) -> str:
    """
    cz(card_customization dict)에 item_id 효과를 적용하고 안내 메시지를 반환.
    랜덤 항목은 결과 헥사값을 메시지에 포함한다.
    """
    if item_id == "nickname_color":
        color = random_hex()
        cz["nickname_color"] = color
        return f"🎨 닉네임 색상이 **{color.upper()}** (으)로 지정되었습니다!"

    if item_id == "nickname_neon":
        cz["nickname_neon"] = True
        return "✨ 닉네임 **네온 효과**가 켜졌습니다!"

    if item_id == "border_solid":
        color = random_hex()
        cz["border"] = {"type": "solid", "colors": [color]}
        return f"🖼️ 프로필 테두리가 **{color.upper()}** 단색으로 지정되었습니다!"

    if item_id == "border_gradient":
        c1, c2 = random_hex(), random_hex()
        cz["border"] = {"type": "gradient", "colors": [c1, c2]}
        return f"🌈 그라데이션 테두리: **{c1.upper()} → {c2.upper()}**"

    if item_id == "bg_gradient":
        c1, c2, c3 = random_hex(), random_hex(), random_hex()
        cz["bg"] = {"type": "gradient", "colors": [c1, c2, c3]}
        return f"🖌️ 배경 그라데이션: **{c1.upper()} → {c2.upper()} → {c3.upper()}**"

    if item_id == "reset":
        cz.clear()
        return "♻️ 모든 디자인이 **기본값으로 초기화**되었습니다."

    return "적용할 수 없는 항목입니다."


def purchase(user_data: dict, item_id: str) -> tuple[bool, str]:
    """
    커스터마이징 항목을 구매/적용한다. (user_data만 변경, 저장은 호출측)

    반환: (성공 여부, 안내 메시지)
    데이터 안전: 실패 시 user_data를 전혀 건드리지 않는다.
    """
    item = CUSTOMIZATION_ITEMS.get(item_id)
    if not item:
        return False, "❌ 존재하지 않는 커스터마이징 항목입니다."

    # 중복 소유 방지 (일회성 항목)
    if item_id in _ONE_TIME and item_id in get_owned(user_data):
        return False, f"이미 **{item['name']}**을(를) 보유 중입니다."

    price = int(item.get("price", 0))
    money = int(user_data.get("money", 0))
    if item_id != "reset" and money < price:
        return False, f"❌ 소지금이 부족합니다. (필요: {price:,}원 / 보유: {money:,}원)"

    # ── 이 시점부터 변경 (실패 지점 없음) ──
    cz = user_data.get(FIELD)
    if not isinstance(cz, dict):
        cz = {}
    # 원본 훼손 방지: 복사본에 적용 후 성공 시 반영
    new_cz = dict(cz)
    msg = _apply(item_id, new_cz)

    user_data[FIELD] = new_cz
    if price > 0:
        user_data["money"] = money - price

    tail = f"\n💰 -{price:,}원 (잔액 {user_data.get('money', 0):,}원)" if price > 0 else ""
    return True, msg + tail
