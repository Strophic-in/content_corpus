"""News sites and news search as sources (ported from TrendCaster's feeds.py).

A `site` source is a domain. Its feeds come from KNOWN_FEEDS (verified by hand:
most news CMSes no longer declare their feeds, publish them under paths no
convention predicts, and some answer a homepage request with 403 while serving
the feed fine), then from what the homepage declares (<link rel="alternate">),
then from conventional paths. At most MAX_FEEDS_PER_DOMAIN per site, so one big
outlet can't crowd out the rest.

A `search` source asks Bing News (RSS, keyless) who covered a topic: the only way
a category reaches newsrooms its site list has never heard of. Bing wraps every
result in a click-tracking redirect; the real URL is unwrapped.

Every request goes through net.get (public addresses only, size-capped).
"""

from __future__ import annotations

import threading
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

import httpx

from .. import net
from . import feeds

MAX_FEEDS_PER_DOMAIN = 4
FEED_BYTES = 3_000_000
_HEADERS = {"User-Agent": net.BROWSER_UA,
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"}
_CONVENTIONAL_PATHS = ("/feed", "/rss", "/rss.xml", "/feed.xml", "/index.xml", "/atom.xml",
                       "/feeds/all.rss.xml", "/rssfeeds.xml")

KNOWN_FEEDS: dict[str, tuple[str, ...]] = {
    # India — general, crime, politics
    "ndtv.com": ("https://feeds.feedburner.com/ndtvnews-india-news",
                 "https://feeds.feedburner.com/ndtvnews-top-stories"),
    "hindustantimes.com": ("https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",
                           "https://www.hindustantimes.com/feeds/rss/cities/rssfeed.xml"),
    "indiatoday.in": ("https://www.indiatoday.in/rss/home", "https://www.indiatoday.in/rss/1206578"),
    "indianexpress.com": ("https://indianexpress.com/feed",),
    "thehindu.com": ("https://www.thehindu.com/feeder/default.rss",),
    "timesofindia.indiatimes.com": ("https://timesofindia.indiatimes.com/rssfeedstopstories.cms",),
    "news18.com": ("https://www.news18.com/rss/india.xml",),
    "firstpost.com": ("https://www.firstpost.com/commonfeeds/v1/mfp/rss/india.xml",),
    # World
    "bbc.com": ("https://feeds.bbci.co.uk/news/rss.xml", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    "aljazeera.com": ("https://www.aljazeera.com/xml/rss/all.xml",),
    "politico.com": ("https://rss.politico.com/politics-news.xml",),
    # Money
    "livemint.com": ("https://www.livemint.com/rss/news",),
    "economictimes.indiatimes.com": ("https://economictimes.indiatimes.com/rssfeedstopstories.cms",),
    "cnbc.com": ("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",),
    "marketwatch.com": ("https://feeds.content.dowjones.io/public/rss/mw_topstories",),
    # Science and tech
    "arstechnica.com": ("https://arstechnica.com/feed/",),
    "techcrunch.com": ("https://techcrunch.com/feed/",),
    "theverge.com": ("https://www.theverge.com/rss/index.xml",),
    "phys.org": ("https://phys.org/rss-feed/",),
    "sciencedaily.com": ("https://www.sciencedaily.com/rss/all.xml",),
    "space.com": ("https://www.space.com/feeds/all",),
    "newscientist.com": ("https://www.newscientist.com/feed/home/",),
    # AI, crypto, quantum
    "venturebeat.com": ("https://venturebeat.com/feed/",),
    "technologyreview.com": ("https://www.technologyreview.com/feed/",),
    "spectrum.ieee.org": ("https://spectrum.ieee.org/customfeeds/feed/all-topics/rss",),
    "coindesk.com": ("https://www.coindesk.com/arc/outboundfeeds/rss/",),
    "cointelegraph.com": ("https://cointelegraph.com/rss",),
    "decrypt.co": ("https://decrypt.co/feed",),
}

_cache_lock = threading.Lock()
_feed_cache: dict[str, list[str]] = {}


def normalize_domain(raw: str) -> str:
    """'https://www.ndtv.com/world/' → 'https://www.ndtv.com'."""
    d = str(raw or "").strip().rstrip("/")
    if not d:
        return ""
    if not d.startswith("http"):
        d = f"https://{d}"
    p = urlparse(d)
    return f"{p.scheme}://{p.netloc}" if p.netloc else ""


def host_key(base: str) -> str:
    host = urlparse(base).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _get_text(client: httpx.Client, url: str) -> str | None:
    try:
        r = net.get(client, url, max_bytes=FEED_BYTES, headers=_HEADERS)
    except Exception:  # noqa: BLE001 - discovery tries the next option
        return None
    try:
        return r.content.decode("utf-8")
    except UnicodeDecodeError:
        return r.content.decode("latin-1")


def looks_like_feed(text: str) -> bool:
    head = text.lstrip()[:400].lower()
    return "<rss" in head or "<feed" in head or "<rdf" in head


class _Links(HTMLParser):
    """<link rel=alternate type=rss/atom> and og: meta tags of a page."""

    def __init__(self):
        super().__init__()
        self.feeds: list[str] = []
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "link" and "alternate" in a.get("rel", "").lower() and \
                any(t in a.get("type", "").lower() for t in ("rss", "atom", "xml")) and a.get("href"):
            self.feeds.append(a["href"].strip())
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in ("og:image", "og:image:secure_url", "twitter:image", "og:video", "og:video:secure_url",
                       "og:title", "og:description") and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"].strip()


def page_links(html_text: str, base: str) -> _Links:
    p = _Links()
    try:
        p.feed(html_text)
    except Exception:  # noqa: BLE001 - malformed pages give what they gave
        pass
    p.feeds = [urljoin(base, u) for u in p.feeds if urljoin(base, u).startswith("http")]
    p.meta = {k: urljoin(base, v) if k.endswith(("image", "video", "secure_url")) else v for k, v in p.meta.items()}
    return p


def discover(client: httpx.Client, domain: str) -> list[str]:
    """Feed URLs for a domain, best first; cached for the process."""
    base = normalize_domain(domain)
    if not base:
        return []
    with _cache_lock:
        if base in _feed_cache:
            return _feed_cache[base]
    found = list(KNOWN_FEEDS.get(host_key(base), ()))
    home = _get_text(client, base)
    if home:
        if looks_like_feed(home):
            found.append(base)
        else:
            found.extend(u for u in page_links(home, base).feeds if u not in found)
    if not found:
        for path in _CONVENTIONAL_PATHS:
            body = _get_text(client, base + path)
            if body and looks_like_feed(body):
                found.append(base + path)
                break
    found = found[:MAX_FEEDS_PER_DOMAIN]
    with _cache_lock:
        _feed_cache[base] = found
    return found


def read_feed(client: httpx.Client, name: str, url: str) -> list[feeds.Item]:
    body = _get_text(client, url)
    if not body:
        raise RuntimeError(f"{url[:80]} did not answer")
    return feeds.parse(name, url, body)


def unwrap_bing(url: str) -> str:
    if "bing.com/news/apiclick" not in url.lower():
        return url
    real = (parse_qs(urlparse(url).query).get("url") or [""])[0]
    return real if real.startswith("http") else url


def search_news(client: httpx.Client, query: str, *, market: str = "en-IN", count: int = 20) -> list[feeds.Item]:
    if not query.strip():
        return []
    url = f"https://www.bing.com/news/search?q={quote_plus(query)}&format=RSS&setmkt={market}&count={count}"
    body = _get_text(client, url)
    if not body or not looks_like_feed(body):
        raise RuntimeError("Bing News did not answer")
    out = []
    for it in feeds.parse(f"news: {query}", url, body)[:count]:
        real = unwrap_bing(it.url)
        if real.startswith("http"):
            out.append(feeds.Item(urlparse(real).netloc.removeprefix("www."), it.title, it.summary, real,
                                  published=it.published, rank=it.rank, media_hint="link"))
    return out
