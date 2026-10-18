"""cpu/plan_shots — an approved script → rows in `shots`, ready to render.

Every value a render depends on is fixed here, once: prompt, seed, size, frame
count. That is what makes a re-render byte-comparable and "regenerate shot 4
only" a real feature. Idempotent: a script that already has shots is left alone.

Shots that show footage (clip, image, stock) are planned at the reel's own size
(1080x1920) with an exact frame count — LTX's 8n+1 grid is for generated shots
only; their asset is the post's asset with the script's number. A clip that keeps
its own sound lasts as long as its window and carries no narration.

A generated shot that names a picture animates it: the picture is its first frame
(image-to-video) and its credit goes on screen. When the owner chose an AI version
of a video, the generated shots recreate it and are labelled "AI reconstruction".

What the template draws over a shot — its role, text, label, layout, transition,
bottom-panel picture, punch-in and timelapse — goes to shots.extras as written. A
"plain" shot is the format's background colour, made on the server. A format with
no voice (audio 'none') has no narration and asks the video model for no speech.
Carousels and cards have no shots: their slides are made by render_slides.

The post's video look (looks.py) gives every generated shot its style words and
what to avoid; a photoreal look labels its generated shots "AI-generated" on screen.
"""

from __future__ import annotations

import hashlib

from psycopg.types.json import Jsonb

from .. import auto, db, looks, prompts
from ..config import settings
from ..runner import Handler, JobContext, Permanent
from ..script.llm import MAX_CLIP_SECONDS, MAX_SHOT_SECONDS, MIN_SHOT_SECONDS

EXTRAS = ("role", "text", "label", "layout", "transition", "timelapse")

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


REEL_W, REEL_H = 1080, 1920


def footage_frames(seconds: float) -> int:
    """Exact frames for a footage shot (no LTX grid)."""
    return max(9, round(seconds * FPS))


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


def extras(shot: dict, assets: dict) -> dict:
    """The on-screen fields, with the bottom panel's picture resolved to its asset."""
    out = {k: shot[k] for k in EXTRAS if shot.get(k) not in (None, "", False)}
    panel = assets.get(int(shot.get("panel_asset") or 0))
    if panel is not None and panel["kind"] == "image":
        out["panel_asset_id"] = str(panel["id"])
        out["panel_credit"] = panel["credit"] or None
    f = shot.get("focus") or {}
    if float(f.get("w") or 0) > 0 and float(f.get("h") or 0) > 0:
        out["focus"] = {k: round(float(f.get(k) or 0), 4) for k in ("x", "y", "w", "h")}
    return out


