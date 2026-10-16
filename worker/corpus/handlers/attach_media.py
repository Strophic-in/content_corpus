"""ideas/attach_media — a card's picture or video, checked and made small.

For the idea's first item with media (a Reddit video, image or gallery, else an
article's lead picture):

  1. moderation on the post's text and preview: sexual content removes the idea
     (recorded as rejected, never shown); graphic content keeps the story, text only;
  2. the preview: a ≤480p MP4 with sound plus a poster, or an image ≤1080 px;
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


def _credit(item: dict) -> str:
    if item.get("subreddit"):
        return f"u/{item.get('author') or 'unknown'} on r/{item['subreddit']}"
    return urlparse(item.get("url") or "").netloc.removeprefix("www.") or item.get("source", "")


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
        next((i for i in items if i.get("media_hint") == "link"), None)
    if item is None:
        sweep.set_media(idea["id"], [], "none")
        return {"media": "none"}
    key = vault.secret(idea["user_id"], "openai")
    if not key:                                   # nothing may be shown unchecked
        sweep.set_media(idea["id"], [], "none", {"note": "no OpenAI key to check media with"})
        return {"media": "none", "why": "no key"}
    st = db.one("select vision_model from app_settings where user_id = %s", (idea["user_id"],)) or {}
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
        try:
            mod = vision.moderate(f"{idea['title']}\n{item.get('title', '')}\n{item.get('summary', '')}", thumb)
        except Exception as e:  # noqa: BLE001 - never show media that wasn't checked
            raise Retryable(f"moderation unavailable: {e}", stage="moderation", retry_in=300) from e
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
            if hint == "video" and media.vreddit_id(link):
                vid = media.reddit_video(client, link, work)
                pst = media.poster(vid, work / "poster.jpg")
                p = media.probe(vid)
                vkey, _ = _store(idea, vid, "video.mp4", "video/mp4", log)
                pkey, _ = _store(idea, pst, "poster.jpg", "image/jpeg", log)
                out.append({"type": "video", "key": vkey, "poster_key": pkey, "w": p.w, "h": p.h,
                            "seconds": round(p.seconds, 1), "has_audio": p.has_audio, "origin": "reddit",
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
                if hint == "image":
                    url = link
                elif hint == "gallery":
                    url = item.get("thumbnail")
                else:
                    url = media.page_image(client, item.get("url") or link) or item.get("thumbnail")
                if url:
                    src = media.download_image(client, url, work / "source")
                    img = media.image_preview(src, work / "image.jpg")
                    p = media.probe(img)
                    ikey, _ = _store(idea, img, "image.jpg", "image/jpeg", log)
                    out.append({"type": "image", "key": ikey, "w": p.w, "h": p.h,
                                "origin": "reddit" if item.get("subreddit") else "article",
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
