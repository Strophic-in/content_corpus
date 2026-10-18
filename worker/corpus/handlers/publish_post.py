"""publish/publish_post — a finished reel → one platform (payload {"platform": ...}).

The post's status follows this job through a trigger (0012). Here: download the
reel, post it, record the attempt, and say how a failure should be treated:

    access expired, quota used up, video refused → Permanent (someone must act)
    network trouble, slow processing             → Retryable (the next run resumes
                                                   the same upload, never a new one)
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from .. import db, packaging, stats, storage
from ..config import settings
from ..crypto import decrypt, encrypt
from ..publish import attempts, instagram, youtube
from ..runner import Handler, JobContext, Permanent, Retryable

log = logging.getLogger("corpus.publish")

NAMES = {"youtube": "YouTube", "instagram": "Instagram"}
TIMEOUT = httpx.Timeout(300, connect=20)
# Instagram tokens live 60 days and can be renewed once they are a day old.
IG_RENEW_WITHIN = timedelta(days=30)
IG_RENEW_AFTER = timedelta(days=1)
INSTAGRAM_LINK_SECONDS = 2 * 3600


def run(ctx: JobContext) -> dict:
    platform = ctx.payload.get("platform")
    if platform not in NAMES:
        raise Permanent(f"unknown platform {platform!r}", stage="input")
    name = NAMES[platform]
    post = db.one("""select p.id, p.user_id, p.channel_id, p.status, p.final_key, p.final_sha256, p.credits,
                            p.format, p.slides,
                            (exists (select 1 from shots x where x.script_id = p.approved_script_id
                                        and x.source = 'generate')
                             or exists (select 1 from jsonb_array_elements(coalesce(s.slides, '[]'::jsonb)) e
                                         where e->'visual'->>'source' = 'ai_image')) as synthetic,
                            s.title, s.description, s.hashtags,
                            coalesce(st.youtube_category_id, '22') as category_id,
                            coalesce(st.youtube_privacy, 'private') as youtube_privacy
                       from posts p
                       join scripts s on s.id = p.approved_script_id
                       left join app_settings st on st.user_id = p.user_id
                      where p.id = %s""", (ctx.job["post_id"],))
    if not post or not post["final_key"]:
        raise Permanent("this post has no finished reel to publish", stage="input")
    acc = db.one("select * from channel_accounts where channel_id = %s and platform = %s",
                 (post["channel_id"], platform))
    if not acc or acc["status"] != "connected":
        raise Permanent(f"{name} is not connected to this channel — connect it on the channel page, "
                        "then post again", stage="publish_auth")

    att = attempts.current(post["id"], platform)
    if att and att["state"] == "live":
        return {"skipped": "already posted", "url": att["remote_url"]}
    att = att or attempts.start(post["id"], platform)

    # Its title, caption, hashtags, first comment and cover (made when the reel was
    # finished; made now if not). Without them it goes out with the script's words.
    pkg = None
    try:
        pkg = packaging.ensure(post["id"], job_id=ctx.job.get("id"))
    except Exception as e:  # noqa: BLE001
        log.warning("no caption package for %s: %s", post["id"], e)
    credits = post["credits"] or []

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            if platform == "youtube":
                video = _download(post)
                out = youtube.publish(
                    client, refresh_token=decrypt(acc["token_ciphertext"]), path=video,
                    meta=youtube.metadata((pkg or {}).get("title") or post["title"], post["description"] or "",
                                          (pkg or {}).get("hashtags") or post["hashtags"] or [],
                                          post["category_id"],
                                          ctx.payload.get("privacy") or post["youtube_privacy"],
                                          credits=credits, synthetic=post["synthetic"],
                                          body=packaging.youtube_description(pkg, credits) if pkg else None),
                    attempt=att, save=lambda **f: attempts.update(att, **f))
            else:
                video = None
                # A carousel or card goes as its slides; YouTube gets its slideshow (final_key).
                slides = [s["key"] for s in (post["slides"] or [])] if post["format"] in ("carousel", "image") else []
                out = instagram.publish(
                    client, token=_instagram_token(client, acc), ig_user_id=acc["external_id"],
                    # Instagram downloads the file itself; the link lapses well after it has.
                    video_url=None if slides else storage.signed_url(post["final_key"], INSTAGRAM_LINK_SECONDS),
                    image_urls=[storage.signed_url(k, INSTAGRAM_LINK_SECONDS) for k in slides] or None,
                    caption=(packaging.instagram_caption(pkg, credits) if pkg else
                             instagram.caption(post["title"], post["description"] or "", post["hashtags"] or [],
                                               credits)),
                    cover_url=(storage.signed_url(pkg["thumbnail_key"], INSTAGRAM_LINK_SECONDS)
                               if pkg and pkg.get("thumbnail_key") and not slides else None),
                    attempt=att, save=lambda **f: attempts.update(att, **f))
    except (youtube.AuthExpired, instagram.AuthExpired) as e:
        _set_account_status(acc, "expired")
        _give_up(att, e)
        raise Permanent(f"{name} access has expired — reconnect {name} on the channel page, then post again",
                        stage="publish_auth") from e
    except youtube.QuotaExceeded as e:
        _give_up(att, e)
        raise Permanent("YouTube's daily upload limit for this app is used up — post again tomorrow",
                        stage="publish_quota") from e
    except (youtube.Rejected, youtube.NotConfigured, instagram.Rejected) as e:
        _give_up(att, e)
        raise Permanent(str(e), stage="publish") from e
    except (youtube.UploadError, instagram.PublishError, httpx.HTTPError) as e:
        # The attempt stays open: the next run resumes this upload or container.
        raise Retryable(f"{name}: {e}", stage="publish", retry_in=120) from e

    attempts.update(att, state="live", remote_id=out["remote_id"], remote_url=out.get("remote_url"),
                    privacy=out.get("privacy"), response=out.get("response") or {}, error=None)
    # Live first; then the cover as YouTube's thumbnail and the first comment. These
    # never undo the post — what happened is recorded on the attempt and the activity.
    extras = _extras(platform, acc["id"], out, pkg)
    if extras:
        attempts.update(att, response={**(out.get("response") or {}), "extras": extras})
    with db.conn() as c:
        db.log_event(c, post["id"], post["status"], post["status"], f"worker:{settings().worker_id}",
                     f"posted to {name}", {"url": out.get("remote_url"), "privacy": out.get("privacy"),
                                           **({"extras": extras} if extras else {})})
    if video:
        video.unlink(missing_ok=True)
    return {"platform": platform, "url": out.get("remote_url"), "privacy": out.get("privacy")}


def _extras(platform: str, account_id, out: dict, pkg: dict | None) -> dict:
    if not pkg or not out.get("remote_id"):
        return {}
    # The account row again: its token may have been renewed during the upload.
    acc = db.one("select token_ciphertext from channel_accounts where id = %s", (account_id,))
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            if platform == "youtube":
                with tempfile.TemporaryDirectory() as tmp:
                    cover = (storage.get_file(pkg["thumbnail_key"], Path(tmp) / "cover.jpg")
                             if pkg.get("thumbnail_key") else None)
                    return youtube.finish(client, refresh_token=decrypt(acc["token_ciphertext"]),
                                          video_id=out["remote_id"], cover=cover,
                                          comment=packaging.first_comment(pkg, "youtube"))
            return {"comment": instagram.comment(client, token=decrypt(acc["token_ciphertext"]),
                                                 media_id=out["remote_id"],
                                                 text=packaging.first_comment(pkg, "instagram"))}
    except Exception as e:  # noqa: BLE001 - the post is live either way
        log.warning("after posting to %s: %s", platform, e)
        return {"error": f"{type(e).__name__}: {e}"[:300]}


def _download(post: dict) -> Path:
    """The reel from R2, kept in the cache until it is posted (a retry reuses it)."""
    dest = settings().cache_dir / "publish" / f"{post['id']}.mp4"
    if dest.exists() and (not post["final_sha256"] or _sha256(dest) == post["final_sha256"]):
        return dest
    storage.get_file(post["final_key"], dest)
    if post["final_sha256"] and _sha256(dest) != post["final_sha256"]:
        dest.unlink(missing_ok=True)
        raise Retryable("the reel downloaded from storage is corrupt", stage="download")
    return dest


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _give_up(att: dict, err: Exception) -> None:
    """Record why it stopped. Close the attempt only if nothing was sent yet: one
    with an upload session or container stays open, because an earlier run may
    have finished it — the next run asks the platform before uploading again."""
    error = {"message": str(err)[:1000], "type": type(err).__name__}
    if att["state"] == "started":
        attempts.update(att, state="failed", error=error)
    else:
        attempts.update(att, error=error)


def _set_account_status(acc: dict, status: str) -> None:
    with db.conn() as c:
        c.execute("update channel_accounts set status = %s, updated_at = now() where id = %s",
                  (status, acc["id"]))


def _instagram_token(client: httpx.Client, acc: dict) -> str:
    """The account's token, renewed first when it is due (see IG_RENEW_*)."""
    token = decrypt(acc["token_ciphertext"])
    now = datetime.now(timezone.utc)
    expires = acc["token_expires_at"]
    if expires and expires <= now:
        raise instagram.AuthExpired("the Instagram token expired")
    if expires and expires - now < IG_RENEW_WITHIN and now - acc["updated_at"] > IG_RENEW_AFTER:
        try:
            token = _renew(client, acc, token)
        except instagram.PublishError as e:      # the old token still works for now
            log.warning("renewing the Instagram token for %s failed: %s", acc["handle"], e)
    return token


