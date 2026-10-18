"""cpu/render_slides — an approved carousel or card → its slides and its slideshow.

Queued by private.request_render for a post whose format is a carousel or an
image. Each slide of the approved script is drawn (media/slides.py) as a JPEG:
with one of the post's approved pictures (credited on the slide), an AI picture
(only where the format allows: the cover, every slide, or none — drawn once and
kept, so a retry never pays again), a chart, or the background colour. The
slides go to R2 for Instagram (posts.slides, in order); YouTube gets the same
slides as a slideshow Short — each slide held for its reading time with a slow
zoom, crossfaded, a CC0 track under it — which becomes the post's final_key.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from psycopg.types.json import Jsonb

from .. import auto, costs, db, images, looks, storage, templates, vault
from ..config import settings
from ..ideas import media as idea_media
from ..media import assemble as join
from ..media import footage, slides
from ..runner import Handler, JobContext, Permanent
from ..script import carousel
from . import assemble as assemble_handler
from .write_script import _classify_openai_error

IMAGES = images.OpenAIImages       # swapped by tests


def slide_prompt(prompt: str, look: str, topic: str) -> str:
    return (f"An illustration for one slide of a social media carousel about: {topic.strip()[:200]}.\n"
            f"Show: {prompt.strip()[:1200]}\n"
            f"Style: {look.strip()[:600] or 'clean editorial illustration, soft light'}.\n"
            "No text, letters, numbers, captions, logos or watermarks. People appear as generic figures, never a "
            "recognisable real person. Nothing graphic.")


def _stored(key: str) -> bool:
    row = db.one("select 1 as ok from storage_objects where key = %s and state = 'stored'", (key,))
    return bool(row)


def _silence(path: Path, frames: int) -> Path:
    samples = frames * join.RATE // join.FPS
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"anullsrc=r={join.RATE}:cl=stereo",
                    "-af", f"atrim=end_sample={samples}", "-c:a", "pcm_s16le", str(path)], check=True,
                   capture_output=True)
    return path


def run(ctx: JobContext) -> dict:
    log = lambda m: print(f"[render_slides] {m}", flush=True)  # noqa: E731
    script_id = ctx.payload["script_id"]
    with db.tx() as c:
        post = c.execute("select * from posts where approved_script_id = %s for update", (script_id,)).fetchone()
        if post is None:
            raise Permanent("post or approved script no longer exists", stage="input")
        if post["final_key"] and post["status"] in ("ready", "scheduled", "published"):
            return {"skipped": "already made", "final_key": post["final_key"]}
        script = c.execute("select slides, title from scripts where id = %s", (script_id,)).fetchone()
        look = templates.look_for_post(c, post)
        fmt = dict(c.execute("select template_id, visual_style from formats where id = %s",
                             (post["format_id"],)).fetchone() or {})
        vlook = looks.get(post.get("look_id"))
        if vlook:                                   # the post's video look styles its AI pictures too
            fmt["visual_style"] = vlook.prompt
        assets = {r["n"]: r for r in c.execute(
            """select id, n, kind, key, credit, license, rights, state from assets
                where post_id = %s and rights = 'approved' and state = 'ready'""", (post["id"],)).fetchall()}
        st = c.execute("select image_model, image_quality from app_settings where user_id = %s",
                       (post["user_id"],)).fetchone() or {}
        old = post["status"]
        c.execute("update posts set status = 'rendering', error = null where id = %s", (post["id"],))
        db.log_event(c, post["id"], old, "rendering", f"worker:{settings().worker_id}", "drawing the slides")
    deck = script["slides"] or []
    if not deck:
        raise Permanent("the approved script has no slides", stage="input")
    t = templates.get(fmt.get("template_id"))
    layout = look.slides.layout if look.slides else "educational"
    prefix = f"{storage.post_prefix(post['user_id'], post['id'])}/slides/{script_id}"
    billed = dict(user_id=post["user_id"], post_id=post["id"], channel_id=post.get("channel_id"),
                  category_id=post.get("category_id"), job_id=ctx.job.get("id"))
    stored, credits = [], []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for i, s in enumerate(deck):
            v = s.get("visual") or {}
            picture, credit = None, None
            if v.get("source") == "asset":
                a = assets.get(int(v.get("asset") or 0))
                if a is None or a["kind"] != "image" or not a["key"]:
                    raise Permanent(f"slide {i + 1}'s picture is no longer approved or available", stage="rights")
                picture = storage.get_file(a["key"], work / f"p{i}.jpg")
                credit = ("AI illustration" if a["license"] == "ai" else (a["credit"] or "").strip() or None)
            elif v.get("source") == "ai_image" and (v.get("prompt") or "").strip():
                picture, credit = _ai_picture(post, s, i, f"{prefix}/ai-{i}.jpg", fmt.get("visual_style") or "",
                                              st, work, billed, log), "AI illustration"
            out = slides.render(s, i, len(deck), layout=layout, look=look, out=work / f"slide{i}.jpg",
                                picture=picture, credit=credit)
            info = storage.put_file(f"{prefix}/{i + 1:02d}.jpg", out, kind="final", user_id=post["user_id"],
                                    post_id=post["id"], content_type="image/jpeg")
            w, h = slides.W, slides.height(look.slides.aspect if look.slides else "4:5")
            stored.append({**info, "w": w, "h": h})
            if credit and credit != "AI illustration":
                credits.append(credit)
        # The slideshow: every slide held for its reading time, blur-padded to 9:16.
        segs = []
        for i, s in enumerate(deck):
            d = work / f"seg{i}"
            d.mkdir()
            info = footage.ken_burns(work / f"slide{i}.jpg", d / "v.mp4", seconds=carousel.seconds(s, look), idx=i,
                                     layout="blur_pad", zoom=max(0.03, look.ken_burns))
            segs.append((d / "v.mp4", _silence(d / "a.wav", info["frames"])))
        track = assemble_handler._music(post, script_id, work)
        out = work / "slideshow.mp4"
        info = join.join_segments(segs, out, log=log, music=track.path if track else None,
                                  music_gain=0.55, transitions=["cut"] + ["crossfade"] * (len(segs) - 1))
        key = f"{storage.post_prefix(post['user_id'], post['id'])}/final/{script_id}.mp4"
        final = storage.put_file(key, out, kind="final", user_id=post["user_id"], post_id=post["id"],
                                 content_type="video/mp4")
    credits = list(dict.fromkeys(credits))
    if track:
        credits.append(track.credit)
    with db.tx() as c:
        c.execute("""update posts set status = 'ready', slides = %s, final_key = %s, final_sha256 = %s,
                                      final_bytes = %s, final_duration_s = %s, error = null, credits = %s, music = %s
                      where id = %s""",
                  (Jsonb(stored), key, final["sha256"], final["bytes"], info["seconds"], Jsonb(credits),
                   Jsonb(track.meta) if track else None, post["id"]))
        db.log_event(c, post["id"], "rendering", "ready", f"worker:{settings().worker_id}",
                     f"{len(stored)} slide{'s' if len(stored) != 1 else ''} and the slideshow made",
                     {"slides": len(stored), "seconds": info["seconds"], "template": t.template_id})
        db.enqueue(c, user_id=post["user_id"], lane="cpu", kind="package_post",
                   dedupe_key=f"package_post:{script_id}", post_id=post["id"], max_attempts=2,
                   lease_seconds=300)                      # its caption and cover, for the post page
    auto.request_publish(post["id"])             # Automatic mode: post it at the picked time
    return {"slides": len(stored), "slideshow_s": info["seconds"], "final_key": key}


def _ai_picture(post: dict, slide: dict, i: int, key: str, look_text: str, st: dict, work: Path, billed: dict,
                log) -> Path:
    """A slide's AI picture: drawn once, kept in R2, reused by a retry."""
    dest = work / f"ai{i}.jpg"
    if _stored(key):
        return storage.get_file(key, dest)
    api_key = vault.secret(post["user_id"], "openai")
    if not api_key:
        raise Permanent("Add your OpenAI API key in Settings.", stage="config")
    model, quality = st.get("image_model") or "gpt-image-1-mini", st.get("image_quality") or "medium"
    try:
        data, usage = IMAGES(api_key).generate(
            model=model, quality=quality,
            prompt=slide_prompt(slide["visual"]["prompt"], look_text, post["topic"]))
    except Exception as e:  # noqa: BLE001 - classified like the script writer's
        raise _classify_openai_error(e) from e
    costs.record_llm(usage, kind="image", note=f"AI picture for slide {i + 1}", **billed)
    raw = work / f"ai{i}.png"
    raw.write_bytes(data)
    idea_media.image_preview(raw, dest, max_side=1600)
    storage.put_file(key, dest, kind="final", user_id=post["user_id"], post_id=post["id"], content_type="image/jpeg")
    log(f"drew slide {i + 1}'s picture ({model}, {quality})")
    return dest


def on_give_up(ctx: JobContext, err: dict) -> None:
    with db.tx() as c:
        post = c.execute("select id, status from posts where approved_script_id = %s for update",
                         (ctx.payload["script_id"],)).fetchone()
        if post and post["status"] in ("queued_for_render", "rendering"):
            c.execute("update posts set status = 'failed', error = %s where id = %s",
                      (Jsonb({"stage": err.get("stage") or "slides",
                              "message": f"Couldn't make the slides: {err.get('message')}"}), post["id"]))
            db.log_event(c, post["id"], post["status"], "failed", "system", "making the slides gave up")


HANDLER = Handler(run=run, on_give_up=on_give_up)
