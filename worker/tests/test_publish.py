"""Posting to YouTube and Instagram, against fake APIs (httpx.MockTransport).

The platform modules are driven directly for their upload protocols — above all
resuming after a crash without posting twice. Then the handler runs end to end
through the real queue and schema, with only storage and HTTP faked.

    worker/.venv/Scripts/python -m pytest worker/tests/test_publish.py -q
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx
import pytest
from corpus import db
from corpus.crypto import encrypt
from corpus.handlers import publish_post
from corpus.publish import instagram, youtube
from corpus.runner import Runner

VIDEO = bytes(range(256)) * 100          # 25,600 bytes
SESSION = "https://upload.test/session/1"


def client(fake) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(fake))


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "reel.mp4"
    path.write_bytes(VIDEO)
    return path


@pytest.fixture(autouse=True)
def google_keys(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")


# ── YouTube ───────────────────────────────────────────────────────────────────

class FakeYouTube:
    """Token refresh, one resumable session, chunked PUTs. `have` bytes are already
    there from an earlier run; `complete` means that run finished the video."""

    def __init__(self, *, have: int = 0, complete: bool = False, error: str | None = None,
                 token_error: str | None = None):
        self.received = bytearray(VIDEO[:have])
        self.complete, self.error, self.token_error = complete, error, token_error
        self.requests: list[httpx.Request] = []
        self.sessions_opened = 0
        self.meta: dict = {}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        url = str(req.url)
        if url.startswith(youtube.TOKEN_URL):
            if self.token_error:
                return httpx.Response(400, json={"error": self.token_error})
            return httpx.Response(200, json={"access_token": "at"})
        if url.startswith(youtube.UPLOAD_URL):
            if self.error:
                return httpx.Response(403, json={"error": {"message": "no", "errors": [{"reason": self.error}]}})
            self.sessions_opened += 1
            self.meta = json.loads(req.content)
            return httpx.Response(200, headers={"Location": SESSION})
        if url.endswith("/old"):
            return httpx.Response(404)
        assert url == SESSION and req.headers["Authorization"] == "Bearer at"
        sent = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", req.headers["Content-Range"])
        if sent:
            assert int(sent[1]) == len(self.received), "a chunk must start where the last one ended"
            self.received += req.content
        if self.complete or len(self.received) == len(VIDEO):
            self.complete = True
            return httpx.Response(200, json={"id": "vid123", "status": {"privacyStatus": "private"}})
        return httpx.Response(308, headers={"Range": f"bytes=0-{len(self.received) - 1}"} if self.received else {})


def _yt(fake, video, attempt, saved=None):
    return youtube.publish(client(fake), refresh_token="rt", path=video,
                           meta=youtube.metadata("Why <the> sky", "Blue light scatters.", ["#sky", "#science"],
                                                 "28", "public"),
                           attempt=attempt, save=lambda **f: (saved if saved is not None else []).append(
                               (f, len(fake.received))))


def test_youtube_saves_the_session_before_any_bytes_then_uploads_in_chunks(video, monkeypatch):
    monkeypatch.setattr(youtube, "CHUNK", 10_000)
    fake, saved = FakeYouTube(), []
    out = _yt(fake, video, {}, saved)
    assert saved == [({"upload_session_uri": SESSION, "state": "uploading"}, 0)]
    assert bytes(fake.received) == VIDEO
    assert [r.headers["Content-Range"] for r in fake.requests if r.method == "PUT"] == [
        "bytes 0-9999/25600", "bytes 10000-19999/25600", "bytes 20000-25599/25600"]
    assert out == {"remote_id": "vid123", "remote_url": "https://youtube.com/shorts/vid123", "privacy": "private",
                   "response": {"id": "vid123", "status": {"privacyStatus": "private"}}}
    assert fake.meta["snippet"] == {"title": "Why the sky", "tags": ["sky", "science"], "categoryId": "28",
                                    "description": "Blue light scatters.\n\n#sky #science"}
    assert fake.meta["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False,
                                   "containsSyntheticMedia": True}


def test_youtube_resumes_where_the_last_run_stopped(video, monkeypatch):
    monkeypatch.setattr(youtube, "CHUNK", 10_000)
    fake = FakeYouTube(have=10_000)
    out = _yt(fake, video, {"upload_session_uri": SESSION})
    assert fake.sessions_opened == 0 and bytes(fake.received) == VIDEO and out["remote_id"] == "vid123"


def test_youtube_records_an_upload_that_had_finished_instead_of_repeating_it(video):
    fake = FakeYouTube(have=len(VIDEO), complete=True)
    out = _yt(fake, video, {"upload_session_uri": SESSION})
    puts = [r for r in fake.requests if r.method == "PUT"]
    assert [p.headers["Content-Range"] for p in puts] == [f"bytes */{len(VIDEO)}"]
    assert fake.sessions_opened == 0 and out["remote_id"] == "vid123"


def test_youtube_starts_over_only_when_it_has_forgotten_the_session(video):
    fake, saved = FakeYouTube(), []
    out = _yt(fake, video, {"upload_session_uri": "https://upload.test/session/old"}, saved)
    assert fake.sessions_opened == 1 and saved[0][0]["upload_session_uri"] == SESSION
    assert out["remote_id"] == "vid123"


def test_youtube_quota_and_revoked_access_are_told_apart(video):
    with pytest.raises(youtube.QuotaExceeded):
        _yt(FakeYouTube(error="quotaExceeded"), video, {})
    with pytest.raises(youtube.Rejected):
        _yt(FakeYouTube(error="forbidden"), video, {})
    with pytest.raises(youtube.AuthExpired):
        _yt(FakeYouTube(token_error="invalid_grant"), video, {})


# ── Instagram ─────────────────────────────────────────────────────────────────

class FakeInstagram:
    """Container from a video_url → processing → publish. `container` fixes the status
    an earlier run's container reports; `statuses` are replies after creating one."""

    def __init__(self, *, statuses=("IN_PROGRESS", "FINISHED"), container: str | None = None,
                 media: list | None = None, error_code: int | None = None):
        self.statuses, self.container, self.media = list(statuses), container, media or []
        self.error_code = error_code
        self.created = self.published = 0
        self.caption = self.video_url = ""

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        form = parse_qs(req.content.decode()) if req.method == "POST" else {}
        if self.error_code:
            return httpx.Response(400, json={"error": {"message": "bad", "code": self.error_code}})
        if req.method == "POST" and path == "/v23.0/178/media":
            if "video_url" not in form:      # what the real API said to upload_type=resumable
                return httpx.Response(400, json={"error": {"message": "The parameter video_url is required",
                                                           "code": 100}})
            assert form["media_type"] == ["REELS"] and "upload_type" not in form
            self.created += 1
            self.caption, self.video_url = form["caption"][0], form["video_url"][0]
            return httpx.Response(200, json={"id": "c1"})
        if req.method == "GET" and path == "/v23.0/c1":
            status = self.container or (self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0])
            return httpx.Response(200, json={"status_code": status, "status": "Error: too short"})
        if req.method == "POST" and path == "/v23.0/178/media_publish":
            assert form["creation_id"] == ["c1"]
            self.published += 1
            return httpx.Response(200, json={"id": "m1"})
        if req.method == "GET" and path == "/v23.0/m1":
            return httpx.Response(200, json={"permalink": "https://www.instagram.com/reel/abc/"})
        if req.method == "GET" and path == "/v23.0/178/media":
            return httpx.Response(200, json={"data": self.media})
        raise AssertionError(f"unexpected {req.method} {req.url}")


