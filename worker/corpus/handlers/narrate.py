"""cpu/narrate — voice each shot's narration and let the voice set the shot length.

Narrated mode's rule: the picture follows the voice. Each line is spoken by the
channel's narrator (Kokoro, on the CPU), stored in R2 through the storage
ledger, and the shot's num_frames becomes the line's length plus a short pause,
rounded to LTX's 8n+1. The line's word timings are measured here too (Whisper
on the line's own recording), so captions are ready before anyone presses
Render. Idempotent: finished shots are skipped, so a retry resumes where a crash
left off.

Footage shots take the line's exact length (no LTX grid); a clip that plays its
own sound has no line and keeps the length of its window.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from psycopg.types.json import Jsonb

from .. import auto, db, storage
from ..config import settings
from ..gpu import ltx25
from ..media import assemble as media
from ..media import tts
from ..runner import Handler, JobContext, Permanent
from ..script.llm import MAX_SHOT_SECONDS
from .plan_shots import footage_frames

SPEAK = tts.speak                    # swapped by tests
WORD_TIMINGS = media.whisper_words   # swapped by tests
PAUSE_SECONDS = 0.35                 # after each line; ltx25.frames_for's default pad


def run(ctx: JobContext) -> dict:
    script_id = ctx.payload["script_id"]
    with db.conn() as c:
        s = c.execute("select id, post_id, state from scripts where id = %s", (script_id,)).fetchone()
        if s is None:
            raise Permanent("script was deleted", stage="input")
        post = c.execute("select id, user_id, audio_source from posts where id = %s",
                         (s["post_id"],)).fetchone()
        if s["state"] != "approved" or post["audio_source"] != "kokoro":
            return {"skipped": "not an approved narrated script"}
        st = c.execute("select narrator_voice, narrator_speed from app_settings where user_id = %s",
                       (post["user_id"],)).fetchone() or {}
        shots = c.execute("""select id, idx, narration, narration_key, narration_words, source, audio_mode
                               from shots where script_id = %s order by idx""", (script_id,)).fetchall()
    if not shots:
        raise Permanent("no shots to narrate", stage="input")
    voice = st.get("narrator_voice") or "am_michael"
    speed = float(st.get("narrator_speed") or 1.1)
    prefix = storage.post_prefix(post["user_id"], post["id"])

    done, total = 0, 0.0
    with tempfile.TemporaryDirectory() as tmp:
        for sh in shots:
            if sh["narration_key"] and sh["narration_words"] is not None:
                continue
            text = (sh["narration"] or "").strip()
            if not text and sh["source"] == "clip" and sh["audio_mode"] == "keep":
                continue                     # the clip speaks for itself
            if not text:
                raise Permanent(f"shot {sh['idx'] + 1} has no narration line", stage="input")
            wav = Path(tmp) / f"{sh['idx']}.wav"
            if sh["narration_key"]:          # voiced by an earlier attempt; only timings missing
                storage.get_file(sh["narration_key"], wav)
            else:
                seconds = SPEAK(text, voice, speed, wav)
                if seconds + PAUSE_SECONDS > MAX_SHOT_SECONDS:
                    # The shot would end mid-sentence: its picture cannot be longer.
                    raise Permanent(f"Shot {sh['idx'] + 1}'s narration takes {seconds:.1f}s to say, but a "
                                    f"shot holds at most {MAX_SHOT_SECONDS}s. Write the script again; "
                                    f"new scripts keep every line short enough.", stage="narration_too_long")
                key = f"{prefix}/narration/{script_id}/{sh['idx']}.wav"
                storage.put_file(key, wav, kind="narration", user_id=post["user_id"], post_id=post["id"],
                                 shot_id=sh["id"], content_type="audio/wav")
                with db.conn() as c:
                    frames = (ltx25.frames_for(seconds) if sh["source"] == "generate"
                              else footage_frames(seconds + PAUSE_SECONDS))
                    c.execute("""update shots set narration_key = %s, narration_seconds = %s, num_frames = %s
                                  where id = %s""", (key, round(seconds, 3), frames, sh["id"]))
                done += 1
                total += seconds
            words = media.narration_words(wav, text, WORD_TIMINGS)
            with db.conn() as c:
                c.execute("update shots set narration_words = %s where id = %s", (Jsonb(words), sh["id"]))
    with db.conn() as c:
        db.log_event(c, post["id"], "approved", "approved", f"worker:{settings().worker_id}",
                     "narration recorded", {"voice": voice, "shots": done, "seconds": round(total, 2)})
    auto.request_render(post["id"])              # Automatic mode: on to the GPU
    return {"voice": voice, "shots_voiced": done, "seconds": round(total, 2)}


def on_give_up(ctx: JobContext, err: dict) -> None:
    """Say why on the post, instead of leaving it 'recording narration' forever."""
    with db.tx() as c:
        post = c.execute("""select p.id, p.status from posts p join scripts s on s.post_id = p.id
                             where s.id = %s for update of p""", (ctx.payload["script_id"],)).fetchone()
        if post and post["status"] == "approved":
            c.execute("update posts set status = 'failed', error = %s where id = %s",
                      (Jsonb({"stage": err.get("stage"), "message": err.get("message")}), post["id"]))
            db.log_event(c, post["id"], "approved", "failed", "system", "narration gave up",
                         {"stage": err.get("stage")})


HANDLER = Handler(run=run, on_give_up=on_give_up)