def _renew(client: httpx.Client, acc: dict, token: str) -> str:
    fresh, expires_in = instagram.refresh(client, token)
    with db.conn() as c:
        c.execute("""update channel_accounts set token_ciphertext = %s, token_expires_at = %s,
                            status = 'connected', updated_at = now() where id = %s""",
                  (encrypt(fresh), datetime.now(timezone.utc) + timedelta(seconds=expires_in), acc["id"]))
    log.info("renewed the Instagram token for %s", acc["handle"])
    return fresh


# ── upkeep, on every publish-lane tick ────────────────────────────────────────

_last_upkeep = 0.0


_last_stats = 0.0
STATS_EVERY_S = 6 * 3600


def upkeep() -> None:
    """Renew Instagram tokens before they lapse, so a channel that has not posted
    for weeks still can, and read back how published reels did (stats.py). At most
    hourly; failures wait for the next round."""
    global _last_upkeep, _last_stats
    if time.monotonic() - _last_upkeep < 3600:
        return
    _last_upkeep = time.monotonic()
    if time.monotonic() - _last_stats >= STATS_EVERY_S or _last_stats == 0.0:
        _last_stats = time.monotonic()
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                n = stats.read_back(client, log=log.info)
            if n:
                log.info("read back the numbers of %s published reel(s)", n)
        except Exception:  # noqa: BLE001
            log.exception("reading back reel statistics failed")
    with db.conn() as c:
        due = c.execute("""select * from channel_accounts
                            where platform = 'instagram' and status = 'connected'
                              and token_expires_at < now() + %s and updated_at < now() - %s""",
                        (IG_RENEW_WITHIN, IG_RENEW_AFTER)).fetchall()
    if not due:
        return
    with httpx.Client(timeout=TIMEOUT) as client:
        for acc in due:
            try:
                if acc["token_expires_at"] <= datetime.now(timezone.utc):
                    _set_account_status(acc, "expired")
                else:
                    _renew(client, acc, decrypt(acc["token_ciphertext"]))
            except instagram.AuthExpired:
                _set_account_status(acc, "expired")
            except Exception:  # noqa: BLE001 - one account must not stop the others
                log.exception("renewing the Instagram token for %s failed", acc["handle"])


HANDLER = Handler(run=run)
