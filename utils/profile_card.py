# utils/profile_card.py
# ──────────────────────────────────────────────────────────
# 실시간 프로필 카드 이미지 합성 (Pillow)
#
#  · 한글 폰트 번들(NanumGothic) → 폰트 깨짐 방지
#  · 컬러 이모지(NotoColorEmoji) 렌더 → 아이콘 두부(□) 방지
#  · 측정 기반 레이아웃 → 텍스트 겹침 방지 (긴 값은 자동 말줄임)
#  · 커스터마이징 훅: 배경(그라데이션/이미지/단색), 테두리(단색/그라데이션),
#    닉네임 색상(헥사/랜덤), 닉네임 네온 효과 — 추후 상점 연동
# ──────────────────────────────────────────────────────────

from __future__ import annotations

import io
import os
import random
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ── 경로 ──
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FONT_DIR = os.path.join(_BASE, "assets", "fonts")
_FONT_REGULAR = os.path.join(_FONT_DIR, "NanumGothic-Regular.ttf")
_FONT_BOLD = os.path.join(_FONT_DIR, "NanumGothic-Bold.ttf")
_FONT_EXTRA = os.path.join(_FONT_DIR, "NanumGothic-ExtraBold.ttf")

# NotoColorEmoji — 번들본 우선(환경 무관 동일 렌더), 없으면 시스템 폰트
_EMOJI_FONT_CANDIDATES = [
    os.path.join(_FONT_DIR, "NotoColorEmoji.ttf"),
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
]
_EMOJI_STRIKE = 109  # NotoColorEmoji 비트맵 고정 크기

# ── 캔버스 ──
W, H = 1200, 680


# ═══════════════════════════════════════════════════════════
# 폰트 / 색상 유틸
# ═══════════════════════════════════════════════════════════

@lru_cache(maxsize=64)
def _font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    path = {"regular": _FONT_REGULAR, "bold": _FONT_BOLD, "extra": _FONT_EXTRA}.get(kind, _FONT_REGULAR)
    return ImageFont.truetype(path, size)


@lru_cache(maxsize=1)
def _emoji_font():
    for p in _EMOJI_FONT_CANDIDATES:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, _EMOJI_STRIKE)
            except Exception:
                continue
    return None


def _hex_to_rgb(value, default=(255, 255, 255)) -> tuple:
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        return tuple(int(v) for v in value[:3])
    if not isinstance(value, str):
        return default
    s = value.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return default
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return default


def random_hex() -> str:
    """랜덤 헥사코드 색상 (닉네임 색상 아이템용). 너무 어두운 색은 피함."""
    while True:
        r, g, b = random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)
        if r + g + b > 240:  # 가독성: 지나치게 어두운 색 제외
            return f"#{r:02x}{g:02x}{b:02x}"


# ═══════════════════════════════════════════════════════════
# 이모지 렌더 (색상 이모지 → RGBA 이미지, 캐시)
# ═══════════════════════════════════════════════════════════

@lru_cache(maxsize=256)
def _emoji_image(char: str, px: int):
    ef = _emoji_font()
    if ef is None:
        return None
    try:
        canvas = Image.new("RGBA", (_EMOJI_STRIKE, _EMOJI_STRIKE), (0, 0, 0, 0))
        d = ImageDraw.Draw(canvas)
        d.text((0, 0), char, font=ef, embedded_color=True)
        bbox = canvas.getbbox()
        if bbox:
            canvas = canvas.crop(bbox)
        return canvas.resize((px, px), Image.LANCZOS)
    except Exception:
        return None


def _paste_emoji(base: Image.Image, char: str, x: int, y: int, px: int) -> bool:
    """이모지를 (x,y)에 붙인다. 실패 시 False (텍스트 폴백용)."""
    img = _emoji_image(char, px)
    if img is None:
        return False
    base.paste(img, (x, y), img)
    return True


# ═══════════════════════════════════════════════════════════
# 그리기 헬퍼
# ═══════════════════════════════════════════════════════════

def _vertical_gradient(size, top_rgb, bottom_rgb) -> Image.Image:
    w, h = size
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        grad.putpixel((0, y), tuple(int(top_rgb[i] + (bottom_rgb[i] - top_rgb[i]) * t) for i in range(3)))
    return grad.resize((w, h))


