"""The headline card: a news clipping drawn at reel size — the article's own photo,
the outlet's name, its headline and the date — so a reel can show "ET Markets
reports…" as the report itself, readably, without a page screenshot's cookie
banners and paywalls (owner's choice, 2026-10-19).

Latin-script headlines only (the fonts have no Devanagari); None otherwise.
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path

from . import text as tx

W, H = 1080, 1920
PHOTO_H = 860
# The reel's captions sit below about y=1340: the clipping's text ends above them.
TEXT_END = 1300
MARGIN = 80
BG = (13, 15, 20)
ACCENT = (225, 29, 72)


def _date(published: str) -> str:
    try:
        d = datetime.fromisoformat(published.strip().replace("Z", "+00:00"))
    except ValueError:
        return ""
    return f"{d.day} {d.strftime('%B %Y')}"


def latin(s: str) -> bool:
    return not re.search(r"[^\x00-ɏ -⃏℀-⅏]", s)


def render(out: Path, *, headline: str, outlet: str, published: str = "", photo: bytes | None = None) -> Path | None:
    """The card as a 1080x1920 JPEG at `out`; None when the headline can't be drawn."""
    from PIL import Image, ImageDraw, ImageFont

    headline = " ".join(headline.split())
    if not headline or not latin(headline + outlet):
        return None
    card = Image.new("RGB", (W, H), BG)
    if photo:
        try:
            im = Image.open(io.BytesIO(photo)).convert("RGB")
            scale = max(W / im.width, PHOTO_H / im.height)
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            left, top = (im.width - W) // 2, max(0, (im.height - PHOTO_H) // 3)
            card.paste(im.crop((left, top, left + W, top + PHOTO_H)), (0, 0))
        except Exception:  # noqa: BLE001 - a card without its photo still reads
            photo = None
    # The photo fades into the page, so the headline sits on the clipping, not on the picture.
    fade = Image.new("L", (1, 420))
    for y in range(420):
        fade.putpixel((0, y), round(255 * (y / 419) ** 1.6))
    card.paste(Image.new("RGB", (W, 420), BG), (0, PHOTO_H - 420), fade.resize((W, 420)))

    d = ImageDraw.Draw(card)
    serif = tx.FONTS_DIR / "NotoSerif-Bold.ttf"
    name = (outlet or "").upper()[:40]
    top = PHOTO_H - 60 if photo else 260
    fit = tx.fit(headline, serif, max_size=84, min_size=44, max_width=W - 2 * MARGIN, max_lines=5,
                 max_height=TEXT_END - top - (100 if name else 0) - 90)
    if fit is None:
        return None
    step = tx.line_height(serif, fit.size) * 1.08
    block = (100 if name else 0) + len(fit.lines) * step + 90
    y = top if photo else round(top + (TEXT_END - top - block) / 2)
    if name:
        f = ImageFont.truetype(str(tx.FONTS_DIR / "Montserrat-ExtraBold.ttf"), 34)
        tw = d.textlength(name, font=f)
        d.rounded_rectangle((MARGIN, y, MARGIN + tw + 44, y + 62), radius=10, fill=ACCENT)
        d.text((MARGIN + 22, y + 12), name, font=f, fill="white")
        y += 100
    f = ImageFont.truetype(str(serif), fit.size)
    for ln in fit.lines:
        d.text((MARGIN, y), ln, font=f, fill=(245, 245, 240))
        y += step
    y += 30
    d.line((MARGIN, y, W - MARGIN, y), fill=(70, 74, 84), width=3)
    when = _date(published)
    if when:
        f = ImageFont.truetype(str(tx.FONTS_DIR / "Montserrat-Medium.ttf"), 34)
        d.text((MARGIN, y + 26), when, font=f, fill=(160, 165, 175))
    out.parent.mkdir(parents=True, exist_ok=True)
    card.save(out, "JPEG", quality=92)
    return out
