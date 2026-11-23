"""cpu/package_post — a finished reel's title, caption, hashtags, first comment and
cover (packaging.py). Queued when the reel is ready, and by "Write it again" on the
post page (payload {"force": true})."""

from __future__ import annotations

import logging

import httpx

from .. import db, ig_music, packaging
from ..runner import Handler, JobContext, Permanent, Retryable

log = logging.getLogger("corpus.package_post")


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
    song = _pick_song(post_id, ctx.job.get("id"))
    return {"title": pkg["title"], "thumbnail": pkg["thumbnail_text"], "hashtags": len(pkg["hashtags"]),
            **({"song": song} if song else {})}


def _pick_song(post_id, job_id) -> str | None:
    """Best effort, last step: a reel bound for a unified Instagram account gets its
    trending song picked now, so the owner sees it before the reel goes out. Whatever
    goes wrong here is logged and left alone: publishing picks again when none is saved."""
    try:
        post = db.one("""select id, user_id, channel_id, format, final_ig_key, ig_music
                           from posts where id = %s""", (post_id,))
        if not post or not post["final_ig_key"] or post["format"] in ("carousel", "image"):
            return None
        acc = db.one("""select * from channel_accounts where channel_id = %s and platform = 'instagram'
                           and status = 'connected' and api = 'unified'""", (post["channel_id"],))
        if not acc:
            return None
        from .publish_post import TIMEOUT, _instagram_token      # the publisher's own token rules
        with httpx.Client(timeout=TIMEOUT) as client:
            token = _instagram_token(client, acc)
            pick = ig_music.choose(client, post=post, acc=acc, token=token, job_id=job_id)
        return pick.get("title") if pick else None
    except Exception:  # noqa: BLE001 - never fails the package; publish picks if none is saved
        log.warning("picking an Instagram song for %s failed; publishing will pick", post_id, exc_info=True)
        return None


HANDLER = Handler(run=run)
