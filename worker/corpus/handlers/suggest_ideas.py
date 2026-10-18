"""ideas/suggest_ideas — one category's sources → new, never-repeated idea cards.

Queued by "More ideas" (one category, or every category of a channel) and once a
day per category (private.schedule_daily_ideas, staggered). For the category:

  1. fetch its sources (Reddit communities, news sites, feeds, searches, trends)
     and record how each one did;
  2. cut junk genres and stale items, rank the rest, keep the best few (select.py);
  3. one model call: the format's idea prompt, the category's brief, the numbered
     items — and what was made, suggested or skipped recently. The model may
     return no ideas at all, which is a fine outcome, not a failure;
  4. keep only ideas unlike each other and unlike the channel's memory (Qdrant);
  5. store them with the items they came from; ideas whose items carry a picture
     or video get an attach_media job, which fetches a preview for the card.

Then housekeeping: ideas older than IDEA_MEMORY_DAYS that were not accepted are
deleted, in Postgres and in the memory; accepted ones (posts) are kept.

Payloads from before categories ({"format_id": …}) are mapped to that format's
category.

The category allows some of the channel's formats (all of them when it names
none); the agent picks one per idea — by topic, by what the items carry, by cost
and by how each format has done here — and says why. Formats that need the
owner's own footage are the owner's to pick. The idea prompt is the first allowed
format's (the channel's default when it is allowed).

As idea_from_video (Explore YouTube → "Make an idea"), the payload carries one
YouTube video: it is the only item, one idea is asked for (or none, if it doesn't
suit the channel), the category's sources aren't read, and a category whose
daily batches are off still takes it — the owner asked for this one.
"""

from __future__ import annotations

import httpx
import numpy as np
from psycopg.types.json import Jsonb

from .. import channels, costs, db, prompts, stats, templates, vault
from ..config import settings
from ..ideas import feeds, memory, reddit, select, sources
from ..ideas.agent import OpenAIIdeaWriter
from ..ideas.embed import embed
from ..runner import Handler, JobContext, Permanent
from .write_script import _classify_openai_error

# Swapped by tests.
WRITER_FACTORY = OpenAIIdeaWriter
FETCH = sources.fetch
EMBED = embed
MEMORY = lambda log: memory.connect(settings().qdrant_url, settings().qdrant_api_key, log)  # noqa: E731

EXTRA = 3            # ask for a few more than needed: some will turn out to be repeats
CANDIDATES = 25      # items the model sees after the prefilter
MEDIA_PRIORITY = 80  # previews come after batches, before nothing else waits on them
SOURCE_BACKOFF_H = (1, 3, 12, 24)   # hours to wait after 1, 2, 3, 4+ failures in a row

CATEGORY_BLOCK = """

## Category: {category_name}
{category_brief}
Keywords: {category_keywords}"""

OUTPUT_NOTE = """

## Linking ideas to the items
For each idea, `items` lists the numbers of the items above that it is based on ([] when it
is evergreen). Ideas based on an item marked video or image will show that video or picture
to the owner, so prefer them when the story is equally good."""


def _text(i) -> str:
    return f"{i['title']}. {i['hook']} {i['brief']}"


def _category(c, payload: dict) -> dict | None:
    if payload.get("category_id"):
        return c.execute("select * from categories where id = %s", (payload["category_id"],)).fetchone()
    if payload.get("format_id"):                       # queued before categories existed
        return c.execute("""select k.* from categories k join formats f on f.channel_id = k.channel_id
                             where f.id = %s order by (k.format_id = f.id) desc nulls last, k.created_at
                             limit 1""", (payload["format_id"],)).fetchone()
    return None


def _formats(c, cat: dict) -> list[dict]:
    """The formats the agent may choose from, in the channel's order (its default
    first): the category's, or all of the channel's; not those that need the
    owner's own footage, unless nothing else is allowed."""
    rows = c.execute("select * from formats where channel_id = %s order by is_default desc, created_at",
                     (cat["channel_id"],)).fetchall()
    allowed = set(cat.get("format_ids") or [])
    pool = [f for f in rows if not allowed or f["id"] in allowed] or rows
    pickable = [f for f in pool if templates.get(f["template_id"]).ai_pick]
    return pickable or pool[:1]


