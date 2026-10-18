"""YouTube: a resumable upload through the YouTube Data API v3.

The session URI is saved on the attempt before any bytes go out. A later run that
finds one asks YouTube how far it got (PUT with `Content-Range: bytes */<size>`):
finished → record that video, partway → send the rest. Only a session YouTube no
longer knows is started over, and an unknown session never finished a video.

A vertical video of three minutes or less is a Short; nothing extra is needed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import httpx

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK = 16 * 1024 * 1024      # resumable chunks must be multiples of 256 KiB


class NotConfigured(Exception):
    """GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are missing on the worker."""


class AuthExpired(Exception):
    """The refresh token no longer works: the owner has to reconnect YouTube."""


class QuotaExceeded(Exception):
    """The Google project's daily YouTube quota is used up (an upload costs 1,600 of 10,000)."""


class Rejected(Exception):
    """YouTube refused the request itself (bad metadata); retrying will not help."""


class UploadError(Exception):
    """Anything else — usually transient. The next run resumes from the saved session."""


def access_token(client: httpx.Client, refresh_token: str) -> str:
    cid, secret = os.environ.get("GOOGLE_CLIENT_ID"), os.environ.get("GOOGLE_CLIENT_SECRET")
    if not cid or not secret:
        raise NotConfigured("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are not set on the worker")
    r = client.post(TOKEN_URL, data={"client_id": cid, "client_secret": secret,
                                     "refresh_token": refresh_token, "grant_type": "refresh_token"})
    if r.status_code in (400, 401) and _json(r).get("error") in ("invalid_grant", "unauthorized_client"):
        raise AuthExpired("YouTube access has expired or was removed")
    if r.status_code != 200:
        raise UploadError(f"Google token refresh: HTTP {r.status_code}")
    return r.json()["access_token"]


def credit_line(credits: list[str]) -> str:
    return ("Footage: " + " · ".join(c.strip() for c in credits if c.strip())) if credits else ""


def metadata(title: str, description: str, hashtags: list[str], category_id: str,
             privacy: str = "private", credits: list[str] | None = None, synthetic: bool = True,
             body: str | None = None) -> dict:
    """The video resource for the upload. YouTube refuses '<' and '>' in text.

    `credits`: who made the footage shown (before the hashtags). `synthetic`: the reel
    has AI-generated shots — YouTube asks for that to be disclosed; a reel made
    only of real footage is not."""
    def clean(s: str) -> str:
        return s.replace("<", "").replace(">", "").strip()

    tags, used = [], 0
    for h in hashtags:
        t = clean(h).lstrip("#")
        if t and used + len(t) + 1 <= 450:      # YouTube's limit is 500 characters in all
            tags.append(t)
            used += len(t) + 1
    # `body`: the description already written whole (packaging: hook, caption, sources,
    # credits, hashtags); otherwise it is put together here.
    body = clean(body) if body else "\n\n".join(x for x in (clean(description), clean(credit_line(credits or [])),
                                                          " ".join(clean(h) for h in hashtags)) if x)
    return {
        "snippet": {"title": clean(title)[:100] or "Untitled", "description": body[:4900],
                    "tags": tags, "categoryId": category_id or "22"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": synthetic},
    }


THUMBNAILS = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
COMMENTS = "https://www.googleapis.com/youtube/v3/commentThreads"


def finish(client: httpx.Client, *, refresh_token: str, video_id: str, cover: Path | None, comment: str) -> dict:
    """After the upload: the cover as its thumbnail, and the first comment. Neither
    stops the post — each says what happened (a channel YouTube hasn't verified can't
    set thumbnails; comments need the account reconnected with the comment permission)."""
    token = access_token(client, refresh_token)
    auth = {"Authorization": f"Bearer {token}"}
    out: dict = {}
    if cover is not None:
        r = client.post(THUMBNAILS, params={"videoId": video_id, "uploadType": "media"},
                        headers={**auth, "Content-Type": "image/jpeg"}, content=cover.read_bytes())
        out["thumbnail"] = "set" if r.status_code == 200 else _why(r, "thumbnail")
    if comment:
        r = client.post(COMMENTS, params={"part": "snippet"}, headers=auth,
                        json={"snippet": {"videoId": video_id,
                                          "topLevelComment": {"snippet": {"textOriginal": comment}}}})
        out["comment"] = ("posted " + _json(r).get("id", "")) if r.status_code == 200 else _why(r, "comment")
    return out


def _why(r: httpx.Response, what: str) -> str:
    err = _json(r).get("error") or {}
    reason = ((err.get("errors") or [{}])[0]).get("reason") or err.get("status") or f"HTTP {r.status_code}"
    if reason in ("insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT", "PERMISSION_DENIED") \
            and what == "comment":
        return "not posted: reconnect YouTube on the channel page to allow comments"
    if reason == "forbidden" and what == "thumbnail":
        return "not set: YouTube allows custom thumbnails once the channel is verified (youtube.com/verify)"
    return f"not done: {reason}: {(err.get('message') or '')[:160]}"


def publish(client: httpx.Client, *, refresh_token: str, path: Path, meta: dict, attempt: dict,
            save: Callable[..., object]) -> dict:
    """Upload `path` and return what to record on the attempt. `save(**fields)`
    writes progress to the attempt row as it happens."""
    token = access_token(client, refresh_token)
    size = path.stat().st_size
    session, offset = attempt.get("upload_session_uri"), 0
    if session:
        video, offset = _status(client, token, session, size)
        if video is not None:
            return _result(video)
        if offset is None:          # YouTube no longer knows the session
            session = None
    if not session:
        session = _open_session(client, token, meta, size)
        save(upload_session_uri=session, state="uploading")
        offset = 0
    return _result(_send(client, token, session, path, size, offset))


def _status(client: httpx.Client, token: str, session: str, size: int) -> tuple[dict | None, int | None]:
    r = client.put(session, headers={"Authorization": f"Bearer {token}",
                                     "Content-Range": f"bytes */{size}"}, content=b"")
    if r.status_code in (200, 201):
        return r.json(), size
    if r.status_code == 308:
        return None, _received(r)
    if r.status_code in (404, 410):
        return None, None
    raise UploadError(f"asking YouTube how far the upload got: HTTP {r.status_code}")


def _open_session(client: httpx.Client, token: str, meta: dict, size: int) -> str:
    r = client.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"},
                    headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Length": str(size),
                             "X-Upload-Content-Type": "video/mp4"}, json=meta)
    if r.status_code != 200 or "location" not in r.headers:
        _raise(r, "starting the upload")
    return r.headers["location"]


