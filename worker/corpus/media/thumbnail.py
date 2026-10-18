"""The cover a posted reel shows before it plays: YouTube's thumbnail, Instagram's
Reel cover. 1080×1920, under YouTube's 2 MB limit.

  one picture        the strongest real photo (or a frame of the reel), full bleed
  before / now       the place as it was on top, as it is below, labelled

and on it, low down over a dark fade: a small red kicker ("BREAKING") and the
thumbnail line in big yellow capitals with a black outline — read at a glance on a
phone, true to the story (packaging.py writes it).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import text as text_

W, H = 1080, 1920
YELLOW = (255, 212, 0)
RED = (230, 30, 40)
MAX_BYTES = 1_900_000


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(ImageOps.exif_transpose(img).convert("RGB"), (w, h), Image.LANCZOS, centering=(0.5, 0.42))


def _fade(canvas: Image.Image, start: float) -> None:
    """Darken from `start` (a fraction of the height) to the bottom, for the text."""
    shade = Image.new("L", (1, H), 0)
    top = int(H * start)
    for y in range(top, H):
        shade.putpixel((0, y), int(225 * min(1.0, (y - top) / (H * 0.22))))
    black = Image.new("RGB", (W, H), (0, 0, 0))
    canvas.paste(black, (0, 0), shade.resize((W, H)))


def _chip(draw: ImageDraw.ImageDraw, xy: tuple[int, int], label: str, fill, ink, size: int = 54) -> int:
    font = ImageFont.truetype(str(text_.heavy("Montserrat")), size)
    x, y = xy
    l, t, r, b = draw.textbbox((0, 0), label, font=font)
    pad_x, pad_y = int(size * 0.45), int(size * 0.28)
    draw.rounded_rectangle((x, y, x + (r - l) + 2 * pad_x, y + (b - t) + 2 * pad_y), radius=int(size * 0.3), fill=fill)
    draw.text((x + pad_x - l, y + pad_y - t), label, font=font, fill=ink)
    return y + (b - t) + 2 * pad_y


def render(out: Path, *, line: str, kicker: str = "", picture: Path | None = None,
           before: Path | None = None, brand: str = "") -> Path:
    """Draw the cover to `out` (JPEG). `before` with `picture`: the before/now split."""
    canvas = Image.new("RGB", (W, H), (12, 12, 14))
    draw = ImageDraw.Draw(canvas)
    if before is not None and picture is not None:
        half = H // 2
        canvas.paste(_cover(Image.open(before), W, half), (0, 0))
        canvas.paste(_cover(Image.open(picture), W, H - half), (0, half))
        _fade(canvas, 0.62)
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, half - 6, W, half + 6), fill=YELLOW)
        _chip(draw, (48, 64), "BEFORE", (255, 255, 255), (0, 0, 0))
        _chip(draw, (48, half + 40), "NOW", RED, (255, 255, 255))
    elif picture is not None:
        img = Image.open(picture)
        base = _cover(img, W, H)
        # A landscape photo stretched to 9:16 loses its sides: fill behind with its blur.
        if img.width > img.height:
            blur = _cover(img, W, H).filter(ImageFilter.GaussianBlur(40))
            fitted = ImageOps.contain(ImageOps.exif_transpose(img).convert("RGB"), (W, int(H * 0.62)), Image.LANCZOS)
            blur.paste(fitted, ((W - fitted.width) // 2, int(H * 0.16)))
            base = blur
        canvas.paste(base, (0, 0))
        _fade(canvas, 0.5)
        draw = ImageDraw.Draw(canvas)

    # The line: big, yellow, outlined; as large as fits in three lines.
    words = " ".join(line.upper().split())
    font_path = text_.heavy("Montserrat")
    f = (text_.fit(words, font_path, max_size=150, min_size=78, max_width=W - 120, max_lines=3)
         or text_.Fit(78, text_.wrap(words, font_path, 78, W - 120)[:3]))
    size, lines = f.size, f.lines
    font = ImageFont.truetype(str(font_path), size)
    lh = int(text_.line_height(font_path, size) * 0.98)
    y = H - 230 - lh * len(lines)
    if kicker and before is None:           # a before/now cover has its BEFORE and NOW labels
        _chip(draw, (60, y - 100), kicker.upper()[:24], RED, (255, 255, 255), size=46)
    for ln in lines:
        draw.text((60, y), ln, font=font, fill=YELLOW, stroke_width=max(6, size // 14), stroke_fill=(0, 0, 0))
        y += lh
    if brand:
        small = ImageFont.truetype(str(text_.body("Montserrat")), 38)
        draw.text((60, H - 140), brand, font=small, fill=(235, 235, 235), stroke_width=2, stroke_fill=(0, 0, 0))

    quality = 90
    while True:
        canvas.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
        if out.stat().st_size <= MAX_BYTES or quality <= 60:
            return out
        quality -= 8