LINK = "https://r2.test/u/p/final.mp4?X-Amz-Signature=abc"


def _ig(fake, video, attempt, saved=None):
    return instagram.publish(client(fake), token="tok", ig_user_id="178", video_url=LINK, caption="A reel",
                             attempt=attempt, save=lambda **f: (saved if saved is not None else []).append(f),
                             sleep=lambda s: None)


def test_instagram_fetches_the_link_waits_for_processing_then_publishes(video):
    fake, saved = FakeInstagram(), []
    out = _ig(fake, video, {}, saved)
    assert saved == [{"upload_session_uri": "ig-container:c1", "state": "uploading"}, {"state": "uploaded"}]
    assert fake.video_url == LINK and fake.published == 1 and fake.caption == "A reel"
    assert out["remote_id"] == "m1" and out["remote_url"] == "https://www.instagram.com/reel/abc/"


def test_instagram_publishes_a_processed_container_without_uploading_again(video):
    fake = FakeInstagram(container="FINISHED")
    out = _ig(fake, video, {"upload_session_uri": "ig-container:c1", "state": "uploaded"})
    assert fake.created == 0 and fake.published == 1 and out["remote_id"] == "m1"


def test_instagram_records_a_reel_an_earlier_run_published(video):
    began = datetime(2026, 10, 16, 12, 59, tzinfo=timezone.utc)
    fake = FakeInstagram(container="PUBLISHED", media=[
        {"id": "m9", "permalink": "https://www.instagram.com/reel/m9/", "timestamp": "2026-10-16T13:00:05+0000"},
        {"id": "m0", "permalink": "https://www.instagram.com/reel/m0/", "timestamp": "2026-10-01T09:00:00+0000"}])
    out = _ig(fake, video, {"upload_session_uri": "ig-container:c1", "state": "uploaded", "created_at": began})
    assert fake.published == 0 and out["remote_id"] == "m9"


