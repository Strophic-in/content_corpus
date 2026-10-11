"""cpu/plan_shots — an approved script → rows in `shots`, ready to render.

Every value a render depends on is fixed here, once: prompt, seed, size, frame
count. That is what makes a re-render byte-comparable and "regenerate shot 4
only" a real feature. Idempotent: a script that already has shots is left alone.
"""

from __future__ import annotations

import hashlib

from .. import db, prompts
from ..config import settings
from ..runner import Handler, JobContext, Permanent
from ..script.llm import MAX_SHOT_SECONDS, MIN_SHOT_SECONDS

FPS = 24
# 9:16-ish and on LTX-2.5's grid: both sides are multiples of 64, because stage 1
# renders at half size and must itself land on the 32-pixel grid. The final
# reel is scaled/cropped to 1080x1920 at assembly.
WIDTH, HEIGHT = 704, 1280
NEGATIVE = ("pc game, console game, video game, cartoon, childish, ugly, blurry, "
            "distorted face, deformed hands, extra fingers, duplicate objects, text, "
            "subtitles, watermark, logo, nude, naked, bare skin, nipples, genitals")
# Narrated mode: the voice-over is added later by TTS, so the video model must not
# invent its own speaker — that would be a second, mismatched voice.
NEGATIVE_NARRATED = NEGATIVE + ", talking, speech, voice, dialogue, narration, singing"
NO_SPEECH = "No one speaks; only sound effects and ambience."


def frames_for(seconds: float) -> int:
    """Nearest legal LTX frame count (8n + 1) for a duration at FPS."""
    n = max(1, round(seconds * FPS / 8))
    return 8 * n + 1


def seed_for(script_id: str, idx: int) -> int:
    # Stable across retries and re-plans; 47 bits keeps it a positive bigint.
    return int.from_bytes(hashlib.sha256(f"{script_id}:{idx}".encode()).digest()[:6], "big") >> 1


def shot_prompt(shot: dict, style: str | None, narrated: bool = False, look: str = "") -> str:
    """What the video model sees: the shot itself first (it matters most), then the
    format's look and this video's additions — each once. Writers sometimes copy the
    look into `visual`; repeating it again only buries the action (seen live)."""
    visual = shot.get("visual", "").strip()
    parts = [visual, shot.get("audio", "").strip()]
    for extra in ((look or "").strip(), (style or "").strip()):
        if extra and not any(prompts.contains(p, extra) for p in parts):
            parts.append(extra)
    if narrated:
        parts.append(NO_SPEECH)
    return " ".join(p for p in parts if p)


def run(ctx: JobContext) -> dict:
    script_id = ctx.payload["script_id"]
    with db.tx() as c:
        s = c.execute("select * from scripts where id = %s for update", (script_id,)).fetchone()
        if s is None:
            raise Permanent("script was deleted", stage="input")
        if s["state"] != "approved":
            return {"skipped": f"script is {s['state']}"}
        have = c.execute("select count(*) as n from shots where script_id = %s",
                         (script_id,)).fetchone()["n"]
        if have:
            return {"shots": have, "reused": True}
        plan = s["shot_plan"] or []
        if not plan:
            raise Permanent("approved script has no shots", stage="input")
        post = c.execute("""select p.audio_source, f.visual_style from posts p
                              left join formats f on f.id = p.format_id where p.id = %s""",
                         (s["post_id"],)).fetchone()
        narrated = post["audio_source"] == "kokoro"
        look = post["visual_style"] or ""

        total = 0.0
        for idx, shot in enumerate(plan):
            seconds = min(MAX_SHOT_SECONDS, max(MIN_SHOT_SECONDS, float(shot.get("seconds", 5))))
            frames = frames_for(seconds)
            total += (frames - 1) / FPS
            c.execute(
                """insert into shots (post_id, script_id, idx, scene_group, chain_role, prompt,
                                      negative_prompt, seed, width, height, num_frames, fps,
                                      narration)
                   values (%s, %s, %s, %s, 'anchor', %s, %s, %s, %s, %s, %s, %s, %s)""",
                (s["post_id"], script_id, idx, idx, shot_prompt(shot, s["style_prompt"], narrated, look),
                 NEGATIVE_NARRATED if narrated else NEGATIVE, seed_for(str(script_id), idx),
                 WIDTH, HEIGHT, frames, FPS, (shot.get("narration") or None) if narrated else None))
        db.log_event(c, s["post_id"], "approved", "approved", f"worker:{settings().worker_id}",
                     "shots planned", {"shots": len(plan), "seconds": round(total, 2)})
        if narrated:
            # The voice sets each shot's final length, so narration comes next.
            user_id = c.execute("select user_id from posts where id = %s",
                                (s["post_id"],)).fetchone()["user_id"]
            db.enqueue(c, user_id=user_id, lane="cpu", kind="narrate",
                       dedupe_key=f"narrate:{script_id}", payload={"script_id": str(script_id)},
                       post_id=s["post_id"], max_attempts=3, lease_seconds=600)
    return {"shots": len(plan), "seconds": round(total, 2)}


HANDLER = Handler(run=run)
