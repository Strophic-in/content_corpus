"""Reading a story's sources in full, for the script writer (ported from TrendCaster's
scrape.py, without the `newspaper` dependency).

A feed gives a headline and two lines; a script needs the facts. For an accepted
idea, research_post reads each linked article — the article's own text only:
news pages wrap the story in "related" cards, author bios, newsletter pitches and
app rails, which clean_body_text() cuts — and, for a second view of the same
story, a few other outlets' reports found by a news search. Every page is fetched
through net (public addresses only, size-capped).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from . import net

PAGE_BYTES = 3_000_000
MAX_TEXT = 5000
TRUNCATED_CHARS = 600           # shorter than this: probably a teaser; try the AMP / "read more" page once

_RELATED_HINT = re.compile(
    r"(related|recommend|trending|popular|more[-_ ]?(news|stories|from)|also[-_ ]?read|"
    r"read[-_ ]?(more|next)|sidebar|carousel[-_ ]?widget|promo|newsletter|outbrain|taboola)", re.IGNORECASE)
_BODY_CLASS = re.compile(r"(article|story|post|entry)[-_]?(body|content|text)", re.IGNORECASE)
_READ_MORE_LABEL = re.compile(
    r"^\W*(read\s+more|continue\s+reading|(read|view|see)\s+(the\s+)?(full|original|complete|entire)\s+\w+|"
    r"full\s+(story|article|coverage|report))\b", re.IGNORECASE)

# Site chrome, matched per sentence (CMSes glue it onto real paragraphs).
_CHROME_RE = re.compile(
    r"posts? from this author|added to your (daily )?(email )?digest|your homepage feed"
    r"|sign\s+up\s+(for|to)\b[^.]{0,60}\b(newsletter|digest|briefing|alerts?)"
    r"|subscribe\s+(to|for)\b[^.]{0,60}\b(newsletter|digest|briefing|updates?)|enter your email"
    r"|by (signing up|subscribing)\b|we use cookies|cookie policy|all rights reserved"
    r"|follow (us|him|her|them|the [^.]{0,40}channel) on\b|join (our|the) (whatsapp|telegram|official)"
    r"|download the [^.]{0,40}\bapp\b|click here to (read|download|subscribe|follow|join)"
    r"|(also|must) read\s*[:–-]|story continues below|scroll (down )?to continue|continue reading below"
    r"|this (content|video) is (not|no longer) available|share this (story|article)|for all the latest\b"
    r"|get (the )?latest\b[^.]{0,60}\bupdates?\b|stay (updated|informed|tuned)\b"
    r"|the views expressed (in|are)\b|catch (all|the latest)\b", re.IGNORECASE)
# Author bios (extractors drop the byline link and leave "is the Verge's weekend editor…").
_BIO_RE = re.compile(
    r"^\s*is\s+(a|an|the|our)\b"
    r"|^\s*[\w.'-]+(\s+[\w.'-]+){0,3}\s+(is|was)\s+(a|an|the)\b[^.]{0,80}"
    r"\b(editor|writer|reporter|correspondent|journalist|columnist|contributor|anchor|producer)\b"
    r"|\b(covered|been covering|written about|reported on)\b[^.]{0,80}\bfor\s+(over\s+|more than\s+|nearly\s+)?\d+\s*years?"
    r"|\bpreviously,?\s+(he|she|they)\s+(was|worked|served)\b|\byou can (reach|contact|email|follow)\s+(him|her|them|me)\b"
    r"|\b(he|she|they) (also )?(writes|covers|hosts) (the|a|an)\b[^.]{0,40}\b(newsletter|podcast|column)\b",
    re.IGNORECASE)
# A paragraph that IS a label ("Advertisement", "Photo: …").
_LABEL_RE = re.compile(
    r"^\s*(advertisement|advt|sponsored|promoted|related|trending|recommended|most read|top stories|watch|video|"
    r"live updates?|comments?|share|published|updated|last updated|first published|"
    r"(file|representative|stock) (photo|image)|photo|image|picture|credit|photograph|source|by)\b\W{0,3}",
    re.IGNORECASE)
_LABEL_MAX_CHARS = 110
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_MIN_PARA_CHARS = 40


@dataclass
class Article:
    url: str
    site: str
    title: str
    text: str
    ok: bool = True
    error: str | None = None


def _clean_paragraph(para: str) -> str:
    kept = [s for s in _SENT_SPLIT.split(para) if s.strip() and not _CHROME_RE.search(s)]
    while kept and _BIO_RE.search(kept[0]):            # a bio runs from the start of its block
        kept.pop(0)
    return " ".join(s.strip() for s in kept).strip()


def clean_body_text(text: str) -> str:
    """Article text without bios, newsletter pitches and site furniture. Thin is
    fine: a story written from an author bio is worse than one with less to go on."""
    out = []
    for para in re.split(r"\n\s*\n|\n", text or ""):
        para = " ".join(para.split())
        if not para or (len(para) <= _LABEL_MAX_CHARS and _LABEL_RE.match(para)):
            continue
        cleaned = _clean_paragraph(para)
        if len(cleaned) >= _MIN_PARA_CHARS:
            out.append(cleaned)
    return "\n\n".join(out).strip()


def _in_related_block(tag) -> bool:
    for parent in tag.parents:
        ident = " ".join([str(parent.get("id") or ""), *map(str, parent.get("class") or [])])
        if ident and _RELATED_HINT.search(ident):
            return True
    return False


def _article_container(soup: BeautifulSoup):
    """The node holding THIS article's body: the biggest <article>, else
    schema.org's articleBody, else a conventional class name."""
    articles = soup.find_all("article")
    if articles:
        best = max(articles, key=lambda n: len(n.get_text(" ", strip=True)))
        if len(best.get_text(" ", strip=True)) > 400:
            return best
    node = soup.find(attrs={"itemprop": "articleBody"})
    return node or soup.find(class_=_BODY_CLASS) or soup.find(id=_BODY_CLASS)


