"""ideas/fetch_asset — a post's footage at full quality, into R2.

Queued when the owner accepts an idea and chooses to use its picture or video
(private.adopt_idea_media). Runs on the ideas lane, the only worker that fetches
URLs that came from posts. The original is fetched again at reel quality (≤1080p,
up to three minutes; the card only has a small preview) and stored as kind
'asset'. If the original is gone, the card's preview stands in, so an approved
clip is never lost. Then cpu/analyze_asset logs what it shows.

The owner's own uploads come here too (fetch_from.upload_key: the file the browser
put straight into R2): checked, normalised — H.264/AAC MP4 with the long side at
most 1920 px and at most UPLOAD_MAX_SECONDS, or a JPEG — stored at the asset's
usual key, and the raw upload deleted.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import httpx

from .. import db, storage
from ..ideas import media
from ..runner import Handler, JobContext, Permanent

ANALYZE_PRIORITY = 40
UPLOAD_MAX_SECONDS = 15 * 60
UPLOAD_LONG_SIDE = 1920


def _normalise_video(src: Path, out: Path) -> media.Probe:
    p = media.probe(src)
    if not p.w or not p.h:
        raise Permanent("that file has no video in it", stage="upload")
    if p.seconds > UPLOAD_MAX_SECONDS + 1:
        raise Permanent(f"the video is {p.seconds / 60:.0f} minutes long; upload at most "
                        f"{UPLOAD_MAX_SECONDS // 60} minutes (trim it first)", stage="upload")
    fits = p.vcodec == "h264" and max(p.w, p.h) <= UPLOAD_LONG_SIDE
    video = (["-c:v", "copy"] if fits else
             ["-vf", f"scale='if(gt(iw,ih),min({UPLOAD_LONG_SIDE},iw),-2)':'if(gt(iw,ih),-2,min({UPLOAD_LONG_SIDE},ih))'"
                     ":flags=lanczos,format=yuv420p",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20"])
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", *video,
                        "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-movflags", "+faststart", str(out)],
                       capture_output=True, text=True, timeout=2400)
    if r.returncode != 0:
        raise Permanent(f"couldn't read that video: {r.stderr.strip()[-200:]}", stage="upload")
    return media.probe(out)


def _ingest_upload(a: dict, raw_key: str, log) -> dict:
    """The owner's upload → the asset's file (normalised), the raw upload removed."""
    ext, ctype = ("mp4", "video/mp4") if a["kind"] == "video" else ("jpg", "image/jpeg")
    key = f"{storage.post_prefix(a['user_id'], a['post_id'])}/assets/{a['id']}.{ext}"
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        try:
            raw = storage.get_file(raw_key, work / ("raw" + Path(raw_key).suffix))
        except Exception as e:  # noqa: BLE001 - the browser never finished the upload
            raise Permanent(f"the upload didn't arrive ({type(e).__name__}) — add the file again", stage="upload") from e
        if a["kind"] == "video":
            p = _normalise_video(raw, work / "video.mp4")
            path = work / "video.mp4"
        else:
            path = media.image_preview(raw, work / "image.jpg", max_side=2560)
            p = media.probe(path)
            if not p.w:
                raise Permanent("that file isn't a picture we can read", stage="upload")
        info = storage.put_file(key, path, kind="asset", user_id=a["user_id"], post_id=a["post_id"],
                                content_type=ctype)
    storage.delete(raw_key)
    with db.tx() as c:
        c.execute("""update assets set key = %s, w = %s, h = %s, seconds = %s, has_audio = %s, error = null
                      where id = %s""",
                  (key, p.w, p.h, round(p.seconds, 2) if a["kind"] == "video" else None,
                   p.has_audio if a["kind"] == "video" else False, a["id"]))
        db.enqueue(c, user_id=a["user_id"], lane="cpu", kind="analyze_asset", dedupe_key=f"analyze_asset:{a['id']}",
                   payload={"asset_id": str(a["id"])}, post_id=a["post_id"], priority=ANALYZE_PRIORITY,
                   max_attempts=2, lease_seconds=1800)
    log(f"upload {a['id']} stored ({info['bytes'] / 1e6:.1f} MB, {p.w}x{p.h})")
    return {"key": key, "bytes": info["bytes"], "w": p.w, "h": p.h, "upload": True}


def _original(client: httpx.Client, kind: str, item: dict, work: Path) -> Path:
    if kind == "video":
        link = item.get("link") or item.get("url") or ""
        if media.vreddit_id(link):
            return media.reddit_video(client, link, work, media.FULL)
        if item.get("video_url"):
            return media.direct_video(client, item["video_url"], work, media.FULL)
        if item.get("hls_url"):
            return media.hls_video(client, item["hls_url"], work, media.FULL)
        raise media.MediaError("no way to fetch this video again")
    url = item.get("image_url") or (item.get("link") if item.get("media_hint") == "image" else None) \
        or media.page_image(client, item.get("link") or item.get("url") or "") or item.get("thumbnail")
    if not url:
        raise media.MediaError("no picture to fetch")
    src = media.download_image(client, url, work / "source")
    return media.image_preview(src, work / "image.jpg", max_side=2160)


def run(ctx: JobContext) -> dict:
    log = lambda m: print(f"[fetch_asset] {m}", flush=True)  # noqa: E731
    a = db.one("select * from assets where id = %s", (ctx.payload["asset_id"],))
    if a is None or a["state"] != "pending" or a["key"]:
        return {"skipped": "no longer waiting to be fetched"}
    fetch = a["fetch_from"] or {}
    if fetch.get("upload_key"):
        return _ingest_upload(a, fetch["upload_key"], log)
    note = None
    with tempfile.TemporaryDirectory() as tmp, httpx.Client(timeout=60) as client:
        work = Path(tmp)
        try:
            path = _original(client, a["kind"], fetch.get("item") or {}, work)
        except Exception as e:  # noqa: BLE001 - the card's preview stands in
            if not fetch.get("preview_key"):
                raise Permanent(f"couldn't fetch the footage: {type(e).__name__}: {str(e)[:200]}",
                                stage="fetch") from e
            note = f"original unavailable ({type(e).__name__}); using the card's preview"
            log(f"asset {a['id']}: {note}")
            path = storage.get_file(fetch["preview_key"], work / ("preview.mp4" if a["kind"] == "video"
                                                                  else "preview.jpg"))
        p = media.probe(path)
        ext, ctype = ("mp4", "video/mp4") if a["kind"] == "video" else ("jpg", "image/jpeg")
        key = f"{storage.post_prefix(a['user_id'], a['post_id'])}/assets/{a['id']}.{ext}"
        info = storage.put_file(key, path, kind="asset", user_id=a["user_id"], post_id=a["post_id"],
                                content_type=ctype)
    with db.tx() as c:
        c.execute("""update assets set key = %s, w = %s, h = %s, seconds = %s, has_audio = %s, error = %s
                      where id = %s""",
                  (key, p.w, p.h, round(p.seconds, 2) if a["kind"] == "video" else None,
                   p.has_audio if a["kind"] == "video" else False, note, a["id"]))
        db.enqueue(c, user_id=a["user_id"], lane="cpu", kind="analyze_asset", dedupe_key=f"analyze_asset:{a['id']}",
                   payload={"asset_id": str(a["id"])}, post_id=a["post_id"], priority=ANALYZE_PRIORITY,
                   max_attempts=2, lease_seconds=900)
    log(f"asset {a['id']} stored ({info['bytes'] / 1e6:.1f} MB, {p.w}x{p.h})")
    return {"key": key, "bytes": info["bytes"], "w": p.w, "h": p.h, "seconds": round(p.seconds, 2),
            "fallback": bool(note)}


def on_give_up(ctx: JobContext, err: dict) -> None:
    """Failed — and so is its AI twin, if one was to be drawn from it."""
    with db.conn() as c:
        c.execute("""update assets set state = 'failed', error = %s
                      where (id = %s or made_from = %s) and state = 'pending'""",
                  ((err.get("message") or "fetch failed")[:500], ctx.payload["asset_id"], ctx.payload["asset_id"]))


HANDLER = Handler(run=run, on_give_up=on_give_up)
