"""The asset finder: real photos for a story, chosen by Jev, before the script.

Runs at the end of research_post (ideas lane: it fetches URLs), when the owner has
a Jev key:

  1. Is the story a real event that was photographed or filmed (an incident, a
     protest, a flood, a match, a launch) — or a concept, an invention, a forecast,
     an explainer? Only a real event looks for news photos; anything else keeps to
     open-licence pictures that show its subject, or none (its shots are generated).
  2. Candidates: the photos of the articles read for the story (their lead picture
     and large in-article pictures), and open-licence pictures from Wikimedia
     Commons and Openverse (searched by the story's own words).
  3. Jev looks at each one (image input) — does it show this story, is it a usable
     photograph, is there a watermark or a channel logo, is it graphic — and the
     best few join the post as assets (approved: owner's rule of 2026-10-18 for real
     events), credited on screen and in the caption, then fetched and analysed like
     any footage. write_script waits for them.

A before/after post (the Before vs. After template) also wants the place as it was:
Jev says of each picture whether it shows the story's place or thing before the event
(intact, undamaged, earlier), and up to BEFORE_KEEP of those are kept besides the
event's own pictures, marked so the script writer opens on one as BEFORE.

A real event's own video counts most: the videos in the articles read (yt-dlp knows
the BBC's, NDTV's, CNN's…) are judged by Jev from a frame and their title, and the
best VIDEO_KEEP join the post as clips (live: the BBC's 30 s of Limoges town hall's
spire collapsing, where the reel had only an AI illustration of it).

Never: a post whose owner asked for an AI version of its media, graphic pictures,
watermarked ones, or more than KEEP (+ BEFORE_KEEP). Videos come from the idea itself (Reddit and
the social feeds); article pages rarely offer a usable video file.
"""

from __future__ import annotations

import io
import logging
import re
from concurrent.futures import ThreadPoolExecutor

import httpx
from psycopg.types.json import Jsonb

from . import db, net
from .ideas import media
from .jev import Jev, score, yes
from .research import Article, sig_tokens

log = logging.getLogger("corpus.finder")

KEEP = 4
BEFORE_KEEP = 2
VIDEO_KEEP = 2
VIDEO_PAGES = 5
MAX_CANDIDATES = 14
IMAGE_BYTES = 8_000_000
COMMONS = "https://commons.wikimedia.org/w/api.php"
WIKIPEDIA = "https://en.wikipedia.org/w/api.php"
OPENVERSE = "https://api.openverse.org/v1/images/"
UA = "ContentCorpus/1.0 (asset finder; https://content-corpus.strophic.in)"

REAL_EVENT = {"real_event": {"type": "noul", "instructions":
              "Is `story` about a specific real event that was photographed or filmed — an incident, accident, "
              "protest, disaster, match, speech, ceremony or launch — rather than a concept, invention, study, "
              "forecast or general explainer?"}}

PHOTO_QUESTIONS = {
    "shows": {"type": "score", "instructions": "How closely does `photo` show `story`?",
              "criteria": ["Unrelated to the story", "The general topic, not this story",
                           "The place, people or things of this story", "The event of this story itself"]},
    "usable": {"type": "noul", "instructions": "Is `photo` a clear photograph that works full screen — not a logo, "
                                              "chart, map, screenshot, collage, poster or text graphic?"},
    "watermark": {"type": "noul", "instructions": "Does `photo` carry a visible watermark or a TV channel's logo?"},
    "graphic": {"type": "noul", "instructions": "Does `photo` show gore, blood, injured or dead people, or other "
                                               "graphic content?"},
}
VIDEO_QUESTIONS = {
    "shows": {"type": "score", "instructions": "How closely does the news video titled `video_title` (one frame of "
                                               "it is `frame`) show `story`?",
              "criteria": ["Unrelated to the story", "The general topic, not this story",
                           "The place, people or things of this story", "The event of this story itself"]},
    "graphic": {"type": "noul", "instructions": "Does `frame` show gore, blood, injured or dead people, or other "
                                               "graphic content?"},
}

BEFORE_QUESTION = {
    "before": {"type": "noul", "instructions": "Does `photo` show the place, building or thing at the centre of `story` "
                                              "as it was BEFORE the event - intact, undamaged, or at an earlier time - "
                                              "rather than during or after it?"},
}


def _query(title: str) -> str:
    """Search words for the picture libraries: the headline's own significant words, in
    order, names first ("Limoges town hall spire falls" → "Limoges town hall spire")."""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]+", title) if sig_tokens(w)]
    names = [w for w in words if w[0].isupper()]
    picked = list(dict.fromkeys(names + words))[:4]
    return " ".join(picked)


