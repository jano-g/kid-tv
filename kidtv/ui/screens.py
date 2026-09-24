"""All on-screen scenes. Every function returns (image, x, y) positioned in
screen pixels for the current output size; the controller hands the result to
the Renderer. Coordinates in this file are in 1080p design units and scaled."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from PIL import Image, ImageDraw

from ..i18n import Translator
from ..util import format_clock
from . import theme as T
from .renderer import DESIGN_H, DESIGN_W


@dataclass
class UIContext:
    tr: Translator
    child_name: str
    tv_name: str
    avatar: Image.Image | None
    width: int = DESIGN_W
    height: int = DESIGN_H
    version: str = ""

    @property
    def scale(self) -> float:
        return min(self.width / DESIGN_W, self.height / DESIGN_H)

    def s(self, v: float) -> int:
        return int(round(v * self.scale))

    def font(self, family: str, size: int, weight: str = "Regular"):  # type: ignore[no-untyped-def]
        return T.font(family, max(8, self.s(size)), weight)

    @property
    def initial(self) -> str:
        return (self.child_name or "").strip()[:1]


@dataclass
class MenuItem:
    key: str
    label: str
    value: str | None = None
    enabled: bool = True
    has_arrows: bool = False  # left/right change the value
    danger: bool = False
    meta: dict = field(default_factory=dict)


Scene = tuple[Image.Image, int, int]


def _canvas(ctx: UIContext, w: int | None = None, h: int | None = None, fill: T.RGBA = T.TRANSPARENT) -> Image.Image:
    return Image.new("RGBA", (w or ctx.width, h or ctx.height), fill)


def _background(ctx: UIContext, accent: T.RGBA = T.ORANGE) -> Image.Image:
    img = _canvas(ctx, fill=T.BG)
    T.stars(img, 90, seed=7, colour=T.TEXT, region=(0, 0, ctx.width, ctx.height // 2))
    d = ImageDraw.Draw(img)
    # Soft accent glow bottom-left.
    glow = Image.new("RGBA", img.size, T.TRANSPARENT)
    gd = ImageDraw.Draw(glow)
    r = ctx.s(700)
    gd.ellipse((-r // 2, ctx.height - r // 2, r // 2, ctx.height + r // 2), fill=T.with_alpha(accent, 28))
    img.alpha_composite(glow)
    del d
    return img


def _header(ctx: UIContext, img: Image.Image, title: str, accent: T.RGBA, subtitle: str | None = None) -> int:
    """Draw the top bar with avatar + TV name on the left and *title* right-aligned.
    Returns the y where content may start."""
    d = ImageDraw.Draw(img)
    s = ctx.s
    T.draw_avatar(img, ctx.avatar, ctx.initial, s(96), s(84), s(72), accent, s(5))
    d.text((s(150), s(84)), ctx.tv_name, font=ctx.font("display", 40, "SemiBold"), fill=T.TEXT, anchor="lm")
    d.text((ctx.width - s(72), s(84)), title, font=ctx.font("display", 40, "Medium"), fill=accent, anchor="rm")
    if subtitle:
        d.text((s(150), s(128)), subtitle, font=ctx.font("body", 24), fill=T.TEXT_MUTED, anchor="lm")
    d.line((s(72), s(160), ctx.width - s(72), s(160)), fill=T.LINE, width=s(2))
    return s(200)


def _footer_hint(ctx: UIContext, img: Image.Image, hint: str) -> None:
    d = ImageDraw.Draw(img)
    d.text((ctx.width // 2, ctx.height - ctx.s(56)), hint, font=ctx.font("body", 26), fill=T.TEXT_DIM, anchor="mm")


def _button(ctx: UIContext, d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], label: str, accent: T.RGBA,
            selected: bool = True) -> None:
    fill = accent if selected else T.PANEL_LIGHT
    T.rounded(d, box, ctx.s(28), fill)
    colour = T.BG if selected else T.TEXT
    d.text(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), label, font=ctx.font("display", 32, "SemiBold"),
           fill=colour, anchor="mm")


# --------------------------------------------------------------------------
# Full-screen scenes
# --------------------------------------------------------------------------

def splash(ctx: UIContext) -> Scene:
    img = _background(ctx)
    d = ImageDraw.Draw(img)
    s = ctx.s
    cx, cy = ctx.width // 2, ctx.height // 2 - s(70)
    T.draw_avatar(img, ctx.avatar, ctx.initial, cx, cy, s(260), T.ORANGE, s(10))
    d.text((cx, cy + s(220)), ctx.tv_name, font=ctx.font("display", 96, "SemiBold"), fill=T.TEXT, anchor="mm")
    d.text((cx, cy + s(310)), ctx.tr("app.loading"), font=ctx.font("body", 30), fill=T.TEXT_MUTED, anchor="mm")
    return img, 0, 0


def message(ctx: UIContext, title: str, text: str = "", hint: str | None = None, accent: T.RGBA = T.ORANGE,
            badge: str | None = None, url: str | None = None, qr: Image.Image | None = None,
            show_avatar: bool = True) -> Scene:
    """Generic centred message (empty channel, limit reached, offline …)."""
    img = _background(ctx, accent)
    d = ImageDraw.Draw(img)
    s = ctx.s
    cx = ctx.width // 2
    # Short messages sit lower on the screen so they feel centred.
    y = s(250) if (url or qr is not None) else s(330)
    if show_avatar:
        T.draw_avatar(img, ctx.avatar, ctx.initial, cx, y, s(180), accent, s(8))
        y += s(150)
    if badge:
        fnt = ctx.font("display", 30, "SemiBold")
        bw = T.text_size(d, badge, fnt)[0] + s(48)
        T.pill(d, (cx - bw // 2, y - s(26), cx + bw // 2, y + s(26)), accent)
        d.text((cx, y), badge, font=fnt, fill=T.BG, anchor="mm")
        y += s(70)
    fnt_title = ctx.font("display", 72, "SemiBold")
    for line in T.wrap_text(d, title, fnt_title, ctx.width - s(300)):
        d.text((cx, y), line, font=fnt_title, fill=T.TEXT, anchor="mt")
        y += s(84)
    y += s(10)
    fnt_body = ctx.font("body", 34)
    for line in T.wrap_text(d, text, fnt_body, ctx.width - s(500)):
        d.text((cx, y), line, font=fnt_body, fill=T.TEXT_MUTED, anchor="mt")
        y += s(46)
    if url:
        y += s(24)
        fnt_url = ctx.font("display", 54, "Medium")
        uw = T.text_size(d, url, fnt_url)[0] + s(80)
        T.rounded(d, (cx - uw // 2, y, cx + uw // 2, y + s(96)), s(30), T.PANEL_LIGHT, outline=accent, width=s(3))
        d.text((cx, y + s(48)), url, font=fnt_url, fill=accent, anchor="mm")
        y += s(120)
    if qr is not None:
        size = s(260)
        q = qr.convert("RGBA").resize((size, size), Image.NEAREST)
        frame = s(16)
        T.rounded(d, (cx - size // 2 - frame, y, cx + size // 2 + frame, y + size + 2 * frame), s(20), T.TEXT)
        img.alpha_composite(q, (cx - size // 2, y + frame))
        y += size + 2 * frame
    if hint:
        _footer_hint(ctx, img, hint)
    return img, 0, 0


def updating(ctx: UIContext, version: str, progress: float | None = None) -> Scene:
    """Shown while an update downloads (with progress) and installs."""
    if progress is None:
        return message(ctx, ctx.tr("update.installing.title"), ctx.tr("update.installing.text", version=version),
                       accent=T.SKY)
    pct = int(round(progress * 100))
    return message(ctx, ctx.tr("update.downloading.title"), ctx.tr("update.downloading", version=version, pct=pct),
                   accent=T.SKY, badge=f"{pct} %")


def standby(ctx: UIContext) -> Scene:
    return message(ctx, ctx.tr("standby.goodnight", name=ctx.child_name), ctx.tr("standby.hint"), accent=T.LAVENDER)


def limit_reached(ctx: UIContext) -> Scene:
    return message(ctx, ctx.tr("limit.title", name=ctx.child_name), ctx.tr("limit.text"), hint=ctx.tr("limit.hint"),
                   accent=T.SKY)


def empty_channel(ctx: UIContext, number: int, url: str | None, qr: Image.Image | None, offline: bool) -> Scene:
    text = ctx.tr("channel.empty.hint") if url else ctx.tr("web.offline")
    return message(ctx, ctx.tr("channel.empty.title", n=number), text, accent=T.channel_colour(number),
                   badge=ctx.tr("channel.label", n=number), url=url, qr=qr, show_avatar=False)


def no_channels(ctx: UIContext, url: str | None, qr: Image.Image | None) -> Scene:
    text = ctx.tr("channel.none.hint") if url else ctx.tr("web.offline")
    return message(ctx, ctx.tr("channel.none.title"), text, accent=T.MINT, url=url, qr=qr)


def music(ctx: UIContext, number: int, channel_name: str, title: str, index: int, count: int,
          position: float | None, duration: float | None) -> Scene:
    accent = T.channel_colour(number)
    img = _background(ctx, accent)
    d = ImageDraw.Draw(img)
    s = ctx.s
    cx = ctx.width // 2
    # Vinyl-like disc with the avatar in the middle.
    r = s(230)
    cy = ctx.height // 2 - s(90)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=T.PANEL_LIGHT)
    for k in range(4):
        rr = r - s(24) - k * s(40)
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=T.with_alpha(accent, 70 + k * 30), width=s(3))
    T.draw_avatar(img, ctx.avatar, ctx.initial, cx, cy, s(200), accent, s(8))
    y = cy + r + s(60)
    fnt = ctx.font("display", 60, "SemiBold")
    d.text((cx, y), T.ellipsize(d, title, fnt, ctx.width - s(300)), font=fnt, fill=T.TEXT, anchor="mm")
    y += s(70)
    sub = f"{ctx.tr('channel.label', n=number)}  ·  {channel_name}  ·  {ctx.tr('channel.episode', i=index, n=count)}"
    d.text((cx, y), sub, font=ctx.font("body", 30), fill=T.TEXT_MUTED, anchor="mm")
    y += s(60)
    _progress(ctx, d, (cx - s(400), y, cx + s(400), y + s(14)), position, duration, accent)
    d.text((cx - s(400), y + s(34)), format_clock(position), font=ctx.font("body", 24), fill=T.TEXT_DIM, anchor="lm")
    d.text((cx + s(400), y + s(34)), format_clock(duration), font=ctx.font("body", 24), fill=T.TEXT_DIM, anchor="rm")
    return img, 0, 0


def _progress(ctx: UIContext, d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], position: float | None,
              duration: float | None, accent: T.RGBA) -> None:
    x0, y0, x1, y1 = box
    T.pill(d, box, T.with_alpha(T.TEXT, 50))
    if position is not None and duration:
        frac = max(0.0, min(1.0, position / duration))
        if frac > 0:
            T.pill(d, (x0, y0, max(x0 + (y1 - y0), int(x0 + (x1 - x0) * frac)), y1), accent)


# --------------------------------------------------------------------------
# Banner, volume, toast (partial overlays)
# --------------------------------------------------------------------------

def channel_banner(ctx: UIContext, number: int, channel_name: str, title: str, index: int, count: int,
                   position: float | None, duration: float | None, paused: bool, remaining_min: int | None) -> Scene:
    accent = T.channel_colour(number)
    s = ctx.s
    w, h = ctx.width - s(160), s(190)
    img = _canvas(ctx, w, h)
    d = ImageDraw.Draw(img)
    T.rounded(d, (0, 0, w - 1, h - 1), s(34), T.PANEL)
    # Big channel number block.
    T.rounded(d, (s(18), s(18), s(190), h - s(18)), s(26), accent)
    d.text((s(104), h // 2 - s(4)), str(number), font=ctx.font("display", 96, "SemiBold"), fill=T.BG, anchor="mm")
    x = s(220)
    d.text((x, s(52)), T.ellipsize(d, channel_name, ctx.font("display", 40, "SemiBold"), w - x - s(420)),
           font=ctx.font("display", 40, "SemiBold"), fill=T.TEXT, anchor="lm")
    d.text((x, s(104)), T.ellipsize(d, title, ctx.font("body", 32), w - x - s(420)), font=ctx.font("body", 32),
           fill=T.TEXT_MUTED, anchor="lm")
    ep = ctx.tr("channel.episode", i=index, n=count)
    d.text((w - s(40), s(52)), ep, font=ctx.font("body", 28), fill=T.TEXT_MUTED, anchor="rm")
    status = ctx.tr("paused") if paused else ""
    if remaining_min is not None:
        rem = ctx.tr("limit.remaining", min=remaining_min)
        status = f"{status}  ·  {rem}" if status else rem
    if status:
        d.text((w - s(40), s(104)), status, font=ctx.font("body", 28), fill=accent, anchor="rm")
    _progress(ctx, d, (x, s(150), w - s(300), s(162)), position, duration, accent)
    d.text((w - s(40), s(156)), f"{format_clock(position)} / {format_clock(duration)}", font=ctx.font("body", 26),
           fill=T.TEXT_DIM, anchor="rm")
    return img, s(80), ctx.height - h - s(60)


def volume_pill(ctx: UIContext, volume: int, muted: bool, max_volume: int = 100) -> Scene:
    s = ctx.s
    w, h = s(520), s(96)
    img = _canvas(ctx, w, h)
    d = ImageDraw.Draw(img)
    T.rounded(d, (0, 0, w - 1, h - 1), s(30), T.PANEL)
    label = ctx.tr("muted") if muted else ctx.tr("volume")
    d.text((s(30), h // 2), label, font=ctx.font("display", 30, "Medium"), fill=T.TEXT, anchor="lm")
    d.text((w - s(30), h // 2), "0" if muted else str(volume), font=ctx.font("display", 34, "SemiBold"),
           fill=T.ORANGE, anchor="rm")
    x0, x1 = s(200), w - s(110)
    T.pill(d, (x0, h // 2 - s(7), x1, h // 2 + s(7)), T.with_alpha(T.TEXT, 50))
    frac = 0 if muted else max(0.0, min(1.0, volume / max(1, max_volume)))
    if frac > 0:
        T.pill(d, (x0, h // 2 - s(7), max(x0 + s(14), int(x0 + (x1 - x0) * frac)), h // 2 + s(7)), T.ORANGE)
    return img, ctx.width - w - s(80), s(60)


def toast(ctx: UIContext, text: str, accent: T.RGBA = T.MINT) -> Scene:
    s = ctx.s
    fnt = ctx.font("body", 30, "SemiBold")
    tmp = ImageDraw.Draw(_canvas(ctx, 10, 10))
    tw = T.text_size(tmp, text, fnt)[0]
    w, h = tw + s(90), s(80)
    img = _canvas(ctx, w, h)
    d = ImageDraw.Draw(img)
    T.pill(d, (0, 0, w - 1, h - 1), T.PANEL)
    d.ellipse((s(26), h // 2 - s(10), s(46), h // 2 + s(10)), fill=accent)
    d.text((s(64), h // 2), text, font=fnt, fill=T.TEXT, anchor="lm")
    return img, (ctx.width - w) // 2, s(60)


# --------------------------------------------------------------------------
# Menu / list / keyboard / wizard
# --------------------------------------------------------------------------

def menu(ctx: UIContext, title: str, items: Sequence[MenuItem], selected: int, hint: str | None = None,
         accent: T.RGBA = T.ORANGE, subtitle: str | None = None, first_visible: int = 0) -> Scene:
    img = _background(ctx, accent)
    y = _header(ctx, img, title, accent, subtitle)
    d = ImageDraw.Draw(img)
    s = ctx.s
    row_h, gap = s(84), s(12)
    x0, x1 = s(72), ctx.width - s(72)
    visible = max(1, (ctx.height - y - s(120)) // (row_h + gap))
    if selected < first_visible:
        first_visible = selected
    if selected >= first_visible + visible:
        first_visible = selected - visible + 1
    for i in range(first_visible, min(len(items), first_visible + visible)):
        item = items[i]
        sel = i == selected
        fill = accent if sel else T.PANEL_LIGHT
        T.rounded(d, (x0, y, x1, y + row_h), s(24), fill)
        label_colour = T.BG if sel else (T.TEXT if item.enabled else T.TEXT_DIM)
        if item.danger and not sel:
            label_colour = T.RED
        d.text((x0 + s(36), y + row_h // 2), item.label, font=ctx.font("display", 34, "Medium" if sel else "Regular"),
               fill=label_colour, anchor="lm")
        if item.value is not None:
            vx = x1 - s(36)
            value_colour = T.BG if sel else T.TEXT_MUTED
            if item.has_arrows:
                T.arrow(d, vx - s(12), y + row_h // 2, s(12), "right", value_colour)
                vx -= s(44)
            d.text((vx, y + row_h // 2), item.value, font=ctx.font("body", 32, "SemiBold"), fill=value_colour, anchor="rm")
            if item.has_arrows:
                vw = T.text_size(d, item.value, ctx.font("body", 32, "SemiBold"))[0]
                T.arrow(d, vx - vw - s(30), y + row_h // 2, s(12), "left", value_colour)
        y += row_h + gap
    if len(items) > visible:
        # Scroll indicator.
        track_top, track_bottom = s(200), ctx.height - s(130)
        d.line((ctx.width - s(48), track_top, ctx.width - s(48), track_bottom), fill=T.LINE, width=s(4))
        frac0 = first_visible / len(items)
        frac1 = min(1.0, (first_visible + visible) / len(items))
        d.line((ctx.width - s(48), track_top + (track_bottom - track_top) * frac0,
                ctx.width - s(48), track_top + (track_bottom - track_top) * frac1), fill=accent, width=s(6))
    _footer_hint(ctx, img, hint or ctx.tr("menu.hint.nav"))
    return img, 0, 0


def pin_entry(ctx: UIContext, entered: int, error: bool) -> Scene:
    img = _background(ctx, T.PINK)
    _header(ctx, img, ctx.tr("menu.title"), T.PINK)
    d = ImageDraw.Draw(img)
    s = ctx.s
    cx, cy = ctx.width // 2, ctx.height // 2
    d.text((cx, cy - s(120)), ctx.tr("menu.pin"), font=ctx.font("display", 54, "SemiBold"), fill=T.TEXT, anchor="mm")
    for i in range(4):
        x = cx - s(150) + i * s(100)
        colour = T.PINK if i < entered else T.PANEL_LIGHT
        d.ellipse((x - s(24), cy - s(24), x + s(24), cy + s(24)), fill=colour)
    if error:
        d.text((cx, cy + s(100)), ctx.tr("menu.pin.wrong"), font=ctx.font("body", 32), fill=T.RED, anchor="mm")
    _footer_hint(ctx, img, ctx.tr("menu.hint.nav"))
    return img, 0, 0


KEY_ROWS_LOWER = ["qwertzuiop", "asdfghjkl", "yxcvbnm", "áäčďéíľĺň", "óôŕšťúýž"]
KEY_ROWS_SYMBOLS = ["1234567890", "@#$%&*-_+=", "!?.,;:'\"()", "/\\|<>[]{}~^", "€£§°´ˇ¨"]
SPECIAL = ["SHIFT", "SYMBOLS", "SPACE", "DELETE", "DONE", "CANCEL"]


def keyboard_layout(symbols: bool, shift: bool) -> list[list[str]]:
    rows = KEY_ROWS_SYMBOLS if symbols else KEY_ROWS_LOWER
    out = [[ch.upper() if shift and not symbols else ch for ch in row] for row in rows]
    out.append(["SHIFT", "SYMBOLS", "SPACE", "DELETE", "DONE", "CANCEL"])
    return out


def keyboard(ctx: UIContext, title: str, text: str, symbols: bool, shift: bool, cursor: tuple[int, int],
             secret: bool = False, hint: str | None = None, accent: T.RGBA = T.SKY) -> Scene:
    img = _background(ctx, accent)
    _header(ctx, img, title, accent)
    d = ImageDraw.Draw(img)
    s = ctx.s
    # Text field.
    fx0, fx1 = s(160), ctx.width - s(160)
    fy = s(210)
    T.rounded(d, (fx0, fy, fx1, fy + s(96)), s(24), T.PANEL_LIGHT, outline=accent, width=s(3))
    shown = ("•" * len(text)) if secret else text
    fnt = ctx.font("display", 44, "Medium")
    shown = shown if T.text_size(d, shown, fnt)[0] < fx1 - fx0 - s(80) else "…" + shown[-30:]
    d.text((fx0 + s(30), fy + s(48)), shown + "|", font=fnt, fill=T.TEXT, anchor="lm")
    rows = keyboard_layout(symbols, shift)
    key_w, key_h, gap = s(104), s(74), s(10)
    y = fy + s(130)
    labels = {"SHIFT": ctx.tr("keyboard.shift"), "SYMBOLS": ctx.tr("keyboard.letters") if symbols else ctx.tr("keyboard.symbols"),
              "SPACE": ctx.tr("keyboard.space"), "DELETE": ctx.tr("keyboard.delete"), "DONE": ctx.tr("keyboard.done"),
              "CANCEL": ctx.tr("keyboard.cancel")}
    for r, row in enumerate(rows):
        special = r == len(rows) - 1
        widths = [s(240) if special else key_w for _ in row]
        total = sum(widths) + gap * (len(row) - 1)
        x = (ctx.width - total) // 2
        for c, key in enumerate(row):
            w = widths[c]
            sel = (r, c) == cursor
            fill = accent if sel else T.PANEL_LIGHT
            if special and key in ("DONE",) and not sel:
                fill = T.with_alpha(T.MINT, 90)
            T.rounded(d, (x, y, x + w, y + key_h), s(18), fill)
            label = labels.get(key, key)
            d.text((x + w // 2, y + key_h // 2), label, font=ctx.font("display", 28 if special else 34, "Medium"),
                   fill=T.BG if sel else T.TEXT, anchor="mm")
            x += w + gap
        y += key_h + gap
    _footer_hint(ctx, img, hint or ctx.tr("keyboard.hint"))
    return img, 0, 0


def wizard_page(ctx: UIContext, step: int, total: int, title: str, text: str, button: str | None,
                accent: T.RGBA = T.ORANGE, url: str | None = None, qr: Image.Image | None = None,
                options: Sequence[str] | None = None, selected: int = 0) -> Scene:
    img = _background(ctx, accent)
    d = ImageDraw.Draw(img)
    s = ctx.s
    cx = ctx.width // 2
    # Step dots.
    for i in range(total):
        x = cx - (total - 1) * s(22) + i * s(44)
        d.ellipse((x - s(9), s(70) - s(9), x + s(9), s(70) + s(9)), fill=accent if i <= step else T.LINE)
    T.draw_avatar(img, ctx.avatar, ctx.initial, cx, s(230), s(150), accent, s(7))
    y = s(350)
    fnt_title = ctx.font("display", 64, "SemiBold")
    d.text((cx, y), title, font=fnt_title, fill=T.TEXT, anchor="mt")
    y += s(90)
    fnt_body = ctx.font("body", 32)
    for line in T.wrap_text(d, text, fnt_body, ctx.width - s(520)):
        d.text((cx, y), line, font=fnt_body, fill=T.TEXT_MUTED, anchor="mt")
        y += s(44)
    y += s(24)
    if url:
        fnt_url = ctx.font("display", 56, "Medium")
        uw = T.text_size(d, url, fnt_url)[0] + s(80)
        T.rounded(d, (cx - uw // 2, y, cx + uw // 2, y + s(100)), s(30), T.PANEL_LIGHT, outline=accent, width=s(3))
        d.text((cx, y + s(50)), url, font=fnt_url, fill=accent, anchor="mm")
        y += s(124)
    if qr is not None:
        size = s(220)
        q = qr.convert("RGBA").resize((size, size), Image.NEAREST)
        frame = s(14)
        T.rounded(d, (cx - size // 2 - frame, y, cx + size // 2 + frame, y + size + 2 * frame), s(18), T.TEXT)
        img.alpha_composite(q, (cx - size // 2, y + frame))
        y += size + 2 * frame + s(20)
    if options:
        bw, bh, gap = s(300), s(84), s(24)
        total_w = len(options) * bw + (len(options) - 1) * gap
        x = cx - total_w // 2
        for i, label in enumerate(options):
            _button(ctx, d, (x, y, x + bw, y + bh), label, accent, selected=i == selected)
            x += bw + gap
    elif button:
        bw, bh = s(360), s(88)
        by = max(y, ctx.height - s(200))
        _button(ctx, d, (cx - bw // 2, by, cx + bw // 2, by + bh), button, accent)
    return img, 0, 0


def learn_remote(ctx: UIContext, action_label: str, step: int, total: int) -> Scene:
    return wizard_page(ctx, step, total, ctx.tr("remote.learn.title"), ctx.tr("remote.learn.text", action=action_label),
                       None, accent=T.LAVENDER)


def confirm(ctx: UIContext, question: str, selected: int) -> Scene:
    return wizard_page(ctx, 0, 1, ctx.tr("confirm.title"), question, None, accent=T.PINK,
                       options=[ctx.tr("confirm.yes"), ctx.tr("confirm.no")], selected=selected)


def make_qr(data: str) -> Image.Image | None:
    try:
        import qrcode
    except ImportError:  # pragma: no cover
        return None
    q = qrcode.QRCode(border=1, box_size=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(data)
    q.make(fit=True)
    return q.make_image(fill_color="#0B1020", back_color="white").convert("RGBA")
