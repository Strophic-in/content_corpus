"""Free trend feeds: what people are reading and searching right now.

A source is {"name", "url"} from the format. Understood formats: RSS 2.0 (including
Google Trends' feed and its news items), Atom (Reddit's .rss feeds), and Wikimedia's
featured feed (Wikipedia's most-read articles). `{yesterday}` in a URL becomes
yesterday's UTC date as YYYY/MM/DD, which is what the Wikimedia feed wants. A feed
that fails is skipped; the batch goes on with the rest.
"""

from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx

USER_AGENT = "ContentCorpus/1.0 (+https://content-corpus.strophic.in)"
PER_SOURCE = 15
SUMMARY_CHARS = 240
# Wikipedia pages that are always "most read" and never an idea.
_WIKI_SKIP = re.compile(r"^(Main_Page|Special:|Wikipedia:|Portal:|File:|Help:|Deaths_in_)")

def default_sources() -> list[dict]:
    """The starting feed list for a new format (prompts/sources.json, shared with the web app)."""
    from ..config import settings

    return json.loads((settings().prompts_dir / "sources.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Item:
    source: str
    title: str
    summary: str
    url: str


def _text(s: str | None) -> str:
    s = re.sub(r"<[^>]+>", " ", html.unescape(s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*submitted by\s+/u/\S+.*$", "", s)      # Reddit's boilerplate
    if s.lower() in ("null", "none", "undefined"):
        return ""
    return s if len(s) <= SUMMARY_CHARS else s[:SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse(source: str, url: str, body: str) -> list[Item]:
    if "api.wikimedia.org/feed" in url:
        data = json.loads(body)
        out = []
        for a in (data.get("mostread") or {}).get("articles", []):
            title = a.get("titles", {}).get("normalized") or a.get("normalizedtitle") or ""
            if not title or _WIKI_SKIP.match(a.get("title", "")):
                continue
            page = (a.get("content_urls") or {}).get("desktop", {}).get("page", "")
            out.append(Item(source, title, _text(a.get("extract")), page))
        return out
    root = ET.fromstring(body.encode("utf-8") if isinstance(body, str) else body)
    out = []
    for el in root.iter():
        kind = _local(el.tag)
        if kind not in ("item", "entry"):
            continue
        fields = {_local(c.tag): c for c in el}
        title = _text((fields.get("title").text if fields.get("title") is not None else ""))
        if not title:
            continue
        if kind == "entry":   # Atom
            link = next((c.get("href") for c in el if _local(c.tag) == "link" and c.get("href")), "")
            body_el = fields.get("summary") if fields.get("summary") is not None else fields.get("content")
            summary = _text(body_el.text if body_el is not None else "")
        else:                 # RSS; Google Trends adds <ht:news_item> children
            link = (fields.get("link").text or "").strip() if fields.get("link") is not None else ""
            summary = _text(fields.get("description").text if fields.get("description") is not None else "")
            if not summary:
                news = [_text(n.text) for n in el.iter() if _local(n.tag) == "news_item_title"]
                summary = _text(" · ".join(n for n in news if n))
            news_url = next((n.text for n in el.iter() if _local(n.tag) == "news_item_url" and n.text), "")
            if news_url and "trends.google" in link:
                link = news_url.strip()
        out.append(Item(source, title, summary, link))
    return out


def _url(template: str) -> str:
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y/%m/%d")
    return template.replace("{yesterday}", yesterday)


def fetch_all(sources: list[dict], log: Callable[[str], None] = print,
              per_source: int = PER_SOURCE) -> list[Item]:
    """Newest items from every source, interleaved so no one feed dominates."""
    def one(src: dict) -> list[Item]:
        url = _url(src["url"])
        try:
            r = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
            r.raise_for_status()
            items = parse(src.get("name") or url, url, r.text)[:per_source]
            log(f"feed {src.get('name')}: {len(items)} items")
            return items
        except Exception as e:  # noqa: BLE001 - one bad feed must not sink the batch
            log(f"feed {src.get('name')}: skipped ({type(e).__name__}: {str(e)[:120]})")
            return []

    with ThreadPoolExecutor(max_workers=6) as pool:
        per_feed = list(pool.map(one, [s for s in sources if s.get("url")]))
    out, seen = [], set()
    for row in range(max((len(f) for f in per_feed), default=0)):
        for feed in per_feed:
            if row < len(feed) and feed[row].title.lower() not in seen:
                seen.add(feed[row].title.lower())
                out.append(feed[row])
    return out


def as_prompt(items: list[Item], limit: int = 70) -> str:
    if not items:
        return "(no trend feeds answered today — suggest strong evergreen ideas)"
    return "\n".join(f"- [{i.source}] {i.title}" + (f" — {i.summary}" if i.summary else "")
                     + (f" ({i.url})" if i.url else "") for i in items[:limit])
