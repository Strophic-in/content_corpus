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
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from .. import db, storage
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


def run(ctx: JobContext) -> dict:
    platform = ctx.payload.get("platform")
    if platform not in NAMES:
        raise Permanent(f"unknown platform {platform!r}", stage="input")
    name = NAMES[platform]
    post = db.one("""select p.id, p.user_id, p.channel_id, p.status, p.final_key, p.final_sha256,
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

    video = _download(post)
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            if platform == "youtube":
                out = youtube.publish(
                    client, refresh_token=decrypt(acc["token_ciphertext"]), path=video,
                    meta=youtube.metadata(post["title"], post["description"] or "", post["hashtags"] or [],
                                          post["category_id"],
                                          ctx.payload.get("privacy") or post["youtube_privacy"]),
                    attempt=att, save=lambda **f: attempts.update(att, **f))
            else:
                out = instagram.publish(
                    client, token=_instagram_token(client, acc), ig_user_id=acc["external_id"], path=video,
                    caption=instagram.caption(post["title"], post["description"] or "", post["hashtags"] or []),
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
    with db.conn() as c:
        db.log_event(c, post["id"], post["status"], post["status"], f"worker:{settings().worker_id}",
                     f"posted to {name}", {"url": out.get("remote_url"), "privacy": out.get("privacy")})
    video.unlink(missing_ok=True)
    return {"platform": platform, "url": out.get("remote_url"), "privacy": out.get("privacy")}


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


def upkeep() -> None:
    """Renew Instagram tokens before they lapse, so a channel that has not posted
    for weeks still can. At most hourly; failures wait for the next round."""
    global _last_upkeep
    if time.monotonic() - _last_upkeep < 3600:
        return
    _last_upkeep = time.monotonic()
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
