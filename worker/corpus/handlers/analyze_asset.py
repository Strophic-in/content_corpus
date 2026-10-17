"""cpu/analyze_asset — log a post's footage for the script writer.

For a video: what is said (Whisper, on this worker, the language detected) and
what happens when (one vision call on a 4x4 contact sheet whose frame times are
known, so `moments` come back with times). For a picture: one look at it. The
result lands in assets.analysis and the asset becomes ready, which lets a waiting
write_script go on — or, for a picture the owner wants an AI version of, lets
make_ai_image draw its twin from the description. Without a vision model the transcript (and the card's own
description) is all there is — the asset is ready all the same.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from psycopg.types.json import Jsonb

from .. import costs, db, storage, vault
from ..ideas import media
from ..ideas.vision import OpenAIVision
from ..media import assemble
from ..runner import Handler, JobContext

# Swapped by tests.
VISION = OpenAIVision
TRANSCRIBE = assemble.transcribe
SHEET_TILES = 4


def run(ctx: JobContext) -> dict:
    log = lambda m: print(f"[analyze_asset] {m}", flush=True)  # noqa: E731
    with db.conn() as c:
        a = c.execute("select * from assets where id = %s", (ctx.payload["asset_id"],)).fetchone()
        if a is None or a["state"] != "pending" or not a["key"]:
            return {"skipped": "not waiting for analysis"}
        post = c.execute("select topic, channel_id, category_id from posts where id = %s", (a["post_id"],)).fetchone()
        st = c.execute("select vision_model, script_model from app_settings where user_id = %s",
                       (a["user_id"],)).fetchone() or {}
    analysis = dict(a["analysis"] or {})
    billed = dict(user_id=a["user_id"], post_id=a["post_id"], channel_id=post["channel_id"],
                  category_id=post["category_id"], job_id=ctx.job.get("id"))
    model = st.get("vision_model")
    key = vault.secret(a["user_id"], "openai") if model else None
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        path = storage.get_file(a["key"], work / ("asset.mp4" if a["kind"] == "video" else "asset.jpg"))
        transcript = ""
        times = None
        if a["kind"] == "video":
            if a["has_audio"]:
                try:
                    analysis["transcript"] = TRANSCRIBE(path)
                    transcript = "\n".join(f"{t['start']:.1f}-{t['end']:.1f}s: {t['text']}"
                                           for t in analysis["transcript"])
                except Exception as e:  # noqa: BLE001 - the picture still tells most of it
                    log(f"no transcript: {e}")
            seconds = max(float(a["seconds"] or 0), 1.0)
            n = SHEET_TILES * SHEET_TILES
            times = [round(k * seconds / n, 1) for k in range(n)]
            sheet = media.contact_sheet(path, work / "sheet.jpg", tiles=SHEET_TILES)
        else:
            sheet = path
        if key:
            try:
                out, usage = VISION(key).analyze(model, sheet, post["topic"], times, transcript)
                costs.record_llm(usage, kind="vision", note="footage log", **billed)
                analysis.update(out.model_dump())
            except Exception as e:  # noqa: BLE001 - a script can still use it, with less to go on
                if getattr(e, "usage", None) is not None:
                    costs.record_llm(e.usage, kind="vision", note="unparsable footage log", **billed)
                analysis["vision_error"] = f"{type(e).__name__}: {str(e)[:200]}"
                log(f"vision skipped: {e}")
    with db.tx() as c:
        c.execute("update assets set analysis = %s, state = 'ready' where id = %s", (Jsonb(analysis), a["id"]))
        draw_twins(c, a)
    return {"moments": len(analysis.get("moments") or []), "transcript_lines": len(analysis.get("transcript") or [])}


def draw_twins(c, a: dict) -> None:
    """Queue the AI version of this picture, if the owner asked for one."""
    for t in c.execute("select id from assets where made_from = %s and state = 'pending'", (a["id"],)).fetchall():
        db.enqueue(c, user_id=a["user_id"], lane="cpu", kind="make_ai_image", dedupe_key=f"make_ai_image:{t['id']}",
                   payload={"asset_id": str(t["id"])}, post_id=a["post_id"], priority=40, max_attempts=2,
                   lease_seconds=600)


def on_give_up(ctx: JobContext, err: dict) -> None:
    """The file is fine: the asset is usable without its log."""
    with db.tx() as c:
        a = c.execute("""update assets set state = 'ready',
                                analysis = coalesce(analysis, '{}'::jsonb) || jsonb_build_object('error', %s::text)
                          where id = %s and state = 'pending' and key is not null returning *""",
                      ((err.get("message") or "analysis failed")[:300], ctx.payload["asset_id"])).fetchone()
        if a:
            draw_twins(c, a)


HANDLER = Handler(run=run, on_give_up=on_give_up)
