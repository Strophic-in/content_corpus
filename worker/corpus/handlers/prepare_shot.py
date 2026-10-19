"""cpu/prepare_shot — make one footage shot (clip, image or stock) of an approved script.

Queued per shot by private.request_render, beside render_post for generated
shots. The shot comes out at the reel's own size (1080x1920, 24 fps, its exact
frame count) with its credit drawn on, is stored like a rendered shot, and goes
to build_segment for captions and sound — from there on nothing knows it wasn't
rendered. Rights were checked when rendering was requested and are checked again
here: footage the owner withdrew is never shown.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import httpx
from psycopg.types.json import Jsonb

from .. import db, stock, storage, templates, vault
from ..config import settings
from ..media import footage
from ..runner import Handler, JobContext, Permanent, Retryable
from .render_post import SEGMENT_PRIORITY

_PEXELS_IN_KEY = re.compile(r"-pexels-(\d+)\.mp4$")


def _used_stock(script_id) -> set[int]:
    with db.conn() as c:
        keys = [r["artifact_key"] for r in c.execute(
            "select artifact_key from shots where script_id = %s and source = 'stock' and artifact_key is not null",
            (script_id,)).fetchall()]
    return {int(m.group(1)) for k in keys if (m := _PEXELS_IN_KEY.search(k))}


def run(ctx: JobContext) -> dict:
    log = lambda m: print(f"[prepare_shot] {m}", flush=True)  # noqa: E731
    with db.tx() as c:
        shot = c.execute("select * from shots where id = %s", (ctx.payload["shot_id"],)).fetchone()
        post = shot and c.execute("select * from posts where id = %s for update", (shot["post_id"],)).fetchone()
        if not shot or post["approved_script_id"] != shot["script_id"] or shot["state"] == "uploaded":
            return {"skipped": "shot is gone, superseded or already made"}
        if shot["source"] == "generate":
            return {"skipped": "generated shots are rendered on the GPU"}
        asset = c.execute("select * from assets where id = %s", (shot["asset_id"],)).fetchone() \
            if shot["asset_id"] else None
        if shot["source"] in ("clip", "image") and (asset is None or asset["rights"] != "approved"
                                                    or asset["state"] != "ready" or not asset["key"]):
            raise Permanent(f"shot {shot['idx'] + 1}'s footage is no longer approved or available", stage="rights")
        look = templates.look_for_post(c, post)
        if post["status"] == "queued_for_render":
            c.execute("update posts set status = 'rendering' where id = %s", (post["id"],))
            db.log_event(c, post["id"], "queued_for_render", "rendering", f"worker:{settings().worker_id}",
                         "making footage shots")
        c.execute("update shots set state = 'rendering' where id = %s", (shot["id"],))

    seconds = shot["num_frames"] / shot["fps"]
    credit = shot["credit"]
    stock_id = None
    ex = shot.get("extras") or {}
    size = templates.split_size(ex, look)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        out = work / "shot.mp4"
        if shot["source"] == "clip":
            src = storage.get_file(asset["key"], work / "asset.mp4")
            how = footage.compose_clip(src, out, seconds=seconds, start=float(shot["clip_in"] or 0),
                                       end=float(shot["clip_out"] or 0), layout=shot["layout"],
                                       audio=shot["audio_mode"], credit=credit,
                                       # the shot's own focus, else the phone video inside a wide frame
                                       focus=ex.get("focus") or (asset.get("analysis") or {}).get("frame"),
                                       timelapse=bool(ex.get("timelapse")), size=size)
        elif shot["source"] == "image":
            src = storage.get_file(asset["key"], work / "asset.jpg")
            how = footage.ken_burns(src, out, seconds=seconds, idx=shot["idx"], credit=credit, layout=shot["layout"],
                                    zoom=look.ken_burns, focus=ex.get("focus"), size=size)
        elif shot["source"] == "chart":
            still = footage.chart_still(shot["chart"] or {}, work / "chart.png", look, size)
            how = footage.ken_burns(still, out, seconds=seconds, idx=0, layout="cover", zoom=0.04, size=size)
        elif shot["source"] == "plain":
            how = footage.plain(out, seconds=seconds, look=look, size=size)
        else:
            key = vault.secret(post["user_id"], "pexels_api_key")
            if not key:
                raise Permanent("Stock shots need a Pexels API key — add it in Settings.", stage="config")
            with httpx.Client(timeout=60) as client:
                try:
                    clip = stock.find(client, key, shot["stock_query"] or shot["prompt"], seconds,
                                      _used_stock(shot["script_id"]))
                except stock.NotFound as e:
                    raise Permanent(f"shot {shot['idx'] + 1}: {e} — rewrite the script or edit the shot",
                                    stage="stock") from e
                except PermissionError as e:
                    raise Permanent(str(e), stage="config") from e
                except httpx.HTTPError as e:
                    raise Retryable(f"Pexels: {e}", stage="stock", retry_in=300) from e
                src = stock.download(client, clip, work / "stock.mp4")
            credit, stock_id = clip.credit, clip.id
            how = footage.compose_clip(src, out, seconds=seconds, layout="cover", audio="mute", credit=credit,
                                       size=size)
            how["pexels"] = {"id": clip.id, "page": clip.page}
        prefix = storage.post_prefix(post["user_id"], post["id"])
        name = f"{shot['idx']}-pexels-{stock_id}.mp4" if stock_id else f"{shot['idx']}-{shot['source']}.mp4"
        info = storage.put_file(f"{prefix}/shots/{shot['script_id']}/{name}", out, kind="shot",
                                user_id=post["user_id"], post_id=post["id"], shot_id=shot["id"],
                                content_type="video/mp4")
    with db.tx() as c:
        c.execute("""update shots set state = 'uploaded', artifact_key = %s, artifact_sha256 = %s, artifact_bytes = %s,
                                      credit = %s, attempts = attempts + 1, error = null
                      where id = %s""",
                  (info["key"], info["sha256"], info["bytes"], credit, shot["id"]))
        db.enqueue(c, user_id=post["user_id"], lane="cpu", kind="build_segment",
                   dedupe_key=f"build_segment:{shot['id']}:{info['sha256'][:16]}",
                   payload={"shot_id": str(shot["id"])}, post_id=post["id"], shot_id=shot["id"],
                   priority=SEGMENT_PRIORITY, max_attempts=2, lease_seconds=600)
    log(f"shot {shot['idx']} ({shot['source']}) ready: {how}")
    return {"idx": shot["idx"], "source": shot["source"], **how}


def on_give_up(ctx: JobContext, err: dict) -> None:
    with db.tx() as c:
        shot = c.execute("select id, idx, post_id from shots where id = %s", (ctx.payload["shot_id"],)).fetchone()
        if not shot:
            return
        c.execute("update shots set state = 'failed', error = %s where id = %s",
                  (Jsonb({"stage": err.get("stage"), "message": err.get("message")}), shot["id"]))
        post = c.execute("select id, status from posts where id = %s for update", (shot["post_id"],)).fetchone()
        if post and post["status"] in ("queued_for_render", "rendering"):
            message = f"Shot {shot['idx'] + 1} couldn't be made: {err.get('message')}"
            c.execute("update posts set status = 'failed', error = %s where id = %s",
                      (Jsonb({"stage": err.get("stage") or "prepare", "message": message}), post["id"]))
            db.log_event(c, post["id"], post["status"], "failed", "system", "a footage shot gave up",
                         {"shot": shot["idx"] + 1})


HANDLER = Handler(run=run, on_give_up=on_give_up)
