"""cpu/package_post — a finished reel's title, caption, hashtags, first comment and
cover (packaging.py). Queued when the reel is ready, and by "Write it again" on the
post page (payload {"force": true})."""

from __future__ import annotations

from .. import db, packaging
from ..runner import Handler, JobContext, Permanent, Retryable


def run(ctx: JobContext) -> dict:
    post_id = ctx.job["post_id"]
    try:
        if ctx.payload.get("force"):
            post = packaging._post(post_id)
            if not post:
                raise Permanent("the post or its approved script is gone", stage="input")
            pkg = packaging.make(post, job_id=ctx.job.get("id"))
        else:
            pkg = packaging.ensure(post_id, job_id=ctx.job.get("id"))
    except Permanent:
        raise
    except RuntimeError as e:
        raise Permanent(str(e), stage="package") from e
    except Exception as e:  # noqa: BLE001 - a model or storage hiccup: try again
        raise Retryable(f"writing the caption and cover: {e}", stage="package", retry_in=60) from e
    if not pkg:
        raise Permanent("the post or its approved script is gone", stage="input")
    with db.conn() as c:
        st = c.execute("select status from posts where id = %s", (post_id,)).fetchone()
        if st:
            db.log_event(c, post_id, st["status"], st["status"], "worker", "caption and cover written",
                         {"title": pkg["title"], "thumbnail": pkg["thumbnail_text"]})
    return {"title": pkg["title"], "thumbnail": pkg["thumbnail_text"], "hashtags": len(pkg["hashtags"])}


HANDLER = Handler(run=run)
