"""Caption styles and cover styles, and Jev's pick of each for a post.

  prompts/caption_styles/<id>.json   the words on screen: font, colours, a box,
                                     how the spoken word stands out, how it arrives
  prompts/thumb_styles/<id>.json     the cover's layout (media/thumbnail.py draws it)

Each has families (news, explainer, story, meme, ad): a post is offered the styles
of its own kind — a meme format's posts the meme styles, every other post the rest.
The owner switches styles on in Settings → Styles; Jev picks among those.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import logging

from .config import settings
from .jev import Jev
from .media.assemble import CaptionStyle

log = logging.getLogger("corpus.styles")
SURE = 0.4
NORMAL = {"news", "explainer", "story"}


@functools.lru_cache(maxsize=2)
def _load(kind: str) -> dict[str, dict]:
    out = {}
    for f in sorted((settings().prompts_dir / kind).glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out[d["id"]] = d
    return out


def captions() -> dict[str, dict]:
    return _load("caption_styles")


def thumbs() -> dict[str, dict]:
    return _load("thumb_styles")


def family_of(template_id: str | None) -> str:
    t = template_id or ""
    return "meme" if "meme" in t else "ad" if t.startswith("ad_") or "_ad" in t else "news"


def caption_style(preset: str | None) -> CaptionStyle | None:
    d = captions().get(preset or "")
    if not d:
        return None
    fields = {f.name for f in dataclasses.fields(CaptionStyle)}
    return CaptionStyle(**{k: v for k, v in d["style"].items() if k in fields})


def _offered(all_: dict[str, dict], enabled: list[str] | None, family: str) -> list[dict]:
    wanted = {family} if family in ("meme", "ad") else NORMAL
    on = [all_[i] for i in (enabled or all_) if i in all_ and wanted & set(all_[i]["families"])]
    return on or [d for d in all_.values() if wanted & set(d["families"])][:1]


def _choose(judge: Jev | None, items: list[dict], question: str, state: dict, fallback: str) -> tuple[str, str]:
    if not items:
        return fallback, "the default"
    if judge is None or len(items) < 2:
        first = next((d for d in items if d["id"] == fallback), items[0])
        return first["id"], "the first switched on"
    criteria = {f"c{i}": f"{d['name']}: {d['description']} Best for {', '.join(d['best_for'])}."
                for i, d in enumerate(items)}
    try:
        a = judge.ask(state, {"style": {"type": "choice", "instructions": question, "criteria": criteria}})
        pick = a.get("style") or {}
        ch, conf = str(pick.get("choice") or ""), float(pick.get("confidence") or 0)
        if ch.startswith("c") and ch[1:].isdigit() and int(ch[1:]) < len(items) and conf >= SURE:
            return items[int(ch[1:])]["id"], f"Jev's pick ({round(conf * 100)}% sure)"
    except Exception as e:  # noqa: BLE001 - a style is still needed
        log.warning("style choice: %s", e)
    first = next((d for d in items if d["id"] == fallback), items[0])
    return first["id"], "the default"


def choose_caption(judge: Jev | None, enabled: list[str] | None, *, story: str, category: str = "",
                   template: str | None = None) -> tuple[str, str]:
    """(caption style id, why) for a post's on-screen captions."""
    fam = family_of(template)
    return _choose(judge, _offered(captions(), enabled, fam),
                   "Which caption style makes `story` most watchable on a phone, for this `category` and `format`?",
                   {"story": story[:1500], "category": category or "news", "format": template or "short video"},
                   "meme_impact" if fam == "meme" else "ad_punchy" if fam == "ad" else "bold_pop")


def choose_thumb(judge: Jev | None, enabled: list[str] | None, *, title: str, line: str, story: str,
                 template: str | None = None, has_before: bool = False, has_number: bool = False) -> tuple[str, str]:
    """(cover style id, why). Before/Now only with a picture of the place before; Big number
    only when the line has a number in it."""
    fam = family_of(template)
    items = [d for d in _offered(thumbs(), enabled, fam)
             if (d["id"] != "before_now" or has_before) and (d["id"] != "big_number" or has_number)]
    return _choose(judge, items,
                   "Which cover layout makes the most people tap on a video titled `title` with the cover line `line`, "
                   "truthfully, given `story`?",
                   {"title": title[:200], "line": line[:80], "story": story[:1200]},
                   "before_now" if has_before else "classic")