def _send(client: httpx.Client, token: str, session: str, path: Path, size: int, offset: int) -> dict:
    with path.open("rb") as f:
        while True:
            f.seek(offset)
            chunk = f.read(CHUNK)
            r = client.put(session, content=chunk, headers={
                "Authorization": f"Bearer {token}",
                "Content-Range": f"bytes {offset}-{offset + len(chunk) - 1}/{size}"})
            if r.status_code in (200, 201):
                return r.json()
            if r.status_code != 308:
                _raise(r, "uploading")
            got = _received(r)
            if got <= offset:
                raise UploadError(f"YouTube accepted nothing past byte {offset}")
            offset = got


def _received(r: httpx.Response) -> int:
    """Bytes YouTube holds, from a 308's `Range: bytes=0-<last>` (none if absent)."""
    rng = r.headers.get("range")
    return int(rng.rsplit("-", 1)[1]) + 1 if rng else 0


def _result(video: dict) -> dict:
    vid = video["id"]
    return {"remote_id": vid, "remote_url": f"https://youtube.com/shorts/{vid}",
            "privacy": (video.get("status") or {}).get("privacyStatus"),
            "response": {"id": vid, "status": video.get("status") or {}}}


def _raise(r: httpx.Response, doing: str) -> None:
    err = _json(r).get("error") or {}
    reasons = {e.get("reason") for e in err.get("errors") or [] if isinstance(e, dict)}
    message = err.get("message") or f"HTTP {r.status_code}"
    if reasons & {"quotaExceeded", "dailyLimitExceeded", "uploadLimitExceeded"}:
        raise QuotaExceeded(message)
    if r.status_code == 401:
        raise UploadError(f"{doing}: the access token expired mid-upload")
    if r.status_code in (400, 403):
        raise Rejected(f"YouTube refused the upload: {message}")
    raise UploadError(f"{doing} on YouTube: {message}")


def _json(r: httpx.Response) -> dict:
    try:
        body = r.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
