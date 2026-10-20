"""What a reel goes out with: its title, caption, hashtags, first comment and cover.

Made once the reel is finished (job package_post, queued by assemble and
render_slides) and kept on the post (posts.package) so the owner sees it on the post
page before it goes out; publish_post makes it there and then if it is missing, and
anew when the script changed since.

  title           gripping and accurate — a curiosity gap, never a false promise
  caption         a hook line, a few short lines (what happened, why it matters),
                  a question; then the sources (YouTube: with links; Instagram:
                  their names), the footage credits and the hashtags
  first comment   more on the story than the video had time for — background, a
                  telling detail from the reports, what happens next — ending on a
                  question; never the sources or links (owner, 2026-10-19)
  cover           media/thumbnail.py: the strongest real photo — or the place
                  before and now — with a short bold line
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from psycopg.types.json import Jsonb
from pydantic import BaseModel

from . import costs, db, jev, storage, styles, vault
from .media import thumbnail
from .style import undash

log = logging.getLogger("corpus.packaging")


class PostCopy(BaseModel):
    title: str
    hook_line: str
    caption: str
    hashtags: list[str]
    first_comment: str
    thumbnail_text: str
    kicker: str


SYSTEM = """You package a short vertical news video for YouTube Shorts and Instagram Reels so that people stop
scrolling and tap - without misleading them. Everything you write must be true to the script and its sources.

- title: at most 70 characters. Lead with the most striking concrete fact and the named place, person or thing.
  A curiosity gap is good ("…and nobody knows what happens next"); a false promise, invented detail or shouty
  ALL CAPS is not. At most one emoji, usually none.
- hook_line: the first line of the caption, at most 110 characters - the one fact that makes people watch.
- caption: 2-4 short lines (no hashtags, no links): what happened, why it matters, and end with a question to the
  viewer. Plain words; at most two emojis in total.
