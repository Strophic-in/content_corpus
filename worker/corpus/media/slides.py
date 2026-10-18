"""Slides: carousel pages and single cards, drawn as JPEGs (Pillow).

Three layouts, each in the format's colours and font:

  educational  a cover (the picture full-bleed under a dark fade, the hook large at
               the bottom — or the hook on the background colour), then one idea a
               slide: a rounded picture or chart, the heading, the body; a page
               counter, the channel's name and a swipe arrow.
  photo        photos with even margins and a short caption band; the cover is a
               photo with its title; a slide without a photo is a text slide.
  card         TrendCaster's news card: the picture across the top, an accent rule,
               the headline and a few lines below, the channel's name at the foot.

`plan` places the text exactly as `render` draws it — and raises Overflow when it
can't fit — so the script writer's checks (script/carousel.py) and the drawing
agree. Third-party pictures carry their credit on the picture; AI pictures are
labelled "AI illustration".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import text as tx

W = 1080
M = 72                     # outer margin
FOOTER = 96                # the brand line and arrow live in the bottom FOOTER px


class Overflow(ValueError):
    """A slide's text doesn't fit its box even at the smallest size."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def height(aspect: str) -> int:
    return 1350 if aspect == "4:5" else 1080


@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int


@dataclass
class Plan:
    picture: Box | None        # where the picture/chart goes (None: no picture area)
    full_bleed: bool           # the picture covers the slide, text over a fade
    heading: tx.Fit | None
    heading_at: tuple[int, int]
    body: tx.Fit | None
    body_at: tuple[int, int]
    counter: bool


def _fit(field: str, text: str, font: Path, *, sizes: tuple[int, int], width: int, lines: int,
         height_: float) -> tx.Fit | None:
    if not text.strip():
        return None
    f = tx.fit(text, font, max_size=sizes[0], min_size=sizes[1], max_width=width, max_lines=lines,
               max_height=height_)
    if f is None:
        raise Overflow(field, f"the {field} is too long for its slide; shorten it")
    return f


def _block(f: tx.Fit | None, font: Path) -> float:
    return 0.0 if f is None else len(f.lines) * tx.line_height(font, f.size) * 1.08


