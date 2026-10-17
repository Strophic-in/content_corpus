"""Text that has to fit: measured with the bundled fonts, wrapped, and shrunk.

The script writer's checks and the renderers use the same measurements, so text
that passed validation is text that fits when drawn: a headline over a reel
(libass), a text beat, a slide's heading and body (Pillow). Widths come from the
font's advance widths (fontTools), the way the caption wrapping already measures;
kerning only ever makes a line narrower than this.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

FONTS_DIR = Path(__file__).parent / "fonts"

# family → (heavy file, body file, ASS font name, ASS bold flag). libass picks a font
# by family name; Montserrat's weights are separate families, Noto Serif's are styles.
FAMILIES = {
    "Montserrat": ("Montserrat-ExtraBold.ttf", "Montserrat-Medium.ttf", "Montserrat ExtraBold", 0),
    "Noto Serif": ("NotoSerif-Bold.ttf", "NotoSerif-Regular.ttf", "Noto Serif", -1),
}


def family(name: str | None) -> tuple[str, str, str, int]:
    return FAMILIES.get(name or "", FAMILIES["Montserrat"])


def heavy(name: str | None) -> Path:
    return FONTS_DIR / family(name)[0]


def body(name: str | None) -> Path:
    return FONTS_DIR / family(name)[1]


@dataclass(frozen=True)
class _Metrics:
    advance: dict[int, int]
    upem: int
    fallback: int
    line: float         # line height, in ems (ascender − descender + gap)


@functools.lru_cache(maxsize=16)
def _metrics(path: Path) -> _Metrics:
    from fontTools.ttLib import TTFont

    f = TTFont(path)
    hmtx = f["hmtx"]
    advance = {cp: hmtx[g][0] for cp, g in f.getBestCmap().items()}
    upem = f["head"].unitsPerEm
    hhea = f["hhea"]
    return _Metrics(advance, upem, advance.get(ord("N"), upem // 2),
                    (hhea.ascent - hhea.descent + hhea.lineGap) / upem)


def width(text: str, font: Path, size: float) -> float:
    m = _metrics(font)
    return sum(m.advance.get(ord(ch), m.fallback) for ch in text) * size / m.upem


def line_height(font: Path, size: float) -> float:
    return _metrics(font).line * size


def wrap(text: str, font: Path, size: float, max_width: float) -> list[str]:
    """Greedy word wrap; a single word wider than the line stays on its own line."""
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if cur and width(trial, font, size) > max_width:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        lines.append(cur)
    while lines and not lines[-1]:
        lines.pop()
    return lines


@dataclass(frozen=True)
class Fit:
    size: int
    lines: list[str]


def fit(text: str, font: Path, *, max_size: int, min_size: int, max_width: float, max_lines: int,
        max_height: float | None = None) -> Fit | None:
    """The largest size from max_size down to min_size at which `text` wraps into at
    most `max_lines` lines no wider than `max_width` (and no taller than
    `max_height`). None: it doesn't fit even at min_size."""
    text = " ".join(text.split()) if "\n" not in text else text.strip()
    if not text:
        return Fit(max_size, [])
    size = max_size
    while size >= min_size:
        lines = wrap(text, font, size, max_width)
        tall = len(lines) * line_height(font, size) * 1.08
        if (len(lines) <= max_lines and all(width(ln, font, size) <= max_width for ln in lines)
                and (max_height is None or tall <= max_height)):
            return Fit(size, lines)
        size -= 2 if size > 40 else 1
    return None
