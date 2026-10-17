"""ideas/research_post — read an accepted idea's story in full before its script.

Queued by the database when an idea is accepted (private.research_accepted_idea).
Reads the articles the idea came from — for a social post, the article it links
to; never the social post's own page — and up to EXTRA_REPORTS other outlets'
reports of the same story from a news search, so the script isn't written from
one source. The texts land in posts.research; write_script waits for them
(research_state 'pending') and then writes from them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from psycopg.types.json import Jsonb

from .. import db, research
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
        post = c.execute("select id, topic, research_state from posts where id = %s",
                         (ctx.payload["post_id"],)).fetchone()
        idea = c.execute("select items, title from ideas where id = %s", (ctx.payload.get("idea_id"),)).fetchone()
    if not post or post["research_state"] != "pending":
        return {"skipped": "no research waiting"}
    urls = _article_urls((idea or {}).get("items") or [])
    articles: list[research.Article] = []
    with httpx.Client(timeout=30) as client:
        for u in urls:
            articles.append(research.read(client, u))
        sites_read = {a.site for a in articles}
        try:
            others = SEARCH(client, post["topic"], count=12)
        except Exception as e:  # noqa: BLE001 - the idea's own sources are enough to go on
            log(f"news search failed: {e}")
            others = []
        for it in others:
            if sum(1 for a in articles if a.url not in urls) >= EXTRA_REPORTS:
                break
            site = urlparse(it.url).netloc.removeprefix("www.")
            if site in sites_read or it.url in urls:
                continue
            a = research.read(client, it.url)
            if a.ok:
                articles.append(a)
                sites_read.add(site)
    good = [a for a in articles if a.ok]
    with db.conn() as c:
        c.execute("update posts set research = %s, research_state = %s where id = %s",
                  (Jsonb({"articles": [{"url": a.url, "site": a.site, "title": a.title, "text": a.text,
                                        "from_idea": a.url in urls} for a in good],
                          "unreadable": [{"url": a.url, "error": a.error} for a in articles if not a.ok],
                          "read_at": datetime.now(timezone.utc).isoformat()}),
                   "ready" if good else "none", post["id"]))
    log(f"{post['topic'][:60]}: read {len(good)} of {len(articles)} pages")
    return {"read": len(good), "tried": len(articles), "sites": sorted({a.site for a in good})}


def on_give_up(ctx: JobContext, err: dict) -> None:
    with db.conn() as c:
        c.execute("update posts set research_state = 'none' where id = %s and research_state = 'pending'",
                  (ctx.payload["post_id"],))


HANDLER = Handler(run=run, on_give_up=on_give_up)
