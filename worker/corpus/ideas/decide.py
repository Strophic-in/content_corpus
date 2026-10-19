"""The idea agent's fast decisions, made by Jev (corpus/jev.py) when a key is set.

rank         after the junk/staleness prefilter: each item is scored for fitting
             the category, being trending today and being a genuine report;
             items that plainly don't fit are dropped and the best KEEP go to the
             writer, best first. Fewer, better items: a cheaper, sharper writer call.
pick_format  for each idea, which of the category's formats suits it — judged on
             the idea, the media its items carry, each format's cost and how it has
             done on this channel. The writer's own pick stands when Jev is unsure.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .. import templates
from ..jev import Jev, score, yes
from .feeds import Item

KEEP = 12
MIN_FIT = 0.8           # of 3: "loosely related" or better
SURE = 0.35             # Jev's confidence needed to override the writer's format


def _item_text(it: Item) -> str:
    when = it.published.strftime("%d %b %Y") if it.published else "unknown date"
    extra = []
    for k in ("views", "score", "comments"):
        if it.extra.get(k):
            extra.append(f"{k}: {it.extra[k]}")
    return (f"{it.source} — {it.title}. {it.summary[:400]} (published {when}"
            + (f"; {', '.join(extra)}" if extra else "") + ")")


RANK_QUESTIONS = {
    "fits": {"type": "score", "instructions": "How well does `item` fit `category`?",
             "criteria": ["Unrelated to the category", "Loosely related", "Clearly in the category",
                          "Exactly what the category is looking for"]},
    "trending": {"type": "score",
                 "instructions": "How much are people following the story in `item` on `today`?",
                 "criteria": ["Routine; few would care today", "Of interest to some people",
                              "Widely discussed today", "A major story many people are following right now"]},
    "genuine": {"type": "noul",
                "instructions": "Is `item` a genuine news report or post about a real event (not an ad, promotion, "
                                "quiz, horoscope or listicle)?"},
}


def rank(jev: Jev, cands: list[Item], category: dict, keep: int = KEEP) -> tuple[list[Item], dict]:
    """(the best `keep` items, best first; what was decided). Items Jev couldn't
    judge keep their place after the judged ones."""
    if len(cands) <= 3:
        return cands, {}
    cat = f"{category['name']}: {category.get('brief') or 'whatever suits the channel'}"
    today = datetime.now(timezone.utc).strftime("%d %B %Y")
    answers = jev.many([({"item": _item_text(it), "category": cat, "today": today}, RANK_QUESTIONS)
                        for it in cands])
    judged, unjudged, dropped = [], [], 0
    for it, a in zip(cands, answers):
        if a is None:
            unjudged.append(it)
            continue
        fit = score(a.get("fits"))
        if fit < MIN_FIT:
            dropped += 1
            continue
        judged.append((fit + 0.8 * score(a.get("trending")) + 1.5 * yes(a.get("genuine")), it))
    judged.sort(key=lambda x: x[0], reverse=True)
    out = [it for _, it in judged] + unjudged
    return out[:keep], {"judged": len(cands) - len(unjudged), "dropped_off_topic": dropped, "kept": min(keep, len(out))}


def _media(its: list[Item]) -> str:
    kinds = {it.media_hint for it in its}
    if "video" in kinds:
        return "a video of the story"
    if kinds & {"image", "gallery"}:
        return "pictures of the story"
    return "no pictures or video"


PLACE_SURE = 0.75
PLACE_CHANGED = {"type": "noul", "instructions":
                 "Is the most striking picture of `idea` a specific, named place, landmark, building or landscape "
                 "that was damaged, destroyed, flooded or transformed - so that showing it before, then now, tells "
                 "the story at a glance?"}


def pick_format(jev: Jev, ideas: list[dict], items_of: list[list[Item]], fmts: list[dict],
                performance: dict) -> list[tuple[int | None, float]]:
    """For each idea, (the index of the format Jev picked, its confidence) — or
    (None, 0) where it couldn't decide."""
    if len(fmts) < 2 or not ideas:
        return [(None, 0.0)] * len(ideas)
    criteria = {}
    for n, f in enumerate(fmts):
        t = templates.get(f["template_id"])
        criteria[f"f{n}"] = (f"{f['name']}: {f.get('description') or t.format}. Best for {', '.join(t.best_for)}. Needs "
                             f"{', '.join(t.required_assets).replace('_', ' ')}. Cost: {t.estimated_render_cost}. "
                             + (performance.get(f["id"]) or ""))
    # Live, 68 of 71 ideas went to the two narrated explainers (owner, 2026-10-19): the
    # instructions say what each kind of format is for, so the story's shape decides.
    q = {"format": {"type": "choice", "criteria": criteria,
                    "instructions": "Which format makes the best short post of `idea`, given `media` and each "
                                    "format's cost and record on this channel? Match the format to the shape of the "
                                    "story, not to its topic - being news is not a reason to pick a news format. A "
                                    "narrated explainer suits a story that needs explaining (a why, a how, numbers, a "
                                    "process); a format without narration suits a story the pictures tell by "
                                    "themselves (a moment caught on camera, an incident, a spectacle, something "
                                    "satisfying or surprising to watch), above all when `media` has a video; a "
                                    "before/after suits a place that changed; a list or countdown suits several "
                                    "items; a carousel or picture card suits a quick fact to read. Prefer the "
                                    "cheaper format when two fit equally well."}}
    # A choice among many formats leans on "it's news" (live: a town hall spire burning
    # went to the news explainer); a yes/no on the one thing a before/after needs is
    # sharper, and wins when Jev is sure.
    before_after = next((n for n, f in enumerate(fmts) if f["template_id"] == "before_after_comparison"), None)
    if before_after is not None:
        q["place_changed"] = PLACE_CHANGED
    answers = jev.many([({"idea": f"{i['title']}. {i['hook']} {i['brief']}", "media": _media(its)}, q)
                        for i, its in zip(ideas, items_of)])
    out = []
    for a in answers:
        changed = yes((a or {}).get("place_changed"), 0.0) if before_after is not None else 0.0
        if changed >= PLACE_SURE:
            out.append((before_after, changed))
            continue
        pick = (a or {}).get("format") or {}
        choice, conf = pick.get("choice"), float(pick.get("confidence") or 0)
        if choice and choice.startswith("f") and choice[1:].isdigit() and int(choice[1:]) < len(fmts):
            out.append((int(choice[1:]), conf))
        else:
            out.append((None, 0.0))
    return out
