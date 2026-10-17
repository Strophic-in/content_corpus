"""How published reels did: views, likes and comments, read back a few times a day
for reels posted in the last WINDOW_DAYS, so the idea agent can learn what works.

YouTube: the public statistics of the owner's videos, read with their YouTube Data
API key (public data — the channel login is not used for this). Instagram: likes
and comments on the owner's own reels, with the Instagram token the reel was
posted with (views need Meta's insights permission, which the app doesn't ask
for). Either is skipped when its key or account isn't there.
"""

from __future__ import annotations

from typing import Callable

import httpx

from . import db, vault
from .crypto import decrypt
from .publish import instagram

YOUTUBE = "https://www.googleapis.com/youtube/v3/videos"
WINDOW_DAYS = 45


def _save(c, post_id, user_id, platform: str, views, likes, comments) -> None:
    c.execute("""insert into post_stats (post_id, user_id, platform, views, likes, comments, fetched_at)
                 values (%s, %s, %s, %s, %s, %s, now())
                 on conflict (post_id, platform) do update set views = excluded.views, likes = excluded.likes,
                     comments = excluded.comments, fetched_at = excluded.fetched_at""",
              (post_id, user_id, platform, views, likes, comments))


def read_back(client: httpx.Client, log: Callable[[str], None] = print) -> int:
    with db.conn() as c:
        live = c.execute(f"""select a.post_id, a.platform, a.remote_id, p.user_id, p.channel_id
                               from publish_attempts a join posts p on p.id = a.post_id
                              where a.state = 'live' and a.remote_id is not null
                                and a.updated_at > now() - interval '{WINDOW_DAYS} days'""").fetchall()
    n = 0
    by_user: dict[str, list[dict]] = {}
    for r in live:
        if r["platform"] == "youtube":
            by_user.setdefault(r["user_id"], []).append(r)
    for user_id, rows in by_user.items():
        key = vault.secret(user_id, "youtube_api_key")
        if not key:
            continue
        for i in range(0, len(rows), 50):
            batch = rows[i:i + 50]
            r = client.get(YOUTUBE, params={"part": "statistics", "id": ",".join(x["remote_id"] for x in batch)},
                           headers={"X-Goog-Api-Key": key})
            if r.status_code != 200:
                log(f"YouTube statistics: HTTP {r.status_code}")
                break
            stats = {v["id"]: v.get("statistics") or {} for v in r.json().get("items") or []}
            with db.conn() as c:
                for x in batch:
                    s = stats.get(x["remote_id"])
                    if s is not None:
                        _save(c, x["post_id"], user_id, "youtube", int(s.get("viewCount") or 0),
                              int(s.get("likeCount") or 0), int(s.get("commentCount") or 0))
                        n += 1
    for x in (r for r in live if r["platform"] == "instagram"):
        with db.conn() as c:
            acc = c.execute("""select token_ciphertext from channel_accounts
                                where channel_id = %s and platform = 'instagram' and status = 'connected'""",
                            (x["channel_id"],)).fetchone()
        if not acc:
            continue
        try:
            r = client.get(f"{instagram.GRAPH}/{x['remote_id']}",
                           params={"fields": "like_count,comments_count", "access_token": decrypt(acc["token_ciphertext"])})
            if r.status_code != 200:
                continue
            body = r.json()
            with db.conn() as c:
                _save(c, x["post_id"], x["user_id"], "instagram", None, body.get("like_count"),
                      body.get("comments_count"))
            n += 1
        except Exception as e:  # noqa: BLE001 - next time
            log(f"Instagram stats: {type(e).__name__}")
    return n


def by_format(c, channel_id) -> dict:
    """How each of the channel's formats has done against the channel's own usual
    views (its average per published post): {format_id: "…"}, for formats with at
    least two posts with numbers. Formats are never called viral — only compared."""
    rows = c.execute("""select p.format_id, count(*) as posts, avg(v.views) as views
                          from posts p
                          join (select post_id, sum(coalesce(views, 0)) as views from post_stats group by post_id) v
                            on v.post_id = p.id
                         where p.channel_id = %s
                         group by p.format_id""", (channel_id,)).fetchall()
    total = sum(r["posts"] for r in rows)
    if not total:
        return {}
    base = sum(float(r["views"] or 0) * r["posts"] for r in rows) / total
    out = {}
    for r in rows:
        if r["format_id"] and r["posts"] >= 2 and base > 0:
            out[r["format_id"]] = (f"On this channel: {r['posts']} posts, {float(r['views'] or 0) / base:.1f}x "
                                   "its usual views.")
    return out


def summary(c, channel_id, limit: int = 10) -> str:
    """The channel's recent reels with how they did, best first — for the idea agent."""
    rows = c.execute("""select p.topic, sum(s.views) as views, sum(s.likes) as likes, sum(s.comments) as comments
                          from posts p join post_stats s on s.post_id = p.id
                         where p.channel_id = %s group by p.id, p.topic
                         order by coalesce(sum(s.views), 0) desc, coalesce(sum(s.likes), 0) desc limit %s""",
                     (channel_id, limit)).fetchall()
    if not rows:
        return ""
    lines = [f"- {r['topic']} — {int(r['views'] or 0):,} views, {int(r['likes'] or 0):,} likes, "
             f"{int(r['comments'] or 0):,} comments" for r in rows]
    return ("\n\n## How this channel's recent videos did (best first) — more like the top ones, "
            "less like the bottom ones\n" + "\n".join(lines))
