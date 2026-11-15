"""Instagram: a Reel, a carousel or a picture, through one of two Instagram APIs.

Instagram Login (graph.instagram.com, GRAPH) is what every account starts on; its
tokens are renewed by `refresh`. Unified Login (graph.facebook.com, GRAPH_UNIFIED)
is the newer one: it alone offers the trending Audio API, and its tokens are not
renewed here. An account's `api` column says which one it is connected through;
`host()` maps that to the base URL every call below is built on.

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

import json
import time
from datetime import datetime
from typing import Callable

import httpx

GRAPH = "https://graph.instagram.com/v23.0"
GRAPH_UNIFIED = "https://graph.facebook.com/v27.0"
CONTAINER = "ig-container:"        # upload_session_uri prefix on the attempt
PROCESS_TIMEOUT_S = 15 * 60
POLL_S = 5


class AuthExpired(Exception):
    """The token is invalid or expired: the owner has to reconnect Instagram."""


class Rejected(Exception):
    """Instagram refused the video or the request; retrying will not help."""


class PublishError(Exception):
    """Transient (rate limit, server error, slow processing): worth another run."""


def host(api: str | None) -> str:
    """The Graph base URL for an account connected through `api` (channel_accounts.api)."""
    return GRAPH_UNIFIED if api == "unified" else GRAPH


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
            clock: Callable[[], float] = time.monotonic, image_urls: list[str] | None = None,
            cover_url: str | None = None, graph: str = GRAPH,
            audio: dict | None = None, fallback_video_url: str | None = None) -> dict:
    """Post the video at `video_url` as a Reel — or `image_urls` as a carousel (or,
    one of them, a picture) — and return what to record on the attempt. `graph` is
    the account's host (see host()). `audio` is the trending song for a Reel
    ({audio_id, audio_volume, video_volume}); if Instagram refuses it, or cannot
    process the video with it, the Reel goes out again from `fallback_video_url`
    without the song, and the result says so in `audio_dropped`."""
    container = _container_of(attempt)
    if container:
        status = _status(client, token, container, graph)
        if status == "PUBLISHED":
            return _find_published(client, token, ig_user_id, attempt["created_at"], graph)
        if status != "FINISHED":
            container = None        # never published; Instagram drops it within a day
    resumed = container is not None  # built by an earlier run, which may have left the song out
    dropped = None
    if image_urls:
        audio = None                # songs are for Reels only
    if not container and image_urls:
        container = _create_images(client, token, ig_user_id, image_urls, caption, sleep, clock, graph)
        save(upload_session_uri=CONTAINER + container, state="uploading")
        _wait_until_processed(client, token, container, sleep, clock, graph)
    elif not container:
        try:
            container = _start_reel(client, token, ig_user_id, video_url or "", caption, cover_url, audio,
                                    save, sleep, clock, graph)
        except Rejected as e:
            if not audio:
                raise
            dropped = str(e)       # the Reel without its song; a refused video still propagates
            container = _start_reel(client, token, ig_user_id, fallback_video_url or video_url or "", caption,
                                    cover_url, None, save, sleep, clock, graph)

    save(state="uploaded")          # from here on, the post may be live
    media = _ok(client.post(f"{graph}/{ig_user_id}/media_publish",
                            data={"creation_id": container, "access_token": token}),
                "publishing the post")
    out = _result(client, token, media["id"], graph)
    if dropped:
        out["audio_dropped"] = dropped
    elif audio and not resumed:
        out["audio_id"] = audio["audio_id"]
    return out


def _container_of(attempt: dict) -> str | None:
    uri = attempt.get("upload_session_uri") or ""
    return uri[len(CONTAINER):] if uri.startswith(CONTAINER) else None


def comment(client: httpx.Client, *, token: str, media_id: str, text: str, graph: str = GRAPH) -> str:
    """The first comment under a published post (instagram_business_manage_comments)."""
    if not text:
        return "none"
    r = client.post(f"{graph}/{media_id}/comments", data={"message": text, "access_token": token})
    if r.status_code == 200:
        return "posted " + str((r.json() or {}).get("id", ""))
    err = (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get("error") or {}
    return f"not posted: {(err.get('message') or f'HTTP {r.status_code}')[:200]}"


def _start_reel(client: httpx.Client, token: str, ig_user_id: str, video_url: str, text: str,
                cover_url: str | None, audio: dict | None, save: Callable[..., object],
                sleep: Callable[[float], None], clock: Callable[[], float], graph: str) -> str:
    """A new REELS container, saved on the attempt, once Instagram has processed it."""
    container = _create(client, token, ig_user_id, video_url, text, cover_url, graph, audio)
    save(upload_session_uri=CONTAINER + container, state="uploading")
    _wait_until_processed(client, token, container, sleep, clock, graph)
    return container


def _create(client: httpx.Client, token: str, ig_user_id: str, video_url: str, text: str,
            cover_url: str | None = None, graph: str = GRAPH, audio: dict | None = None) -> str:
    data = {"media_type": "REELS", "video_url": video_url, "caption": text, "share_to_feed": "true",
            "access_token": token}
    if cover_url:
        data["cover_url"] = cover_url           # the reel's cover in the grid and feed
    if audio:
        data["audio_configuration"] = json.dumps(audio)    # the trending song (Audio API)
    return _ok(client.post(f"{graph}/{ig_user_id}/media", data=data), "creating the reel")["id"]


def _create_images(client: httpx.Client, token: str, ig_user_id: str, urls: list[str], text: str,
                   sleep: Callable[[float], None], clock: Callable[[], float], graph: str) -> str:
    """A picture's container, or a carousel's: one per slide, then the CAROUSEL one."""
    if len(urls) == 1:
        return _ok(client.post(f"{graph}/{ig_user_id}/media", data={
            "image_url": urls[0], "caption": text, "access_token": token}), "creating the picture post")["id"]
    children = []
    for k, url in enumerate(urls[:10], 1):
        child = _ok(client.post(f"{graph}/{ig_user_id}/media", data={
            "image_url": url, "is_carousel_item": "true", "access_token": token}), f"adding slide {k}")["id"]
        _wait_until_processed(client, token, child, sleep, clock, graph)
        children.append(child)
    return _ok(client.post(f"{graph}/{ig_user_id}/media", data={
        "media_type": "CAROUSEL", "children": ",".join(children), "caption": text, "access_token": token}),
        "creating the carousel")["id"]


def _status(client: httpx.Client, token: str, container: str, graph: str) -> str:
    body = _ok(client.get(f"{graph}/{container}",
                          params={"fields": "status_code,status", "access_token": token}),
               "checking the reel")
    return str(body.get("status_code") or "")


def _wait_until_processed(client: httpx.Client, token: str, container: str,
                          sleep: Callable[[float], None], clock: Callable[[], float], graph: str) -> None:
    deadline = clock() + PROCESS_TIMEOUT_S
    while True:
        status = _status(client, token, container, graph)
        if status == "FINISHED":
            return
        if status == "ERROR":
            body = _ok(client.get(f"{graph}/{container}", params={"fields": "status",
                                                                  "access_token": token}), "")
            raise Rejected(f"Instagram could not process the video: {body.get('status') or 'unknown error'}")
        if status == "EXPIRED" or clock() > deadline:
            raise PublishError("Instagram took too long to process the video")
        sleep(POLL_S)


def _find_published(client: httpx.Client, token: str, ig_user_id: str, since: datetime, graph: str) -> dict:
    """The post a container became, when an earlier run published it but died
    before recording it: the newest reel on the account since the attempt began."""
    body = _ok(client.get(f"{graph}/{ig_user_id}/media", params={
        "fields": "id,permalink,timestamp", "limit": 10, "access_token": token}), "listing recent posts")
    for m in body.get("data") or []:
        ts = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        if ts >= since:
            return {"remote_id": m["id"], "remote_url": m.get("permalink"), "privacy": "public",
                    "response": {"id": m["id"], "recovered": True}}
    raise PublishError("Instagram reports the reel as published, but it is not on the account yet")


def _result(client: httpx.Client, token: str, media_id: str, graph: str) -> dict:
    try:
        link = _ok(client.get(f"{graph}/{media_id}", params={"fields": "permalink",
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
