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
                 media: list | None = None, error_code: int | None = None, version: str = "v23.0",
                 refuse_audio: bool = False, audio_breaks_processing: bool = False,
                 audio_list: list | None = None, choice: str | None = None):
        self.statuses, self.container, self.media = list(statuses), container, media or []
        self.error_code, self.version = error_code, version
        self.refuse_audio, self.audio_breaks_processing = refuse_audio, audio_breaks_processing
        self.audio_list, self.audio_searches = audio_list, 0
        self.choice, self.decisions = choice, 0     # the song the Decisions API answers with
        self.created = self.published = 0
        self.caption = self.video_url = self.audio = ""
        self.with_audio: dict[str, bool] = {}     # container id → created with a song?
        self.published_id = None

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.url.host == "api.openai.com":
            assert path == "/v1/decisions"
            self.decisions += 1
            return httpx.Response(200, json={"answers": [{"type": "choice", "name": "song",
                                                          "choice": self.choice, "confidence": 0.9}],
                                             "usage": {"input_tokens": 500}})
        form = parse_qs(req.content.decode()) if req.method == "POST" else {}
        if self.error_code:
            return httpx.Response(400, json={"error": {"message": "bad", "code": self.error_code}})
        if req.method == "POST" and path == f"/{self.version}/178/media":
            if "video_url" not in form:      # what the real API said to upload_type=resumable
                return httpx.Response(400, json={"error": {"message": "The parameter video_url is required",
                                                           "code": 100}})
            assert form["media_type"] == ["REELS"] and "upload_type" not in form
            self.audio = form.get("audio_configuration", [""])[0]
            self.caption, self.video_url = form["caption"][0], form["video_url"][0]
            self.created += 1
            cid = f"c{self.created}"
            self.with_audio[cid] = bool(self.audio)
            if self.refuse_audio and self.audio:
                return httpx.Response(400, json={"error": {"message": "Invalid audio", "code": 100}})
            return httpx.Response(200, json={"id": cid})
        if req.method == "GET" and path.startswith(f"/{self.version}/c"):
            cid = path.rsplit("/", 1)[1]
            if self.audio_breaks_processing and self.with_audio.get(cid):
                return httpx.Response(200, json={"status_code": "ERROR", "status": "Error: audio unavailable"})
            status = self.container or (self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0])
            return httpx.Response(200, json={"status_code": status, "status": "Error: too short"})
        if req.method == "POST" and path == f"/{self.version}/178/media_publish":
            assert form["creation_id"][0] in ("c1", "c2")
            self.published_id = form["creation_id"][0]
            self.published += 1
            return httpx.Response(200, json={"id": "m1"})
        if req.method == "GET" and path == f"/{self.version}/m1":
            return httpx.Response(200, json={"permalink": "https://www.instagram.com/reel/abc/"})
        if req.method == "GET" and path == f"/{self.version}/178/media":
            return httpx.Response(200, json={"data": self.media})
        if req.method == "GET" and path == f"/{self.version}/ig_audio":
            self.audio_searches += 1
            return httpx.Response(200, json={"audio": self.audio_list or []})
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


def test_instagram_host_follows_the_account_api():
    assert instagram.host("unified") == "https://graph.facebook.com/v27.0"
    assert instagram.host("instagram_login") == instagram.GRAPH
    assert instagram.host(None) == instagram.GRAPH


def test_instagram_publishes_through_the_unified_host(video):
    fake = FakeInstagram(version="v27.0")
    out = instagram.publish(client(fake), token="tok", ig_user_id="178", video_url=LINK, caption="A reel",
                            attempt={}, save=lambda **f: None, sleep=lambda s: None,
                            graph=instagram.GRAPH_UNIFIED)
    assert out["remote_id"] == "m1" and fake.published == 1


SONG = {"audio_id": "587", "audio_volume": 25, "video_volume": 100}


def test_instagram_attaches_the_song_to_the_reel(video):
    fake = FakeInstagram()
    out = instagram.publish(client(fake), token="tok", ig_user_id="178", video_url=LINK, caption="A reel",
                            attempt={}, save=lambda **f: None, sleep=lambda s: None, audio=SONG)
    assert json.loads(fake.audio) == {"audio_id": "587", "audio_volume": 25, "video_volume": 100}
    assert out["audio_id"] == "587" and "audio_dropped" not in out


def test_instagram_posts_without_the_song_when_it_is_refused(video):
    fake = FakeInstagram(refuse_audio=True)
    out = instagram.publish(client(fake), token="tok", ig_user_id="178", video_url=LINK + "&ig", caption="A reel",
                            attempt={}, save=lambda **f: None, sleep=lambda s: None,
                            audio=SONG, fallback_video_url=LINK)
    assert out["remote_id"] == "m1" and "audio" in out["audio_dropped"]
    assert fake.video_url == LINK and fake.audio == ""        # second container: bed version, no song
    assert fake.published_id == "c2"