def _same_picture(url: str) -> str:
    """One key for the sizes and crops of one picture (…/976/abc-1.jpg, …/1536/abc-1.jpg)."""
    name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1].lower()
    name = re.sub(r"\.(webp|avif)$", "", name) if re.search(r"\.(jpe?g|png)\.(webp|avif)$", name) else name
    return re.sub(r"[-_.]?(\d{2,4}x\d{2,4}|\d{3,4}w)(?=\.)", "", name)


def commons(client: httpx.Client, query: str, n: int = 5) -> list[dict]:
    r = client.get(COMMONS, params={"action": "query", "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
                                    "gsrnamespace": 6, "gsrlimit": n, "prop": "imageinfo",
                                    "iiprop": "url|extmetadata|size", "iiurlwidth": 1280, "format": "json"},
                   headers={"User-Agent": UA}, timeout=20)
    return _commons_files(r.json())


def _commons_files(body: dict, origin: str = "commons") -> list[dict]:
    out = []
    for page in ((body.get("query") or {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()[:60]
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        if not info.get("thumburl") or not lic:
            continue
        out.append({"url": info["thumburl"], "page": info.get("descriptionurl"), "origin": origin,
                    "credit": f"{artist or 'Unknown'} / Wikimedia Commons, {lic}"[:120],
                    "license": "cc0" if re.search(r"public domain|cc0", lic, re.I) else "third_party"})
    return out


# Words that name what happened rather than where: dropped from a "before" search.
NEWS_WORDS = {"protest", "protests", "protesters", "arrested", "arrests", "arrest", "falls", "fall", "fell", "collapses",
              "collapse", "collapsed", "burns", "burned", "burning", "fire", "fires", "blaze", "killed", "dead", "dies",
              "says", "after", "amid", "during", "over", "as", "in", "the", "a", "an", "of", "and", "to", "at", "on",
              "for", "with", "by", "from", "is", "are", "was", "were", "hit", "hits", "destroyed", "damaged", "flood",
              "floods", "flooded", "storm", "quake", "earthquake", "breaking", "live", "update", "updates", "video",
              "before", "vs", "now", "then", "watch", "moment"}


def _place_queries(title: str, most: int = 5) -> list[str]:
    """Short searches for the place in a headline. Sentence case names it in capitals
    ("Joshimath sinking: cracks widen" → "Joshimath"); in Title Case every word is
    capitalised, so short runs of the words left after dropping what happened are
    tried ("Protests in France: 1,000 Arrested as Limoges Town Hall Spire Falls" →
    "Limoges Town Hall", "Town Hall Spire", …)."""
    raw = re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'-]+", title)
    words = [w for w in raw if w.lower() not in NEWS_WORDS]
    caps = [w for w in raw if w[0].isupper()]
    out: list[str] = []
    if raw and len(caps) / len(raw) < 0.6:             # sentence case: the names are the place
        run: list[str] = []
        for w in raw + ["."]:
            if w[0].isupper() and w.lower() not in NEWS_WORDS:
                run.append(w)
            elif run:
                out.append(" ".join(run))
                run = []
        return list(dict.fromkeys(out))[:most]
    for size in (3, 2, 4):
        for i in range(len(words) - size + 1):
            q = " ".join(words[i:i + size])
            if q not in out:
                out.append(q)
    # Middle windows first: a headline's place is rarely its first or last word.
    out.sort(key=lambda q: (len(q.split()) != 3, abs(len(words) / 2 - words.index(q.split()[0]) - 1)))
    return out[:most]


def wikipedia(client: httpx.Client, *titles: str, per_query: int = 2) -> list[dict]:
    """The lead pictures of the Wikipedia articles a headline's place searches find: a
    landmark's article leads with a free photo of it as it is normally — the "before".
    Several titles (the post's topic and the report's headline): a report may not name
    the place ("historic French town hall") where the topic does ("Limoges")."""
    names: list[str] = []
    queries = list(dict.fromkeys(q for t in titles if t for q in _place_queries(t, most=4)))[:7]
    for q in queries:
        r = client.get(WIKIPEDIA, params={"action": "query", "generator": "search", "gsrsearch": q,
                                          "gsrlimit": per_query, "prop": "pageimages", "piprop": "name",
                                          "format": "json"}, headers={"User-Agent": UA}, timeout=20)
        pages = sorted(((r.json().get("query") or {}).get("pages") or {}).values(), key=lambda p: p.get("index", 99))
        for pg in pages:
            if pg.get("pageimage") and pg["pageimage"] not in names:
                names.append(pg["pageimage"])
    if not names:
        return []
    r = client.get(COMMONS, params={"action": "query", "titles": "|".join(f"File:{n}" for n in names[:8]),
                                    "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": 1280,
                                    "format": "json"}, headers={"User-Agent": UA}, timeout=20)
    return _commons_files(r.json(), origin="wikipedia")


def openverse(client: httpx.Client, query: str, n: int = 5) -> list[dict]:
    r = client.get(OPENVERSE, params={"q": query, "page_size": n, "license_type": "commercial,modification",
                                      "mature": "false"}, headers={"User-Agent": UA}, timeout=20)
    out = []
    for it in r.json().get("results") or []:
        if not it.get("url"):
            continue
        lic = f"CC {str(it.get('license', '')).upper()} {it.get('license_version') or ''}".strip()
        out.append({"url": it["url"], "page": it.get("foreign_landing_url"), "origin": "openverse",
                    "credit": f"{(it.get('creator') or 'Unknown')[:50]} / {it.get('source') or 'Openverse'}, {lic}"[:120],
                    "license": "cc0" if it.get("license") in ("cc0", "pdm") else "third_party"})
    return out


def article_photos(articles: list[Article]) -> list[dict]:
    return [{"url": im["url"], "page": a.url, "origin": "article", "credit": a.site, "license": "third_party",
             "caption": im.get("caption", "")}
            for a in articles if a.ok for im in a.images]


def _download(client: httpx.Client, url: str) -> bytes | None:
    """The picture as a JPEG Jev can read (at most 1280 px, at least 280 px a side)."""
    from PIL import Image

    try:
        raw = net.get(client, url, max_bytes=IMAGE_BYTES, accept=("image/",),
                      headers={"User-Agent": net.user_agent(url)}).content
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:  # noqa: BLE001 - an unreadable picture is skipped
        return None
    if min(img.size) < 400:
        return None
    img = img.convert("RGB")
    img.thumbnail((1280, 1280))
    if min(img.size) < 280:
        return None
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def find(judge: Jev, client: httpx.Client, story: str, articles: list[Article],
         title: str = "", want_before: bool = False, topic: str = "") -> tuple[list[dict], float]:
    """(the pictures worth adding to the post, best first, with their Jev scores;
    how sure Jev is that the story is a real, filmed event). want_before: a
    before/after post — pictures of the place before the event are kept too."""
    real = yes((judge.ask({"story": story[:1500]}, REAL_EVENT)).get("real_event"))
    cands = article_photos(articles) if real >= 0.5 else []
    q = _query(title or story.split(".")[0])
    for src in (commons, openverse):
        try:
            cands += src(client, q)
        except Exception as e:  # noqa: BLE001 - one library down is fine
            log.warning("finder: %s: %s", src.__name__, e)
    if want_before:
        try:
            cands = wikipedia(client, topic, title or story.split(".")[0]) + cands
        except Exception as e:  # noqa: BLE001
            log.warning("finder: wikipedia: %s", e)
    # One copy of each picture; a news site's "branded" copy (its logo burned in) last.
    cands.sort(key=lambda c: "brand" in c["url"].lower())
    seen, unique = set(), []
    for c in cands:
        key = _same_picture(c["url"])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    unique = unique[:MAX_CANDIDATES]
    with ThreadPoolExecutor(max_workers=6) as pool:
        pictures = list(pool.map(lambda c: _download(client, c["url"]), unique))
    jobs = [(c, data) for c, data in zip(unique, pictures) if data]
    answers = _ask_images(judge, story, jobs, want_before)
    picked = []
    for (c, _), a in zip(jobs, answers):
        if a is None:
            continue
        shows, usable = score(a.get("shows")), yes(a.get("usable"))
        if yes(a.get("graphic"), 1.0) >= 0.3 or yes(a.get("watermark"), 1.0) >= 0.5 or usable < 0.5:
            continue
        # A photo from an article about this very story is relevant by where it came from:
        # it needs only to show its subject (Jev scored the BBC's own photos of an event
        # 1.2-1.7 of 3, live). A library picture has to earn it: the story's place, people
        # or things.
        before = yes(a.get("before")) if want_before else 0.0
        # A picture of the place as it was cannot show the event itself: Jev scored the
        # intact Hôtel de Ville of Limoges 1.71 for a story about its spire burning (and
        # other cities' town halls under 1), so a sure "before" needs only 1.5.
        need = 1.1 if c["origin"] == "article" else 1.5 if before >= 0.8 else 1.8
        if shows < need:
            continue
        picked.append({**c, "shows": round(shows, 2), "usable": round(usable, 2), "before": round(before, 2)})
    picked.sort(key=lambda c: (c["origin"] == "article", c["shows"] + c["usable"]), reverse=True)
    clips: list[dict] = []
    if real >= 0.5:
        try:
            clips = videos(judge, client, story, articles)
        except Exception as e:  # noqa: BLE001 - the photos still go
            log.warning("finder: videos: %s", e)
    if not want_before:
        return clips + picked[:KEEP], real
    # The place as it was, first (best-shown first), then the event's own pictures.
    befores = sorted((c for c in picked if c["before"] >= 0.6), key=lambda c: c["shows"], reverse=True)[:BEFORE_KEEP]
    rest = [c for c in picked if c not in befores][:KEEP]
    return befores + clips + rest, real


def videos(judge: Jev, client: httpx.Client, story: str, articles: list[Article]) -> list[dict]:
    """The best videos in the articles read for a real event, judged by Jev from a frame
    and their title; one copy of each (a clip often sits on two pages)."""
    pages = [a for a in articles if a.ok][:VIDEO_PAGES]
    with ThreadPoolExecutor(max_workers=4) as pool:
        found = list(pool.map(lambda a: [(a, v) for v in media.page_videos(a.url)], pages))
    by_id: dict[str, tuple[Article, dict]] = {}
    for a, v in (x for lst in found for x in lst):
        if v["id"] not in by_id or (v["thumbnail"] and not by_id[v["id"]][1]["thumbnail"]):
            by_id[v["id"]] = (a, v)
    picked = []
    for a, v in list(by_id.values())[:6]:
        frame = _download(client, v["thumbnail"]) if v["thumbnail"] else _video_frame(v)
        if not frame:
            continue
        try:
            ans = judge.ask({"story": story[:1200], "video_title": v["title"], "frame": "frame-1"}, VIDEO_QUESTIONS,
                            images={"frame-1": frame})
        except Exception as e:  # noqa: BLE001
            log.warning("finder: jev on a video: %s", e)
            continue
        shows = score(ans.get("shows"))
        if yes(ans.get("graphic"), 1.0) >= 0.3 or shows < 1.6:
            continue
        picked.append({"kind": "video", "url": v["page"], "page": v["page"], "index": v["index"], "video_id": v["id"],
                       "title": v["title"], "seconds": v["seconds"], "origin": "article", "credit": a.site,
                       "license": "third_party", "shows": round(shows, 2), "usable": 1.0, "before": 0.0})
    picked.sort(key=lambda c: c["shows"], reverse=True)
    return picked[:VIDEO_KEEP]


def _video_frame(v: dict) -> bytes | None:
    """A frame of a page's video that has no thumbnail: a small copy, its poster."""
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as tmp:
            clip = media.page_video(v["page"], v["index"], Path(tmp), media.PREVIEW)
            return media.poster(clip, Path(tmp) / "poster.jpg").read_bytes()
    except Exception as e:  # noqa: BLE001
        log.warning("finder: a frame of %s: %s", v["page"], e)
        return None


def _ask_images(judge: Jev, story: str, jobs: list[tuple[dict, bytes]], want_before: bool = False) -> list[dict | None]:
    questions = {**PHOTO_QUESTIONS, **BEFORE_QUESTION} if want_before else PHOTO_QUESTIONS

    def one(job):
        try:
            return judge.ask({"story": story[:1200], "photo": "photo-1"}, questions, images={"photo-1": job[1]})
        except Exception as e:  # noqa: BLE001 - that picture is skipped
            log.warning("finder: jev: %s", e)
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(one, jobs))


def add_to_post(post: dict, picked: list[dict]) -> int:
    """The chosen pictures and videos as the post's assets (approved, credited), queued to fetch."""
    added = 0
    with db.tx() as c:
        have = set()
        for r in c.execute("select fetch_from from assets where post_id = %s", (post["id"],)).fetchall():
            item = (r["fetch_from"] or {}).get("item", {})
            have.add(item.get("image_url") or item.get("video_id"))
        n = c.execute("select coalesce(max(n), 0) as n from assets where post_id = %s", (post["id"],)).fetchone()["n"]
        for p in picked:
            video = p.get("kind") == "video"
            if (p["video_id"] if video else p["url"]) in have:
                continue
            n += 1
            item = ({"page_url": p["page"], "page_index": p["index"], "video_id": p["video_id"], "media_hint": "video",
                     "link": p["page"], "title": p.get("title", "")} if video
                    else {"image_url": p["url"], "media_hint": "image", "link": p.get("page")})
            aid = c.execute(
                """insert into assets (user_id, post_id, n, kind, origin, source_url, credit, license, rights, fetch_from)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, 'approved', %s) returning id""",
                (post["user_id"], post["id"], n, "video" if video else "image", p["origin"], p.get("page"),
                 p["credit"], p["license"],
                 Jsonb({"item": item, "found": {"shows": p["shows"], "usable": p["usable"],
                                                "before": p.get("before", 0.0)}}))).fetchone()["id"]
            db.enqueue(c, user_id=post["user_id"], lane="ideas", kind="fetch_asset", dedupe_key=f"fetch_asset:{aid}",
                       payload={"asset_id": str(aid)}, post_id=post["id"], priority=30, max_attempts=2,
                       lease_seconds=900)
            added += 1
    return added
