"""The asset finder: a post's real pictures and videos, collected before its script.

Every post collects its assets first (owner, 2026-10-19: a reel about the Jio IPO
had no Jio logo, no article, only abstract generated shots). collect() runs at the
end of research_post (ideas lane: it fetches URLs) and adds, as approved, credited
assets that write_script waits for:

  1. Who and what the story names (entities.py): a company's logo — drawn on a clean
     card, shown as a still because the video model can't draw logos — and a
     person's or place's photo, from Wikipedia and Wikidata.
  2. The report itself: a headline card (media/headline_card.py) — the outlet, its
     headline, the date and its lead photo — for each of up to HEADLINE_CARDS
     outlets read.
  3. Photos (find): the articles' own pictures (lead picture and large in-article
     pictures) and open-licence pictures from Wikimedia Commons and Openverse
     (searched by the story's own words). Jev looks at each one (image input) — does
     it show this story, is it a usable photograph, is there a watermark or a
     channel logo, is it graphic — and the best KEEP join the post.
  4. Videos: the videos in the articles read (yt-dlp knows the BBC's, NDTV's,
     CNN's…), judged by Jev from a frame and their title; the best VIDEO_KEEP join
     the post as clips (live: the BBC's 30 s of Limoges town hall's spire collapsing,
     where the reel had only an AI illustration of it).

A before/after post (the Before vs. After template) also wants the place as it was:
Jev says of each picture whether it shows the story's place or thing before the event
(intact, undamaged, earlier), and up to BEFORE_KEEP of those are kept besides the
event's own pictures, marked so the script writer opens on one as BEFORE.

Never: a post whose owner asked for an AI version of its media, graphic pictures,
watermarked ones, or more than the limits above. The owner adds their own besides
(uploads and links, on the post page).
"""

from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import httpx
from psycopg.types.json import Jsonb

from . import db, entities, net, storage
from .ideas import media
from .media import headline_card
from .jev import Jev, score, yes
from .research import Article, sig_tokens

log = logging.getLogger("corpus.finder")

KEEP = 4
BEFORE_KEEP = 2
VIDEO_KEEP = 2
VIDEO_PAGES = 5
LOGO_KEEP = 3
PEOPLE_KEEP = 2
HEADLINE_CARDS = 2
MAX_CANDIDATES = 14
IMAGE_BYTES = 8_000_000
COMMONS = "https://commons.wikimedia.org/w/api.php"
WIKIPEDIA = "https://en.wikipedia.org/w/api.php"
OPENVERSE = "https://api.openverse.org/v1/images/"
UA = "ContentCorpus/1.0 (asset finder; https://content-corpus.strophic.in)"

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
         title: str = "", want_before: bool = False, topic: str = "") -> list[dict]:
    """The pictures and videos worth adding to the post, best first, with their Jev
    scores. want_before: a before/after post — pictures of the place before the
    event are kept too."""
    cands = article_photos(articles)
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
    try:
        clips = videos(judge, client, story, articles)
    except Exception as e:  # noqa: BLE001 - the photos still go
        log.warning("finder: videos: %s", e)
    if not want_before:
        return clips + picked[:KEEP]
    # The place as it was, first (best-shown first), then the event's own pictures.
    befores = sorted((c for c in picked if c["before"] >= 0.6), key=lambda c: c["shows"], reverse=True)[:BEFORE_KEEP]
    rest = [c for c in picked if c not in befores][:KEEP]
    return befores + clips + rest


def videos(judge: Jev, client: httpx.Client, story: str, articles: list[Article]) -> list[dict]:
    """The best videos in the articles read for the story, judged by Jev from a frame
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
        frame = (_download(client, _thumb_url(v["thumbnail"])) if v["thumbnail"] else None) or _video_frame(v)
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


def _thumb_url(url: str) -> str:
    """The BBC's thumbnails are templates (…/images/ic/$recipe/p0ph9g1b.jpg): ask for a size."""
    return url.replace("$recipe", "976x549")


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
                 Jsonb({"item": item, "found": {"shows": p.get("shows", 3.0), "usable": p.get("usable", 1.0),
                                                "before": p.get("before", 0.0), "role": p.get("role", "photo"),
                                                "entity": p.get("entity", "")}}))).fetchone()["id"]
            db.enqueue(c, user_id=post["user_id"], lane="ideas", kind="fetch_asset", dedupe_key=f"fetch_asset:{aid}",
                       payload={"asset_id": str(aid)}, post_id=post["id"], priority=30, max_attempts=2,
                       lease_seconds=900)
            added += 1
    return added


# ── the whole collection ──────────────────────────────────────────────────────

def _have(post_id) -> set[tuple[str, str]]:
    """(role, what) of the post's collected assets: a second run adds nothing twice."""
    with db.conn() as c:
        rows = c.execute("""select fetch_from->'found'->>'role' as role, fetch_from->'found'->>'entity' as entity
                              from assets where post_id = %s""", (post_id,)).fetchall()
    return {(r["role"] or "", r["entity"] or "") for r in rows}


