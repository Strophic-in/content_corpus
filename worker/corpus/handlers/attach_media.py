"""ideas/attach_media — a card's picture or video, checked and made small.

For the idea's first item with media (a post's video, image or gallery — Reddit,
Bluesky, Mastodon, Lemmy, a YouTube thumbnail — else an article's lead picture):

  1. moderation on the post's text and preview: sexual content removes the idea
     (recorded as rejected, never shown); graphic content keeps the story, text only;
  2. the preview: a ≤480p MP4 with sound plus a poster, or an image ≤1080 px (a
     video that can't be fetched falls back to its thumbnail);
  3. for a video, one vision call on a contact sheet (if a vision model is set in
     Settings): what it shows, and whether it carries a logo or watermark;
  4. stored as idea_media (its own storage budget; when full, the oldest
     unswiped previews make room) and the card is marked ready.

A source that can't be fetched is not a failure: the card simply has no media.
Only an unreachable moderation service is retried — media is never shown unchecked.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
from psycopg.types.json import Jsonb

from .. import costs, db, storage, vault
from ..ideas import media, sweep
from ..ideas.vision import OpenAIVision, verdict
from ..runner import Handler, JobContext, Retryable

# Swapped by tests.
VISION = OpenAIVision


PLATFORMS = {"bluesky": "Bluesky", "mastodon": "Mastodon", "lemmy": "Lemmy", "youtube": "YouTube"}


def _credit(item: dict) -> str:
    if item.get("subreddit"):
        return f"u/{item.get('author') or 'unknown'} on r/{item['subreddit']}"
    if item.get("platform") in PLATFORMS and item.get("author"):
        where = f"c/{item['community']}" if item.get("community") else PLATFORMS[item["platform"]]
        return f"{item['author']} on {where}"
    url = item.get("link") or item.get("url") or ""
    return urlparse(url).netloc.removeprefix("www.") or item.get("source", "")


def _origin(item: dict) -> str:
    return item.get("platform") or ("reddit" if item.get("subreddit") else "article")


def _video(client, item: dict, link: str, work: Path) -> Path | None:
    if media.vreddit_id(link):
        return media.reddit_video(client, link, work)
    if item.get("video_url"):
        return media.direct_video(client, item["video_url"], work)
    if item.get("hls_url"):
        return media.hls_video(client, item["hls_url"], work)
    return None


def _picture_url(client, item: dict, hint: str | None, link: str) -> str | None:
    if hint == "image":
        return item.get("image_url") or link
    if hint in ("gallery", "video"):                       # a video we couldn't fetch: its thumbnail
        return item.get("image_url") or item.get("thumbnail")
    return media.page_image(client, item.get("link") or item.get("url") or link) or item.get("thumbnail")


def _store(idea: dict, path: Path, name: str, content_type: str, log) -> tuple[str, int]:
    key = f"u/{idea['user_id']}/ideas/{idea['id']}/{name}"
    try:
        info = storage.put_file(key, path, kind="idea_media", user_id=idea["user_id"], content_type=content_type)
    except storage.StorageFull:
        sweep.evict(path.stat().st_size * 3, log)          # room for this and the next few
        info = storage.put_file(key, path, kind="idea_media", user_id=idea["user_id"], content_type=content_type)
    return key, info["bytes"]


def run(ctx: JobContext) -> dict:
    log = lambda m: print(f"[attach_media] {m}", flush=True)  # noqa: E731
    idea = db.one("select * from ideas where id = %s", (ctx.payload["idea_id"],))
    if not idea or idea["status"] != "new" or idea["media_state"] != "pending":
        return {"skipped": "no longer waiting for media"}
    items = idea["items"] or []
    item = next((i for i in items if i.get("media_hint") in ("video", "image", "gallery")), None) or \
        next((i for i in items if i.get("media_hint") in ("link", "")
              and str(i.get("url") or "").startswith("http")), None)
    if item is None:
        sweep.set_media(idea["id"], [], "none")
        return {"media": "none"}
    key = vault.secret(idea["user_id"], "openai")
    if not key:                                   # nothing may be shown unchecked
        sweep.set_media(idea["id"], [], "none", {"note": "no OpenAI key to check media with"})
        return {"media": "none", "why": "no key"}
    st = db.one("select vision_model, script_model from app_settings where user_id = %s",
                (idea["user_id"],)) or {}
    vision = VISION(key)
    billed = dict(user_id=idea["user_id"], channel_id=idea["channel_id"], category_id=idea["category_id"],
                  job_id=ctx.job.get("id"))
    hint, link = item.get("media_hint"), item.get("link") or item.get("url") or ""
    credit = _credit(item)

    with tempfile.TemporaryDirectory() as tmp, httpx.Client(timeout=30) as client:
        work = Path(tmp)
        thumb = None
        if item.get("thumbnail"):
            try:
                thumb = media.download_image(client, item["thumbnail"], work / "thumb.jpg")
            except Exception:  # noqa: BLE001 - moderation can run on the text alone
                thumb = None
        text = f"{idea['title']}\n{item.get('title', '')}\n{item.get('summary', '')}"
        try:
            mod = vision.moderate(text, thumb)
        except Exception as e:  # noqa: BLE001 - never show media that wasn't checked
            if getattr(e, "status_code", None) not in (401, 403, 404):
                raise Retryable(f"moderation unavailable: {e}", stage="moderation", retry_in=300) from e
            # This key may not call /moderations (a restricted key): ask a chat model instead.
            model = st.get("vision_model") or st.get("script_model")
            if not model:
                sweep.set_media(idea["id"], [], "none", {"note": "this key can't run moderation"})
                return {"media": "none", "why": "no moderation"}
            try:
                mod, usage = vision.safety(model, text, thumb)
            except Exception as e2:  # noqa: BLE001
                if getattr(e2, "usage", None) is not None:
                    costs.record_llm(e2.usage, kind="moderation", note="unparsable safety check", **billed)
                raise Retryable(f"safety check unavailable: {e2}", stage="moderation", retry_in=300) from e2
            costs.record_llm(usage, kind="moderation", note="safety check", **billed)
        analysis = {"moderation": mod}
        v = verdict(mod)
        if v == "remove":
            with db.conn() as c:
                c.execute("""update ideas set status = 'rejected', decided_at = now(), media_state = 'none',
                                    analysis = %s,
                                    reject_reason = 'Removed automatically: flagged by moderation'
                              where id = %s""", (Jsonb(analysis), idea["id"]))
            log(f"{idea['title'][:60]}: removed ({', '.join(mod['categories'])})")
            return {"removed": mod["categories"]}
        if v == "no_media":
            sweep.set_media(idea["id"], [], "none", analysis)
            return {"media": "none", "why": mod["categories"]}

        out: list[dict] = []
        try:
            vid = None
            if hint == "video":
                try:
                    vid = _video(client, item, link, work)
                except Exception as e:  # noqa: BLE001 - the thumbnail still makes a card
                    log(f"{idea['title'][:60]}: video not fetched ({type(e).__name__}: {str(e)[:160]})")
                    analysis["video_error"] = f"{type(e).__name__}: {str(e)[:300]}"
            if vid is not None:
                pst = media.poster(vid, work / "poster.jpg")
                p = media.probe(vid)
                vkey, _ = _store(idea, vid, "video.mp4", "video/mp4", log)
                pkey, _ = _store(idea, pst, "poster.jpg", "image/jpeg", log)
                out.append({"type": "video", "key": vkey, "poster_key": pkey, "w": p.w, "h": p.h,
                            "seconds": round(p.seconds, 1), "has_audio": p.has_audio, "origin": _origin(item),
                            "source_url": item.get("url"), "credit": credit})
                if st.get("vision_model"):
                    sheet = media.contact_sheet(vid, work / "sheet.jpg")
                    try:
                        an, usage = vision.describe(st["vision_model"], sheet, idea["title"])
                        costs.record_llm(usage, kind="vision", note="video description", **billed)
                        analysis["video"] = an.model_dump()
                    except Exception as e:  # noqa: BLE001 - the card works without it
                        if getattr(e, "usage", None) is not None:
                            costs.record_llm(e.usage, kind="vision", note="unparsable description", **billed)
                        log(f"vision skipped: {e}")
            else:
                url = _picture_url(client, item, hint, link)
                if url:
                    src = media.download_image(client, url, work / "source")
                    img = media.image_preview(src, work / "image.jpg")
                    p = media.probe(img)
                    ikey, _ = _store(idea, img, "image.jpg", "image/jpeg", log)
                    out.append({"type": "image", "key": ikey, "w": p.w, "h": p.h,
                                "origin": _origin(item),
                                "source_url": item.get("url"), "credit": credit,
                                "gallery": hint == "gallery"})
        except Exception as e:  # noqa: BLE001 - no media is a fine outcome
            log(f"{idea['title'][:60]}: no media ({type(e).__name__}: {str(e)[:160]})")
            analysis["media_error"] = f"{type(e).__name__}: {str(e)[:300]}"
            sweep.set_media(idea["id"], out, "ready" if out else "none", analysis)
            return {"media": len(out), "error": analysis["media_error"]}

    sweep.set_media(idea["id"], out, "ready" if out else "none", analysis)
    return {"media": [m["type"] for m in out], "analysed": "video" in analysis}


def on_give_up(ctx: JobContext, err: dict) -> None:
    sweep.set_media(ctx.payload["idea_id"], [], "none", {"media_error": err.get("message")})


HANDLER = Handler(run=run, on_give_up=on_give_up)
