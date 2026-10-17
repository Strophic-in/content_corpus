"""A category's sources → one interleaved list of trend items, and how each source did.

Reddit communities of a category are fetched together (one request per sort
order, see reddit.py); every other source on its own — Bluesky, Mastodon, Lemmy,
Hacker News and YouTube's chart in social.py. A source that fails is reported,
not fatal: the batch goes on with whatever answered, and the caller records the
error (and backs off) on that source.

Reddit ends its public RSS feeds on REDDIT_RSS_END. Its sources keep being tried
(they cost one request) but, from that day, say why they fail and are not
retried one community at a time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import httpx

from .. import net
from . import feeds, reddit, sites, social

PER_SOURCE = 15
WIKI = "https://api.wikimedia.org/feed/v1/wikipedia/{lang}/featured/{yesterday}"
TRENDS = "https://trends.google.com/trending/rss?geo={geo}"
ONE_BY_ONE_BUDGET_S = 480       # when a combined Reddit request fails, how long to spend retrying singly
REDDIT_RSS_END = date(2026, 11, 13)
SOCIAL = {"bluesky": social.bluesky, "mastodon": social.mastodon, "lemmy": social.lemmy,
          "hackernews": social.hackernews}


@dataclass
class Outcome:
    source_id: str
    ok: bool
    items: int = 0
    error: str | None = None


def _reddit_error(e: reddit.RedditError) -> str:
    if date.today() >= REDDIT_RSS_END and e.status in (403, 404, 410):
        return (f"{e} — Reddit ended its public feeds on 13 Nov 2026; follow this topic on Bluesky, "
                "Mastodon or Lemmy instead")
    return str(e)


def _reddit_item(p: reddit.Post) -> feeds.Item:
    return feeds.Item(
        source=f"r/{p.subreddit}", title=p.title, summary=p.selftext[:240], url=p.permalink,
        published=p.published, rank=p.rank, media_hint=p.kind,
        extra={"subreddit": p.subreddit, "author": p.author, "link": p.link, "thumbnail": p.thumbnail,
               "kind": p.kind, "post_id": p.id, "score": p.score, "comments": p.comments,
               "over_18": p.over_18, "video": p.video})


def _reddit(rows: list[dict], client: httpx.Client, api: reddit.RedditAPI | None,
            log: Callable[[str], None]) -> tuple[list[feeds.Item], list[Outcome]]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        o = r.get("options") or {}
        groups.setdefault((o.get("sort", "top"), o.get("t", "day")), []).append(r)
    items: list[feeds.Item] = []
    out: list[Outcome] = []

    def get(subs: list[str], sort: str, t: str) -> list[reddit.Post]:
        if api is not None:
            return api.listing(subs, sort=sort, t=t, limit=50)
        return reddit.feed(client, subs, sort=sort, t=t, limit=50)

    for (sort, t), group in groups.items():
        subs = [g["value"] for g in group]
        try:
            posts = get(subs, sort, t)
            fetched = {s.lower(): [] for s in subs}
            for p in posts:
                if p.over_18:
                    continue
                fetched.setdefault(p.subreddit.lower(), []).append(p)
                items.append(_reddit_item(p))
            for g in group:
                out.append(Outcome(str(g["id"]), True, len(fetched.get(g["value"].lower(), []))))
            log(f"reddit r/{'+'.join(subs)} ({sort}): {len(posts)} posts")
        except reddit.RedditError as e:
            if len(group) == 1 or e.status not in (403, 404) or date.today() >= REDDIT_RSS_END:
                out += [Outcome(str(g["id"]), False, error=_reddit_error(e)) for g in group]
                log(f"reddit r/{'+'.join(subs)}: {e}")
                continue
            # One bad community (banned, private, misspelt) fails the whole combined
            # feed: find it by asking each community alone, within a time budget.
            log(f"reddit r/{'+'.join(subs)}: {e} — trying each community alone")
            t0 = time.monotonic()
            for g in group:
                if time.monotonic() - t0 > ONE_BY_ONE_BUDGET_S:
                    out.append(Outcome(str(g["id"]), False, error="not checked this time (rate limit)"))
                    continue
                try:
                    posts = [p for p in get([g["value"]], sort, t) if not p.over_18]
                    items += [_reddit_item(p) for p in posts]
                    out.append(Outcome(str(g["id"]), True, len(posts)))
                except reddit.RedditError as e2:
                    out.append(Outcome(str(g["id"]), False, error=str(e2)))
    return items, out


def _one(row: dict, client: httpx.Client, youtube_key: str | None = None) -> list[feeds.Item]:
    kind, value, opts = row["kind"], row["value"], row.get("options") or {}
    if kind in SOCIAL:
        return SOCIAL[kind](client, value)
    if kind == "youtube":
        return social.youtube(client, value, youtube_key)
    if kind == "rss":
        return sites.read_feed(client, opts.get("name") or sites.host_key(value) or value, value)[:PER_SOURCE]
    if kind == "site":
        urls = sites.discover(client, value)
        if not urls:
            raise RuntimeError(f"no feeds found for {value}")
        got: list[feeds.Item] = []
        for u in urls:
            try:
                got += sites.read_feed(client, sites.host_key(sites.normalize_domain(value)), u)[:PER_SOURCE]
            except Exception:  # noqa: BLE001 - one of a site's feeds failing is fine
                continue
        if not got:
            raise RuntimeError(f"none of {value}'s feeds answered")
        return got
    if kind == "search":
        return sites.search_news(client, value, market=opts.get("market", "en-IN"))[:PER_SOURCE]
    if kind == "google_trends":
        return sites.read_feed(client, f"Google Trends {value}", TRENDS.format(geo=value))[:PER_SOURCE]
    if kind == "wikipedia":
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y/%m/%d")
        url = WIKI.format(lang=value or "en", yesterday=yesterday)
        body = net.get(client, url, max_bytes=sites.FEED_BYTES, accept=("application/json",)).content
        return feeds.parse("Wikipedia most read", url, body.decode("utf-8"))[:PER_SOURCE]
    raise RuntimeError(f"unknown source kind {kind}")


def fetch(rows: list[dict], *, client: httpx.Client, api: reddit.RedditAPI | None = None,
          youtube_key: str | None = None,
          log: Callable[[str], None] = print) -> tuple[list[feeds.Item], list[Outcome]]:
    """All of a category's enabled sources → (items interleaved by source, outcomes)."""
    per_source: list[list[feeds.Item]] = []
    outcomes: list[Outcome] = []
    reddit_rows = [r for r in rows if r["kind"] == "reddit"]
    if reddit_rows:
        items, outs = _reddit(reddit_rows, client, api, log)
        by_sub: dict[str, list[feeds.Item]] = {}
        for it in items:
            by_sub.setdefault(it.source, []).append(it)
        per_source += list(by_sub.values())
        outcomes += outs
    for row in rows:
        if row["kind"] == "reddit":
            continue
        try:
            got = _one(row, client, youtube_key)
            per_source.append(got)
            outcomes.append(Outcome(str(row["id"]), True, len(got)))
            log(f"{row['kind']} {row['value'][:60]}: {len(got)} items")
        except Exception as e:  # noqa: BLE001 - one bad source must not sink the batch
            why = str(e)[:200] if isinstance(e, social.SourceError) else f"{type(e).__name__}: {str(e)[:200]}"
            outcomes.append(Outcome(str(row["id"]), False, error=why))
            log(f"{row['kind']} {row['value'][:60]}: skipped ({type(e).__name__}: {str(e)[:120]})")
    merged, seen = [], set()
    for n in range(max((len(s) for s in per_source), default=0)):
        for s in per_source:
            if n < len(s):
                key = (s[n].title.lower(), s[n].url)
                if key[0] and key not in seen:
                    seen.add(key)
                    merged.append(s[n])
    return merged, outcomes
