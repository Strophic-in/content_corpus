"""cpu/make_ai_image — the AI version of a post's picture.

When the owner accepts an idea choosing "AI version", its picture becomes two
assets: the original (fetched and described, never shown) and its twin, which
this job draws once the original's description is ready (analyze_asset queues it).
The twin is credited "AI illustration" on screen. If it can't be drawn, it is
marked failed and the script goes on without it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from psycopg.types.json import Jsonb

from .. import costs, db, images, storage, vault
from ..ideas import media
from ..runner import Handler, JobContext, Permanent
from .write_script import _classify_openai_error

# Swapped by tests.
IMAGES = images.OpenAIImages


def run(ctx: JobContext) -> dict:
    with db.conn() as c:
        twin = c.execute("select * from assets where id = %s", (ctx.payload["asset_id"],)).fetchone()
        if twin is None or twin["state"] != "pending":
            return {"skipped": "not waiting to be drawn"}
        original = c.execute("select * from assets where id = %s", (twin["made_from"],)).fetchone()
        post = c.execute("""select p.topic, p.channel_id, p.category_id, f.visual_style
                              from posts p left join formats f on f.id = p.format_id where p.id = %s""",
                         (twin["post_id"],)).fetchone()
        st = c.execute("select image_model, image_quality from app_settings where user_id = %s",
                       (twin["user_id"],)).fetchone() or {}
    an = (original or {}).get("analysis") or {}
    description = an.get("summary") or (an.get("card") or {}).get("summary") or post["topic"]
    key = vault.secret(twin["user_id"], "openai")
    if not key:
        raise Permanent("Add your OpenAI API key in Settings.", stage="config")
    model, quality = st.get("image_model") or "gpt-image-1-mini", st.get("image_quality") or "medium"
    billed = dict(user_id=twin["user_id"], post_id=twin["post_id"], channel_id=post["channel_id"],
                  category_id=post["category_id"], job_id=ctx.job.get("id"))
    try:
        data, usage = IMAGES(key).generate(model=model, quality=quality,
                                           prompt=images.prompt_for(description, post["visual_style"] or "",
                                                                    post["topic"]))
    except Exception as e:  # noqa: BLE001 - classified like the script writer's
        raise _classify_openai_error(e) from e
    costs.record_llm(usage, kind="image", note=f"AI version of picture #{(original or {}).get('n', '?')}",
                     **billed)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "drawn.png"
        raw.write_bytes(data)
        jpg = media.image_preview(raw, Path(tmp) / "ai.jpg", max_side=2160)
        p = media.probe(jpg)
        k = f"{storage.post_prefix(twin['user_id'], twin['post_id'])}/assets/{twin['id']}.jpg"
        storage.put_file(k, jpg, kind="asset", user_id=twin["user_id"], post_id=twin["post_id"],
                         content_type="image/jpeg")
    with db.conn() as c:
        c.execute("""update assets set key = %s, w = %s, h = %s, has_audio = false, state = 'ready',
                            analysis = %s where id = %s""",
                  (k, p.w, p.h, Jsonb({"summary": f"AI illustration of: {description}"}), twin["id"]))
    return {"model": model, "quality": quality, "w": p.w, "h": p.h}


def on_give_up(ctx: JobContext, err: dict) -> None:
    with db.conn() as c:
        c.execute("update assets set state = 'failed', error = %s where id = %s and state = 'pending'",
                  ((err.get("message") or "couldn't draw it")[:500], ctx.payload["asset_id"]))


HANDLER = Handler(run=run, on_give_up=on_give_up)