def test_instagram_failures_are_told_apart(video):
    with pytest.raises(instagram.Rejected, match="too short"):
        _ig(FakeInstagram(statuses=("ERROR",)), video, {})
    with pytest.raises(instagram.AuthExpired):
        _ig(FakeInstagram(error_code=190), video, {})
    with pytest.raises(instagram.PublishError):
        _ig(FakeInstagram(error_code=4), video, {})                     # rate limited


def test_instagram_caption_keeps_to_the_limits():
    text = instagram.caption("Title", "x" * 3000, [f"#t{i}" for i in range(40)])
    assert len(text) == 2200 and text.startswith("Title\n\n")
    assert instagram.caption("T", "D", [f"#t{i}" for i in range(40)]).count("#") == 30


# ── the handler, through the real queue ───────────────────────────────────────

@pytest.fixture
def owner():
    with db.conn() as c:
        c.execute("delete from jobs where lane = 'publish' and state in ('queued','claimed')")
        yield c


@pytest.fixture
def user(owner):
    uid = f"test-{uuid.uuid4().hex[:10]}"
    owner.execute('insert into "user" (id, name, email, "emailVerified") values (%s,%s,%s,true)',
                  (uid, uid, f"{uid}@example.test"))
    owner.execute("insert into app_settings (user_id, youtube_privacy) values (%s, 'unlisted')", (uid,))
    yield uid
    owner.execute('delete from "user" where id = %s', (uid,))


def _ready_post(owner, uid) -> str:
    ch = owner.execute("insert into channels (user_id, name) values (%s, %s) returning id",
                       (uid, f"ch-{uuid.uuid4().hex[:6]}")).fetchone()["id"]
    owner.execute("""insert into channel_accounts (user_id, channel_id, platform, external_id, token_ciphertext)
                     values (%s, %s, 'youtube', 'UC1', %s)""", (uid, ch, encrypt("rt")))
    slot = date(2031, 1, 1) + timedelta(days=uuid.uuid4().int % 3000)
    pid = owner.execute("insert into posts (user_id, channel_id, topic, slot_date) values (%s, %s, 'sky', %s) "
                        "returning id", (uid, ch, slot)).fetchone()["id"]
    sid = owner.execute("""insert into scripts (post_id, version, state, title, description, hashtags)
                           values (%s, 1, 'approved', 'Why is the sky blue?', 'Scattering.', '{#sky}')
                           returning id""", (pid,)).fetchone()["id"]
    owner.execute("""update posts set status = 'ready', approved_script_id = %s, final_key = 'u/p/final.mp4',
                                      final_sha256 = %s where id = %s""",
                  (sid, hashlib.sha256(VIDEO).hexdigest(), pid))
    return pid


def _request(owner, uid, pid, platforms=("youtube",)):
    owner.execute("select set_config('app.user_id', %s, false)", (uid,))
    try:
        owner.execute("select api.request_publish(%s, %s::text[])", (pid, list(platforms)))
    finally:
        owner.execute("select set_config('app.user_id', '', false)")


def _status(owner, pid) -> str:
    return owner.execute("select status from posts where id = %s", (pid,)).fetchone()["status"]


@pytest.fixture
def fake_http(monkeypatch, video):
    """Route the handler's HTTP to a fake and its download to the test video."""
    real = httpx.Client

    def install(fake):
        monkeypatch.setattr(publish_post.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(fake)))
        monkeypatch.setattr(publish_post, "_download", lambda post: video)
        return fake
    return install


def test_handler_posts_once_and_the_post_follows(owner, user, fake_http):
    fake = fake_http(FakeYouTube())
    pid = _ready_post(owner, user)
    _request(owner, user, pid)
    assert _status(owner, pid) == "scheduled"

    assert Runner("publish", {"publish_post": publish_post.HANDLER}).tick()
    job = owner.execute("select state, error from jobs where dedupe_key = %s", (f"publish:{pid}:youtube",)).fetchone()
    assert job["state"] == "succeeded", job["error"]
    attempt = owner.execute("select state, remote_id, remote_url, privacy from publish_attempts where post_id = %s",
                            (pid,)).fetchone()
    assert attempt == {"state": "live", "remote_id": "vid123", "remote_url": "https://youtube.com/shorts/vid123",
                       "privacy": "private"}
    assert fake.meta["status"]["privacyStatus"] == "unlisted"             # the owner's setting
    assert _status(owner, pid) == "published"
    assert owner.execute("select reason from post_events where post_id = %s and reason = 'posted to YouTube'",
                         (pid,)).fetchone()


