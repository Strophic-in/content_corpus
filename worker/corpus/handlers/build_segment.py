"""cpu/build_segment — finish one rendered shot while the GPU renders the next.

render_post queues this the moment a shot is stored in R2. The shot becomes its
finished piece of the reel (1080x1920, captions burned in, its exact-length sound
bed) and waits in this worker's local cache; cpu/assemble then only has to join
the pieces. The cache is a speed-up, never the source of truth: assemble rebuilds
any piece it cannot find (another machine, a restart, a changed caption style).

Footage shots (cpu/prepare_shot) come through here the same way. In a narrated
reel a clip that keeps its own sound has no narration: its sound plays at full
level and its captions are what is said in it, as heard.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from psycopg.types.json import Jsonb

from .. import db, storage, templates
from ..config import settings
from ..media import assemble as media
from ..runner import Handler, JobContext

WORD_TIMINGS = media.whisper_words   # swapped by tests

SHOT_COLS = """id, post_id, script_id, idx, state, artifact_key, artifact_sha256,
               narration, narration_key, narration_words, source, audio_mode, credit, asset_id,
               clip_in, clip_out, extras"""


def _clip_speaks(shot: dict) -> bool:
    """Whether the asset's transcript (voice-activity filtered) has speech inside the
    clip's window: Whisper asked directly about a silent clip tends to invent a
    "Thank you." for the captions."""
    if shot.get("source") != "clip" or not shot.get("asset_id"):
        return True
    with db.conn() as c:
        row = c.execute("select analysis from assets where id = %s", (shot["asset_id"],)).fetchone()
    lines = ((row or {}).get("analysis") or {}).get("transcript")
    if lines is None:
        return True                                        # never transcribed: let Whisper listen
    lo, hi = float(shot.get("clip_in") or 0), float(shot.get("clip_out") or 1e9)
    return any(t["end"] > lo and t["start"] < hi for t in lines)


def caption_style(c, post: dict) -> media.CaptionStyle:
    sid = post.get("caption_style_id") or (c.execute(
        "select caption_style_id from app_settings where user_id = %s", (post["user_id"],)).fetchone() or {}).get(
        "caption_style_id")
    if not sid:
        return media.CaptionStyle()
    row = c.execute("""select font_family, font_size_px, primary_color, accent_color, outline_px, shadow_px,
                              position_y, words_per_group, active_scale, uppercase
                         from caption_styles where id = %s""", (sid,)).fetchone()
    return media.CaptionStyle(**{k: (float(v) if k in ("position_y", "active_scale") else v)
                                 for k, v in row.items()}) if row else media.CaptionStyle()


def cache_dir(post_id) -> Path:
    return settings().cache_dir / "segments" / str(post_id)


def ensure_segment(post: dict, shot: dict, style: media.CaptionStyle, hint: str,
                   look: templates.Look | None = None) -> tuple[Path, Path, bool]:
    """(picture, sound, was_cached) for a rendered shot, building and caching it if needed.
    `look`: what the post's template draws over it (None: captions only, as before templates)."""
    narrated = post["audio_source"] == "kokoro"
    ex = shot.get("extras") or {}
    d = cache_dir(post["id"])
    d.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=d) as tmp:
        work = Path(tmp)
        narration = None
        words = shot.get("narration_words")
        voiced = narrated and bool(shot.get("narration_key"))
        if voiced:
            narration = storage.get_file(shot["narration_key"], work / "narration.wav")
            if words is None:   # voiced before word timings were recorded at narrate time
                words = media.narration_words(narration, shot["narration"] or "", WORD_TIMINGS)
                with db.conn() as c:
                    c.execute("update shots set narration_words = %s where id = %s", (Jsonb(words), shot["id"]))
        # Footage shots carry their credit already; a generated one may have a label to draw.
        label = shot.get("credit") if (shot.get("source") or "generate") == "generate" else None
        key = hashlib.sha256(json.dumps(
            [media.SEGMENT_VERSION, shot["artifact_sha256"] or shot["artifact_key"], shot["narration_key"],
             words, None if voiced else hint, asdict(style), media.LEAD_IN, media.SFX_GAIN,
             shot.get("source"), shot.get("audio_mode"), label, ex,
            look.model_dump() if look is not None else None],
            sort_keys=True, default=str).encode()).hexdigest()[:16]
        video, audio = d / f"{shot['idx']}-{key}.mp4", d / f"{shot['idx']}-{key}.wav"
        if video.exists() and audio.exists():
            return video, audio, True
        clip = storage.get_file(shot["artifact_key"], work / "clip.mp4")
        if voiced:
            timed = media.shifted([tuple(w) for w in words], media.LEAD_IN)
        elif (not media.has_audio(clip) or (shot.get("source") or "generate") in ("image", "stock", "plain", "chart")
              or not _clip_speaks(shot)
              or (post["audio_source"] == "none" and shot.get("source") != "clip")):
            timed = []                                     # nothing is said (no voice: only a clip may speak)
        else:                                              # characters, or a clip, speak
            timed = media.dialogue_words(clip, "" if narrated else hint, WORD_TIMINGS)
        panel = None
        if ex.get("panel_asset_id"):
            with db.conn() as c:
                a = c.execute("select key, rights, state from assets where id = %s", (ex["panel_asset_id"],)).fetchone()
            if a and a["key"] and a["rights"] == "approved" and a["state"] == "ready":
                panel = storage.get_file(a["key"], work / "panel.jpg")
        media.build_segment(clip, work / "seg.mp4", work / "seg.wav", narration=narration, words=timed,
                            style=style, label=label, look=look, extras=ex, panel=panel,
                            panel_credit=ex.get("panel_credit") if panel else None)
        # Sound first, picture last: a picture on disk means the pair is complete.
        os.replace(work / "seg.wav", audio)
        os.replace(work / "seg.mp4", video)
    return video, audio, False


def run(ctx: JobContext) -> dict:
    with db.conn() as c:
        shot = c.execute(f"select {SHOT_COLS} from shots where id = %s", (ctx.payload["shot_id"],)).fetchone()
        post = shot and c.execute("select * from posts where id = %s", (shot["post_id"],)).fetchone()
        if not shot or post["approved_script_id"] != shot["script_id"] or shot["state"] != "uploaded":
            return {"skipped": "shot is gone, superseded or not rendered"}
        style = caption_style(c, post)
        look = templates.look_for_post(c, post)
        hint = c.execute("select intended_dialogue from scripts where id = %s",
                         (shot["script_id"],)).fetchone()["intended_dialogue"]
    video, _, cached = ensure_segment(post, shot, style, hint, look)
    return {"idx": shot["idx"], "segment": video.name, "cached": cached}


HANDLER = Handler(run=run)
