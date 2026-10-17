"""What a template draws over a shot: one ASS file per segment, rendered by libass.

  captions   "karaoke"/"speech": the spoken words in groups, the active one
             enlarged in the accent colour (assemble.captions_ass's events);
             "beats": the shot's `text`, large in the middle, popping in;
             "kinetic": the words themselves as the picture — one to three at a
             time, popping in on their beat (the narration's timing, or spread
             evenly over the shot), CAPITALISED words in the accent colour;
             "none": nothing.
  headline   the shot's `text` at the top (in a split screen: at the top of the
             bottom panel), wrapped and sized exactly as the script check measured.
  label      a chip ("MYTH" red, "FACT" green, others in the accent colour) or a
             big rank number ("#3").

Every size and wrap comes from media/text.py, as in script/structure.py.
"""

from __future__ import annotations

import re

from . import text as tx

W, H = 1080, 1920
SPLIT_Y = 960                     # a split screen's panel starts here
HEADLINE = dict(max_size=66, min_size=50, max_lines=3)
BEAT = dict(max_size=92, min_size=62, max_lines=5)
KINETIC = 176                     # the largest kinetic word; longer groups shrink to fit
RANK = re.compile(r"^#\s*(\d{1,2})$")
CHIP_COLOURS = {"myth": "#EF4444", "fact": "#22C55E", "false": "#EF4444", "true": "#22C55E",
                "unconfirmed": "#F59E0B", "developing": "#F59E0B", "confirmed": "#22C55E"}
BS = chr(92)                      # a literal backslash, for ASS override tags


