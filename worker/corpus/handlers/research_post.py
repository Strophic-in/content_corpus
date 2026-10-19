"""ideas/research_post — read a post's story in full and collect its assets, before its script.

Queued by the database when an idea is accepted (private.research_accepted_idea) or
a post is made by hand (api.collect_assets). Reads the articles the idea came from —
for a social post, the article it links to; never the social post's own page — and
up to EXTRA_REPORTS other outlets' reports of the same story from a news search, so
the script isn't written from one source. The texts land in posts.research.

Then it collects the post's assets (finder.collect): the logos and photos of who
and what the story names, a headline card of each report, and the reports' own
photos and videos. write_script waits for all of it (research_state 'pending', then
the assets being fetched) and writes with them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from psycopg.types.json import Jsonb

from .. import costs, db, entities, finder, jev, research, vault
from ..ideas import sites
from ..runner import Handler, JobContext

MAX_SOURCES = 3
EXTRA_REPORTS = 2
SOCIAL_HOSTS = ("reddit.com", "redd.it", "bsky.app", "youtube.com", "youtu.be", "news.ycombinator.com")

# Swapped by tests.
SEARCH = sites.search_news


def _article_urls(items: list[dict]) -> list[str]:
    out: list[str] = []
    for it in items:
        for u in (it.get("link"), it.get("url")):
            host = urlparse(u or "").netloc.lower()
            if not (u or "").startswith("http") or any(host == h or host.endswith("." + h) for h in SOCIAL_HOSTS):
                continue
            if it.get("platform") in ("mastodon", "lemmy", "bluesky") and u == it.get("url"):
                continue                                   # the post's own page, not an article
            if u not in out:
                out.append(u)
            break
    return out[:MAX_SOURCES]


def run(ctx: JobContext) -> dict:
    log = lambda m: print(f"[research_post] {m}", flush=True)  # noqa: E731
    with db.conn() as c:
        post = c.execute("""select id, user_id, channel_id, category_id, format_id, topic, brief, research_state,
                                   media_choice
                              from posts where id = %s""",
                         (ctx.payload["post_id"],)).fetchone()
        idea = c.execute("select items, title from ideas where id = %s", (ctx.payload.get("idea_id"),)).fetchone()
    if not post or post["research_state"] != "pending":
        return {"skipped": "no research waiting"}
    urls = _article_urls((idea or {}).get("items") or [])
    articles: list[research.Article] = []
    judge = jev.for_user(post["user_id"])         # decides "same story?" when the owner has a Jev key
    with httpx.Client(timeout=30) as client:
        for u in urls:
            articles.append(research.read(client, u))
        sites_read = {a.site for a in articles}
        # Search by what the source itself calls the story (the card's title is often a
        # question), and keep only reports that share its specific words.
        headline = next((a.title for a in articles if a.ok and a.title), "") or post["topic"]
        story = f"{headline} {post['topic']}"
        try:
            others = SEARCH(client, headline, count=12)
        except Exception as e:  # noqa: BLE001 - the idea's own sources are enough to go on
            log(f"news search failed: {e}")
            others = []
        skipped = 0
        for it in others:
            if sum(1 for a in articles if a.url not in urls) >= EXTRA_REPORTS:
                break
            site = urlparse(it.url).netloc.removeprefix("www.")
            if site in sites_read or it.url in urls:
                continue
            if not research.same_event(judge, it.title, story):
                skipped += 1
                continue
            a = research.read(client, it.url)
            if a.ok and research.same_event(judge, a.title or it.title, story, a.text):
                articles.append(a)
                sites_read.add(site)
        if skipped:
            log(f"left out {skipped} search result(s) about other stories")
        # The post's assets (not when the owner asked for an AI version of its media).
        got = {}
        if post.get("media_choice") != "ai":
            names = _names(post, articles, headline, ctx, log)
            got = finder.collect(post, judge, client, [a for a in articles if a.ok], story=story, title=headline,
                                 topic=post["topic"], want_before=_before_after(post), names=names, log=log)
            log(f"collected: {got} (names: {', '.join(e.name for e in names) or 'none'})")
    if judge is not None:
        judge.record("Jev: same story, real photos", user_id=post["user_id"], post_id=post["id"],
                     channel_id=post["channel_id"], category_id=post["category_id"], job_id=ctx.job.get("id"))
    good = [a for a in articles if a.ok]
    with db.conn() as c:
        c.execute("update posts set research = %s, research_state = %s where id = %s",
                  (Jsonb({"articles": [{"url": a.url, "site": a.site, "title": a.title, "text": a.text,
                                        "from_idea": a.url in urls} for a in good],
                          "unreadable": [{"url": a.url, "error": a.error} for a in articles if not a.ok],
                          "read_at": datetime.now(timezone.utc).isoformat()}),
                   "ready" if good else "none", post["id"]))
    log(f"{post['topic'][:60]}: read {len(good)} of {len(articles)} pages")
    return {"read": len(good), "tried": len(articles), "sites": sorted({a.site for a in good}), "collected": got}


def on_give_up(ctx: JobContext, err: dict) -> None:
    with db.conn() as c:
        c.execute("update posts set research_state = 'none' where id = %s and research_state = 'pending'",
                  (ctx.payload["post_id"],))


HANDLER = Handler(run=run, on_give_up=on_give_up)


def _before_after(post: dict) -> bool:
    """A post made with the Before vs. After template: its finder looks for the place as it was."""
    if not post.get("format_id"):
        return False
    row = db.one("select template_id from formats where id = %s", (post["format_id"],))
    return bool(row) and row["template_id"] == "before_after_comparison"


def _names(post: dict, articles: list, headline: str, ctx: JobContext, log) -> list:
    """The story's named companies, people and places, by the script model (the owner's
    OpenAI key); [] without one."""
    key = vault.secret(post["user_id"], "openai")
    model = (db.one("select script_model from app_settings where user_id = %s", (post["user_id"],)) or {}) \
        .get("script_model")
    if not key or not model:
        return []
    text = "\n\n".join([headline, post["topic"], post.get("brief") or ""]
                        + [a.text[:2500] for a in articles if a.ok][:2])
    try:
        names, usage = entities.extract(key, model, text)
    except Exception as e:  # noqa: BLE001 - the rest of the collection still runs
        log(f"names: {type(e).__name__}: {e}")
        return []
    costs.record_llm(usage, user_id=post["user_id"], post_id=post["id"], channel_id=post["channel_id"],
                     category_id=post["category_id"], job_id=ctx.job.get("id"), note="named in the story")
    return names