def formats_block(fmts: list[dict], performance: dict) -> str:
    if len(fmts) == 1:
        t = templates.get(fmts[0]["template_id"])
        return (f"\n\n## Format\nEvery idea is made as \"{fmts[0]['name']}\" ({t.display_name}: {t.format}). "
                "Set `format` to 1 and `format_why` to \"\".")
    lines = [templates.describe_for_planner(n, f["name"], templates.get(f["template_id"]), performance.get(f["id"], ""))
             for n, f in enumerate(fmts, 1)]
    return ("\n\n## Formats you can make an idea in\n" + "\n".join(lines) + "\n\n"
            "For each idea, `format` is the number of the format that suits it best. Judge by the topic (a list → a "
            "countdown or a carousel; a few striking numbers → an infographic or a picture card; a common belief → "
            "myth vs fact; a process → a timelapse; a story with an arc → documentary), by what its items carry (a "
            "video or pictures to show → a format that uses footage; nothing to show → a generated or text format), "
            "by what the format costs to make, and by how it has done on this channel. Vary formats across the "
            "batch when the ideas allow. `format_why`: a few words on why that format.")


def _record_outcomes(outcomes: list[sources.Outcome]) -> None:
    with db.conn() as c:
        for o in outcomes:
            if o.ok:
                c.execute("""update category_sources set status = 'ok', last_fetched_at = now(), checked_at = now(),
                                    last_items = %s, last_error = null, fail_count = 0, next_try_at = null
                              where id = %s""", (o.items, o.source_id))
            else:
                c.execute("""update category_sources set status = 'error', checked_at = now(), last_error = %s,
                                    fail_count = fail_count + 1,
                                    next_try_at = now() + make_interval(hours =>
                                      (array[%s, %s, %s, %s])[least(fail_count + 1, 4)])
                              where id = %s""", (o.error, *SOURCE_BACKOFF_H, o.source_id))


def _has_media(it: feeds.Item) -> bool:
    """A picture may be had: a post's own media, or an article's lead picture (og:image)."""
    if it.media_hint in ("video", "image", "gallery"):
        return True
    return it.media_hint in ("link", "") and (bool(it.extra.get("thumbnail")) or it.url.startswith("http"))


def _item_json(it: feeds.Item) -> dict:
    return {"title": it.title, "url": it.url, "source": it.source, "summary": it.summary,
            "published": it.published.isoformat() if it.published else None, "rank": it.rank,
            "media_hint": it.media_hint, **{k: v for k, v in it.extra.items() if v not in (None, "", {})}}


def video_item(v: dict) -> feeds.Item:
    """An Explore YouTube result as a trend item (the shape social.youtube() gives)."""
    thumb = v.get("thumbnail")
    return feeds.Item(source=f"YouTube · {v.get('channel') or 'video'}", title=str(v["title"])[:200],
                      summary=str(v.get("description") or "")[:240],
                      url=f"https://www.youtube.com/watch?v={v['id']}", published=feeds._when(v.get("published")),
                      rank=0, media_hint="image" if thumb else "self",
                      extra={"platform": "youtube", "author": v.get("channel"), "image_url": thumb, "thumbnail": thumb,
                             "views": int(v.get("views") or 0), "score": int(v.get("likes") or 0),
                             "comments": int(v.get("comments") or 0)})


