"""cpu/suggest_ideas — free trend feeds → new, never-repeated video ideas to swipe.

Queued by the app's "Find ideas" button and once a day per channel (at its
ideas_daily_at; see private.schedule_daily_ideas). For the format's channel:

  1. read the format's free feeds (Wikipedia most-read, Google Trends, science news…)
  2. ask the model, with the format's idea prompt, for a few more ideas than needed,
     telling it what was made, suggested or skipped (and why) recently
  3. keep only ideas that are new: unlike each other and unlike anything in the
     channel's memory (Qdrant, local bge-small embeddings, cosine ≥ SIMILAR = repeat)
  4. store them as 'new' ideas and remember them

Then housekeeping: ideas older than IDEA_MEMORY_DAYS that were not accepted are
deleted, in Postgres and in the memory; accepted ones (posts) are kept.
"""

from __future__ import annotations

import numpy as np
from psycopg.types.json import Jsonb

from .. import channels, db, prompts, vault
from ..config import settings
from ..ideas import feeds, memory
from ..ideas.agent import OpenAIIdeaWriter
from ..ideas.embed import embed
from ..runner import Handler, JobContext, Permanent, Retryable
from .write_script import _classify_openai_error

# Swapped by tests.
WRITER_FACTORY = OpenAIIdeaWriter
FETCH = feeds.fetch_all
EMBED = embed
MEMORY = lambda log: memory.connect(settings().qdrant_url, settings().qdrant_api_key, log)  # noqa: E731

EXTRA = 4   # ask for a few more than needed: some will turn out to be repeats


def _text(i) -> str:
    return f"{i['title']}. {i['hook']} {i['brief']}"


def run(ctx: JobContext) -> dict:
    log = lambda m: print(f"[suggest_ideas] {m}", flush=True)  # noqa: E731
    with db.conn() as c:
        fmt = c.execute("select * from formats where id = %s", (ctx.payload["format_id"],)).fetchone()
        if fmt is None:
            return {"skipped": "format deleted"}
        st = c.execute("select * from app_settings where user_id = %s", (fmt["user_id"],)).fetchone() or {}
        prof = channels.profile(c, fmt["user_id"], fmt["channel_id"])
        avoid = [r["t"] for r in c.execute(
            """select topic as t from posts where channel_id = %s and created_at > now() - interval '120 days'
               union all
               select title from ideas where channel_id = %s and status <> 'rejected'
                 and created_at > now() - interval '30 days'
               limit 120""", (fmt["channel_id"], fmt["channel_id"])).fetchall()]
        rejected = c.execute("""select title, reject_reason from ideas where channel_id = %s and status = 'rejected'
                                   and created_at > now() - interval '30 days'
                                 order by decided_at desc limit 25""", (fmt["channel_id"],)).fetchall()
    model = st.get("script_model")
    if not model:
        raise Permanent("Choose a script model in Settings.", stage="config")
    key = vault.secret(fmt["user_id"], "openai")
    if not key:
        raise Permanent("Add your OpenAI API key in Settings.", stage="config")

    count = fmt["ideas_per_batch"]
    items = FETCH(fmt["sources"] or feeds.default_sources(), log=log)
    system = prompts.fill(fmt["idea_prompt"], {
        **{k: prof.get(k) or "(not set)" for k in channels.PROFILE_KEYS},
        "format_name": fmt["name"], "format_description": fmt["description"] or "(none)",
        "trends": feeds.as_prompt(items),
        "avoid": "\n".join(f"- {t}" for t in avoid) or "(nothing yet)",
        "rejected": "\n".join(f"- {r['title']}" + (f" — {r['reject_reason']}" if r["reject_reason"] else "")
                              for r in rejected) or "(nothing yet)",
        "count": count + EXTRA,
    })
    try:
        out, usage = WRITER_FACTORY(key).write(model=model, system=system,
                                               user=f"Suggest {count + EXTRA} ideas now.")
    except Exception as e:  # noqa: BLE001 - classified like the script writer's
        raise _classify_openai_error(e) from e
    cands = [i.model_dump() for i in out.ideas]
    if not cands:
        raise Retryable("the model suggested no ideas", stage="llm")

    mem = MEMORY(log)
    vecs = EMBED([_text(i) for i in cands])
    channel = str(fmt["channel_id"])
    kept, kept_vecs, repeats = [], [], []
    for idea, v in zip(cands, vecs):
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

    with db.tx() as c:
        rows = [c.execute("""insert into ideas (user_id, channel_id, format_id, title, hook, brief, why_now, sources)
                             values (%s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                          (fmt["user_id"], fmt["channel_id"], fmt["id"], i["title"][:200], i["hook"], i["brief"],
                           i["why_now"], Jsonb([{"url": u} for u in i["sources"][:5]]))).fetchone()["id"]
                for i in kept]
    mem.remember([{"id": rid, "vector": v.tolist(), "channel_id": channel, "kind": "idea", "title": i["title"]}
                  for rid, v, i in zip(rows, kept_vecs, kept)])
    _remember_posts(mem, fmt["channel_id"])
    forgotten = _forget_old(mem, fmt["channel_id"])
    log(f"{len(kept)} new ideas, {len(repeats)} repeats dropped, {len(items)} trend items read")
    return {"ideas": len(kept), "repeats": len(repeats), "trend_items": len(items), "forgotten": forgotten,
            "tokens": usage.input_tokens + usage.output_tokens, "trigger": ctx.payload.get("trigger")}


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
    with db.tx() as c:
        gone = [r["id"] for r in c.execute(
            f"""delete from ideas where channel_id = %s and status <> 'accepted'
                   and created_at < now() - interval '{memory.IDEA_MEMORY_DAYS} days' returning id""",
            (channel_id,)).fetchall()]
    mem.forget(gone)
    return len(gone)


HANDLER = Handler(run=run)
