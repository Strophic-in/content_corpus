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

from psycopg.types.json import Jsonb

import httpx

from .. import auto, db, music, storage, templates, vault
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
        look = templates.look_for_post(c, post)
        old = post["status"]
        c.execute("update posts set status = 'post_processing' where id = %s", (post["id"],))
        db.log_event(c, post["id"], old, "post_processing", f"worker:{settings().worker_id}", "assembling")
    if any(s["state"] != "uploaded" for s in shots):
        raise Permanent("not every shot is rendered yet", stage="input")

    built = [build_segment.ensure_segment(post, s, style, hint, look) for s in shots]
    # How each shot begins: its own transition, else the format's.
    transitions = [((s.get("extras") or {}).get("transition") or look.transition) for s in shots]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "final.mp4"
        track = _music(post, script_id, Path(tmp))
        info = media.join_segments([(v, a) for v, a, _ in built], out,
                                   log=lambda m: print(f"[assemble {script_id}] {m}", flush=True),
                                   music=track.path if track else None, music_gain=music.GAIN,
                                   transitions=transitions, loop=look.loop)
        info["segments_ready"] = sum(cached for _, _, cached in built)
        key = f"{storage.post_prefix(post['user_id'], post['id'])}/final/{script_id}.mp4"
        stored = storage.put_file(key, out, kind="final", user_id=post["user_id"], post_id=post["id"],
                                  content_type="video/mp4")
    # Who made the footage shown, in order of appearance: for the description and caption.
    # ("AI reconstruction" and "AI illustration" are labels, not credits.)
    credits = list(dict.fromkeys(s["credit"].strip() for s in shots
                                 if (s.get("credit") or "").strip() and not s["credit"].startswith("AI ")))
    if track:
        credits.append(track.credit)
    with db.tx() as c:
        c.execute("""update posts set status = 'ready', final_key = %s, final_sha256 = %s, final_bytes = %s,
                                      final_duration_s = %s, error = null, credits = %s, music = %s
                      where id = %s""", (key, stored["sha256"], stored["bytes"], info["seconds"],
                                         Jsonb(credits), Jsonb(track.meta) if track else None, post["id"]))
        db.log_event(c, post["id"], "post_processing", "ready", f"worker:{settings().worker_id}",
                     "reel assembled", {**info, "bytes": stored["bytes"]})
    shutil.rmtree(build_segment.cache_dir(post["id"]), ignore_errors=True)
    auto.request_publish(post["id"])             # Automatic mode: post it at the picked time
    return {**info, "final_key": key}


class _Track:
    def __init__(self, t: music.Track, mood: str):
        self.path, self.credit = t.path, t.credit
        self.meta = {"id": t.id, "name": t.name, "author": t.author, "page": t.page, "mood": mood}


def _music(post: dict, script_id, work: Path) -> _Track | None:
    """The script's music mood → a CC0 track the owner hasn't used lately (None: no music)."""
    with db.conn() as c:
        mood = (c.execute("select music_mood from scripts where id = %s", (script_id,)).fetchone() or {}).get(
            "music_mood")
        recent = {int(r["id"]) for r in c.execute(
            """select (music->>'id') as id from posts where user_id = %s and music is not null
                order by updated_at desc limit %s""", (post["user_id"], music.RECENT)).fetchall() if r["id"]}
    key = vault.secret(post["user_id"], "freesound_api_key") if mood else None
    if not key:
        return None
    try:
        with httpx.Client(timeout=30) as client:
            t = music.find(client, key, mood, recent, work / "music.mp3")
    except Exception as e:  # noqa: BLE001 - a reel without music is still a reel
        print(f"[assemble {script_id}] no music: {e}", flush=True)
        return None
    return _Track(t, mood) if t else None


def on_give_up(ctx: JobContext, err: dict) -> None:
    with db.tx() as c:
        post = c.execute("select id, status from posts where approved_script_id = %s for update",
                         (ctx.payload["script_id"],)).fetchone()
        if post and post["status"] == "post_processing":
            # The expensive part (the GPU) is done and stored: say so, and how to finish.
            message = (f"Couldn't join the finished shots into the reel ({err.get('message')}). "
                       "Your rendered shots are safe in storage; press Retry assembly, no GPU needed.")
            c.execute("update posts set status = 'failed', error = %s where id = %s",
                      (Jsonb({"stage": "assemble", "message": message}), post["id"]))
            db.log_event(c, post["id"], "post_processing", "failed", "system", "assembly gave up")


HANDLER = Handler(run=run, on_give_up=on_give_up)