def _plan_footage(c, s: dict, idx: int, shot: dict, source: str, assets: dict, narrated: bool) -> float:
    asset = assets.get(int(shot.get("asset") or 0)) if source in ("clip", "image") else None
    if source in ("clip", "image") and (asset is None or asset["kind"] != ("video" if source == "clip" else "image")):
        raise Permanent(f"shot {idx + 1} uses footage #{shot.get('asset')}, which this post doesn't have",
                        stage="input")
    keep = source == "clip" and bool(shot.get("keep_audio"))
    start, end = float(shot.get("start") or 0), float(shot.get("end") or 0)
    if keep:
        seconds = min(MAX_CLIP_SECONDS, max(1.0, end - start))
    else:                       # an estimate: the narration, once recorded, sets the length
        seconds = min(MAX_CLIP_SECONDS, max(MIN_SHOT_SECONDS, float(shot.get("seconds", 5))))
    narration = (shot.get("narration") or None) if narrated and not keep else None
    c.execute(
        """insert into shots (post_id, script_id, idx, scene_group, chain_role, prompt, seed, width, height,
                              num_frames, fps, narration, source, asset_id, clip_in, clip_out, audio_mode,
                              stock_query, credit, chart, extras)
           values (%s, %s, %s, %s, 'anchor', %s, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (s["post_id"], s["id"], idx, idx, (shot.get("visual") or "").strip() or source, REEL_W, REEL_H,
         footage_frames(seconds), FPS, narration, source, asset["id"] if asset else None,
         start if source == "clip" else None, end if source == "clip" else None,
         "keep" if keep else ("duck" if source == "clip" else "mute"),
         (shot.get("stock_query") or "").strip() or None if source == "stock" else None,
         asset["credit"] if asset else None, Jsonb(shot.get("chart")) if source == "chart" else None,
         Jsonb(extras(shot, assets))))
    return seconds


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
        post = c.execute("""select p.audio_source, p.format, p.look_id, f.visual_style from posts p
                              left join formats f on f.id = p.format_id where p.id = %s""",
                         (s["post_id"],)).fetchone()
        slides = post["format"] in ("carousel", "image")
        plan = s["shot_plan"] or []
        if not plan and not slides:
            raise Permanent("approved script has no shots", stage="input")
        narrated = post["audio_source"] == "kokoro"
        silent = post["audio_source"] == "none"     # nobody speaks: text, music and the shots' own sound
        vlook = looks.get(post["look_id"])
        look = vlook.prompt if vlook else (post["visual_style"] or "")
        avoid = f", {vlook.avoid}" if vlook and vlook.avoid else ""
        ai_label = "AI-generated" if vlook and vlook.realism == "photoreal" else None

        assets = {r["n"]: r for r in c.execute(
            "select id, n, kind, credit, key, rights from assets where post_id = %s", (s["post_id"],)).fetchall()}
        # The owner wanted an AI version of the idea's video: what is generated recreates it.
        reconstruction = any(a["kind"] == "video" and a["rights"] == "needs_review" for a in assets.values())
        total = 0.0
        if slides:
            plan = []
        for idx, shot in enumerate(plan):
            source = shot.get("source") or "generate"
            if source != "generate":
                total += _plan_footage(c, s, idx, shot, source, assets, narrated)
                continue
            seconds = min(MAX_SHOT_SECONDS, max(MIN_SHOT_SECONDS, float(shot.get("seconds", 5))))
            frames = frames_for(seconds)
            total += (frames - 1) / FPS
            guide = assets.get(int(shot.get("asset") or 0))
            if shot.get("asset") and (guide is None or guide["kind"] != "image"):
                raise Permanent(f"shot {idx + 1} animates footage #{shot.get('asset')}, which isn't a picture "
                                "of this post", stage="input")
            credit = guide["credit"] if guide else ("AI reconstruction" if reconstruction else ai_label)
            c.execute(
                """insert into shots (post_id, script_id, idx, scene_group, chain_role, prompt,
                                      negative_prompt, seed, width, height, num_frames, fps,
                                      narration, asset_id, guide_kind, guide_key, credit, extras)
                   values (%s, %s, %s, %s, 'anchor', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (s["post_id"], script_id, idx, idx,
                 shot_prompt(shot, s["style_prompt"], narrated or silent, look),
                 (NEGATIVE_NARRATED if narrated or silent else NEGATIVE) + avoid, seed_for(str(script_id), idx),
                 WIDTH, HEIGHT, frames, FPS, (shot.get("narration") or None) if narrated else None,
                 guide["id"] if guide else None, "first_frame" if guide else None,
                 guide["key"] if guide else None, credit, Jsonb(extras(shot, assets))))
        if not slides:
            db.log_event(c, s["post_id"], "approved", "approved", f"worker:{settings().worker_id}",
                         "shots planned", {"shots": len(plan), "seconds": round(total, 2)})
        if narrated:
            # The voice sets each shot's final length, so narration comes next.
            user_id = c.execute("select user_id from posts where id = %s",
                                (s["post_id"],)).fetchone()["user_id"]
            db.enqueue(c, user_id=user_id, lane="cpu", kind="narrate",
                       dedupe_key=f"narrate:{script_id}", payload={"script_id": str(script_id)},
                       post_id=s["post_id"], max_attempts=3, lease_seconds=600)
    if not narrated:
        auto.request_render(s["post_id"])        # Automatic mode: nothing to voice, on to rendering
    if slides:
        return {"slides": True}
    return {"shots": len(plan), "seconds": round(total, 2)}


HANDLER = Handler(run=run)
