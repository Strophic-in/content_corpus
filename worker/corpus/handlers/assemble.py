"""cpu/assemble — the finished shot segments → the reel in R2.

By the time the GPU is done, cpu/build_segment has normally finished every shot
(captioned, encoded, sound bed cut to length) while later shots were rendering, so
this is a join: the pictures are copied, the sound is normalised once and encoded.
A segment missing from the cache is built here. Idempotent: a post already
pointing at its final reel is left alone.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .. import db, storage
from ..config import settings
from ..media import assemble as media
from ..runner import Handler, JobContext, Permanent
from . import build_segment


def run(ctx: JobContext) -> dict:
    script_id = ctx.payload["script_id"]
    with db.conn() as c:
        post = c.execute("select * from posts where approved_script_id = %s", (script_id,)).fetchone()
        if post is None:
            raise Permanent("post or approved script no longer exists", stage="input")
        if post["final_key"] and post["status"] in ("ready", "scheduled", "published"):
            return {"skipped": "already assembled", "final_key": post["final_key"]}
        hint = c.execute("select intended_dialogue from scripts where id = %s",
                         (script_id,)).fetchone()["intended_dialogue"]
        shots = c.execute(f"select {build_segment.SHOT_COLS} from shots where script_id = %s order by idx",
                          (script_id,)).fetchall()
        style = build_segment.caption_style(c, post)
        old = post["status"]
        c.execute("update posts set status = 'post_processing' where id = %s", (post["id"],))
        db.log_event(c, post["id"], old, "post_processing", f"worker:{settings().worker_id}", "assembling")
    if any(s["state"] != "uploaded" for s in shots):
        raise Permanent("not every shot is rendered yet", stage="input")

    built = [build_segment.ensure_segment(post, s, style, hint) for s in shots]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "final.mp4"
        info = media.join_segments([(v, a) for v, a, _ in built], out)
        info["segments_ready"] = sum(cached for _, _, cached in built)
        key = f"{storage.post_prefix(post['user_id'], post['id'])}/final/{script_id}.mp4"
        stored = storage.put_file(key, out, kind="final", user_id=post["user_id"], post_id=post["id"],
                                  content_type="video/mp4")
    with db.tx() as c:
        c.execute("""update posts set status = 'ready', final_key = %s, final_sha256 = %s, final_bytes = %s,
                                      final_duration_s = %s, error = null
                      where id = %s""", (key, stored["sha256"], stored["bytes"], info["seconds"], post["id"]))
        db.log_event(c, post["id"], "post_processing", "ready", f"worker:{settings().worker_id}",
                     "reel assembled", {**info, "bytes": stored["bytes"]})
    shutil.rmtree(build_segment.cache_dir(post["id"]), ignore_errors=True)
    return {**info, "final_key": key}


def on_give_up(ctx: JobContext, err: dict) -> None:
    from psycopg.types.json import Jsonb

    with db.tx() as c:
        post = c.execute("select id, status from posts where approved_script_id = %s for update",
                         (ctx.payload["script_id"],)).fetchone()
        if post and post["status"] == "post_processing":
            c.execute("update posts set status = 'failed', error = %s where id = %s",
                      (Jsonb({"stage": err.get("stage"), "message": err.get("message")}), post["id"]))
            db.log_event(c, post["id"], "post_processing", "failed", "system", "assembly gave up")


HANDLER = Handler(run=run, on_give_up=on_give_up)