def _horizontal_gradient(size, left_rgb, right_rgb) -> Image.Image:
    w, h = size
    grad = Image.new("RGB", (w, 1))
    for x in range(w):
        t = x / max(1, w - 1)
        grad.putpixel((x, 0), tuple(int(left_rgb[i] + (right_rgb[i] - left_rgb[i]) * t) for i in range(3)))
    return grad.resize((w, h))


def _circle_avatar(avatar_img: Image.Image, diameter: int, ring_rgb=(255, 255, 255)) -> Image.Image:
    """아바타를 원형으로 마스킹하고 링을 두른다."""
    ss = 4  # 슈퍼샘플링(계단현상 방지)
    big = diameter * ss
    src = avatar_img.convert("RGBA").resize((big, big), Image.LANCZOS)
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big, big), fill=255)
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    out.paste(src, (0, 0), mask)
    # 링
    ring = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((ss, ss, big - ss, big - ss), outline=ring_rgb + (255,), width=ss * 3)
    out = Image.alpha_composite(out, ring)
    return out.resize((diameter, diameter), Image.LANCZOS)


def _fit_font(draw, text, kind, max_size, min_size, max_width):
    """max_width 안에 들어오는 최대 폰트 크기를 찾는다 (닉네임 겹침 방지)."""
    size = max_size
    while size > min_size:
        f = _font(kind, size)
        if draw.textlength(text, font=f) <= max_width:
            return f
        size -= 2
    return _font(kind, min_size)