def test_handler_posts_to_instagram_from_a_signed_link(owner, user, fake_http, monkeypatch):
    fake = fake_http(FakeInstagram())
    monkeypatch.setattr(publish_post.storage, "signed_url", lambda key, seconds: f"{LINK}&key={key}&ttl={seconds}")
    monkeypatch.setattr(publish_post.instagram, "POLL_S", 0)
    pid = _ready_post(owner, user)
    owner.execute("""insert into channel_accounts (user_id, channel_id, platform, external_id, token_ciphertext,
                                                   token_expires_at)
                     select %s, channel_id, 'instagram', '178', %s, now() + interval '50 days'
                       from posts where id = %s""", (user, encrypt("tok"), pid))
    _request(owner, user, pid, ("instagram",))
    assert Runner("publish", {"publish_post": publish_post.HANDLER}).tick()
    job = owner.execute("select state, error from jobs where dedupe_key = %s", (f"publish:{pid}:instagram",)).fetchone()
    assert job["state"] == "succeeded", job["error"]
    assert fake.video_url == f"{LINK}&key=u/p/final.mp4&ttl=7200"
    assert fake.caption == "Why is the sky blue?\n\nScattering.\n\n#sky"
    assert owner.execute("select remote_url from publish_attempts where post_id = %s",
                         (pid,)).fetchone()["remote_url"] == "https://www.instagram.com/reel/abc/"
    assert _status(owner, pid) == "published"


def test_handler_reports_expired_access_and_frees_the_post(owner, user, fake_http):
    fake_http(FakeYouTube(token_error="invalid_grant"))
    pid = _ready_post(owner, user)
    _request(owner, user, pid)
    Runner("publish", {"publish_post": publish_post.HANDLER}).tick()
    job = owner.execute("select state, error from jobs where dedupe_key = %s", (f"publish:{pid}:youtube",)).fetchone()
    assert job["state"] == "dead" and "reconnect YouTube" in job["error"]["message"]
    assert owner.execute("select status from channel_accounts where channel_id = (select channel_id from posts "
                         "where id = %s)", (pid,)).fetchone()["status"] == "expired"
    assert owner.execute("select state from publish_attempts where post_id = %s",
                         (pid,)).fetchone()["state"] == "failed"       # nothing was sent
    assert _status(owner, pid) == "ready"


def test_handler_keeps_a_half_done_upload_open_for_the_next_run(owner, user, fake_http, monkeypatch):
    fake = fake_http(FakeYouTube())
    monkeypatch.setattr(youtube, "CHUNK", 10_000)
    real = FakeYouTube.__call__

    def drop_second_chunk(self, req):
        if req.method == "PUT" and req.headers.get("Content-Range", "").startswith("bytes 10000-"):
            raise httpx.ConnectError("connection reset")
        return real(self, req)
    monkeypatch.setattr(FakeYouTube, "__call__", drop_second_chunk)
    pid = _ready_post(owner, user)
    _request(owner, user, pid)
    Runner("publish", {"publish_post": publish_post.HANDLER}).tick()
    job = owner.execute("select state from jobs where dedupe_key = %s", (f"publish:{pid}:youtube",)).fetchone()
    attempt = owner.execute("select state, upload_session_uri from publish_attempts where post_id = %s",
                            (pid,)).fetchone()
    assert job["state"] == "queued" and attempt == {"state": "uploading", "upload_session_uri": SESSION}
    assert _status(owner, pid) == "scheduled"

    monkeypatch.setattr(FakeYouTube, "__call__", real)                    # the network is back
    owner.execute("update jobs set not_before = now() where dedupe_key = %s", (f"publish:{pid}:youtube",))
    Runner("publish", {"publish_post": publish_post.HANDLER}).tick()
    assert fake.sessions_opened == 1 and bytes(fake.received) == VIDEO   # resumed, not restarted
    assert _status(owner, pid) == "published"


def test_automatic_posts_schedule_themselves_on_their_connected_platforms(owner, user):
    from corpus import auto
    owner.execute("update app_settings set pipeline_mode = 'auto' where user_id = %s", (user,))
    pid = _ready_post(owner, user)                                       # YouTube connected, Instagram not
    owner.execute("update posts set platforms = '{youtube,instagram}', publish_at = now() + interval '2 hours' "
                  "where id = %s", (pid,))
    assert auto.request_publish(pid, log=lambda m: None)
    jobs = owner.execute("""select j.payload->>'platform' as platform, j.not_before = p.publish_at as on_time
                              from jobs j join posts p on p.id = j.post_id
                             where j.post_id = %s and j.lane = 'publish'""", (pid,)).fetchall()
    assert jobs == [{"platform": "youtube", "on_time": True}] and _status(owner, pid) == "scheduled"
    manual = _ready_post(owner, user)
    owner.execute("update posts set pipeline_mode = 'manual' where id = %s", (manual,))
    assert not auto.request_publish(manual, log=lambda m: None)          # manual posts wait for a click
