"""Open social sources: what people are sharing right now, read without a login.

Reddit is closing its public feeds (RSS ends 2026-11-13, the API in 2027), so a
category can also follow places whose public APIs are open by design:

  bluesky     "whats-hot" (the Discover feed), "trending" (trending topics, text
              only), or a custom feed's https://bsky.app/profile/<who>/feed/<id>
  mastodon    an instance's trending posts and links ("mastodon.social"), or a
              hashtag on an instance ("#science@mastodon.social")
  lemmy       an instance's top posts of the day ("lemmy.world"), or one
              community ("technology@lemmy.world")
  hackernews  the front page ("front_page"), or stories matching search terms
  youtube     the most-popular chart of a country, optionally one category
              ("IN", "IN:28"); needs a YouTube Data API key (a free Google
              Cloud API key, not the owner's login)

Every request goes through net (public addresses only, size-capped): instance
names are typed by the owner. Posts their authors or the platform mark as adult,
sensitive or "not for logged-out viewers" are skipped, as are age-restricted
videos. Items carry the same extra fields Reddit's do (author, score, comments,
media links), so the prefilter, the cards and attach_media treat them alike.
YouTube videos are never downloaded: their card shows the thumbnail only.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

import httpx

from .. import net
from .feeds import Item, _when

JSON_BYTES = 4_000_000
PER_SOURCE = 30
TITLE_CHARS = 140
SUMMARY_CHARS = 240

BSKY = "https://public.api.bsky.app/xrpc/"
WHATS_HOT = "at://did:plc:z72i7hdynmk6r22z27h6tvur/app.bsky.feed.generator/whats-hot"
# Labels (by Bluesky's moderation or the author) that keep a post out of the deck.
# "!no-unauthenticated": the author asked not to be shown to logged-out readers.
BSKY_SKIP = {"porn", "sexual", "nudity", "sexual-figurative", "graphic-media", "gore", "!no-unauthenticated"}
BSKY_FEED_URL = re.compile(r"^https://bsky\.app/profile/([^/\s]+)/feed/([A-Za-z0-9_-]+)$")

YOUTUBE = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CATEGORIES = {
    "1": "Film & Animation", "2": "Autos & Vehicles", "10": "Music", "15": "Pets & Animals", "17": "Sports",
    "19": "Travel & Events", "20": "Gaming", "22": "People & Blogs", "23": "Comedy", "24": "Entertainment",
    "25": "News & Politics", "26": "Howto & Style", "27": "Education", "28": "Science & Technology",
}


class SourceError(RuntimeError):
    """A readable reason the source gave nothing (shown on the category page)."""


def _json(client: httpx.Client, url: str, headers: dict | None = None):
    try:
        r = net.get(client, url, max_bytes=JSON_BYTES, accept=("application/json",), headers=headers)
    except httpx.HTTPStatusError as e:
        raise SourceError(f"HTTP {e.response.status_code} from {httpx.URL(url).host}") from None
    return json.loads(r.content)


def _plain(text: str | None) -> str:
    """HTML or plain text → one clean line."""
    s = re.sub(r"<br\s*/?>|</p>", "\n", text or "", flags=re.IGNORECASE)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[ \t\r\f\v]+", " ", s).strip()


def _cut(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def _title_and_summary(text: str, fallback_title: str = "") -> tuple[str, str]:
    """A post has no headline: its first line or sentence becomes one, the rest the summary."""
    text = text.strip()
    if not text:
        return _cut(fallback_title, TITLE_CHARS), ""
    first = text.split("\n", 1)[0].strip()
    m = re.match(r"(.{20,}?[.!?])\s", first)
    head = m.group(1) if m and len(m.group(1)) <= TITLE_CHARS else first
    rest = text[len(head):].strip() if text.startswith(head) else text
    return _cut(head, TITLE_CHARS), _cut(rest, SUMMARY_CHARS)


# ── Bluesky ───────────────────────────────────────────────────────────────────

def _bsky_feed_uri(client: httpx.Client, value: str) -> tuple[str, str]:
    if value == "whats-hot":
        return WHATS_HOT, "Bluesky · What's Hot"
    m = BSKY_FEED_URL.match(value)
    if not m:
        raise SourceError("not a Bluesky feed link (https://bsky.app/profile/…/feed/…)")
    actor, rkey = m.groups()
    did = actor if actor.startswith("did:") else \
        _json(client, BSKY + "com.atproto.identity.resolveHandle?" + urlencode({"handle": actor}))["did"]
    return f"at://{did}/app.bsky.feed.generator/{rkey}", f"Bluesky · {rkey}"


def _bsky_post(p: dict, rank: int, source: str) -> Item | None:
    labels = {lab.get("val") for lab in (p.get("labels") or []) + ((p.get("author") or {}).get("labels") or [])}
    if labels & BSKY_SKIP:
        return None
    rec, author = p.get("record") or {}, p.get("author") or {}
    handle = author.get("handle") or author.get("did") or "unknown"
    permalink = f"https://bsky.app/profile/{handle}/post/{p.get('uri', '').rsplit('/', 1)[-1]}"
    e = p.get("embed") or {}
    if e.get("$type", "").startswith("app.bsky.embed.recordWithMedia"):
        e = e.get("media") or {}
    kind = e.get("$type", "")
    extra = {"platform": "bluesky", "author": f"@{handle}", "score": p.get("likeCount", 0),
             "comments": p.get("replyCount", 0), "reposts": p.get("repostCount", 0)}
    hint, ext_title = "self", ""
    if kind.startswith("app.bsky.embed.images") and e.get("images"):
        img = e["images"][0]
        hint = "image"
        extra.update(image_url=img.get("fullsize"), thumbnail=img.get("thumb"), alt=img.get("alt") or None,
                     images=len(e["images"]))
    elif kind.startswith("app.bsky.embed.video") and e.get("playlist"):
        hint = "video"
        extra.update(hls_url=e["playlist"], thumbnail=e.get("thumbnail"))
    elif kind.startswith("app.bsky.embed.external") and e.get("external"):
        ext = e["external"]
        hint, ext_title = "link", ext.get("title") or ""
        extra.update(link=ext.get("uri"), thumbnail=ext.get("thumb"))
    title, summary = _title_and_summary(rec.get("text", ""), ext_title)
    if not title:
        return None
    if ext_title and ext_title not in (title, summary):
        summary = _cut(f"{summary} [{ext_title}]".strip(), SUMMARY_CHARS)
    return Item(source=source, title=title, summary=summary, url=permalink, published=_when(rec.get("createdAt")),
                rank=rank, media_hint=hint, extra=extra)


def bluesky(client: httpx.Client, value: str) -> list[Item]:
    if value == "trending":
        topics = _json(client, BSKY + "app.bsky.unspecced.getTrendingTopics?limit=15").get("topics") or []
        return [Item(source="Bluesky · trending", title=_cut(t.get("displayName") or t.get("topic") or "", TITLE_CHARS),
                     summary=_cut(t.get("description") or "", SUMMARY_CHARS),
                     url=("https://bsky.app" + t["link"]) if str(t.get("link", "")).startswith("/") else t.get("link", ""),
                     rank=n, media_hint="text", extra={"platform": "bluesky"})
                for n, t in enumerate(topics) if t.get("displayName") or t.get("topic")]
    uri, source = _bsky_feed_uri(client, value)
    feed = _json(client, BSKY + "app.bsky.feed.getFeed?" + urlencode({"feed": uri, "limit": 50})).get("feed") or []
    out = []
    for f in feed:
        it = _bsky_post(f.get("post") or {}, len(out), source)
        if it:
            out.append(it)
    return out[:PER_SOURCE]


# ── Mastodon ──────────────────────────────────────────────────────────────────

def _masto_status(s: dict, rank: int, source: str, instance: str) -> Item | None:
    acct = s.get("account") or {}
    if s.get("sensitive") or s.get("spoiler_text") or acct.get("noindex") or s.get("visibility") not in (None, "public"):
        return None
    handle = acct.get("acct") or acct.get("username") or "unknown"
    if "@" not in handle:
        handle = f"{handle}@{instance}"
    extra = {"platform": "mastodon", "author": f"@{handle}", "score": s.get("favourites_count", 0),
             "comments": s.get("replies_count", 0), "reposts": s.get("reblogs_count", 0)}
    hint, card_title = "self", ""
    media = s.get("media_attachments") or []
    if media and media[0].get("type") == "image":
        hint = "image"
        extra.update(image_url=media[0].get("url"), thumbnail=media[0].get("preview_url"),
                     alt=media[0].get("description") or None)
    elif media and media[0].get("type") in ("video", "gifv"):
        hint = "video"
        extra.update(video_url=media[0].get("url"), thumbnail=media[0].get("preview_url"),
                     seconds=((media[0].get("meta") or {}).get("original") or {}).get("duration"))
    elif s.get("card") and (s["card"].get("url") or "").startswith("http"):
        hint, card_title = "link", s["card"].get("title") or ""
        extra.update(link=s["card"]["url"], thumbnail=s["card"].get("image"))
    title, summary = _title_and_summary(_plain(s.get("content")), card_title)
    if not title:
        return None
    return Item(source=source, title=title, summary=summary, url=s.get("url") or s.get("uri") or "",
                published=_when(s.get("created_at")), rank=rank, media_hint=hint, extra=extra)


def mastodon(client: httpx.Client, value: str) -> list[Item]:
    tag, _, instance = value.partition("@") if value.startswith("#") else ("", "", value)
    base = f"https://{instance}/api/v1/"
    if tag:
        statuses = _json(client, base + f"timelines/tag/{quote(tag[1:])}?limit=40")
        # A hashtag's timeline is newest-first; the most shared rise to the top.
        statuses.sort(key=lambda s: (s.get("reblogs_count", 0) + s.get("favourites_count", 0)), reverse=True)
        source = f"Mastodon {tag}"
    else:
        statuses = _json(client, base + "trends/statuses?limit=30")
        source = f"Mastodon · {instance}"
    out = []
    for s in statuses:
        it = _masto_status(s, len(out), source, instance)
        if it:
            out.append(it)
    if not tag:                                  # what people share links to: mostly news
        try:
            links = _json(client, base + "trends/links?limit=10")
        except Exception:  # noqa: BLE001 - trending posts are enough
            links = []
        for n, k in enumerate(links):
            if k.get("title") and (k.get("url") or "").startswith("http"):
                out.append(Item(source=f"Mastodon · {instance} links", title=_cut(k["title"], TITLE_CHARS),
                                summary=_cut(k.get("description") or "", SUMMARY_CHARS), url=k["url"],
                                published=_when(k.get("published_at")), rank=n, media_hint="link",
                                extra={"platform": "mastodon", "author": k.get("provider_name") or None,
                                       "thumbnail": k.get("image"), "link": k["url"]}))
    return out[:PER_SOURCE + 10]


# ── Lemmy ─────────────────────────────────────────────────────────────────────

def lemmy(client: httpx.Client, value: str) -> list[Item]:
    community, _, instance = value.rpartition("@")
    q = {"sort": "TopDay", "limit": 30}
    q.update({"community_name": community} if community else {"type_": "All"})
    data = _json(client, f"https://{instance}/api/v3/post/list?" + urlencode(q))
    out = []
    for pv in data.get("posts") or []:
        p, comm, who = pv.get("post") or {}, pv.get("community") or {}, pv.get("creator") or {}
        if p.get("nsfw") or comm.get("nsfw") or p.get("removed") or p.get("deleted"):
            continue
        counts = pv.get("counts") or {}
        extra = {"platform": "lemmy", "author": f"u/{who.get('name') or 'unknown'}", "community": comm.get("name"),
                 "score": counts.get("score", 0), "comments": counts.get("comments", 0)}
        url, ctype = p.get("url") or "", (p.get("url_content_type") or "").lower()
        hint = "self"
        if url and ctype.startswith("image/"):
            hint = "image"
            extra.update(image_url=url, thumbnail=p.get("thumbnail_url"))
        elif url and ctype.startswith("video/"):
            hint = "video"
            extra.update(video_url=url, thumbnail=p.get("thumbnail_url"))
        elif url.startswith("http"):
            hint = "link"
            extra.update(link=url, thumbnail=p.get("thumbnail_url"))
        title = _cut(p.get("name") or "", TITLE_CHARS)
        if not title:
            continue
        out.append(Item(source=f"c/{comm.get('name')}" if community else f"Lemmy · {instance}", title=title,
                        summary=_cut(_plain(p.get("body")), SUMMARY_CHARS), url=p.get("ap_id") or url,
                        published=_when(p.get("published")), rank=len(out), media_hint=hint, extra=extra))
    return out


# ── Hacker News ───────────────────────────────────────────────────────────────

def hackernews(client: httpx.Client, value: str) -> list[Item]:
    if value == "front_page":
        url = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"
    else:
        since = int((datetime.now(timezone.utc) - timedelta(hours=48)).timestamp())
        url = "https://hn.algolia.com/api/v1/search?" + urlencode(
            {"query": value, "tags": "story", "numericFilters": f"created_at_i>{since}", "hitsPerPage": 30})
    hits = sorted(_json(client, url).get("hits") or [], key=lambda h: h.get("points") or 0, reverse=True)
    out = []
    for h in hits:
        if not h.get("title"):
            continue
        discussion = f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        link = h.get("url") or ""
        out.append(Item(source="Hacker News", title=_cut(h["title"], TITLE_CHARS),
                        summary=_cut(_plain(h.get("story_text")), SUMMARY_CHARS), url=link or discussion,
                        published=_when(h.get("created_at")), rank=len(out), media_hint="link" if link else "self",
                        extra={"platform": "hackernews", "author": h.get("author"), "score": h.get("points") or 0,
                               "comments": h.get("num_comments") or 0, "link": link or None,
                               "discussion": discussion}))
    return out


# ── YouTube ───────────────────────────────────────────────────────────────────

def youtube(client: httpx.Client, value: str, api_key: str | None) -> list[Item]:
    if not api_key:
        raise SourceError("add a YouTube API key in Settings to read the trending chart")
    region, _, category = value.partition(":")
    q = {"part": "snippet,statistics,contentDetails", "chart": "mostPopular", "regionCode": region, "maxResults": 25}
    if category:
        q["videoCategoryId"] = category
    # The key goes in a header, never the URL: URLs end up in logs and error messages.
    try:
        data = _json(client, YOUTUBE + "?" + urlencode(q), headers={"X-Goog-Api-Key": api_key})
    except SourceError as e:
        raise SourceError(f"{e} (check the YouTube API key, and that this chart exists for {value})") from None
    name = f"YouTube trending {region}" + (f" · {YOUTUBE_CATEGORIES.get(category, category)}" if category else "")
    out = []
    for v in data.get("items") or []:
        sn, stats, details = v.get("snippet") or {}, v.get("statistics") or {}, v.get("contentDetails") or {}
        if (details.get("contentRating") or {}).get("ytRating") == "ytAgeRestricted" or not sn.get("title"):
            continue
        thumbs = sn.get("thumbnails") or {}
        thumb = next((thumbs[k]["url"] for k in ("maxres", "standard", "high", "medium") if k in thumbs), None)
        out.append(Item(source=name, title=_cut(sn["title"], TITLE_CHARS),
                        summary=_cut(_plain(sn.get("description")), SUMMARY_CHARS),
                        url=f"https://www.youtube.com/watch?v={v.get('id')}", published=_when(sn.get("publishedAt")),
                        rank=len(out), media_hint="image" if thumb else "self",
                        extra={"platform": "youtube", "author": sn.get("channelTitle"), "image_url": thumb,
                               "thumbnail": thumb, "score": int(stats.get("likeCount") or 0),
                               "views": int(stats.get("viewCount") or 0),
                               "comments": int(stats.get("commentCount") or 0),
                               "duration": details.get("duration")}))
    return out


def lemmy_community_exists(client: httpx.Client, value: str) -> bool:
    community, _, instance = value.rpartition("@")
    if not community:
        return True
    try:
        _json(client, f"https://{instance}/api/v3/community?" + urlencode({"name": community}))
        return True
    except Exception:  # noqa: BLE001
        return False