- hashtags: 8-12, each starting with #, most important first (YouTube shows the first three): the place, the
  topic, the event, then broader ones (#news, #worldnews, …). No spaces inside a tag, no misleading tags.
- first_comment: 2-4 short sentences (at most 450 characters) that tell viewers more than the video had time
  for: the background, a telling detail or number from the reports, or what happens next - only facts the
  reports state. End with a question that starts a conversation. No links, no list of sources, no hashtags,
  never begging for likes.
- Style: never use em dashes or en dashes as punctuation; write a comma, a full stop or a colon.
- thumbnail_text: 2-5 words in capitals that tell the story at a glance and make people curious (for a before/now
  video, name what is gone or changed: "SPIRE GONE IN MINUTES"). True, no question marks spam, no clickbait lies.
- kicker: one or two words for a small red label above it ("BREAKING", "BEFORE / NOW", "LIVE", "UPDATE"), or ""
  when none fits.
Never name victims of crimes or minors; nobody is guilty before a verdict; stay non-partisan."""


class OpenAICopywriter:
    def __init__(self, api_key: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, timeout=90, max_retries=2)

    def write(self, *, model: str, system: str, user: str):
        from .script.llm import Unparsed, Usage

        resp = self.client.responses.parse(model=model, instructions=system, input=user, text_format=PostCopy)
        if resp.output_parsed is None:
            raise Unparsed("model returned no parsable post copy", Usage.of(resp))
        return resp.output_parsed, Usage.of(resp)


COPYWRITER = OpenAICopywriter        # swapped by tests


def _post(post_id) -> dict | None:
    return db.one("""select p.id, p.user_id, p.channel_id, p.category_id, p.format, p.final_key, p.credits,
                            p.research, p.package, p.approved_script_id, p.topic,
                            s.title, s.hook, s.description, s.hashtags, s.shot_plan, s.slides,
                            f.template_id, ch.name as channel, ch.niche, ch.audience,
                            k.name as category, st.script_model, st.thumb_styles_enabled
                       from posts p
                       join scripts s on s.id = p.approved_script_id
                       left join formats f on f.id = p.format_id
                       left join channels ch on ch.id = p.channel_id
                       left join categories k on k.id = p.category_id
                       left join app_settings st on st.user_id = p.user_id
                      where p.id = %s""", (post_id,))


def sources(post: dict, most: int = 4) -> list[dict]:
    """The articles the story was checked against: the idea's own first."""
    arts = sorted((post.get("research") or {}).get("articles") or [], key=lambda a: not a.get("from_idea"))
    out, seen = [], set()
    for a in arts:
        host = urlparse(a.get("url") or "").netloc.removeprefix("www.")
        if not host or host in seen:
            continue
        seen.add(host)
        out.append({"site": _site_name(a.get("site") or host), "title": (a.get("title") or "")[:140], "url": a["url"]})
        if len(out) >= most:
            break
    return out


SITE_NAMES = {"bbc.co.uk": "BBC News", "bbc.com": "BBC News", "inews.co.uk": "i News", "ndtv.com": "NDTV",
              "thehindu.com": "The Hindu", "hindustantimes.com": "Hindustan Times", "indiatoday.in": "India Today",
              "timesofindia.indiatimes.com": "Times of India", "aljazeera.com": "Al Jazeera",
              "theguardian.com": "The Guardian", "reuters.com": "Reuters", "apnews.com": "AP News"}


def _site_name(site: str) -> str:
    host = site.removeprefix("www.").lower()
    return SITE_NAMES.get(host, site)


def _brief(post: dict) -> str:
    lines = [f"Channel: {post.get('channel') or ''} - {post.get('niche') or ''}",
             f"Audience: {post.get('audience') or ''}",
             f"Category: {post.get('category') or 'news'}",
             f"Video format: {post.get('template_id') or 'news video'}"
             + (" (before vs now: the place as it was, then as it is now)"
                if post.get("template_id") == "before_after_comparison" else ""),
             "", f"Script title: {post['title']}", f"Hook: {post.get('hook') or ''}",
             f"Script description: {post.get('description') or ''}",
             f"Script hashtags: {' '.join(post.get('hashtags') or [])}", "", "What the video says:"]
    for s in post.get("shot_plan") or []:
        said = (s.get("narration") or s.get("text") or "").strip()
        if said:
            lines.append(f"- {said}")
    for s in post.get("slides") or []:
        lines.append(f"- {s.get('heading', '')}: {s.get('body', '')}")
    src = sources(post)
    if src:
        lines += ["", "Sources: " + "; ".join(f"{s['site']} - {s['title']}" for s in src)]
    # What the reports say, for the first comment's extra context.
    arts = sorted((post.get("research") or {}).get("articles") or [], key=lambda a: not a.get("from_idea"))
    texts = [(a.get("site") or "", (a.get("text") or "").strip()) for a in arts if (a.get("text") or "").strip()][:2]
    if texts:
        lines += ["", "What the reports say (for the first comment):"]
        lines += [f"[{site}] {text[:1800]}" for site, text in texts]
    return "\n".join(lines)


def _tags(tags: list[str]) -> list[str]:
    out = []
    for t in tags:
        t = "#" + "".join(ch for ch in t.lstrip("#") if ch.isalnum() or ch == "_")
        if len(t) > 1 and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out[:12]


def youtube_description(pkg: dict, credits: list[str]) -> str:
    parts = [pkg["hook_line"], pkg["caption"]]
    if pkg.get("sources"):
        parts.append("Sources:\n" + "\n".join(f"• {s['site']}: {s['url']}" for s in pkg["sources"]))
    if credits:
        parts.append("Footage: " + " · ".join(credits))
    parts.append(" ".join(pkg["hashtags"]))
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def instagram_caption(pkg: dict, credits: list[str]) -> str:
    parts = [pkg["hook_line"], pkg["caption"]]
    if pkg.get("sources"):
        parts.append("Sources: " + " · ".join(s["site"] for s in pkg["sources"]))
    if credits:
        parts.append("Footage: " + " · ".join(credits))
    parts.append(" ".join(pkg["hashtags"][:30]))
    return "\n\n".join(p.strip() for p in parts if p and p.strip())[:2200]


def first_comment(pkg: dict, platform: str) -> str:
    """The comment as written: more on the story, no sources (they're in the caption)."""
    return pkg["first_comment"].strip()[:2000]


# ── the cover ─────────────────────────────────────────────────────────────────

def _assets(post_id) -> list[dict]:
    with db.conn() as c:
        return c.execute("""select n, kind, key, credit,
                                   coalesce((fetch_from->'found'->>'shows')::float, 0) as shows,
                                   coalesce((fetch_from->'found'->>'before')::float, 0) as before
                              from assets where post_id = %s and state = 'ready' and rights = 'approved'
                               and key is not null order by n""", (post_id,)).fetchall()


def _frame(final_key: str, work: Path, at: float = 1.2) -> Path | None:
    video, out = work / "final.mp4", work / "frame.jpg"
    try:
        storage.get_file(final_key, video)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at}", "-i", str(video), "-frames:v", "1",
                        "-q:v", "2", str(out)], check=True, timeout=120)
        return out
    except Exception as e:  # noqa: BLE001 - no frame: a plain cover
        log.warning("cover frame: %s", e)
        return None


SAME_PLACE = {"same": {"type": "noul", "instructions": "Do `before` and `now` show the same building, landmark or "
                                                       "place (at different times)?"}}


