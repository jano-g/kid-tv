"""Colours, fonts and drawing helpers for the on-screen UI.

Design: warm night-sky palette (deep navy, cream text) with one playful accent
per channel. Big rounded shapes and a rounded display font (Fredoka) keep it
friendly for a child; Nunito carries body text."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .. import paths

RGBA = tuple[int, int, int, int]

BG: RGBA = (11, 16, 32, 255)  # #0B1020 deep navy
BG_SOFT: RGBA = (17, 24, 46, 255)
PANEL: RGBA = (22, 29, 51, 235)
PANEL_LIGHT: RGBA = (31, 41, 71, 255)
PANEL_HOVER: RGBA = (44, 56, 96, 255)
LINE: RGBA = (60, 72, 110, 255)
TEXT: RGBA = (246, 241, 232, 255)  # cream
TEXT_MUTED: RGBA = (168, 176, 200, 255)
TEXT_DIM: RGBA = (110, 120, 150, 255)
SHADOW: RGBA = (0, 0, 0, 110)
TRANSPARENT: RGBA = (0, 0, 0, 0)

ORANGE: RGBA = (255, 179, 71, 255)
MINT: RGBA = (127, 209, 174, 255)
PINK: RGBA = (242, 140, 177, 255)
SKY: RGBA = (126, 200, 242, 255)
YELLOW: RGBA = (255, 216, 102, 255)
LAVENDER: RGBA = (183, 165, 245, 255)
RED: RGBA = (240, 110, 110, 255)

CHANNEL_COLOURS = [ORANGE, MINT, PINK, SKY, YELLOW, LAVENDER]


def channel_colour(number: int) -> RGBA:
    return CHANNEL_COLOURS[(max(1, number) - 1) % len(CHANNEL_COLOURS)]


def with_alpha(colour: RGBA, alpha: int) -> RGBA:
    return (colour[0], colour[1], colour[2], alpha)


def mix(a: RGBA, b: RGBA, t: float) -> RGBA:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(4))  # type: ignore[return-value]


@lru_cache(maxsize=256)
def font(family: str, size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    """family: 'display' (Fredoka) or 'body' (Nunito). Variable fonts are set to
    the requested weight; falls back to DejaVu when the bundled file is missing."""
    file = paths.FONTS_DIR / ("Fredoka.ttf" if family == "display" else "Nunito.ttf")
    if not file.exists():  # pragma: no cover
        for candidate in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                          "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            if Path(candidate).exists():
                return ImageFont.truetype(candidate, size)
        return ImageFont.load_default()
    f = ImageFont.truetype(str(file), size)
    try:
        f.set_variation_by_name(weight)
    except Exception:  # noqa: BLE001 – font without that instance
        pass
    return f


def text_size(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=fnt)
    return right - left, bottom - top


def wrap_text(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        current = ""
        for word in words:
            trial = (current + " " + word).strip()
            if text_size(draw, trial, fnt)[0] <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def ellipsize(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_width: int) -> str:
    if text_size(draw, text, fnt)[0] <= max_width:
        return text
    while text and text_size(draw, text + "…", fnt)[0] > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill: RGBA,
            outline: RGBA | None = None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def pill(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: RGBA) -> None:
    x0, y0, x1, y1 = box
    rounded(draw, box, (y1 - y0) // 2, fill)


def arrow(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, direction: str, fill: RGBA) -> None:
    """Small solid triangle; direction in up/down/left/right."""
    s = size
    pts = {
        "up": [(cx, cy - s), (cx - s, cy + s // 2), (cx + s, cy + s // 2)],
        "down": [(cx, cy + s), (cx - s, cy - s // 2), (cx + s, cy - s // 2)],
        "left": [(cx - s, cy), (cx + s // 2, cy - s), (cx + s // 2, cy + s)],
        "right": [(cx + s, cy), (cx - s // 2, cy - s), (cx - s // 2, cy + s)],
    }[direction]
    draw.polygon(pts, fill=fill)


def circle_crop(img: Image.Image, size: int) -> Image.Image:
    """Square-crop *img*, resize to *size* and cut a circle out of it."""
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    img = img.crop((left, top, left + side, top + side)).convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), TRANSPARENT)
    out.paste(img, (0, 0), mask)
    return out


def default_avatar(initial: str, size: int, colour: RGBA) -> Image.Image:
    """Placeholder avatar: coloured disc with the child's initial."""
    img = Image.new("RGBA", (size, size), TRANSPARENT)
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, size - 1, size - 1), fill=colour)
    fnt = font("display", int(size * 0.55), "SemiBold")
    d.text((size / 2, size / 2 + size * 0.02), (initial or "?")[:1].upper(), font=fnt, fill=BG, anchor="mm")
    return img


def draw_avatar(canvas: Image.Image, avatar: Image.Image | None, initial: str, cx: int, cy: int, size: int,
                ring: RGBA, ring_width: int) -> None:
    """Circular avatar with a coloured ring, centred at (cx, cy)."""
    d = ImageDraw.Draw(canvas)
    r = size // 2 + ring_width
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ring)
    disc = circle_crop(avatar, size) if avatar is not None else default_avatar(initial, size, PANEL_LIGHT)
    canvas.alpha_composite(disc, (cx - size // 2, cy - size // 2))


def load_avatar(path: Path | None = None) -> Image.Image | None:
    path = path or paths.avatar_file()
    try:
        img = Image.open(path)
        img.load()
        return img.convert("RGBA")
    except (OSError, ValueError):
        return None


def stars(canvas: Image.Image, count: int, seed: int, colour: RGBA, region: tuple[int, int, int, int]) -> None:
    """Deterministic scatter of tiny soft dots – a hint of night sky."""
    import random

    rnd = random.Random(seed)
    d = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = region
    for _ in range(count):
        x, y = rnd.randint(x0, x1), rnd.randint(y0, y1)
        r = rnd.choice([1, 1, 2, 2, 3])
        a = rnd.randint(60, 170)
        d.ellipse((x - r, y - r, x + r, y + r), fill=with_alpha(colour, a))
