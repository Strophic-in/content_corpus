"""Reddit communities as a source: keyless feeds by default, the API when approved.

Keyless (verified from the server, 2026-10-16): every JSON endpoint answers 403;
the Atom feeds work, about one request a minute (x-ratelimit-remaining reached 0
after a single request). One feed can cover several communities at once —
`/r/a+b+c/top/.rss?t=day&limit=50` — so a category costs one request, and a
process-wide limiter spaces requests MIN_INTERVAL apart and honours
x-ratelimit-reset. Only the ideas worker calls this module, so the limit is
never shared with another process.

Each Atom entry carries the post's community (<category term>), author,
publish time, a preview (<media:thumbnail>), the self text (<div class="md">),
and an "[link]" anchor to what was posted: v.redd.it (video), i.redd.it (image),
/gallery/ (images; only the first is reachable keyless), another post
(crosspost) or an article. Keyless there is no score, comment count or NSFW
flag: the post's rank in top-of-day stands in for its score.

API mode (oauth.reddit.com, app-only OAuth) returns the same Post objects with
score, comments, over_18 and the video's own URLs. Since 2025 Reddit grants API
access only after a manual review, and commercial use needs its written
approval; until then keyless is the way in.
"""

from __future__ import annotations

import html
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import httpx

from ..net import UA

FEED = "https://www.reddit.com/r/{subs}/{sort}/.rss"
API = "https://oauth.reddit.com/r/{subs}/{sort}"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
MIN_INTERVAL = 65.0          # seconds between keyless requests
SORTS = ("top", "hot", "new", "rising")

# Swapped by tests.
SLEEP = time.sleep
CLOCK = time.monotonic