def _jpeg(path: Path) -> bytes:
    from io import BytesIO

    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((1024, 1024))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _same_place(user_id: str, before: Path, now: Path) -> bool:
    """A BEFORE / NOW cover only when both halves show the same place (live: the
    "now" photo was riot police by a fire elsewhere, under "spire collapsed"). Jev
    looks at both; without Jev, no split."""
    judge = jev.for_user(user_id)
    if judge is None:
        return False
    try:
        a = judge.ask({"before": "photo-1", "now": "photo-2"}, SAME_PLACE,
                      images={"photo-1": _jpeg(before), "photo-2": _jpeg(now)})
        return jev.yes(a.get("same"), 0.0) >= 0.6
    except Exception as e:  # noqa: BLE001
        log.warning("same place? %s", e)
        return False


def _cover(post: dict, pkg: dict, work: Path) -> Path:
    images = [a for a in _assets(post["id"]) if a["kind"] == "image"]
    befores = sorted((a for a in images if a["before"] >= 0.6), key=lambda a: a["shows"], reverse=True)
    nows = sorted((a for a in images if a["before"] < 0.6), key=lambda a: a["shows"], reverse=True)

    def get(a: dict) -> Path:
        return storage.get_file(a["key"], work / f"asset{a['n']}")

    before = get(befores[0]) if befores and post.get("template_id") == "before_after_comparison" else None
    picture = get(nows[0]) if nows else (_frame(post["final_key"], work) if post.get("final_key") else None)
    kicker = pkg.get("kicker") or ""
    if before is not None and (picture is None or not _same_place(post["user_id"], before, picture)):
        # No true "now" of the same place: the place as it was, full screen, marked so.
        picture, before, kicker = before, None, "Before the fire" if "fire" in story_words(post) else "Before"
    style, why = styles.choose_thumb(jev.for_user(post["user_id"]), post.get("thumb_styles_enabled"),
                                     title=pkg["title"], line=pkg["thumbnail_text"], story=_brief(post)[:1200],
                                     template=post.get("template_id"), has_before=before is not None,
                                     has_number=thumbnail._number(pkg["thumbnail_text"]) is not None)
    pkg["thumb_style"], pkg["thumb_why"] = style, why
    out = work / "cover.jpg"
    return thumbnail.render(out, line=pkg["thumbnail_text"], kicker=kicker, picture=picture,
                            before=before, brand=post.get("channel") or "", style=style)


def story_words(post: dict) -> str:
    return f"{post.get('title') or ''} {post.get('topic') or ''} {post.get('description') or ''}".lower()


# ── make it ───────────────────────────────────────────────────────────────────

def ensure(post_id, *, job_id=None) -> dict | None:
    """The post's package, made now if it has none for its current script."""
    post = _post(post_id)
    if not post:
        return None
    have = post.get("package") or {}
    if have.get("script_id") == str(post["approved_script_id"]) and have.get("thumbnail_key"):
        return have
    return make(post, job_id=job_id)


def make(post: dict, *, job_id=None) -> dict:
    key = vault.secret(post["user_id"], "openai")
    model = post.get("script_model")
    if not key or not model:
        raise RuntimeError("an OpenAI key and a script model are needed to write the caption")
    out, usage = COPYWRITER(key).write(model=model, system=SYSTEM, user=_brief(post))
    costs.record_llm(usage, note="caption and thumbnail", user_id=post["user_id"], post_id=post["id"],
                     channel_id=post["channel_id"], category_id=post["category_id"], job_id=job_id)
    pkg = {"title": undash(out.title.strip())[:100], "hook_line": undash(out.hook_line.strip()),
           "caption": undash(out.caption.strip()),
           "hashtags": _tags(out.hashtags) or _tags(post.get("hashtags") or []),
           "first_comment": undash(out.first_comment.strip()), "thumbnail_text": undash(out.thumbnail_text.strip())[:60],
           "kicker": out.kicker.strip()[:24], "sources": sources(post), "model": usage.model,
           "script_id": str(post["approved_script_id"]), "made_at": datetime.now(timezone.utc).isoformat()}
    with tempfile.TemporaryDirectory() as tmp:
        cover = _cover(post, pkg, Path(tmp))
        k = f"{storage.post_prefix(post['user_id'], post['id'])}/cover/{post['approved_script_id']}.jpg"
        storage.put_file(k, cover, kind="other", user_id=post["user_id"], post_id=post["id"],
                         content_type="image/jpeg")
    pkg["thumbnail_key"] = k
    with db.conn() as c:
        c.execute("update posts set package = %s where id = %s", (Jsonb(pkg), post["id"]))
    return pkg