def ass_colour(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _ts(t: float) -> str:
    t = max(t, 0.0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    """Text as ASS shows it literally: braces would start override blocks."""
    return text.replace(BS, "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def _ass_size(font, px: float) -> float:
    """libass sizes a font by ascent+descent, not by its em (see assemble._ass_font_size)."""
    from fontTools.ttLib import TTFont

    f = _font_cache.get(font)
    if f is None:
        t = TTFont(font)
        f = _font_cache[font] = (t["OS/2"].usWinAscent + t["OS/2"].usWinDescent) / t["head"].unitsPerEm
    return px * f


_font_cache: dict = {}


def styles(look) -> list[str]:
    """The overlay styles (the caption style "Cap" is added by the caller)."""
    _, _, name, bold = tx.family(look.font)
    heavy = tx.heavy(look.font)
    white, accent = ass_colour(look.primary_color), ass_colour(look.accent_color)
    m = look.safe_margin_px

    def st(n, size, prim, outline_col, back, border, outline, shadow, align, mv):
        return (f"Style: {n},{name},{_ass_size(heavy, size):.0f},{prim},{prim},{outline_col},{back},{bold},0,0,0,"
                f"100,100,0,0,{border},{outline},{shadow},{align},{m},{m},{mv},1")
    return [
        st("Head", 66, white, "&H00000000", "&H96000000", 1, 6, 3, 8, 300),
        st("Beat", 92, white, "&H5A000000", "&H00000000", 3, 26, 0, 5, 0),
        st("Chip", 42, "&H00FFFFFF", accent, "&H00000000", 3, 14, 0, 7, 0),
        st("Rank", 150, accent, "&H00000000", "&H96000000", 1, 8, 4, 7, 0),
        st("Kin", KINETIC, white, "&H00000000", "&H96000000", 1, 9, 4, 5, 0),
    ]


def _fitted(text: str, font, spec: dict, width: float) -> tuple[int, str] | None:
    f = tx.fit(text, font, max_width=width, **spec)
    if f is None:
        return None
    return f.size, f"{BS}N".join(_esc(ln) for ln in f.lines)


def headline(text: str, look, seconds: float, split: bool, label: str = "") -> list[str]:
    if not text.strip():
        return []
    heavy = tx.heavy(look.font)
    width = W - 2 * look.safe_margin_px
    got = _fitted(text, heavy, HEADLINE, width) or _fitted(text, heavy, {**HEADLINE, "max_lines": 4,
                                                                        "min_size": 40}, width)
    if got is None:
        return []
    size, body = got
    y = SPLIT_Y + 36 if split else 400 if RANK.match(label.strip()) else 300     # below a big rank number
    fs = f"{BS}fs{_ass_size(heavy, size):.0f}"
    return [f"Dialogue: 2,{_ts(0)},{_ts(seconds)},Head,,0,0,0,,{{{BS}an8{BS}pos({W // 2},{y}){fs}{BS}fad(180,0)}}"
            f"{body}"]


def beat(text: str, look, seconds: float, split: bool) -> list[str]:
    if not text.strip():
        return []
    heavy = tx.heavy(look.font)
    width = W - 2 * look.safe_margin_px - 52            # the box's padding
    got = _fitted(text, heavy, BEAT, width) or _fitted(text, heavy, {**BEAT, "min_size": 44, "max_lines": 7}, width)
    if got is None:
        return []
    size, body = got
    y = (SPLIT_Y + (H - SPLIT_Y) // 2) if split else H // 2
    fs = f"{BS}fs{_ass_size(heavy, size):.0f}"
    pop = f"{BS}fscx88{BS}fscy88{BS}t(0,200,{BS}fscx100{BS}fscy100){BS}fad(140,120)"
    return [f"Dialogue: 2,{_ts(0)},{_ts(seconds)},Beat,,0,0,0,,{{{BS}an5{BS}pos({W // 2},{y}){fs}{pop}}}{body}"]


def label(text: str, look, seconds: float) -> list[str]:
    t = text.strip()
    if not t:
        return []
    m = look.safe_margin_px
    if RANK.match(t):
        n = RANK.match(t).group(1)
        return [f"Dialogue: 3,{_ts(0)},{_ts(seconds)},Rank,,0,0,0,,{{{BS}an7{BS}pos({m},{170}){BS}fscx70{BS}fscy70"
                f"{BS}t(0,180,{BS}fscx100{BS}fscy100)}}#{n}"]
    colour = CHIP_COLOURS.get(t.lower())
    box = f"{BS}3c{ass_colour(colour)}" if colour else ""
    return [f"Dialogue: 3,{_ts(0)},{_ts(seconds)},Chip,,0,0,0,,{{{BS}an7{BS}pos({m + 14},{200}){box}{BS}fad(120,0)}}"
            f"{_esc(t.upper())}"]


def kinetic(words: list[tuple[float, float, str]], look, seconds: float, split: bool) -> list[str]:
    """Words popping onto the screen one beat at a time: one word, or two short ones
    said close together (at most 12 letters); a stressed (CAPITALISED) word is always
    alone, larger, in the accent colour. Each shows until the next."""
    if not words:
        return []
    heavy = tx.heavy(look.font)
    accent, white = ass_colour(look.accent_color), ass_colour(look.primary_color)
    width = W - 2 * look.safe_margin_px
    groups: list[list[tuple[float, float, str]]] = []
    def stressed(word: str) -> bool:
        clean = word.strip(",.;:!?\"“”")
        return len(clean) > 1 and clean.isupper()

    for w in words:
        last = groups[-1] if groups else None
        if (last and len(last) < 2 and w[0] - last[-1][1] < 0.35 and not last[-1][2].endswith((".", "!", "?", ","))
                and len(last[-1][2]) + len(w[2]) <= 12 and not stressed(w[2]) and not stressed(last[-1][2])):
            last.append(w)
        else:
            groups.append([w])
    y = (SPLIT_Y + (H - SPLIT_Y) // 2) if split else int(H * 0.47)
    out = []
    for k, g in enumerate(groups):
        start = g[0][0]
        stop = groups[k + 1][0][0] if k + 1 < len(groups) else min(seconds, g[-1][1] + 0.6)
        if stop <= start:
            continue
        shown = []
        for _, _, w in g:
            clean = w.strip(",.;:\"“”")
            emph = len(clean) > 1 and clean.isupper()
            shown.append((clean.upper(), emph))
        line = " ".join(w for w, _ in shown)
        size = KINETIC
        while size > 70 and tx.width(line, heavy, size) > width:
            size -= 4
        sep = f"{BS}N" if tx.width(line, heavy, size) > width else " "   # three long words: one per line
        body = sep.join((f"{{{BS}c{accent}&}}{_esc(w)}{{{BS}c{white}&}}" if e else _esc(w)) for w, e in shown)
        pop = f"{BS}fscx60{BS}fscy60{BS}t(0,140,{BS}fscx108{BS}fscy108){BS}t(140,220,{BS}fscx100{BS}fscy100)"
        out.append(f"Dialogue: 2,{_ts(start)},{_ts(stop)},Kin,,0,0,0,,{{{BS}an5{BS}pos({W // 2},{y})"
                   f"{BS}fs{_ass_size(heavy, size):.0f}{pop}}}{body}")
    return out


def even_words(text: str, seconds: float, lead: float = 0.25) -> list[tuple[float, float, str]]:
    """A text with no voice, spread evenly over the shot for kinetic typography."""
    words = text.split()
    if not words:
        return []
    span = max(0.5, seconds - lead - 0.4)
    step = span / len(words)
    return [(lead + i * step, lead + (i + 1) * step, w) for i, w in enumerate(words)]


def document(look, cap_style_line: str, events: list[str]) -> str:
    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        cap_style_line, *styles(look), "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *events, ""])
