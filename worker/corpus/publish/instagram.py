"""Instagram: a Reel, a carousel or a picture, through the Instagram API with Instagram Login.

Create a REELS container from `video_url` (a short-lived signed link to the reel
in R2: Instagram fetches the file itself), wait while Instagram processes it,
then publish. Direct byte uploads (upload_type=resumable) exist only on the
Facebook-login API; with Instagram Login the container insists on video_url
(seen 2026-10-16). The container id is saved on the attempt as soon as it exists,
and the attempt moves to 'uploaded' just before media_publish, so a later run
continues from what the container says:

    PUBLISHED            → find the post it became and record it
    FINISHED             → publish it
    anything else        → it never went out: start a new container

A carousel is a container per slide (is_carousel_item, from `image_urls`) and a
CAROUSEL container holding them, which is the one saved and published; a single
picture is one IMAGE container. Slides are JPEGs at 4:5 or 1:1 — the shapes the
API accepts.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

import httpx

GRAPH = "https://graph.instagram.com/v23.0"
CONTAINER = "ig-container:"        # upload_session_uri prefix on the attempt
PROCESS_TIMEOUT_S = 15 * 60
POLL_S = 5


class AuthExpired(Exception):
    """The token is invalid or expired: the owner has to reconnect Instagram."""


class Rejected(Exception):
    """Instagram refused the video or the request; retrying will not help."""


class PublishError(Exception):
    """Transient (rate limit, server error, slow processing): worth another run."""


def refresh(client: httpx.Client, token: str) -> tuple[str, int]:
    """A fresh 60-day token for one at least a day old. Returns (token, expires_in)."""
    r = client.get("https://graph.instagram.com/refresh_access_token",
                   params={"grant_type": "ig_refresh_token", "access_token": token})
    body = _ok(r, "refreshing the Instagram token")
    return body["access_token"], int(body.get("expires_in") or 5_184_000)


def caption(title: str, description: str, hashtags: list[str], credits: list[str] | None = None) -> str:
    """Instagram allows 2,200 characters and 30 hashtags. Credits come before the
    hashtags, so a long caption loses tags, not credits."""
    tags = " ".join(h.strip() for h in hashtags[:30] if h.strip())
    footage = ("Footage: " + " · ".join(c.strip() for c in credits if c.strip())) if credits else ""
    return "\n\n".join(x for x in (title.strip(), description.strip(), footage, tags) if x)[:2200]


def publish(client: httpx.Client, *, token: str, ig_user_id: str, video_url: str | None = None, caption: str,
            attempt: dict, save: Callable[..., object], sleep: Callable[[float], None] = time.sleep,
            clock: Callable[[], float] = time.monotonic, image_urls: list[str] | None = None) -> dict:
    """Post the video at `video_url` as a Reel — or `image_urls` as a carousel (or,
    one of them, a picture) — and return what to record on the attempt."""
    container = _container_of(attempt)
    if container:
        status = _status(client, token, container)
        if status == "PUBLISHED":
            return _find_published(client, token, ig_user_id, attempt["created_at"])
        if status != "FINISHED":
            container = None        # never published; Instagram drops it within a day
    if not container:
        container = (_create_images(client, token, ig_user_id, image_urls, caption, sleep, clock) if image_urls
                     else _create(client, token, ig_user_id, video_url or "", caption))
        save(upload_session_uri=CONTAINER + container, state="uploading")
        _wait_until_processed(client, token, container, sleep, clock)

    save(state="uploaded")          # from here on, the post may be live
    media = _ok(client.post(f"{GRAPH}/{ig_user_id}/media_publish",
                            data={"creation_id": container, "access_token": token}),
                "publishing the post")
    return _result(client, token, media["id"])


def _container_of(attempt: dict) -> str | None:
    uri = attempt.get("upload_session_uri") or ""
    return uri[len(CONTAINER):] if uri.startswith(CONTAINER) else None


def _create(client: httpx.Client, token: str, ig_user_id: str, video_url: str, text: str) -> str:
    return _ok(client.post(f"{GRAPH}/{ig_user_id}/media", data={
        "media_type": "REELS", "video_url": video_url, "caption": text,
        "share_to_feed": "true", "access_token": token}), "creating the reel")["id"]


def _create_images(client: httpx.Client, token: str, ig_user_id: str, urls: list[str], text: str,
                   sleep: Callable[[float], None], clock: Callable[[], float]) -> str:
    """A picture's container, or a carousel's: one per slide, then the CAROUSEL one."""
    if len(urls) == 1:
        return _ok(client.post(f"{GRAPH}/{ig_user_id}/media", data={
            "image_url": urls[0], "caption": text, "access_token": token}), "creating the picture post")["id"]
    children = []
    for k, url in enumerate(urls[:10], 1):
        child = _ok(client.post(f"{GRAPH}/{ig_user_id}/media", data={
            "image_url": url, "is_carousel_item": "true", "access_token": token}), f"adding slide {k}")["id"]
        _wait_until_processed(client, token, child, sleep, clock)
        children.append(child)
    return _ok(client.post(f"{GRAPH}/{ig_user_id}/media", data={
        "media_type": "CAROUSEL", "children": ",".join(children), "caption": text, "access_token": token}),
        "creating the carousel")["id"]


def _status(client: httpx.Client, token: str, container: str) -> str:
    body = _ok(client.get(f"{GRAPH}/{container}",
                          params={"fields": "status_code,status", "access_token": token}),
               "checking the reel")
    return str(body.get("status_code") or "")


def _wait_until_processed(client: httpx.Client, token: str, container: str,
                          sleep: Callable[[float], None], clock: Callable[[], float]) -> None:
    deadline = clock() + PROCESS_TIMEOUT_S
    while True:
        status = _status(client, token, container)
        if status == "FINISHED":
            return
        if status == "ERROR":
            body = _ok(client.get(f"{GRAPH}/{container}", params={"fields": "status",
                                                                  "access_token": token}), "")
            raise Rejected(f"Instagram could not process the video: {body.get('status') or 'unknown error'}")
        if status == "EXPIRED" or clock() > deadline:
            raise PublishError("Instagram took too long to process the video")
        sleep(POLL_S)


def _find_published(client: httpx.Client, token: str, ig_user_id: str, since: datetime) -> dict:
    """The post a container became, when an earlier run published it but died
    before recording it: the newest reel on the account since the attempt began."""
    body = _ok(client.get(f"{GRAPH}/{ig_user_id}/media", params={
        "fields": "id,permalink,timestamp", "limit": 10, "access_token": token}), "listing recent posts")
    for m in body.get("data") or []:
        ts = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        if ts >= since:
            return {"remote_id": m["id"], "remote_url": m.get("permalink"), "privacy": "public",
                    "response": {"id": m["id"], "recovered": True}}
    raise PublishError("Instagram reports the reel as published, but it is not on the account yet")


def _result(client: httpx.Client, token: str, media_id: str) -> dict:
    try:
        link = _ok(client.get(f"{GRAPH}/{media_id}", params={"fields": "permalink",
                                                             "access_token": token}), "").get("permalink")
    except (PublishError, Rejected, AuthExpired):
        link = None                 # it is posted; the link is a nicety
    return {"remote_id": media_id, "remote_url": link, "privacy": "public",
            "response": {"id": media_id}}


def _ok(r: httpx.Response, doing: str) -> dict:
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    if r.status_code == 200 and "error" not in body:
        return body
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = err.get("code")
    message = err.get("error_user_msg") or err.get("message") or f"HTTP {r.status_code}"
    if code == 190 or r.status_code == 401:
        raise AuthExpired("Instagram access has expired or was removed")
    if r.status_code >= 500 or r.status_code == 429 or code in (1, 2, 4, 17, 32, 341, 613):
        raise PublishError(f"{doing}: {message}")
    raise Rejected(f"Instagram refused {doing or 'the request'}: {message}")
