"""ideas/auto_pick — the day's post, when the owner hasn't picked one.

Queued once a day per channel with daily_auto_post on (private.schedule_daily_pick,
at the channel's daily_pick_at). On a day the owner was there — they pressed "More
ideas" and picked something for today — a post for today is already on its way,
and this stands aside. Otherwise it takes the channel's single best story of the
day — or its best few, channels.daily_auto_count, topped up to that many around the
owner's own picks — and makes and posts them on autopilot (owner, 2026-10-19):

  1. every enabled category's sources are read (no model call);
  2. Jev scores each story (fit, trending today, a genuine report, and its pull —
     how many of the audience would stop and tap) and the best one overall wins,
     unless the channel covered the same story lately;
  3. it becomes an idea straight from the story itself — no idea-writing call, the
     tokens are saved — in the format Jev picks for it;
  4. the idea is accepted for today at the channel's posting time (or soon, when
     that time is too close) and put on autopilot: its sources are read, its
     assets collected, the script written, voiced, rendered and posted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from psycopg.types.json import Jsonb

from .. import channels, db, jev, vault
from ..ideas import decide, reddit, select, voice
from ..research import sig_tokens
from ..runner import Handler, JobContext
from . import suggest_ideas as si

# What's "on its way" for a day: anything past a plain draft, or a draft set to go.
UNDER_WAY = ("scripting", "awaiting_approval", "approved", "queued_for_render", "rendering", "rendered",
             "post_processing", "ready", "scheduled", "published")
LEAD = timedelta(minutes=90)        # the least time between the pick and the post going out
SPACING = timedelta(minutes=90)     # between a day's automatic posts
WHY_NOW = "Today's top story"       # marks an automatic pick's idea
SAME_STORY = 0.6                    # share of a story's words already in a recent post's topic


def _covered(title: str, recent: list[str]) -> bool:
    words = sig_tokens(title)
    return bool(words) and any(len(words & sig_tokens(t)) / len(words) >= SAME_STORY for t in recent)


def _on_its_way(c, ch: dict, today) -> int:
    """Posts going out today: the owner's picks (anything past a plain draft, or set
    to go) and today's automatic picks (a late one's post may fall past midnight)."""
    return c.execute(
        """select count(distinct p.id) as n from posts p
            where p.channel_id = %s
              and ((p.slot_date = %s and (p.status = any(%s) or p.go_ahead or p.pipeline_mode = 'auto'))
                   or p.id in (select i.post_id from ideas i where i.channel_id = %s and i.why_now = %s
                                 and i.created_at >= (%s::date::timestamp at time zone %s)))""",
        (ch["id"], today, list(UNDER_WAY), ch["id"], WHY_NOW, today, ch["timezone"])).fetchone()["n"]


def _choose(scored: list, n: int) -> list:
    """The best n stories, each a different story, from different categories while
    there are good ones in others (a category's second best waits for the others' best)."""
    picked: list = []
    rest = sorted(scored, key=lambda x: x[0], reverse=True)
    while rest and len(picked) < n:
        used = {c["id"] for _, _, c in picked}
        fresh = [x for x in rest if x[2]["id"] not in used]
        pick = (fresh or rest)[0]
        picked.append(pick)
        rest = [x for x in rest if x is not pick and not _covered(x[1].title, [p[1].title for p in picked])]
    return picked


def run(ctx: JobContext) -> dict:
    log = lambda m: print(f"[auto_pick] {m}", flush=True)  # noqa: E731
    with db.conn() as c:
        ch = c.execute("select * from channels where id = %s", (ctx.payload["channel_id"],)).fetchone()
        if not ch or not ch["daily_auto_post"]:
            return {"skipped": "automatic daily post is off"}
        tz = ZoneInfo(ch["timezone"])
        today = datetime.now(tz).date()
        if str(today) != ctx.payload.get("day"):
            return {"skipped": "that day has passed"}
        want = max(1, int(ch.get("daily_auto_count") or 1))
        going = _on_its_way(c, ch, today)
        need = want - going
        if need <= 0:
            return {"skipped": f"{going} post(s) already on their way today (the day takes {want})"}
        cats = c.execute("select * from categories where channel_id = %s and enabled order by created_at",
                         (ch["id"],)).fetchall()
        recent = [r["topic"] for r in c.execute(
            "select topic from posts where channel_id = %s and created_at > now() - interval '21 days'",
            (ch["id"],)).fetchall()]
        prof = channels.profile(c, ch["user_id"], ch["id"])
    judge = jev.for_user(ch["user_id"])
    scored: list = []
    with httpx.Client(timeout=30) as client:
        rid, rsecret = vault.secret(ch["user_id"], "reddit_client_id"), vault.secret(ch["user_id"], "reddit_client_secret")
        api = reddit.RedditAPI(client, rid, rsecret) if rid and rsecret else None
        for cat in cats:
            with db.conn() as c:
                rows = c.execute("""select id, kind, value, options from category_sources
                                     where category_id = %s and enabled and (next_try_at is null or next_try_at <= now())
                                     order by created_at""", (cat["id"],)).fetchall()
            if not rows:
                continue
            try:
                items, outcomes = si.FETCH(rows, client=client, api=api, log=log,
                                           youtube_key=vault.secret(ch["user_id"], "youtube_api_key"))
            except Exception as e:  # noqa: BLE001 - the other categories still count
                log(f"{cat['name']}: fetch failed: {e}")
                continue
            si._record_outcomes(outcomes)
            cands, _ = select.prefilter(items, keep=si.CANDIDATES)
            cands = [it for it in cands if not _covered(it.title, recent)]
            if not cands:
                continue
            ranked = (decide.rank_scored(judge, cands, cat, audience=prof.get("audience") or "")
                      if judge is not None else [(1.0 - n / 100, it) for n, it in enumerate(cands)])
            scored += [(sc, it, cat) for sc, it in ranked[:need + 2]]
    if judge is not None:
        judge.record("Jev: the day's top stories", user_id=ch["user_id"], channel_id=ch["id"], job_id=ctx.job.get("id"))
    chosen = _choose(scored, need)
    if not chosen:
        log("nothing worth posting today")
        return {"picked": [], "wanted": need}
    # The day's posts an hour and a half apart, from the usual time (or from two hours
    # from now, when that time is too close), clear of the owner's own picks.
    now = datetime.now(tz)
    hh, mm = ch["default_publish_time"].hour, ch["default_publish_time"].minute
    at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if at - now < LEAD:
        at = (now + timedelta(hours=2)).replace(second=0, microsecond=0)
    with db.conn() as c:
        taken = [r["at"] for r in c.execute(
            "select publish_at as at from posts where channel_id = %s and slot_date = %s and publish_at is not null",
            (ch["id"], today)).fetchall()]
    out = []
    for score, item, cat in chosen:
        while any(abs((at - t).total_seconds()) < SPACING.total_seconds() / 2 for t in taken):
            at += SPACING
        out.append(_make(ctx, ch, judge, cat, item, score, at, log))
        taken.append(at)
        at += SPACING
    db.note_enqueued("ideas")
    db.note_enqueued("cpu")
    return {"picked": [o["title"] for o in out], "posts": out, "wanted": need}


def _make(ctx: JobContext, ch: dict, judge, cat: dict, item, score: float, at: datetime, log) -> dict:
    """One story → an idea (straight from the story, no idea-writing call) → a post
    accepted for `at` and put on autopilot."""
    with db.conn() as c:
        fmts = si._formats(c, cat)
    fmt = fmts[0]
    idea = {"title": item.title[:200], "hook": (item.summary or "")[:240], "brief": item.summary or item.title}
    if judge is not None and len(fmts) > 1:
        try:
            [(pick, sure)] = decide.pick_format(judge, [idea], [[item]], fmts, {})
            if pick is not None and sure >= decide.SURE:
                fmt = fmts[pick]
        except Exception as e:  # noqa: BLE001 - the category's first format stands
            log(f"format pick skipped: {e}")
    why = "Jev's pick: the day's top story"
    with db.tx() as c:
        fmt, why = voice.Budget.load(c, ch["id"], ch.get("voice_share")).fit(fmt, fmts, why)
        iid = c.execute(
            """insert into ideas (user_id, channel_id, format_id, category_id, title, hook, brief, why_now,
                                  sources, items, media_state, batch_job_id, format_why)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'none', %s, %s) returning id""",
            (ch["user_id"], ch["id"], fmt["id"], cat["id"], idea["title"], idea["hook"], idea["brief"], WHY_NOW,
             Jsonb([{"url": item.url, "title": item.title}] if item.url else []),
             Jsonb([si._item_json(item)]), ctx.job.get("id"), why)).fetchone()["id"]
        c.execute("select set_config('app.user_id', %s, true)", (ch["user_id"],))
        pid = c.execute("select (api.decide_idea_v2(%s, true, %s, null, null, false, 'none', %s)).post_id as p",
                        (iid, at.astimezone(timezone.utc), fmt["id"])).fetchone()["p"]
        what = c.execute("select api.autopilot(%s, true) as r", (pid,)).fetchone()["r"]
    log(f"{ch['name']}: picked {item.title[:80]!r} ({cat['name']}, score {score:.2f}) as {fmt['name']} "
        f"for {at:%H:%M}; {what}")
    return {"title": item.title, "category": cat["name"], "format": fmt["name"], "post_id": str(pid),
            "publish_at": at.isoformat(), "score": round(score, 2)}


HANDLER = Handler(run=run)
