"""House style for what the models write (owner, 2026-10-20: "remove AI dashes").

Em and en dashes used as punctuation read as machine-written; a model told not to
still slips one in now and then, so every title, caption, comment and line on
screen passes through undash() too: a dash between words becomes a comma (one at
the start or end goes), a range like 2019–2024 keeps its hyphen.
"""

from __future__ import annotations

import re

NO_DASHES = ("Never use em dashes or en dashes (— or –) as punctuation: write a comma, a full stop, a colon or "
             "brackets instead.")

_RANGE = re.compile(r"(?<=\d)\s*[–—]\s*(?=\d)")
_DASH = re.compile(r"\s*[—–]\s*")


def undash(text: str) -> str:
    if not text or ("—" not in text and "–" not in text):
        return text
    out = _RANGE.sub("-", text)
    out = _DASH.sub(", ", out)
    out = re.sub(r"^[,\s]+|[,\s]+$", "", out)
    out = re.sub(r",\s*([,.!?;:])", r"\1", out)
    return re.sub(r"\s{2,}", " ", out)
