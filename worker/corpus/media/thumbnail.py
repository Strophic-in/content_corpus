"""The cover a posted reel shows before it plays: YouTube's thumbnail, Instagram's
Reel cover. 1080×1920, under YouTube's 2 MB limit.

A style (prompts/thumb_styles/<id>.json; Jev picks one per post in packaging.py)
lays out the picture and the line:

  classic          the photo full bleed, big yellow words low over a dark fade
  breaking_bar     a red BREAKING bar and a white headline band (TV news)
  top_headline     the words at the top over a dark sky
  big_number       the story's number huge, a short line under it
  question_hook    a big question centred over a darkened photo
  circle_arrow     a red circle and arrow on the subject, words below
  side_panel       a coloured panel with the words stacked, the photo beside it
  before_now       the place as it was on top, as it is below
  minimal_center   a blurred, dimmed photo and clean centred words
  boxed_words      each line on its own white or yellow box
  documentary      cinema bars and a serif title
  meme_top_bottom  meme capitals at the top and the bottom ("top / bottom")
  ad_badge         an offer badge and a call-to-action bar
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import text as text_

W, H = 1080, 1920
YELLOW = (255, 212, 0)
RED = (230, 30, 40)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
MAX_BYTES = 1_900_000
STYLES = ("classic", "breaking_bar", "top_headline", "big_number", "question_hook", "circle_arrow", "side_panel",
          "before_now", "minimal_center", "boxed_words", "documentary", "meme_top_bottom", "ad_badge")


def _cover(img: Image.Image, w: int, h: int, centering=(0.5, 0.42)) -> Image.Image:
    return ImageOps.fit(ImageOps.exif_transpose(img).convert("RGB"), (w, h), Image.LANCZOS, centering=centering)


def _fade(canvas: Image.Image, start: float, top: bool = False, strength: int = 225) -> None:
    """Darken from `start` (a fraction of the height) towards the bottom (or the top)."""
    shade = Image.new("L", (1, H), 0)
    edge = int(H * start)
    for y in range(H):
        d = (edge - y) if top else (y - edge)
        if d > 0:
            shade.putpixel((0, y), int(strength * min(1.0, d / (H * 0.22))))
    canvas.paste(Image.new("RGB", (W, H), BLACK), (0, 0), shade.resize((W, H)))


def _font(size: int, serif: bool = False, heavy: bool = True) -> ImageFont.FreeTypeFont:
    name = "Noto Serif" if serif else "Montserrat"
    return ImageFont.truetype(str(text_.heavy(name) if heavy else text_.body(name)), size)


def _fit(words: str, max_w: int, max_size: int, min_size: int, lines: int, serif: bool = False):
    path = text_.heavy("Noto Serif" if serif else "Montserrat")
    f = (text_.fit(words, path, max_size=max_size, min_size=min_size, max_width=max_w, max_lines=lines)
         or text_.Fit(min_size, text_.wrap(words, path, min_size, max_w)[:lines]))
    return f.size, f.lines, int(text_.line_height(path, f.size) * 0.98)


def _chip(draw: ImageDraw.ImageDraw, xy: tuple[int, int], label: str, fill, ink, size: int = 54) -> int:
    font = _font(size)
    x, y = xy
    l, t, r, b = draw.textbbox((0, 0), label, font=font)
    pad_x, pad_y = int(size * 0.45), int(size * 0.28)
    draw.rounded_rectangle((x, y, x + (r - l) + 2 * pad_x, y + (b - t) + 2 * pad_y), radius=int(size * 0.3), fill=fill)
    draw.text((x + pad_x - l, y + pad_y - t), label, font=font, fill=ink)
    return y + (b - t) + 2 * pad_y


def _lines(draw, lines, size, lh, x, y, fill=YELLOW, stroke=True, serif=False, center=False):
    font = _font(size, serif)
    for ln in lines:
        lx = (W - draw.textlength(ln, font=font)) / 2 if center else x
        draw.text((lx, y), ln, font=font, fill=fill, stroke_width=max(6, size // 14) if stroke else 0,
                  stroke_fill=BLACK)
        y += lh
    return y


def _photo(picture: Path | None, blur: float = 0.0) -> Image.Image:
    if picture is None:
        return Image.new("RGB", (W, H), (14, 14, 20))
    img = Image.open(picture)
    base = _cover(img, W, H)
    if img.width > img.height:          # a landscape photo: fill behind with its blur, keep it whole
        back = _cover(img, W, H).filter(ImageFilter.GaussianBlur(40))
        fitted = ImageOps.contain(ImageOps.exif_transpose(img).convert("RGB"), (W, int(H * 0.62)), Image.LANCZOS)
        back.paste(fitted, ((W - fitted.width) // 2, int(H * 0.16)))
        base = back
    return base.filter(ImageFilter.GaussianBlur(blur)) if blur else base


def _number(line: str) -> tuple[str, str] | None:
    m = re.search(r"(₹|\$|£|€)?\d[\d,.]*\s?(%|k|m|bn|crore|lakh|million|billion)?", line, re.I)
    if not m or not re.search(r"\d", m.group(0)):
        return None
    rest = (line[:m.start()] + line[m.end():]).strip(" ,:-")
    return m.group(0).strip(), rest


def render(out: Path, *, line: str, kicker: str = "", picture: Path | None = None,
           before: Path | None = None, brand: str = "", style: str = "classic") -> Path:
    """Draw the cover to `out` (JPEG) in `style`. `before` with `picture`: before/now."""
    words = " ".join(line.upper().split())
    if style == "before_now" and (before is None or picture is None):
        style = "classic"
    if before is not None and picture is not None and style in ("classic", "before_now"):
        style = "before_now"
    if style == "big_number" and not _number(line):
        style = "classic"
    canvas = _photo(picture, blur=24 if style in ("minimal_center", "question_hook") else 0)
    draw = ImageDraw.Draw(canvas)

    if style == "before_now":
        half = H // 2
        canvas.paste(_cover(Image.open(before), W, half), (0, 0))
        canvas.paste(_cover(Image.open(picture), W, H - half), (0, half))
        _fade(canvas, 0.62)
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, half - 6, W, half + 6), fill=YELLOW)
        _chip(draw, (48, 64), "BEFORE", WHITE, BLACK)
        _chip(draw, (48, half + 40), "NOW", RED, WHITE)
        size, lines, lh = _fit(words, W - 120, 150, 78, 3)
        _lines(draw, lines, size, lh, 60, H - 230 - lh * len(lines))
    elif style == "breaking_bar":
        _fade(canvas, 0.5)
        draw = ImageDraw.Draw(canvas)
        size, lines, lh = _fit(words, W - 120, 120, 70, 3)
        band_top = H - 300 - lh * len(lines)
        draw.rectangle((0, band_top - 100, W, band_top), fill=RED)
        label = (kicker or "Breaking").upper()[:20]
        draw.text((60, band_top - 86), label, font=_font(64), fill=WHITE)
        draw.rectangle((0, band_top, W, band_top + lh * len(lines) + 60), fill=(12, 12, 16))
        _lines(draw, lines, size, lh, 60, band_top + 30, fill=WHITE, stroke=False)
    elif style == "top_headline":
        _fade(canvas, 0.42, top=True, strength=235)
        draw = ImageDraw.Draw(canvas)
        size, lines, lh = _fit(words, W - 120, 140, 76, 3)
        if kicker:
            _chip(draw, (60, 120), kicker.upper()[:22], RED, WHITE, size=44)
        _lines(draw, lines, size, lh, 60, 230)
    elif style == "big_number":
        num, rest = _number(line)
        _fade(canvas, 0.38, strength=240)
        draw = ImageDraw.Draw(canvas)
        nsize, nlines, nlh = _fit(num.upper(), W - 120, 320, 160, 1)
        y = H - 760
        _lines(draw, nlines, nsize, nlh, 60, y)
        size, lines, lh = _fit(rest.upper() or words, W - 120, 96, 60, 3)
        _lines(draw, lines, size, lh, 60, y + nlh + 10, fill=WHITE)
    elif style == "question_hook":
        canvas.paste(Image.new("RGB", (W, H), BLACK), (0, 0), Image.new("L", (W, H), 120))
        draw = ImageDraw.Draw(canvas)
        q = words if words.endswith("?") else words + "?"
        size, lines, lh = _fit(q, W - 140, 150, 80, 4)
        _lines(draw, lines, size, lh, 70, (H - lh * len(lines)) // 2, fill=WHITE, center=True)
    elif style == "circle_arrow":
        _fade(canvas, 0.6)
        draw = ImageDraw.Draw(canvas)
        cx, cy, r = W // 2, int(H * 0.38), 210
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=RED, width=18)
        tip = (cx + int(r * 0.72), cy + int(r * 0.72))
        draw.line((cx + r + 40, cy + r + 170, tip[0] + 30, tip[1] + 30), fill=RED, width=22)
        draw.polygon([tip, (tip[0] + 90, tip[1] + 14), (tip[0] + 14, tip[1] + 90)], fill=RED)
        size, lines, lh = _fit(words, W - 120, 140, 76, 3)
        _lines(draw, lines, size, lh, 60, H - 230 - lh * len(lines))
    elif style == "side_panel":
        panel_w = int(W * 0.46)
        canvas.paste(_cover(Image.open(picture), W - panel_w, H) if picture else Image.new("RGB", (W - panel_w, H)),
                     (panel_w, 0))
        draw.rectangle((0, 0, panel_w, H), fill=(91, 76, 240))
        size, lines, lh = _fit(words, panel_w - 90, 120, 56, 7)
        _lines(draw, lines, size, lh, 45, (H - lh * len(lines)) // 2, fill=WHITE, stroke=False)
    elif style == "minimal_center":
        canvas.paste(Image.new("RGB", (W, H), BLACK), (0, 0), Image.new("L", (W, H), 140))
        draw = ImageDraw.Draw(canvas)
        size, lines, lh = _fit(line.strip(), W - 200, 110, 64, 4)
        y = (H - lh * len(lines)) // 2
        draw.rectangle((W // 2 - 60, y - 60, W // 2 + 60, y - 52), fill=YELLOW)
        _lines(draw, lines, size, lh, 100, y, fill=WHITE, stroke=False, center=True)
    elif style == "boxed_words":
        _fade(canvas, 0.55, strength=160)
        draw = ImageDraw.Draw(canvas)
        size, lines, lh = _fit(words, W - 200, 120, 70, 4)
        y = H - 300 - (lh + 26) * len(lines)
        f = _font(size)
        for i, ln in enumerate(lines):
            tw = draw.textlength(ln, font=f)
            draw.rounded_rectangle((60, y - 10, 60 + tw + 50, y + lh + 6), radius=16, fill=YELLOW if i % 2 else WHITE)
            draw.text((85, y), ln, font=f, fill=BLACK)
            y += lh + 26
    elif style == "documentary":
        _fade(canvas, 0.55, strength=170)
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, W, 210), fill=BLACK)
        draw.rectangle((0, H - 210, W, H), fill=BLACK)
        size, lines, lh = _fit(line.strip(), W - 160, 104, 60, 3, serif=True)
        _lines(draw, lines, size, lh, 80, H - 330 - lh * len(lines), fill=WHITE, stroke=False, serif=True)
    elif style == "meme_top_bottom":
        top, _, bottom = line.partition("/")
        if not bottom.strip():
            parts = line.split()
            top, bottom = " ".join(parts[: len(parts) // 2]), " ".join(parts[len(parts) // 2:])
        for txt, at_top in ((top, True), (bottom, False)):
            size, lines, lh = _fit(txt.strip().upper(), W - 100, 130, 70, 2)
            y = 90 if at_top else H - 140 - lh * len(lines)
            _lines(draw, lines, size, lh, 50, y, fill=WHITE, center=True)
    elif style == "ad_badge":
        _fade(canvas, 0.55)
        draw = ImageDraw.Draw(canvas)
        cx, cy, r = W - 230, 330, 170
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 122, 26))
        f = _font(54)
        badge = (kicker or "New").upper()[:10]
        draw.text((cx - draw.textlength(badge, font=f) / 2, cy - 34), badge, font=f, fill=WHITE)
        size, lines, lh = _fit(words, W - 120, 130, 72, 3)
        y = _lines(draw, lines, size, lh, 60, H - 420 - lh * len(lines), fill=WHITE)
        draw.rounded_rectangle((60, y + 40, W - 60, y + 170), radius=60, fill=WHITE)
        cta = _font(56)
        draw.text(((W - draw.textlength("LEARN MORE", font=cta)) / 2, y + 72), "LEARN MORE", font=cta, fill=BLACK)
    else:                                   # classic
        _fade(canvas, 0.5)
        draw = ImageDraw.Draw(canvas)
        size, lines, lh = _fit(words, W - 120, 150, 78, 3)
        y = H - 230 - lh * len(lines)
        if kicker:
            _chip(draw, (60, y - 100), kicker.upper()[:24], RED, WHITE, size=46)
        _lines(draw, lines, size, lh, 60, y)

    if brand and style not in ("meme_top_bottom", "documentary", "side_panel", "ad_badge"):
        draw.text((60, H - 140), brand, font=_font(38, heavy=False), fill=(235, 235, 235), stroke_width=2,
                  stroke_fill=BLACK)

    quality = 90
    while True:
        canvas.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
        if out.stat().st_size <= MAX_BYTES or quality <= 60:
            return out
        quality -= 8