def test_instagram_posts_without_the_song_when_processing_fails_on_it(video):
    fake = FakeInstagram(audio_breaks_processing=True)
    out = instagram.publish(client(fake), token="tok", ig_user_id="178", video_url=LINK + "&ig", caption="A reel",
                            attempt={}, save=lambda **f: None, sleep=lambda s: None,
                            audio=SONG, fallback_video_url=LINK)
    assert out["remote_id"] == "m1" and out["audio_dropped"] and fake.created == 2 and fake.audio == ""
    assert fake.published_id == "c2"


def test_instagram_saves_the_fallback_container_over_the_refused_one(video):
    fake, saved = FakeInstagram(refuse_audio=True), []
    instagram.publish(client(fake), token="tok", ig_user_id="178", video_url=LINK, caption="A reel",
                      attempt={}, save=lambda **f: saved.append(f), sleep=lambda s: None,
                      audio=SONG, fallback_video_url=LINK)
    assert saved[0] == {"upload_session_uri": "ig-container:c2", "state": "uploading"}
    assert saved[-1] == {"state": "uploaded"}


def _due_unified(owner, user, pid):
    """An account due for renewal by its dates — but on Unified Login."""
    owner.execute("""insert into channel_accounts (user_id, channel_id, platform, external_id, token_ciphertext,
                                                   token_expires_at, api, updated_at)
                     select %s, channel_id, 'instagram', '178', %s, now() + interval '2 days', 'unified',
                            now() - interval '3 days' from posts where id = %s""", (user, encrypt("tok"), pid))
    return owner.execute("select * from channel_accounts where external_id = '178'").fetchone()


def test_upkeep_never_renews_a_unified_token(owner, user, monkeypatch):
    _due_unified(owner, user, _ready_post(owner, user))
    calls = []
    monkeypatch.setattr(publish_post.instagram, "refresh", lambda *a: calls.append(a) or ("new", 5_184_000))
    monkeypatch.setattr(publish_post, "_last_upkeep", -1e18)      # upkeep's hourly gate is open
    monkeypatch.setattr(publish_post, "_last_stats", 1e18)        # no stats round
    publish_post.upkeep()
    assert calls == []
    assert owner.execute("select status from channel_accounts where external_id = '178'").fetchone()["status"] == "connected"


def test_publishing_never_renews_a_unified_token(owner, user, monkeypatch):
    acc = _due_unified(owner, user, _ready_post(owner, user))
    calls = []
    monkeypatch.setattr(publish_post.instagram, "refresh", lambda *a: calls.append(a) or ("new", 5_184_000))
    assert publish_post._instagram_token(httpx.Client(), acc) == "tok" and calls == []


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


def _unified(owner, user, pid):
    owner.execute("""insert into channel_accounts (user_id, channel_id, platform, external_id, token_ciphertext, api)
                     select %s, channel_id, 'instagram', '178', %s, 'unified' from posts where id = %s""",
                  (user, encrypt("tok"), pid))
    owner.execute("update posts set final_ig_key = 'u/p/final.ig.mp4', credits = %s where id = %s",
                  (json.dumps(["Music: “x” by y (Freesound, CC0)"]), pid))


LISTED = {"audio_id": "587", "title": "Dil", "display_artist": "A", "duration_in_ms": 30000}


def _publish_unified(owner, user, fake_http, monkeypatch, fake, ig_music=None, narrated=False):
    fake_http(fake)
    monkeypatch.setattr(publish_post.storage, "signed_url", lambda key, seconds: f"{LINK}&key={key}")
    monkeypatch.setattr(publish_post.instagram, "POLL_S", 0)
    pid = _ready_post(owner, user)
    _unified(owner, user, pid)
    if narrated:
        owner.execute("update posts set audio_source = 'kokoro' where id = %s", (pid,))
    if ig_music is not None:
        owner.execute("update posts set ig_music = %s where id = %s", (json.dumps(ig_music), pid))
    _request(owner, user, pid, ("instagram",))
    assert Runner("publish", {"publish_post": publish_post.HANDLER}).tick()
    job = owner.execute("select state, error from jobs where dedupe_key = %s", (f"publish:{pid}:instagram",)).fetchone()
    assert job["state"] == "succeeded", job["error"]
    return pid


def test_handler_attaches_a_picked_song_from_the_music_free_copy(owner, user, fake_http, monkeypatch):
    fake = FakeInstagram(version="v27.0", audio_list=[LISTED])
    pid = _publish_unified(owner, user, fake_http, monkeypatch, fake)
    assert fake.video_url.endswith("key=u/p/final.ig.mp4")
    assert json.loads(fake.audio) == {"audio_id": "587", "audio_volume": 100, "video_volume": 40}  # not narrated
    assert "Freesound" not in fake.caption
    saved = owner.execute("select ig_music from posts where id = %s", (pid,)).fetchone()["ig_music"]
    assert saved["audio_id"] == "587" and saved["picked_by"] == "only"