def _truncate(draw, text, font, max_width) -> str:
    """max_width를 넘으면 …로 말줄임 (텍스트 겹침 방지)."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    ell = "…"
    while text and draw.textlength(text + ell, font=font) > max_width:
        text = text[:-1]
    return text + ell


def _neon_text(base: Image.Image, xy, text, font, fill_rgb, glow_rgb=None):
    """네온 효과: 흐림 글로우 레이어 + 선명한 본문."""
    glow_rgb = glow_rgb or fill_rgb
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.text(xy, text, font=font, fill=glow_rgb + (255,))
    glow = glow.filter(ImageFilter.GaussianBlur(6))
    # 글로우 2회 합성으로 발광 강화
    base.alpha_composite(glow)
    base.alpha_composite(glow)
    ImageDraw.Draw(base).text(xy, text, font=font, fill=fill_rgb + (255,))


# ═══════════════════════════════════════════════════════════
# 메인 렌더
# ═══════════════════════════════════════════════════════════

def _default_customization() -> dict:
    return {
        "bg": {"type": "gradient", "colors": ["#1b1029", "#3d1d4d", "#101018"]},
        "border": {"type": "gradient", "colors": ["#f8a8c4", "#8a5cff"]},
        "nickname_color": "#ffffff",
        "nickname_neon": False,
        "text_color": "#e8e8f0",
        "accent_color": "#f8a8c4",
    }


def _apply_bg(customization) -> Image.Image:
    bg = customization.get("bg", {})
    btype = bg.get("type", "gradient")
    if btype == "image":
        try:
            img = Image.open(bg["path"]).convert("RGB").resize((W, H), Image.LANCZOS)
            # 어둡게 오버레이 (텍스트 가독성)
            ov = Image.new("RGBA", (W, H), (0, 0, 0, 110))
            return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
        except Exception:
            pass
    if btype == "solid":
        return Image.new("RGB", (W, H), _hex_to_rgb(bg.get("color", "#1b1029")))
    colors = [_hex_to_rgb(c) for c in bg.get("colors", ["#1b1029", "#3d1d4d"])]
    if len(colors) >= 3:
        top = _vertical_gradient((W, H // 2), colors[0], colors[1])
        bot = _vertical_gradient((W, H - H // 2), colors[1], colors[2])
        canvas = Image.new("RGB", (W, H))
        canvas.paste(top, (0, 0)); canvas.paste(bot, (0, H // 2))
        return canvas
    return _vertical_gradient((W, H), colors[0], colors[-1])


def _draw_border(card: Image.Image, customization):
    border = customization.get("border", {})
    btype = border.get("type", "gradient")
    if btype == "none":
        return
    radius = 28
    inset = 10
    box = (inset, inset, W - inset, H - inset)
    if btype == "gradient":
        colors = [_hex_to_rgb(c) for c in border.get("colors", ["#f8a8c4", "#8a5cff"])]
        grad = _horizontal_gradient((W, H), colors[0], colors[-1]).convert("RGBA")
        mask = Image.new("L", (W, H), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle(box, radius=radius, outline=255, width=6)
        card.paste(grad, (0, 0), mask)
    else:
        col = _hex_to_rgb(border.get("colors", ["#f8a8c4"])[0]) if border.get("colors") else (248, 168, 196)
        ImageDraw.Draw(card).rounded_rectangle(box, radius=radius, outline=col + (255,), width=6)


def _stat_row(card, draw, x, y, emoji, label, value, text_rgb, accent_rgb, col_width):
    """아이콘 + 라벨 + 값(강조) 한 줄. 겹침 방지: 값은 col_width 안에서 말줄임."""
    icon_px = 38
    pasted = _paste_emoji(card, emoji, x, y - 2, icon_px)
    tx = x + (icon_px + 12 if pasted else 0)
    label_font = _font("regular", 27)
    value_font = _font("bold", 29)
    label_txt = f"{label} "
    label_rgb = tuple(int(c * 0.82) for c in text_rgb)  # 값보다 살짝 어둡게(위계)
    draw.text((tx, y), label_txt, font=label_font, fill=label_rgb)
    vx = tx + int(draw.textlength(label_txt, font=label_font))
    remaining = (x + col_width) - vx
    value = _truncate(draw, str(value), value_font, max(20, remaining))
    draw.text((vx, y - 1), value, font=value_font, fill=accent_rgb + (255,))


def render_profile_card(data: dict, avatar_img: Image.Image = None, customization: dict = None) -> io.BytesIO:
    """
    프로필 카드 PNG를 생성해 BytesIO로 반환.

    data 예시 키:
      nickname, title, level, level_max(bool), exp, next_exp,
      money, tuna_can, money_rank, streak, cats_owned, catdex,
      battle_wins, best_floor, skill_track, skill_combat, skill_trade,
      remit_left(str), footer_date(str)
    """
    cz = _default_customization()
    if customization:
        cz.update({k: v for k, v in customization.items() if v is not None})

    text_rgb = _hex_to_rgb(cz.get("text_color", "#e8e8f0"))
    accent_rgb = _hex_to_rgb(cz.get("accent_color", "#f8a8c4"))
    nick_color = cz.get("nickname_color", "#ffffff")
    if nick_color == "random":
        nick_color = random_hex()
    nick_rgb = _hex_to_rgb(nick_color)

    # 배경 + 카드
    card = _apply_bg(cz).convert("RGBA")

    # 내부 반투명 패널 (가독성)
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle((28, 28, W - 28, H - 28), radius=26, fill=(10, 8, 18, 150))
    card = Image.alpha_composite(card, panel)

    draw = ImageDraw.Draw(card)

    # ── 아바타 ──
    av_d = 160
    av_x, av_y = 62, 60
    if avatar_img is not None:
        try:
            av = _circle_avatar(avatar_img, av_d, ring_rgb=accent_rgb)
            card.paste(av, (av_x, av_y), av)
        except Exception:
            avatar_img = None
    if avatar_img is None:
        ImageDraw.Draw(card).ellipse((av_x, av_y, av_x + av_d, av_y + av_d),
                                     fill=(60, 40, 70, 255), outline=accent_rgb + (255,), width=5)

    # ── 닉네임 / 칭호 ──
    head_x = av_x + av_d + 34
    nick = str(data.get("nickname", "이름 없음"))
    max_nick_w = W - head_x - 70
    nick_font = _fit_font(draw, nick, "extra", 58, 30, max_nick_w)
    nick = _truncate(draw, nick, nick_font, max_nick_w)
    if cz.get("nickname_neon"):
        _neon_text(card, (head_x, 66), nick, nick_font, nick_rgb, glow_rgb=accent_rgb)
        draw = ImageDraw.Draw(card)
    else:
        draw.text((head_x, 66), nick, font=nick_font, fill=nick_rgb + (255,))

    title = data.get("title")
    y_after_nick = 66 + nick_font.size + 6
    if title:
        tfont = _font("regular", 26)
        ttxt = _truncate(draw, f"『{title}』", tfont, max_nick_w)
        draw.text((head_x, y_after_nick), ttxt, font=tfont, fill=accent_rgb + (230,))
        y_after_nick += 34

    # ── 레벨 + EXP 바 ──
    level = data.get("level", 1)
    lvl_txt = f"Lv.{level}" + (" MAX" if data.get("level_max") else "")
    lfont = _font("bold", 30)
    draw.text((head_x, y_after_nick + 4), lvl_txt, font=lfont, fill=text_rgb + (255,))
    lvl_w = draw.textlength(lvl_txt + "  ", font=lfont)
    bar_x = head_x + int(lvl_w) + 8
    bar_y = y_after_nick + 12
    bar_w = W - bar_x - 70
    bar_h = 22
    exp, next_exp = data.get("exp", 0), data.get("next_exp", 1)
    ratio = 1.0 if data.get("level_max") else (min(exp / next_exp, 1.0) if next_exp else 0.0)
    # ★ 빈 트랙: 불투명 색 사용 (알파 기반 fill은 convert('RGB')에서 흰색으로 변함)
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=11, fill=(56, 50, 70))
    if ratio > 0:
        fillw = max(bar_h, int(bar_w * ratio))
        grad = _horizontal_gradient((fillw, bar_h), accent_rgb, _hex_to_rgb("#8a5cff")).convert("RGBA")
        m = Image.new("L", (fillw, bar_h), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, fillw, bar_h), radius=11, fill=255)
        card.paste(grad, (bar_x, bar_y), m)
        draw = ImageDraw.Draw(card)
    exp_label = "MAX" if data.get("level_max") else f"{exp:,}/{next_exp:,}"
    ef = _font("regular", 18)
    ew = draw.textlength(exp_label, font=ef)
    draw.text((bar_x + bar_w - ew - 6, bar_y + 2), exp_label, font=ef, fill=(235, 235, 240))

    # ── 구분선 (불투명 dim accent) ──
    dim = tuple(int(c * 0.55) for c in accent_rgb)
    ImageDraw.Draw(card).line((60, 258, W - 60, 258), fill=dim, width=2)

    # ── 스탯 2열 ──
    left = [
        ("💰", "돈", f"{data.get('money', 0):,}원"),
        ("🐟", "참치캔", f"{data.get('tuna_can', 0)}개"),
        ("🐱", "보유 냥이", f"{data.get('cats_owned', 0)}마리"),
        ("📖", "도감", f"{data.get('catdex', 0)}종"),
        ("⚔️", "전투 승리", f"{data.get('battle_wins', 0)}회"),
    ]
    right = [
        ("🏆", "돈 순위", data.get("money_rank", "-")),
        ("✅", "연속 출석", f"{data.get('streak', 0)}일"),
        ("🏅", "업적", f"{data.get('achievements', 0)}개"),
        ("🏛️", "미궁 최고", f"{data.get('best_floor', 0)}층"),
        ("⭐", "스킬", f"추적{data.get('skill_track',0)}·전투{data.get('skill_combat',0)}·상술{data.get('skill_trade',0)}"),
    ]
    col_w = (W - 60 - 60 - 40) // 2
    lx, rx = 66, 66 + col_w + 40
    row_y0, row_h = 290, 66
    for i, (em, lb, val) in enumerate(left):
        _stat_row(card, draw, lx, row_y0 + i * row_h, em, lb, val, text_rgb, accent_rgb, col_w)
    for i, (em, lb, val) in enumerate(right):
        _stat_row(card, draw, rx, row_y0 + i * row_h, em, lb, val, text_rgb, accent_rgb, col_w)

    # ── 푸터 ──
    ffont = _font("regular", 22)
    foot_rgb = (165, 165, 178)
    if _paste_emoji(card, "🐾", 60, H - 54, 26):
        ImageDraw.Draw(card).text((94, H - 52), "카요코 봇", font=ffont, fill=foot_rgb)
    else:
        draw.text((60, H - 52), "카요코 봇", font=ffont, fill=foot_rgb)
    fdate = str(data.get("footer_date", ""))
    if fdate:
        draw2 = ImageDraw.Draw(card)
        fw = draw2.textlength(fdate, font=ffont)
        draw2.text((W - 60 - fw, H - 52), fdate, font=ffont, fill=foot_rgb)

    # 테두리(맨 위)
    _draw_border(card, cz)

    out = io.BytesIO()
    card.convert("RGB").save(out, format="PNG")
    out.seek(0)
    return out