def _fuller_versions(page_url: str, soup: BeautifulSoup, container) -> list[str]:
    out: list[str] = []

    def add(raw: str | None) -> None:
        url = urljoin(page_url, (raw or "").strip())
        if url.startswith("http") and url.split("#")[0].rstrip("/") != page_url.split("#")[0].rstrip("/") \
                and url not in out:
            out.append(url)
    amp = soup.find("link", rel="amphtml")
    if amp:
        add(amp.get("href"))
    for a in (container if container is not None else soup).find_all("a", href=True):
        if _READ_MORE_LABEL.match(a.get_text(" ", strip=True)[:80]):
            add(a["href"])
    return out[:2]


def extract(html: str, url: str) -> tuple[str, str, BeautifulSoup, object]:
    """(title, cleaned text, soup, container) of one page."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form"]):
        t.decompose()
    og = soup.find("meta", attrs={"property": "og:title"})
    title = ((og.get("content") if og else "") or (soup.title.get_text(strip=True) if soup.title else "")).strip()
    container = _article_container(soup)
    scope = container if container is not None else soup
    text = "\n\n".join(p.get_text(" ", strip=True) for p in scope.find_all("p")
                       if len(p.get_text(strip=True)) > 40 and not _in_related_block(p))
    if not text:
        for name, attr in (("description", "name"), ("og:description", "property")):
            m = soup.find("meta", attrs={attr: name})
            if m and m.get("content"):
                text = m["content"]
                break
    return title, clean_body_text(text), soup, container


def read(client: httpx.Client, url: str, *, _hop: int = 0) -> Article:
    site = urlparse(url).netloc.removeprefix("www.")
    try:
        page = net.get(client, url, max_bytes=PAGE_BYTES, accept=("text/html", "application/xhtml"),
                       headers={"User-Agent": net.BROWSER_UA})
        title, text, soup, container = extract(page.content.decode("utf-8", "replace"), page.url)
    except Exception as e:  # noqa: BLE001 - one unreadable page doesn't stop the research
        return Article(url, site, "", "", ok=False, error=f"{type(e).__name__}: {str(e)[:160]}")
    if _hop == 0 and len(text) < TRUNCATED_CHARS:
        for alt in _fuller_versions(page.url, soup, container):
            fuller = read(client, alt, _hop=1)
            if fuller.ok and len(fuller.text) >= len(text) + 200:
                return Article(url, site, title or fuller.title, fuller.text[:MAX_TEXT])
    return Article(url, site, title, text[:MAX_TEXT], ok=bool(text))