def test_handler_keeps_the_bed_version_when_instagram_has_no_songs(owner, user, fake_http, monkeypatch):
    fake = FakeInstagram(version="v27.0", audio_list=[])
    pid = _publish_unified(owner, user, fake_http, monkeypatch, fake)
    assert fake.video_url.endswith("key=u/p/final.mp4") and fake.audio == ""
    assert owner.execute("select ig_music from posts where id = %s", (pid,)).fetchone()["ig_music"] is None


def test_a_retry_reuses_the_saved_song(owner, user, fake_http, monkeypatch):
    fake = FakeInstagram(version="v27.0", audio_list=[{**LISTED, "audio_id": "999"}])
    _publish_unified(owner, user, fake_http, monkeypatch, fake,
                     ig_music={"audio_id": "587", "audio_volume": 25, "video_volume": 100})
    assert json.loads(fake.audio)["audio_id"] == "587" and fake.audio_searches == 0


def test_a_narrated_reel_keeps_the_song_quiet_under_the_voice(owner, user, fake_http, monkeypatch):
    fake = FakeInstagram(version="v27.0", audio_list=[LISTED])
    _publish_unified(owner, user, fake_http, monkeypatch, fake, narrated=True)
    assert json.loads(fake.audio) == {"audio_id": "587", "audio_volume": 25, "video_volume": 100}


def test_a_failed_pick_posts_the_bed_version(owner, user, fake_http, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("the picker fell over")
    monkeypatch.setattr(publish_post.ig_music, "choose", broken)
    fake = FakeInstagram(version="v27.0", audio_list=[LISTED])
    _publish_unified(owner, user, fake_http, monkeypatch, fake)
    assert fake.video_url.endswith("key=u/p/final.mp4") and fake.audio == ""


def test_expired_access_during_the_pick_marks_instagram_for_reconnecting(owner, user, fake_http, monkeypatch):
    def expired(*args, **kwargs):
        raise instagram.AuthExpired("Instagram access has expired or was removed")
    monkeypatch.setattr(publish_post.ig_music, "choose", expired)
    fake_http(FakeInstagram(version="v27.0", audio_list=[LISTED]))
    monkeypatch.setattr(publish_post.storage, "signed_url", lambda key, seconds: f"{LINK}&key={key}")
    pid = _ready_post(owner, user)
    _unified(owner, user, pid)
    _request(owner, user, pid, ("instagram",))
    Runner("publish", {"publish_post": publish_post.HANDLER}).tick()
    job = owner.execute("select state, error from jobs where dedupe_key = %s", (f"publish:{pid}:instagram",)).fetchone()
    assert job["state"] == "dead" and "reconnect Instagram" in job["error"]["message"]
    assert owner.execute("select status from channel_accounts where platform = 'instagram' and channel_id = "
                         "(select channel_id from posts where id = %s)", (pid,)).fetchone()["status"] == "expired"


def test_a_song_instagram_refuses_is_recorded_and_the_reel_goes_out_without_it(owner, user, fake_http, monkeypatch):
    fake = FakeInstagram(version="v27.0", audio_list=[LISTED], refuse_audio=True)
    pid = _publish_unified(owner, user, fake_http, monkeypatch, fake)
    assert fake.video_url.endswith("key=u/p/final.mp4") and fake.published == 1
    saved = owner.execute("select ig_music from posts where id = %s", (pid,)).fetchone()["ig_music"]
    assert saved["audio_id"] == "587" and "Invalid audio" in saved["dropped"]
    assert owner.execute("select reason from post_events where post_id = %s and reason = %s",
                         (pid, "posted to Instagram without its song")).fetchone()


SECOND = {"audio_id": "700", "title": "Kal", "display_artist": "B", "duration_in_ms": 20000}


def test_the_song_pick_is_costed(owner, user, fake_http, monkeypatch):
    monkeypatch.setattr(publish_post.ig_music.vault, "secret", lambda uid, name: "sk")
    fake = FakeInstagram(version="v27.0", audio_list=[LISTED, SECOND], choice="Kal — B")
    pid = _publish_unified(owner, user, fake_http, monkeypatch, fake)
    assert fake.decisions == 1 and json.loads(fake.audio)["audio_id"] == "700"
    saved = owner.execute("select ig_music from posts where id = %s", (pid,)).fetchone()["ig_music"]
    assert saved["audio_id"] == "700" and saved["picked_by"] == "decisions"
    cost = owner.execute("select kind, model, quantity from costs where post_id = %s and kind = 'music_pick'",
                         (pid,)).fetchone()
    assert cost == {"kind": "music_pick", "model": "gpt-6-luna", "quantity": {"input": 500, "cached_input": 0,
                                                                              "output": 0}}


def test_a_refused_song_is_not_tried_again(owner, user, fake_http, monkeypatch):
    fake = FakeInstagram(version="v27.0", audio_list=[LISTED])
    _publish_unified(owner, user, fake_http, monkeypatch, fake,
                     ig_music={"audio_id": "587", "dropped": "Invalid audio"})
    assert fake.video_url.endswith("key=u/p/final.mp4") and fake.audio == "" and fake.audio_searches == 0


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
