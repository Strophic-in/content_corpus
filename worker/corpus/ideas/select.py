"""The cheap first gate before any token is spent (ported from TrendCaster's research.py).

junk_reason() cuts whole genres that can never carry a video — corporate calendar
notices, reviews and buying guides, deals, listicles and roundups, opinion and
live blogs, daily-utility pages, press releases — and says which, so the log can
show an over-eager pattern. score() ranks the survivors by what predicts a
stop-scroll: a consequence ("arrested", "banned", "collapses"), a real figure,
freshness, and — new here — the post's rank in Reddit's top-of-day and whether
it comes with video or pictures. Only the top few reach the model, which may
then still pick none of them.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .feeds import Item

_JUNK_PATTERNS: tuple[tuple[str, str], ...] = (
    ("calendar", r"\b(record date|ex[- ]dividend|agm|egm|board meeting|bonus issue|stock split|rights issue|"
                 r"earnings call|analyst meet|to be held on|scheduled for)\b"),
    # Anchored to shapes only shopping content has: bare "review" or "vs" would cut
    # "Supreme Court to review its order" and "India vs Australia".
    ("review", r"\b(hands[- ]on|first look|unboxing|buying guide|we tried|i tried|we tested)\b"
               r"|\breview\s*[:|]|\breview\s*$|\btop \d+\b|\b\d+ best\b"
               r"|\bbest\b[^.]{0,25}\b(under|to buy|of \d{4}|in \d{4})\b"),
    ("deal", r"\b(deal|deals|discount|coupon|sale|price drop|prime day|black friday|cyber monday|"
             r"lowest price|save \$|\d+% off)\b"),
    ("listicle", r"^\s*\d+\s+(things|ways|reasons|tips|facts|signs|of the)|"
                 r"\b(roundup|round-up|week in review|this week in|weekly digest|morning brief|news wrap|"
                 r"top stories|what to watch|everything you need to know|everything we know|what to know)\b"),
    ("opinion", r"\b(opinion|editorial|commentary|essay|memoir|my favou?rite|why i |i spent|i watched|"
                r"newsletter|weekend edition)\b|\bpodcast (episode|drops|out now)\b"),
    ("live", r"\b(live updates?|live blog|live score|as it happened|highlights:|minute by minute|"
             r"full scorecard)\b"),
    ("utility", r"\b(horoscope|rashifal|numerology|weather forecast|lottery result|sambad|admit card|"
                r"answer key|hall ticket|merit list|cut ?off list|exam date|petrol.{0,15}price today|"
                r"gold rate today|silver rate today)\b"),
    ("pr", r"\b(sponsored|partner content|promoted|press release|webinar|announces partnership|signs mou|"
           r"appointed as|named as the new|felicitated|inaugurates|launches new website)\b"),
    # Reddit housekeeping.
    ("meta", r"\b(megathread|weekly thread|daily discussion|mod post|subreddit rules)\b"),
)
_JUNK_RE = tuple((label, re.compile(pat, re.IGNORECASE)) for label, pat in _JUNK_PATTERNS)

_STAKES_RE = re.compile(
    r"\b(arrest\w*|jail\w*|sentenc\w*|convict\w*|acquit\w*|verdict|custody|raid\w*|seiz\w*|confess\w*|"
    r"charged|indict\w*|summon\w*|probe|manhunt|sues|sued|lawsuit|fined|penalt\w*|banned?|bans|block\w*|"
    r"halt\w*|suspend\w*|revok\w*|overturn\w*|strike\w*|shutdown|resign\w*|quits|fired|sacked|ousted|"
    r"steps down|layoffs?|lays off|dies|died|dead|killed|murder\w*|shot|stabb\w*|kidnapp\w*|abduct\w*|"
    r"assault\w*|missing|rescued|evacuat\w*|fraud|scam|scandal|bribe\w*|launder\w*|embezzl\w*|leak\w*|"
    r"hack\w*|breach\w*|stolen|exposed|caught|busted|crackdown|crash\w*|collaps\w*|plunge\w*|plummet\w*|"
    r"tumbl\w*|wipe\w*|surg\w*|soar\w*|spike\w*|jump\w*|rally|rallies|bankrupt\w*|default\w*|bailout|"
    r"recall\w*|explosion|blast|fire|flood\w*|earthquake|cyclone|landslide|warns?|threaten\w*|reject\w*|"
    r"denies|admits|reveal\w*|accus\w*|first[- ]ever|biggest|worst|record|breaks?|shatter\w*|beats?|wins?|"
    r"defeat\w*|upset|approve[sd]?|clears?|discover\w*|found|footage|captured|filmed)\b",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(
    r"[₹$€£]\s?\d|\b\d[\d,.]*\s?(crore|lakh|billion|million|trillion|bn|mn|k)\b|\b\d+(\.\d+)?%", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d")


def junk_reason(title: str) -> str | None:
    for label, pattern in _JUNK_RE:
        if pattern.search(title or ""):
            return label
    return None


def _hours(item: Item) -> float | None:
    if item.published is None:
        return None
    return (datetime.now(timezone.utc) - item.published).total_seconds() / 3600


def score(item: Item) -> float:
    title = item.title or ""
    s = 0.0
    if _STAKES_RE.search(title):
        s += 3.0
    if _MONEY_RE.search(title):
        s += 2.5
    elif _NUMBER_RE.search(title):
        s += 1.0
    hours = _hours(item)
    if hours is not None:
        s += 3.0 if hours <= 3 else 2.0 if hours <= 12 else 1.0 if hours <= 24 else (-2.0 if hours >= 48 else 0)
    words = len(title.split())
    if 6 <= words <= 14:
        s += 0.5
    elif words > 20:
        s -= 1.0
    reddit = item.extra.get("subreddit") is not None
    if reddit:
        # Rank in top-of-day is Reddit's own vote count, the best signal there is.
        s += 3.0 if item.rank < 5 else 2.0 if item.rank < 15 else 1.0 if item.rank < 30 else 0
    elif title.rstrip().endswith("?"):
        s -= 1.5            # on news sites a question headline is usually opinion or SEO bait
    if item.media_hint == "video":
        s += 1.5
    elif item.media_hint in ("image", "gallery"):
        s += 1.0
    return s


def prefilter(items: list[Item], *, keep: int = 25, max_age_hours: float = 48) -> tuple[list[Item], dict]:
    """(the `keep` best, cut counts by reason). Junk and stale items are removed."""
    cuts: dict[str, int] = {}
    kept: list[Item] = []
    for it in items:
        reason = junk_reason(it.title)
        if reason is None and it.media_hint == "crosspost":
            reason = "crosspost"          # its media lives in another post, unreachable keyless
        if reason is None:
            hours = _hours(it)
            if hours is not None and hours > max_age_hours:
                reason = "stale"
        if reason:
            cuts[reason] = cuts.get(reason, 0) + 1
            continue
        kept.append(it)
    kept.sort(key=score, reverse=True)
    return kept[:keep], cuts
