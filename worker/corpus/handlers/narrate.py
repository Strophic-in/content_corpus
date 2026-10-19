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

from .. import auto, costs, db, jev, storage, vault, voices
from ..config import settings
from ..gpu import ltx25
from ..media import assemble as media
from ..media import tts
from ..runner import Handler, JobContext, Permanent
from ..script.llm import MAX_CLIP_SECONDS, MAX_SHOT_SECONDS
from .plan_shots import footage_frames

SPEAK = tts.speak                    # swapped by tests
SPEAK_OPENAI = voices.speak_openai   # swapped by tests
WORD_TIMINGS = media.whisper_words   # swapped by tests
PAUSE_SECONDS = 0.35                 # after each line; ltx25.frames_for's default pad


def run(ctx: JobContext) -> dict:
    script_id = ctx.payload["script_id"]
    with db.conn() as c:
        s = c.execute("select id, post_id, state from scripts where id = %s", (script_id,)).fetchone()
        if s is None:
            raise Permanent("script was deleted", stage="input")
        post = c.execute("""select p.id, p.user_id, p.channel_id, p.category_id, p.audio_source, p.topic, p.brief,
                                   p.voice_id, p.voice_style, ch.language, k.name as category,
                                   (select f.template_id from formats f where f.id = p.format_id) as template_id
                              from posts p left join channels ch on ch.id = p.channel_id
                              left join categories k on k.id = p.category_id
                             where p.id = %s""", (s["post_id"],)).fetchone()
        if s["state"] != "approved" or post["audio_source"] != "kokoro":
            return {"skipped": "not an approved narrated script"}
        st = c.execute("""select narrator_voice, narrator_speed, voice_mode, voices_enabled, fixed_voice, script_model
                            from app_settings where user_id = %s""", (post["user_id"],)).fetchone() or {}
        shots = c.execute("""select id, idx, narration, narration_key, narration_words, source, audio_mode
                               from shots where script_id = %s order by idx""", (script_id,)).fetchall()
    if not shots:
        raise Permanent("no shots to narrate", stage="input")
    v = voices.catalog()[_voice_for(post, st, shots)]
    voice = v.id
    speed = float(st.get("narrator_speed") or 1.1)
    api_key = vault.secret(post["user_id"], "openai") if v.engine == "openai" else None
    if v.engine == "openai" and not api_key:
        raise Permanent("This post's voice is an OpenAI voice — add your OpenAI key in Settings, or switch "
                        "OpenAI voices off in Settings → Voices.", stage="config")
    # An AI voice is told how to sound, written from the script itself; kept on the
    # post (voice_style) so a retry reads every line the same way.
    instructions = post["voice_style"] or ""
    if v.engine == "openai" and not instructions:
        said = "\n".join((sh["narration"] or "").strip() for sh in shots if (sh["narration"] or "").strip())
        instructions, usage = (voices.direction(api_key, st["script_model"], said, post["language"])
                               if st.get("script_model") else (voices.DEFAULT_DIRECTION, None))
        if usage is not None:
            costs.record_llm(usage, user_id=post["user_id"], post_id=post["id"], channel_id=post["channel_id"],
                             category_id=post["category_id"], job_id=ctx.job.get("id"), note="voice direction")
        with db.conn() as c:
            c.execute("update posts set voice_style = %s where id = %s", (instructions, post["id"]))
    spoken = 0.0
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
                if v.engine == "openai":
                    seconds = SPEAK_OPENAI(api_key, v.voice, instructions, text, wav)
                    spoken += seconds
                else:
                    seconds = SPEAK(text, v.voice, speed, wav)
                # A generated shot is one LTX take (≤ MAX_SHOT_SECONDS); footage can run longer.
                cap = MAX_SHOT_SECONDS if sh["source"] == "generate" else MAX_CLIP_SECONDS
                if seconds + PAUSE_SECONDS > cap:
                    # The shot would end mid-sentence: its picture cannot be longer.
                    raise Permanent(f"Shot {sh['idx'] + 1}'s narration takes {seconds:.1f}s to say, but this "
                                    f"shot holds at most {cap}s. Write the script again; "
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
    if spoken:
        costs.record_tts(user_id=post["user_id"], post_id=post["id"], channel_id=post["channel_id"],
                         category_id=post["category_id"], seconds=spoken, model=voices.TTS_MODEL,
                         job_id=ctx.job.get("id"))
    with db.conn() as c:
        db.log_event(c, post["id"], "approved", "approved", f"worker:{settings().worker_id}",
                     "narration recorded", {"voice": voice, "shots": done,
                                            "seconds": round(total, 2)})
    auto.request_render(post["id"])              # Automatic mode: on to the GPU
    return {"voice": voice, "shots_voiced": done, "seconds": round(total, 2)}


def _voice_for(post: dict, st: dict, shots: list) -> str:
    """The post's voice: kept from an earlier attempt, else chosen now (Jev picks from
    the voices switched on) and kept on the post."""
    if post["voice_id"] in voices.catalog():
        return post["voice_id"]
    said = " ".join((sh["narration"] or "") for sh in shots)[:1200]
    voice_id, why = voices.choose(
        jev.for_user(post["user_id"]), st, language=post["language"], story=f"{post['topic']}. {said}",
        category=post["category"] or "", template=post["template_id"] or "")
    with db.conn() as c:
        c.execute("update posts set voice_id = %s, voice_style = null, voice_why = %s where id = %s",
                  (voice_id, why, post["id"]))
    post["voice_style"] = None
    return voice_id


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