def add_made(post: dict, path: Path, *, origin: str, credit: str, license: str, found: dict) -> None:
    """A picture made here (a logo card, a headline card) as the post's asset: stored as an
    upload, so fetch_asset normalises it and analyze_asset logs it like any other."""
    with db.tx() as c:
        n = c.execute("select coalesce(max(n), 0) + 1 as n from assets where post_id = %s", (post["id"],)).fetchone()["n"]
        aid = c.execute(
            """insert into assets (user_id, post_id, n, kind, origin, credit, license, rights, fetch_from)
               values (%s, %s, %s, 'image', %s, %s, %s, 'approved', '{}') returning id""",
            (post["user_id"], post["id"], n, origin, credit[:120], license)).fetchone()["id"]
        raw = f"{storage.post_prefix(post['user_id'], post['id'])}/uploads/{aid}.jpg"
        c.execute("update assets set fetch_from = %s where id = %s",
                  (Jsonb({"upload_key": raw, "found": {**found, "shows": 3.0, "usable": 1.0}}), aid))
    storage.put_file(raw, path, kind="asset", user_id=post["user_id"], post_id=post["id"], content_type="image/jpeg")
    with db.tx() as c:
        db.enqueue(c, user_id=post["user_id"], lane="ideas", kind="fetch_asset", dedupe_key=f"fetch_asset:{aid}",
                   payload={"asset_id": str(aid)}, post_id=post["id"], priority=30, max_attempts=2,
                   lease_seconds=900)


def _names(post: dict, client: httpx.Client, ents: list, have: set, log) -> int:
    """Logos and photos of the story's named companies, people and places."""
    import tempfile

    added, logos, people = 0, 0, 0
    photos: list[dict] = []
    for e in sorted(ents, key=lambda e: not e.central):
        hit = entities.lookup(client, e)
        if not hit or (hit["role"], hit["entity"]) in have:
            continue
        have.add((hit["role"], hit["entity"]))
        if hit["role"] == "logo":
            if logos >= LOGO_KEEP:
                continue
            try:
                raw = net.get(client, hit["url"], max_bytes=IMAGE_BYTES, accept=("image/",),
                              headers={"User-Agent": UA}).content
                with tempfile.TemporaryDirectory() as tmp:
                    card = entities.logo_card(raw, Path(tmp) / "logo.jpg")
                    add_made(post, card, origin="wikidata", credit=hit["credit"], license=hit["license"],
                             found={"role": "logo", "entity": hit["entity"]})
                logos += 1
                added += 1
            except Exception as ex:  # noqa: BLE001 - the other names still go
                log(f"logo of {hit['entity']}: {type(ex).__name__}: {ex}")
        elif people < PEOPLE_KEEP:
            photos.append(hit)
            people += 1
    return added + add_to_post(post, photos)


def clean_title(title: str, site: str, outlet: str = "") -> str:
    """The headline without the site's name tacked on ("… audio only fix - BusinessToday")."""
    m = re.search(r"\s+[-|–—:]\s+([^-|–—:]{2,40})$", title)
    if m:
        tail = re.sub(r"[^a-z0-9]", "", m.group(1).lower())
        names = {re.sub(r"[^a-z0-9]", "", n.lower()) for n in (outlet, site.split(".")[0], site.rsplit(".", 1)[0])}
        if tail and any(n and (tail in n or n in tail) for n in names):
            return title[:m.start()].strip()
    return title.strip()


def _headlines(post: dict, client: httpx.Client, articles: list[Article], have: set, log) -> int:
    import tempfile

    added = 0
    for a in [a for a in articles if a.ok and a.title][:HEADLINE_CARDS]:
        if ("headline", a.url) in have:
            continue
        photo = None
        for im in a.images[:3]:          # the lead picture, else the next that downloads
            try:
                photo = net.get(client, im["url"], max_bytes=IMAGE_BYTES, accept=("image/",),
                                headers={"User-Agent": net.user_agent(im["url"])}).content
                break
            except Exception:  # noqa: BLE001 - a card without its photo still reads
                photo = None
        outlet = a.outlet or a.site
        with tempfile.TemporaryDirectory() as tmp:
            card = headline_card.render(Path(tmp) / "headline.jpg", headline=clean_title(a.title, a.site, a.outlet),
                                        outlet=outlet,
                                        published=a.published, photo=photo)
            if card is None:
                continue
            add_made(post, card, origin="article", credit=outlet, license="third_party",
                     found={"role": "headline", "entity": a.url, "outlet": outlet})
        have.add(("headline", a.url))
        added += 1
    return added


def collect(post: dict, judge: Jev | None, client: httpx.Client, articles: list[Article], *, story: str,
            title: str, topic: str, want_before: bool, names: list, log) -> dict:
    """Everything above, for one post; each part on its own (one failing never stops
    the rest). `names`: the story's named entities (entities.extract), or []."""
    have = _have(post["id"])
    got = {"names": 0, "headlines": 0, "found": 0}
    for part, run in (("names", lambda: _names(post, client, names, have, log)),
                      ("headlines", lambda: _headlines(post, client, articles, have, log)),
                      ("found", lambda: add_to_post(post, find(judge, client, story, articles, title=title,
                                                               want_before=want_before, topic=topic))
                       if judge is not None else 0)):
        try:
            got[part] = run()
        except Exception as e:  # noqa: BLE001 - the script goes ahead with what there is
            log(f"collect {part}: {type(e).__name__}: {e}")
    return got