def run(ctx: JobContext) -> dict:
    log = lambda m: print(f"[suggest_ideas] {m}", flush=True)  # noqa: E731
    video = ctx.payload.get("video")
    with db.conn() as c:
        cat = _category(c, ctx.payload)
        if cat is None:
            return {"skipped": "category deleted"}
        if not cat["enabled"] and not video:
            return {"skipped": "category is turned off"}
        if ctx.payload.get("trigger") == "daily" and c.execute(
                "select 1 from channels where id = %s and ideas_paused_until > now()", (cat["channel_id"],)).fetchone():
            return {"skipped": "daily ideas are paused for this channel"}
        fmts = _formats(c, cat)
        if not fmts:
            return {"skipped": "channel has no format"}
        fmt = fmts[0]                       # its idea prompt finds the ideas
        st = c.execute("select * from app_settings where user_id = %s", (cat["user_id"],)).fetchone() or {}
        prof = channels.profile(c, cat["user_id"], cat["channel_id"])
        rows = c.execute("""select id, kind, value, options from category_sources
                             where category_id = %s and enabled and (next_try_at is null or next_try_at <= now())
                             order by created_at""", (cat["id"],)).fetchall()
        avoid = [r["t"] for r in c.execute(
            """select topic as t from posts where channel_id = %s and created_at > now() - interval '120 days'
               union all
               select title from ideas where channel_id = %s and status <> 'rejected'
                 and created_at > now() - interval '30 days'
               limit 120""", (cat["channel_id"], cat["channel_id"])).fetchall()]
        rejected = c.execute("""select title, reject_reason from ideas where channel_id = %s and status = 'rejected'
                                   and created_at > now() - interval '30 days'
                                 order by decided_at desc limit 25""", (cat["channel_id"],)).fetchall()
        performance = stats.summary(c, cat["channel_id"])
        per_format = stats.by_format(c, cat["channel_id"])
    model = st.get("script_model")
    if not model:
        raise Permanent("Choose a script model in Settings.", stage="config")
    if why := db.over_quota(cat["user_id"]):
        return {"skipped": why}
    key = vault.secret(cat["user_id"], "openai")
    if not key:
        raise Permanent("Add your OpenAI API key in Settings.", stage="config")

    if video:
        items = cands = [video_item(video)]
        cuts: dict = {}
    else:
        with httpx.Client(timeout=30) as client:
            rid, rsecret = (vault.secret(cat["user_id"], "reddit_client_id"),
                            vault.secret(cat["user_id"], "reddit_client_secret"))
            api = reddit.RedditAPI(client, rid, rsecret) if rid and rsecret else None
            items, outcomes = FETCH(rows, client=client, api=api, log=log,
                                    youtube_key=vault.secret(cat["user_id"], "youtube_api_key"))
        _record_outcomes(outcomes)
        cands, cuts = select.prefilter(items, keep=CANDIDATES)
        if cuts:
            log("cut before the model: " + ", ".join(f"{n} {why}" for why, n in sorted(cuts.items())))

    count = 1 if video else cat["ideas_per_batch"]
    template = fmt["idea_prompt"]
    if "{category_name}" not in template:
        template += CATEGORY_BLOCK
    system = prompts.fill(template + performance + formats_block(fmts, per_format) + OUTPUT_NOTE, {
        **{k: prof.get(k) or "(not set)" for k in channels.PROFILE_KEYS},
        "format_name": fmt["name"], "format_description": fmt["description"] or "(none)",
        "category_name": cat["name"],
        "category_brief": cat["brief"] or "(no category prompt: follow the channel's niche)",
        "category_keywords": cat["keywords"] or "(none)",
        "trends": feeds.as_prompt(cands),
        "avoid": "\n".join(f"- {t}" for t in avoid) or "(nothing yet)",
        "rejected": "\n".join(f"- {r['title']}" + (f" — {r['reject_reason']}" if r["reject_reason"] else "")
                              for r in rejected) or "(nothing yet)",
        "count": count if video else count + EXTRA,
    })
    billed = dict(user_id=cat["user_id"], channel_id=cat["channel_id"], category_id=cat["id"],
                  job_id=ctx.job.get("id"))
    try:
        ask = ("The owner picked item 1, a trending YouTube video. Make one idea for this channel from its "
               "story — our own video about it, never a copy of theirs — or none if it doesn't fit the channel."
               if video else f"Suggest up to {count + EXTRA} ideas now, or none.")
        out, usage = WRITER_FACTORY(key).write(model=model, system=system, user=ask)
    except Exception as e:  # noqa: BLE001 - classified like the script writer's
        if getattr(e, "usage", None) is not None:
            costs.record_llm(e.usage, note="unparsable idea batch", **billed)
        raise _classify_openai_error(e) from e
    costs.record_llm(usage, note=f"idea from a YouTube video: {cat['name']}" if video else f"ideas: {cat['name']}",
                     **billed)
    cands_ideas = [i.model_dump() for i in out.ideas]
    if not cands_ideas:
        log(f"{cat['name']}: nothing worth making today ({len(items)} items read)")
        return {"ideas": 0, "trend_items": len(items), "nothing_worth_making": True}

    mem = MEMORY(log)
    vecs = EMBED([_text(i) for i in cands_ideas])
    channel = str(cat["channel_id"])
    kept, kept_vecs, repeats = [], [], []
    for idea, v in zip(cands_ideas, vecs):
        if kept_vecs and float(np.max(np.array(kept_vecs) @ v)) >= memory.SIMILAR:
            repeats.append((idea["title"], "same as another idea in this batch"))
            continue
        score, like = mem.nearest(channel, v.tolist())
        if score >= memory.SIMILAR:
            repeats.append((idea["title"], f"like \"{like}\" ({score:.2f})"))
            continue
        kept.append(idea)
        kept_vecs.append(v)
        if len(kept) == count:
            break
    for t, why in repeats:
        log(f"dropped as a repeat: {t} — {why}")

    rows_out = []
    with db.tx() as c:
        for i in kept:
            its = [cands[n - 1] for n in dict.fromkeys(i["items"]) if 1 <= n <= len(cands)][:5]
            media = any(_has_media(it) for it in its)
            chosen = fmts[i["format"] - 1] if 1 <= i.get("format", 0) <= len(fmts) else fmt
            rid = c.execute(
                """insert into ideas (user_id, channel_id, format_id, category_id, title, hook, brief, why_now,
                                      sources, items, media_state, batch_job_id, format_why)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                (cat["user_id"], cat["channel_id"], chosen["id"], cat["id"], i["title"][:200], i["hook"], i["brief"],
                 i["why_now"], Jsonb([{"url": it.url, "title": it.title} for it in its if it.url]),
                 Jsonb([_item_json(it) for it in its]), "pending" if media else "none",
                 ctx.job.get("id"), (i.get("format_why") or "")[:200] if len(fmts) > 1 else "")).fetchone()["id"]
            rows_out.append(rid)
            if media:
                db.enqueue(c, user_id=cat["user_id"], lane="ideas", kind="attach_media",
                           dedupe_key=f"attach_media:{rid}", payload={"idea_id": str(rid)},
                           priority=MEDIA_PRIORITY, max_attempts=2, lease_seconds=600)
    mem.remember([{"id": rid, "vector": v.tolist(), "channel_id": channel, "kind": "idea", "title": i["title"]}
                  for rid, v, i in zip(rows_out, kept_vecs, kept)])
    _remember_posts(mem, cat["channel_id"])
    forgotten = _forget_old(mem, cat["channel_id"])
    log(f"{cat['name']}: {len(kept)} new ideas, {len(repeats)} repeats dropped, {len(items)} items read")
    return {"ideas": len(kept), "repeats": len(repeats), "trend_items": len(items), "candidates": len(cands),
            "cut": cuts, "forgotten": forgotten, "tokens": usage.input_tokens + usage.output_tokens,
            "trigger": ctx.payload.get("trigger")}


def _remember_posts(mem, channel_id) -> None:
    """Posts made by hand (not from an idea) count as done too; re-sending the
    recent ones is idempotent (the point id is the post id)."""
    with db.conn() as c:
        posts = c.execute("""select id, topic from posts where channel_id = %s
                               and created_at > now() - interval '30 days'""", (channel_id,)).fetchall()
    if posts:
        vecs = EMBED([p["topic"] for p in posts])
        mem.remember([{"id": p["id"], "vector": v.tolist(), "channel_id": str(channel_id), "kind": "post",
                       "title": p["topic"]} for p, v in zip(posts, vecs)])


def _forget_old(mem, channel_id) -> int:
    """Ideas not accepted within IDEA_MEMORY_DAYS are deleted (their card media is
    removed by the ideas lane's sweeper, which finds it orphaned)."""
    with db.tx() as c:
        gone = [r["id"] for r in c.execute(
            f"""delete from ideas where channel_id = %s and status <> 'accepted'
                   and created_at < now() - interval '{memory.IDEA_MEMORY_DAYS} days' returning id""",
            (channel_id,)).fetchall()]
    mem.forget(gone)
    return len(gone)


HANDLER = Handler(run=run)