def plan(slide: dict, idx: int, total: int, layout: str, aspect: str, font_name: str, has_visual: bool) -> Plan:
    H = height(aspect)
    heavy, body = tx.heavy(font_name), tx.body(font_name)
    heading, text = slide.get("heading") or "", slide.get("body") or ""
    width = W - 2 * M
    bottom = H - FOOTER
    cover = idx == 0 and total > 1

    if layout == "card":
        pic = Box(0, 0, W, int(H * 0.56))
        top = pic.h + 64
        h = _fit("heading", heading, heavy, sizes=(70, 42), width=width, lines=4, height_=(bottom - top) * 0.6)
        y = top + _block(h, heavy) + 22
        b = _fit("body", text, body, sizes=(38, 27), width=width, lines=6, height_=bottom - y)
        return Plan(pic, False, h, (M, top), b, (M, int(y)), False)

    if layout == "photo" and has_visual and not cover:
        pic = Box(M // 2, M // 2, W - M, H - M // 2 - 150)
        h = _fit("heading", heading, heavy, sizes=(44, 30), width=width, lines=2, height_=120)
        return Plan(pic, False, h, (M, pic.y + pic.h + 26), None, (M, 0), False)

    if cover and has_visual:                               # educational or photo cover over a picture
        h_room = H * 0.42
        b = _fit("body", text, body, sizes=(40, 29), width=width, lines=3, height_=H * 0.16)
        h = _fit("heading", heading, heavy, sizes=(100, 56), width=width, lines=4, height_=h_room)
        y_body = bottom - 20 - _block(b, body)
        y_head = y_body - (18 if b else 0) - _block(h, heavy)
        return Plan(Box(0, 0, W, H), True, h, (M, int(y_head)), b, (M, int(y_body)), False)

    if cover:                                              # a cover with no picture
        top = int(H * 0.22)
        h = _fit("heading", heading, heavy, sizes=(108, 60), width=width, lines=6, height_=H * 0.5)
        y = top + _block(h, heavy) + 30
        b = _fit("body", text, body, sizes=(44, 30), width=width, lines=4, height_=bottom - y)
        return Plan(None, False, h, (M, top), b, (M, int(y)), False)

    top = M + 70                                           # below the page counter
    if has_visual:
        pic = Box(M, top, width, int(H * (0.42 if aspect == "4:5" else 0.36)))
        y = pic.y + pic.h + 44
        h = _fit("heading", heading, heavy, sizes=(64, 40), width=width, lines=3, height_=(bottom - y) * 0.55)
        yb = y + _block(h, heavy) + 18
        b = _fit("body", text, body, sizes=(40, 27), width=width, lines=8, height_=bottom - yb)
        return Plan(pic, False, h, (M, int(y)), b, (M, int(yb)), True)
    h = _fit("heading", heading, heavy, sizes=(86, 50), width=width, lines=4, height_=H * 0.36)
    yb = top + 20 + _block(h, heavy) + 30
    b = _fit("body", text, body, sizes=(48, 30), width=width, lines=12, height_=bottom - yb)
    # A text-only slide: the words centred in the space between the counter and the footer.
    block = _block(h, heavy) + (30 + _block(b, body) if b else 0)
    y0 = max(top + 20, int(top + (bottom - top - block) / 2))
    return Plan(None, False, h, (M, y0), b, (M, int(y0 + _block(h, heavy) + 30)), True)


# ── drawing ───────────────────────────────────────────────────────────────────

def _rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


def _cover(img, w: int, h: int):
    from PIL import Image

    s = max(w / img.width, h / img.height)
    r = img.resize((max(w, round(img.width * s)), max(h, round(img.height * s))), Image.LANCZOS)
    x, y = (r.width - w) // 2, (r.height - h) // 2
    return r.crop((x, y, x + w, y + h))


def _font(path: Path, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(str(path), size)


def _lines(draw, f: tx.Fit, at: tuple[int, int], font: Path, fill) -> None:
    x, y = at
    pf = _font(font, f.size)
    step = tx.line_height(font, f.size) * 1.08
    for i, line in enumerate(f.lines):
        draw.text((x, y + i * step), line, font=pf, fill=fill)


def _credit(img, box: Box, credit: str, font_name: str) -> None:
    from PIL import ImageDraw

    d = ImageDraw.Draw(img, "RGBA")
    f = tx.body(font_name)
    size = 24
    label = credit.strip()[:80]
    w = tx.width(label, f, size)
    x, y = box.x + 18, box.y + box.h - 18 - 40
    d.rounded_rectangle((x, y, x + w + 24, y + 40), radius=8, fill=(0, 0, 0, 150))
    d.text((x + 12, y + 7), label, font=_font(f, size), fill=(255, 255, 255, 235))


def draw_chart(img, box: Box, chart: dict, look) -> None:
    """A chart in `box`: bar (horizontal), stat (one big number), compare (2-3 side
    by side) or line. Only the numbers given; the largest bar fills the width."""
    from PIL import ImageDraw

    d = ImageDraw.Draw(img, "RGBA")
    heavy, body = tx.heavy(look.font), tx.body(look.font)
    fg, accent = _rgb(look.primary_color), _rgb(look.accent_color)
    panel = _rgb(look.panel_color)
    d.rounded_rectangle((box.x, box.y, box.x + box.w, box.y + box.h), radius=28, fill=panel)
    kind = chart.get("kind") or "bar"
    labels = [str(x)[:40] for x in chart.get("labels") or []]
    values = [float(v) for v in chart.get("values") or []]
    unit = (chart.get("unit") or "").strip()
    pad = 40
    title = (chart.get("title") or "").strip()
    y0 = box.y + pad
    if title:
        tf = tx.fit(title, heavy, max_size=40, min_size=26, max_width=box.w - 2 * pad, max_lines=2)
        if tf:
            _lines(d, tf, (box.x + pad, y0), heavy, fg)
            y0 += int(len(tf.lines) * tx.line_height(heavy, tf.size) * 1.08) + 18

    def num(v: float) -> str:
        s = f"{v:,.0f}" if abs(v) >= 100 or float(v).is_integer() else f"{v:,.1f}"
        return f"{s}{unit}" if unit == "%" else f"{s} {unit}".strip()

    if kind in ("stat", "compare") and values:
        # One size for every number (the smallest that fits each column), the block
        # centred in the box.
        n = len(values)
        col = (box.w - 2 * pad) / n
        sizes = [tx.fit(num(v), heavy, max_size=210 if n == 1 else 120, min_size=40, max_width=col - 24,
                        max_lines=1) for v in values]
        size = min(f.size for f in sizes if f) if any(sizes) else 40
        label_fits = [tx.fit(lab, body, max_size=40 if n == 1 else 34, min_size=22, max_width=col - 24,
                             max_lines=3) for lab in labels]
        label_h = max((len(f.lines) * tx.line_height(body, f.size) * 1.08 for f in label_fits if f), default=0)
        block = tx.line_height(heavy, size) + 24 + label_h
        top = max(y0, box.y + (box.h - block) / 2)
        for k, (v, lf) in enumerate(zip(values, label_fits)):
            cx = box.x + pad + col * k + (col - 24) / 2 if n > 1 else box.x + box.w / 2
            d.text((cx, top), num(v), font=_font(heavy, size), fill=accent, anchor="ma")
            if lf:
                ly = top + tx.line_height(heavy, size) + 24
                for i, line in enumerate(lf.lines):
                    d.text((cx, ly + i * tx.line_height(body, lf.size) * 1.08), line, font=_font(body, lf.size),
                           fill=fg, anchor="ma")
        return
    if kind == "line" and len(values) >= 2:
        x0, x1 = box.x + pad + 20, box.x + box.w - pad - 20
        ya, yb = y0 + 70, box.y + box.h - pad - 46
        lo, hi = min(values), max(values)
        span = (hi - lo) or 1.0
        pts = [(x0 + (x1 - x0) * k / (len(values) - 1), yb - (yb - ya) * (v - lo) / span) for k, v in enumerate(values)]
        d.line(pts, fill=accent, width=8, joint="curve")
        sf = _font(body, 26)
        for (px, py), lab in zip(pts, labels):
            d.ellipse((px - 10, py - 10, px + 10, py + 10), fill=accent)
            d.text((px, yb + 16), lab[:10], font=sf, fill=fg, anchor="ma")
        hx, hy = max(pts, key=lambda q: -q[1])                       # the highest point
        d.text((hx, hy - 22), num(max(values)), font=_font(heavy, 34), fill=fg, anchor="md")
        lx, ly = pts[-1]
        if (lx, ly) != (hx, hy):
            d.text((lx, ly - 22), num(values[-1]), font=_font(heavy, 30), fill=fg, anchor="rd")
        return
    rows = max(1, len(values))
    row_h = (box.y + box.h - pad - y0) / rows
    top = max(values) if values else 1.0
    lf, vf = _font(body, 30), _font(heavy, 30)
    for k, (lab, v) in enumerate(zip(labels, values)):
        y = y0 + k * row_h
        d.text((box.x + pad, y), lab, font=lf, fill=fg)
        bar_w = max(10, (box.w - 2 * pad - 170) * (v / top if top else 0))
        by = y + 40
        bh = max(14, min(46, row_h - 56))
        d.rounded_rectangle((box.x + pad, by, box.x + pad + bar_w, by + bh), radius=8, fill=accent)
        d.text((box.x + pad + bar_w + 14, by + bh / 2), num(v), font=vf, fill=fg, anchor="lm")


def render(slide: dict, idx: int, total: int, *, layout: str, look, out: Path, picture: Path | None = None,
           credit: str | None = None) -> Path:
    """One slide → `out` (JPEG). `picture`: the slide's picture file, when its visual
    is a picture; a chart is drawn from slide['visual']['chart']."""
    from PIL import Image, ImageDraw

    aspect = (look.slides.aspect if look.slides else "4:5")
    H = height(aspect)
    visual = slide.get("visual") or {}
    has_visual = picture is not None or visual.get("source") == "chart"
    p = plan(slide, idx, total, layout, aspect, look.font, has_visual)
    bg, fg, accent = _rgb(look.background_color), _rgb(look.primary_color), _rgb(look.accent_color)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img, "RGBA")
    heavy, body = tx.heavy(look.font), tx.body(look.font)

    if p.picture is not None and picture is not None:
        src = Image.open(picture).convert("RGB")
        box = p.picture
        tile = _cover(src, box.w, box.h)
        if p.full_bleed or layout == "card":
            img.paste(tile, (box.x, box.y))
        else:
            mask = Image.new("L", (box.w, box.h), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, box.w, box.h), radius=28, fill=255)
            img.paste(tile, (box.x, box.y), mask)
        if p.full_bleed:                                   # a fade to the background under the text
            fade = Image.new("L", (1, H), 0)
            for yy in range(H):
                t = max(0.0, (yy - H * 0.30) / (H * 0.70))
                fade.putpixel((0, yy), int(255 * min(1.0, t * 1.15) * 0.93))
            img.paste(Image.new("RGB", (W, H), bg), (0, 0), fade.resize((W, H)))
        if credit:
            _credit(img, box if not p.full_bleed else Box(0, 0, W, 150), credit, look.font)
    elif p.picture is not None and visual.get("source") == "chart":
        draw_chart(img, p.picture, visual.get("chart") or {}, look)
    elif idx == 0 and total > 1:                           # a cover with no picture: one quiet accent shape
        d.ellipse((W - 420, -240, W + 240, 420), fill=(*accent, 38))

    d = ImageDraw.Draw(img, "RGBA")
    if p.heading:
        hx, hy = p.heading_at
        if layout == "card" or (idx == 0 and total > 1):
            d.rectangle((hx, hy - 30, hx + 120, hy - 20), fill=accent)
        _lines(d, p.heading, p.heading_at, heavy, fg)
    if p.body:
        _lines(d, p.body, p.body_at, body, _mix(fg, bg, 0.18))
    small = _font(body, 26)
    if p.counter and total > 1:
        d.text((M, M), f"{idx + 1}/{total}", font=_font(heavy, 28), fill=accent)
    if look.brand_text:
        d.text((M, H - FOOTER / 2), look.brand_text[:40], font=small, fill=_mix(fg, bg, 0.4), anchor="lm")
    if total > 1 and idx < total - 1:
        d.text((W - M, H - FOOTER / 2), "→", font=_font(heavy, 40), fill=accent, anchor="rm")
    img.save(out, "JPEG", quality=90, optimize=True, progressive=True)
    return out