_lock = threading.Lock()
_next_ok = 0.0
_ATOM = {"a": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/"}


class RedditError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class Post:
    id: str                   # t3_…
    title: str
    permalink: str
    subreddit: str
    author: str
    published: datetime | None
    selftext: str
    link: str                 # what was posted (a media URL, an article, or the post itself)
    thumbnail: str
    kind: str                 # video | image | gallery | link | self | crosspost
    rank: int
    score: int | None = None
    comments: int | None = None
    over_18: bool | None = None
    video: dict = field(default_factory=dict)   # API mode: {hls, fallback, duration, height}

    def as_dict(self) -> dict:
        d = asdict(self)
        d["published"] = self.published.isoformat() if self.published else None
        return d


def _wait() -> None:
    global _next_ok
    with _lock:
        now = CLOCK()
        if now < _next_ok:
            SLEEP(_next_ok - now)
        _next_ok = CLOCK() + MIN_INTERVAL


def _note_limits(r: httpx.Response) -> None:
    """When Reddit says the budget is spent, don't ask again before it resets."""
    global _next_ok
    try:
        remaining = float(r.headers.get("x-ratelimit-remaining", "1"))
        reset = float(r.headers.get("x-ratelimit-reset", "0"))
    except ValueError:
        return
    if remaining < 1 and reset > 0:
        with _lock:
            _next_ok = max(_next_ok, CLOCK() + reset + 2)


def classify(link: str, permalink: str) -> str:
    l = link.lower()
    if "v.redd.it/" in l:
        return "video"
    if "i.redd.it/" in l or re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", l):
        return "image"
    if "/gallery/" in l:
        return "gallery"
    if re.search(r"reddit\.com/r/[^/]+/comments/", l):
        same = permalink and l.rstrip("/").endswith(permalink.lower().rstrip("/").split("reddit.com")[-1])
        return "self" if same else "crosspost"
    return "link" if l.startswith("http") else "self"


def _plain(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse(xml_text: str) -> list[Post]:
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    posts: list[Post] = []
    for entry in root.findall("a:entry", _ATOM):
        content = html.unescape(entry.findtext("a:content", default="", namespaces=_ATOM))
        permalink = (entry.find("a:link", _ATOM).get("href") if entry.find("a:link", _ATOM) is not None else "")
        m = re.search(r'<a href="([^"]+)">\[link\]</a>', content)
        link = html.unescape(m.group(1)) if m else permalink
        md = re.search(r'<div class="md">(.*?)</div>', content, re.S)
        cat = entry.find("a:category", _ATOM)
        thumb = entry.find("media:thumbnail", _ATOM)
        author = (entry.findtext("a:author/a:name", default="", namespaces=_ATOM) or "").removeprefix("/u/")
        stamp = entry.findtext("a:published", default="", namespaces=_ATOM) or \
            entry.findtext("a:updated", default="", namespaces=_ATOM)
        try:
            published = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else None
        except ValueError:
            published = None
        posts.append(Post(
            id=entry.findtext("a:id", default="", namespaces=_ATOM),
            title=html.unescape(entry.findtext("a:title", default="", namespaces=_ATOM)).strip(),
            permalink=permalink,
            subreddit=(cat.get("term") if cat is not None else "") or "",
            author=author, published=published,
            selftext=_plain(md.group(1))[:2000] if md else "",
            link=link, thumbnail=html.unescape(thumb.get("url", "")) if thumb is not None else "",
            kind=classify(link, permalink), rank=len(posts)))
    return posts


def feed(client: httpx.Client, subs: list[str], *, sort: str = "top", t: str = "day",
         limit: int = 50) -> list[Post]:
    """One keyless request for all of `subs`. Waits its turn under the limiter."""
    if not subs:
        return []
    sort = sort if sort in SORTS else "top"
    params = {"limit": str(min(max(limit, 1), 100))}
    if sort == "top":
        params["t"] = t if t in ("hour", "day", "week", "month", "year", "all") else "day"
    url = FEED.format(subs="+".join(subs), sort=sort)
    for attempt in range(2):
        _wait()
        r = client.get(url, params=params, headers={"User-Agent": UA}, follow_redirects=True, timeout=30)
        _note_limits(r)
        if r.status_code == 429 and attempt == 0:
            continue                       # _note_limits pushed the next slot past the reset
        if r.status_code != 200:
            raise RedditError(f"Reddit answered {r.status_code} for r/{'+'.join(subs)[:80]}", r.status_code)
        return parse(r.text)
    raise RedditError("Reddit kept answering 429 (rate limited)", 429)


def existing(client: httpx.Client, names: list[str]) -> set[str]:
    """Which of `names` are live, public communities: one combined /new feed; any
    community with a post in it exists. (A banned or private one in the list can
    make the whole request fail; then the caller checks them one by one.)"""
    posts = feed(client, names, sort="new", limit=100)
    return {p.subreddit.lower() for p in posts}


# ── API mode ──────────────────────────────────────────────────────────────────

class RedditAPI:
    """App-only OAuth with an approved app's id and secret (Settings → Reddit)."""

    def __init__(self, client: httpx.Client, client_id: str, client_secret: str):
        self.client, self.id, self.secret = client, client_id, client_secret
        self._token, self._expires = "", 0.0

    def _auth(self) -> str:
        if self._token and CLOCK() < self._expires - 60:
            return self._token
        r = self.client.post(TOKEN_URL, auth=(self.id, self.secret), data={"grant_type": "client_credentials"},
                             headers={"User-Agent": UA}, timeout=30)
        if r.status_code != 200:
            raise RedditError(f"Reddit refused the app's keys ({r.status_code})", r.status_code)
        body = r.json()
        self._token, self._expires = body["access_token"], CLOCK() + float(body.get("expires_in", 3600))
        return self._token

    def listing(self, subs: list[str], *, sort: str = "top", t: str = "day", limit: int = 50) -> list[Post]:
        params = {"limit": str(min(max(limit, 1), 100)), "raw_json": "1"}
        if sort == "top":
            params["t"] = t
        r = self.client.get(API.format(subs="+".join(subs), sort=sort if sort in SORTS else "top"),
                            params=params, timeout=30,
                            headers={"User-Agent": UA, "Authorization": f"Bearer {self._auth()}"})
        if r.status_code != 200:
            raise RedditError(f"Reddit API answered {r.status_code}", r.status_code)
        return [_from_api(c["data"], n) for n, c in enumerate(r.json()["data"]["children"])]


def _from_api(d: dict, rank: int) -> Post:
    permalink = "https://www.reddit.com" + d.get("permalink", "")
    link = d.get("url_overridden_by_dest") or d.get("url") or permalink
    rv = ((d.get("secure_media") or d.get("media") or {}).get("reddit_video")) or {}
    if d.get("is_video") and rv:
        kind = "video"
    elif d.get("is_gallery"):
        kind = "gallery"
    elif d.get("crosspost_parent"):
        kind = "crosspost"
    elif d.get("is_self"):
        kind = "self"
    else:
        kind = classify(link, permalink)
    preview = (((d.get("preview") or {}).get("images") or [{}])[0].get("source") or {}).get("url", "")
    return Post(id=d.get("name", ""), title=d.get("title", ""), permalink=permalink,
                subreddit=d.get("subreddit", ""), author=d.get("author", ""),
                published=datetime.fromtimestamp(d["created_utc"], timezone.utc) if d.get("created_utc") else None,
                selftext=(d.get("selftext") or "")[:2000], link=link, thumbnail=preview,
                kind=kind, rank=rank, score=d.get("score"), comments=d.get("num_comments"),
                over_18=d.get("over_18"),
                video={"hls": rv.get("hls_url"), "fallback": rv.get("fallback_url"),
                       "duration": rv.get("duration"), "height": rv.get("height")} if rv else {})
