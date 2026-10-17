"""Sources, the prefilter, safe fetching, card media and the cost ledger.

Everything external is faked (httpx.MockTransport, moto S3, a fake vision
client); ffmpeg, the queue and the schema are real. Feeds here are synthetic —
no real Reddit users or posts in a public repository.
"""

from __future__ import annotations

import socket
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import httpx
import pytest
from moto import mock_aws

from corpus import costs, db, net, storage
from corpus.crypto import encrypt
from corpus.handlers import attach_media, suggest_ideas
from corpus.ideas import feeds, reddit, select, sources, sweep
from corpus.ideas.agent import Idea, IdeasOut
from corpus.ideas.vision import VideoAnalysis
from corpus.runner import Defer, Handler, Runner
from corpus.script.llm import Usage

NOW = datetime.now(timezone.utc)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _public(host, port, **kw):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """Test hosts resolve to a public address, so net's checks pass for them."""
    monkeypatch.setattr(net, "RESOLVE", _public)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    slept: list[float] = []
    clock = [1000.0]
    monkeypatch.setattr(reddit, "SLEEP", lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s)))
    monkeypatch.setattr(reddit, "CLOCK", lambda: clock[0])
    monkeypatch.setattr(reddit, "_next_ok", 0.0)
    return slept


@pytest.fixture
def s3(monkeypatch):
    with mock_aws():
        c = boto3.client("s3", region_name="us-east-1", aws_access_key_id="t", aws_secret_access_key="t")
        c.create_bucket(Bucket="corpus-test-media")
        monkeypatch.setattr(storage, "client", lambda: c)
        monkeypatch.setattr(storage, "bucket", lambda: "corpus-test-media")
        yield c


@pytest.fixture(scope="session")
def clips(tmp_path_factory) -> dict[str, bytes]:
    d = tmp_path_factory.mktemp("clips")

    def ff(*args):
        subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)
    ff("-f", "lavfi", "-i", "testsrc2=size=270x480:rate=24", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
       str(d / "v.mp4"))
    ff("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "3", "-c:a", "aac", str(d / "a.mp4"))
    ff("-f", "lavfi", "-i", "testsrc2=size=640x360", "-frames:v", "1", str(d / "p.jpg"))
    return {k: (d / f).read_bytes() for k, f in (("video", "v.mp4"), ("audio", "a.mp4"), ("jpg", "p.jpg"))}


@pytest.fixture
def user():
    uid = f"test-{uuid.uuid4().hex[:10]}"
    with db.conn() as c:
        c.execute("delete from jobs where lane = 'ideas' and state in ('queued','claimed')")
        c.execute('insert into "user" (id, name, email, "emailVerified") values (%s,%s,%s,true)',
                  (uid, uid, f"{uid}@example.test"))
        c.execute("insert into app_settings (user_id, script_model, vision_model) "
                  "values (%s, 'gpt-4o-mini', 'gpt-4.1-nano')", (uid,))
        c.execute("insert into user_keys (user_id, name, ciphertext) values (%s, 'openai', %s)",
                  (uid, encrypt("sk-test-key")))
        ch = c.execute("insert into channels (user_id, name, is_default) values (%s, 'News', true) returning id",
                       (uid,)).fetchone()["id"]
        c.execute("insert into formats (user_id, channel_id, name, idea_prompt, script_prompt, is_default) "
                  "values (%s, %s, 'News', 'Ideas: {trends} Give {count}.', 's', true)", (uid, ch))
        cat = c.execute("select id from categories where channel_id = %s", (ch,)).fetchone()["id"]
    yield {"id": uid, "channel": ch, "category": cat}
    with db.conn() as c:
        c.execute('delete from "user" where id = %s', (uid,))


# ── a synthetic Reddit feed ───────────────────────────────────────────────────

def _entry(n: int, sub: str, title: str, link: str, *, hours: float = 2.0, self_text: str = "") -> str:
    permalink = f"https://www.reddit.com/r/{sub}/comments/p{n}/post_{n}/"
    published = (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    md = f'&lt;div class="md"&gt;&lt;p&gt;{self_text}&lt;/p&gt;&lt;/div&gt;' if self_text else ""
    return f"""<entry>
  <author><name>/u/tester{n}</name><uri>https://www.reddit.com/user/tester{n}</uri></author>
  <category term="{sub}" label="r/{sub}"/>
  <content type="html">{md}&lt;span&gt;&lt;a href="{link}"&gt;[link]&lt;/a&gt;&lt;/span&gt;</content>
  <id>t3_p{n}</id>
  <media:thumbnail url="https://preview.test/thumb{n}.jpg"/>
  <link href="{permalink}"/>
  <published>{published}</published>
  <title>{title}</title>
</entry>"""


def atom(*entries: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:media="http://search.yahoo.com/mrss/">' + "".join(entries) + "</feed>")


FEED = atom(
    _entry(1, "videos", "Bridge collapses during storm, caught on camera", "https://v.redd.it/abc123"),
    _entry(2, "pics", "Rare white tiger spotted in the wild", "https://i.redd.it/xyz.jpeg"),
    _entry(3, "pics", "Ten photos of the eclipse", "https://www.reddit.com/gallery/gal1"),
    _entry(4, "news", "Court bans the sale of fake medicine", "https://news.test/story/42"),
    _entry(5, "news", "TIL about quiet places", "https://www.reddit.com/r/news/comments/p5/post_5/",
           self_text="Some text."),
    _entry(6, "news", "Look at this", "https://www.reddit.com/r/other/comments/zz/xpost/"),
)


def test_the_feed_parser_reads_every_kind_of_post():
    posts = reddit.parse(FEED)
    assert [p.kind for p in posts] == ["video", "image", "gallery", "link", "self", "crosspost"]
    v = posts[0]
    assert (v.subreddit, v.author, v.link, v.rank) == ("videos", "tester1", "https://v.redd.it/abc123", 0)
    assert v.thumbnail == "https://preview.test/thumb1.jpg" and v.published < NOW
    assert posts[4].selftext == "Some text."


def test_the_limiter_waits_its_turn_and_honours_reddits_reset(no_waiting):
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, text=FEED, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "120"})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    reddit.feed(client, ["videos", "pics"])
    reddit.feed(client, ["news"])
    assert "/r/videos+pics/top/.rss" in calls[0] and "t=day" in calls[0]
    assert no_waiting == [122.0]                       # past the reset, not just MIN_INTERVAL


_RealClient = httpx.Client          # handlers' httpx.Client gets patched; build fakes with the real one


def _routes(table: dict):
    def handler(req):
        for prefix, resp in table.items():
            if str(req.url).startswith(prefix):
                if callable(resp):
                    return resp(req)
                # A fresh copy each time: a response's body can be streamed only once.
                return httpx.Response(resp.status_code, headers=resp.headers, content=resp.content)
        return httpx.Response(404, text="no route")
    return _RealClient(transport=httpx.MockTransport(handler))


RSS = """<rss><channel><item><title>Parliament passes the data bill</title><link>https://site.test/a</link>
<pubDate>{}</pubDate></item></channel></rss>""".format(NOW.strftime("%a, %d %b %Y %H:%M:%S GMT"))


def test_a_category_reads_its_communities_in_one_request_and_survives_a_bad_source(no_waiting):
    client = _routes({
        "https://www.reddit.com/r/videos+pics/top/.rss": httpx.Response(200, text=FEED),
        "https://feeds.test/rss": httpx.Response(200, text=RSS, headers={"content-type": "application/rss+xml"}),
        "https://broken.test/": httpx.Response(500),
    })
    rows = [{"id": "r1", "kind": "reddit", "value": "videos", "options": {}},
            {"id": "r2", "kind": "reddit", "value": "pics", "options": {}},
            {"id": "f1", "kind": "rss", "value": "https://feeds.test/rss", "options": {"name": "Feeds"}},
            {"id": "b1", "kind": "rss", "value": "https://broken.test/", "options": {}}]
    items, outcomes = sources.fetch(rows, client=client, log=lambda m: None)
    got = {o.source_id: (o.ok, o.items) for o in outcomes}
    assert got["r1"] == (True, 1) and got["r2"] == (True, 2) and got["f1"] == (True, 1)
    assert got["b1"][0] is False
    assert items[0].extra["subreddit"] and any(i.source == "Feeds" for i in items)


def test_one_bad_community_is_found_by_asking_each_alone(no_waiting):
    client = _routes({
        "https://www.reddit.com/r/videos+gone/": httpx.Response(404),
        "https://www.reddit.com/r/videos/": httpx.Response(200, text=FEED),
        "https://www.reddit.com/r/gone/": httpx.Response(404),
    })
    rows = [{"id": "a", "kind": "reddit", "value": "videos", "options": {}},
            {"id": "b", "kind": "reddit", "value": "gone", "options": {}}]
    _, outcomes = sources.fetch(rows, client=client, log=lambda m: None)
    assert {o.source_id: o.ok for o in outcomes} == {"a": True, "b": False}


def test_the_prefilter_cuts_genres_crossposts_and_stale_items_and_puts_video_first():
    items = [feeds.Item("r/news", "Look at this", "", "u1", NOW, 5, "crosspost", {"subreddit": "news"}),
             feeds.Item("site", "Best phones under 20000 to buy", "", "u2", NOW),
             feeds.Item("site", "Old news about a merger", "", "u3", NOW - timedelta(days=4)),
             feeds.Item("r/news", "Minister arrested in bribery probe", "", "u4", NOW, 20, "link",
                        {"subreddit": "news"}),
             feeds.Item("r/videos", "Minister arrested in bribery probe on camera", "", "u5", NOW, 20, "video",
                        {"subreddit": "videos"})]
    kept, cuts = select.prefilter(items)
    assert [i.url for i in kept] == ["u5", "u4"]
    assert cuts == {"crosspost": 1, "review": 1, "stale": 1}


def test_safe_fetching_refuses_private_addresses_and_oversized_answers(monkeypatch):
    client = _routes({
        "https://ok.test/big": httpx.Response(200, content=b"x" * 2000, headers={"content-type": "image/jpeg"}),
        "https://ok.test/hop": httpx.Response(302, headers={"location": "http://internal.test/meta"}),
    })
    with pytest.raises(net.Blocked):
        net.get(client, "ftp://ok.test/a", max_bytes=10)
    with pytest.raises(net.TooBig):
        net.get(client, "https://ok.test/big", max_bytes=1000)
    with pytest.raises(net.WrongType):
        net.get(client, "https://ok.test/big", max_bytes=5000, accept=("video/",))

    def private(host, port, **kw):
        ip = "169.254.169.254" if host == "internal.test" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(net, "RESOLVE", private)
    with pytest.raises(net.Blocked):                    # checked again on the redirect hop
        net.get(client, "https://ok.test/hop", max_bytes=1000)


# ── card media ────────────────────────────────────────────────────────────────

MPD = """<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period>
<AdaptationSet contentType="video"><Representation height="720"><BaseURL>CMAF_720.mp4</BaseURL></Representation>
<Representation height="480"><BaseURL>CMAF_480.mp4</BaseURL></Representation></AdaptationSet>
<AdaptationSet contentType="audio"><Representation bandwidth="64000"><BaseURL>CMAF_AUDIO_64.mp4</BaseURL>
</Representation></AdaptationSet></Period></MPD>"""


class FakeVision:
    flagged: list[str] = []
    described = 0

    def __init__(self, key):
        assert key == "sk-test-key"

    def moderate(self, text, image):
        return {"flagged": bool(FakeVision.flagged), "categories": FakeVision.flagged}

    def describe(self, model, sheet, title):
        FakeVision.described += 1
        assert sheet.stat().st_size > 0
        return (VideoAnalysis(summary="A bridge falls into a river.", moments=["storm", "collapse"],
                              logos_or_watermarks=True, logo_names=["News 24"], identifiable_people=False,
                              graphic=False, spoken_language="none"),
                Usage(model, 1200, 150))


@pytest.fixture
def media_web(monkeypatch, clips):
    FakeVision.flagged, FakeVision.described = [], 0
    monkeypatch.setattr(attach_media, "VISION", FakeVision)
    table = {
        "https://v.redd.it/abc123/DASHPlaylist.mpd": httpx.Response(200, text=MPD,
                                                                    headers={"content-type": "application/dash+xml"}),
        "https://v.redd.it/abc123/CMAF_480.mp4": httpx.Response(200, content=clips["video"],
                                                               headers={"content-type": "video/mp4"}),
        "https://v.redd.it/abc123/CMAF_AUDIO_64.mp4": httpx.Response(200, content=clips["audio"],
                                                                    headers={"content-type": "audio/mp4"}),
        "https://preview.test/": httpx.Response(200, content=clips["jpg"], headers={"content-type": "image/jpeg"}),
        "https://i.redd.it/": httpx.Response(200, content=clips["jpg"], headers={"content-type": "image/jpeg"}),
    }
    monkeypatch.setattr(attach_media.httpx, "Client", lambda **kw: _routes(table))   # a fresh one per run


def _idea(u, item: dict) -> str:
    with db.conn() as c:
        return c.execute("""insert into ideas (user_id, channel_id, category_id, title, brief, items, media_state)
                            values (%s, %s, %s, %s, 'b', %s, 'pending') returning id""",
                         (u["id"], u["channel"], u["category"], item["title"], db.Jsonb([item]))).fetchone()["id"]


def _attach(idea_id):
    return attach_media.run(attach_media.JobContext(job={"id": None, "payload": {"idea_id": str(idea_id)}}))


VIDEO_ITEM = {"title": "Bridge collapses", "media_hint": "video", "link": "https://v.redd.it/abc123",
              "url": "https://www.reddit.com/r/videos/comments/p1/x/", "thumbnail": "https://preview.test/t1.jpg",
              "subreddit": "videos", "author": "tester1"}


def test_a_reddit_video_becomes_a_playable_card_preview(s3, user, media_web):
    iid = _idea(user, VIDEO_ITEM)
    _attach(iid)
    with db.conn() as c:
        row = c.execute("select media, media_state, analysis from ideas where id = %s", (iid,)).fetchone()
        cost = c.execute("select kind, model, usd_micros from costs where user_id = %s", (user["id"],)).fetchone()
    assert row["media_state"] == "ready"
    m = row["media"][0]
    assert m["type"] == "video" and m["has_audio"] and m["credit"] == "u/tester1 on r/videos"
    body = s3.get_object(Bucket="corpus-test-media", Key=m["key"])
    data = body["Body"].read()
    assert body["ContentType"] == "video/mp4" and data.index(b"moov") < data.index(b"mdat")   # faststart
    assert s3.get_object(Bucket="corpus-test-media", Key=m["poster_key"])["ContentType"] == "image/jpeg"
    assert row["analysis"]["video"]["logo_names"] == ["News 24"]
    assert cost == {"kind": "vision", "model": "gpt-4.1-nano", "usd_micros": 1200 * 0.10 + 150 * 0.40}


def test_flagged_posts_are_removed_before_anything_is_downloaded(s3, user, media_web):
    FakeVision.flagged = ["sexual"]
    iid = _idea(user, VIDEO_ITEM)
    _attach(iid)
    with db.conn() as c:
        row = c.execute("select status, media_state, reject_reason from ideas where id = %s", (iid,)).fetchone()
    assert row["status"] == "rejected" and row["media_state"] == "none" and "moderation" in row["reject_reason"]
    assert s3.list_objects_v2(Bucket="corpus-test-media").get("KeyCount", 0) == 0


def test_old_and_unwanted_card_media_is_swept(s3, user, media_web):
    keep, old, rejected = (_idea(user, {**VIDEO_ITEM, "media_hint": "image", "link": "https://i.redd.it/x.jpg",
                                       "title": t}) for t in ("keep", "old", "rejected"))
    for i in (keep, old, rejected):
        _attach(i)
    with db.conn() as c:
        c.execute("update ideas set created_at = now() - interval '8 days' where id = %s", (old,))
        c.execute("update ideas set status = 'rejected', decided_at = now() - interval '2 days' where id = %s",
                  (rejected,))
    sweep.sweep(lambda m: None)            # global: it also clears files orphaned by earlier tests
    with db.conn() as c:
        live = {r["idea"] for r in c.execute(
            """select nullif(substring(key from '/ideas/([0-9a-f-]{36})/'), '')::uuid as idea
                 from storage_objects where kind = 'idea_media' and state = 'stored'""")}
    assert keep in live and old not in live and rejected not in live
    with db.conn() as c:
        states = {r["id"]: r["media_state"] for r in c.execute(
            "select id, media_state from ideas where id = any(%s)", ([keep, old, rejected],))}
    assert states[keep] == "ready" and states[old] == "expired"
    assert sweep.evict(1, lambda m: None) > 0                     # oldest unswiped first: only `keep` is left
    with db.conn() as c:
        assert c.execute("select media_state from ideas where id = %s", (keep,)).fetchone()["media_state"] == "expired"


# ── the batch, the runner, the ledger ─────────────────────────────────────────

class OneIdeaWriter:
    picks: list[Idea] = []

    def __init__(self, key):
        pass

    def write(self, *, model, system, user):
        return IdeasOut(ideas=OneIdeaWriter.picks), Usage(model, 1000, 200, cached_input_tokens=400)


def test_a_batch_links_ideas_to_their_posts_and_queues_their_media(user, monkeypatch):
    items = [feeds.Item("r/videos", "Bridge collapses during storm", "", "https://www.reddit.com/r/videos/p1",
                        NOW, 0, "video", {"subreddit": "videos", "author": "tester1",
                                          "link": "https://v.redd.it/abc123"}),
             feeds.Item("Feeds", "Parliament passes the data bill", "", "https://site.test/a", NOW)]
    monkeypatch.setattr(suggest_ideas, "FETCH", lambda rows, **kw: (items, []))
    monkeypatch.setattr(suggest_ideas, "WRITER_FACTORY", OneIdeaWriter)
    monkeypatch.setattr(suggest_ideas, "EMBED", lambda texts: __import__("numpy").eye(len(texts), 384))

    class Mem:
        def nearest(self, ch, v): return (0.0, "")
        def remember(self, pts): pass
        def forget(self, ids): pass
    monkeypatch.setattr(suggest_ideas, "MEMORY", lambda log: Mem())
    OneIdeaWriter.picks = [Idea(title="A bridge falls in the storm", hook="h", brief="b", why_now="today",
                                items=[1, 1, 9], format=1, format_why="")]
    ctx = suggest_ideas.JobContext(job={"id": None, "payload": {"category_id": str(user["category"])}})
    assert suggest_ideas.run(ctx)["ideas"] == 1
    with db.conn() as c:
        idea = c.execute("select id, items, media_state, category_id from ideas where channel_id = %s",
                         (user["channel"],)).fetchone()
        job = c.execute("select lane, kind from jobs where dedupe_key = %s", (f"attach_media:{idea['id']}",)).fetchone()
        cost = c.execute("select kind, usd_micros, quantity from costs where user_id = %s", (user["id"],)).fetchone()
    assert [i["subreddit"] for i in idea["items"]] == ["videos"]               # duplicates and #9 ignored
    assert idea["media_state"] == "pending" and idea["category_id"] == user["category"]
    assert job == {"lane": "ideas", "kind": "attach_media"}
    assert cost["kind"] == "llm" and cost["quantity"]["cached_input"] == 400
    assert cost["usd_micros"] == round(600 * 0.15 + 400 * 0.075 + 200 * 0.60)  # gpt-4o-mini list price

    OneIdeaWriter.picks = []                                                   # a slow day: none is fine
    assert suggest_ideas.run(ctx)["nothing_worth_making"] is True


def test_deferring_gives_the_attempt_back(user):
    with db.conn() as c:
        job = db.enqueue(c, user_id=user["id"], lane="ideas", kind="wait_a_bit", dedupe_key=f"t:{uuid.uuid4()}",
                         max_attempts=1)

    def wait(ctx):
        raise Defer("the analysis isn't done yet", retry_in=90)
    assert Runner("ideas", {"wait_a_bit": Handler(run=wait)}).tick()
    with db.conn() as c:
        j = c.execute("select state, attempts, not_before > now() + interval '80 seconds' as later "
                      "from jobs where id = %s", (job["id"],)).fetchone()
    assert j == {"state": "queued", "attempts": 0, "later": True}


def test_gpu_time_and_unknown_models_are_recorded(user):
    costs.record_gpu(user_id=user["id"], post_id=None, job_id=None, pod_id=7, gpu="NVIDIA RTX 4090",
                     seconds=1800, rate_paise_h=6900)
    costs.record_llm(Usage("some-new-model", 10, 10), user_id=user["id"])
    with db.conn() as c:
        rows = {r["kind"]: r for r in c.execute("select kind, inr_paise, usd_micros from costs where user_id = %s",
                                                (user["id"],))}
    assert rows["gpu"]["inr_paise"] == 3450 and rows["llm"]["usd_micros"] is None


class Forbidden(Exception):
    status_code = 403            # what OpenAI answers a restricted key on /moderations


def test_a_key_that_cannot_moderate_falls_back_to_a_safety_check(s3, user, media_web, monkeypatch):
    class Restricted(FakeVision):
        def moderate(self, text, image):
            raise Forbidden("this key may not call /moderations")

        def safety(self, model, text, image):
            return {"flagged": False, "categories": [], "by": model}, Usage(model, 300, 20)
    monkeypatch.setattr(attach_media, "VISION", Restricted)
    iid = _idea(user, {**VIDEO_ITEM, "media_hint": "image", "link": "https://i.redd.it/x.jpg"})
    _attach(iid)
    with db.conn() as c:
        assert c.execute("select media_state from ideas where id = %s", (iid,)).fetchone()["media_state"] == "ready"
        cost = c.execute("select kind, model from costs where user_id = %s", (user["id"],)).fetchone()
    assert cost == {"kind": "moderation", "model": "gpt-4.1-nano"}       # the vision model, checked and billed


def test_a_feed_story_gets_its_articles_lead_picture(s3, user, media_web, monkeypatch, clips):
    page = '<html><head><meta property="og:image" content="https://i.redd.it/lead.jpg"></head></html>'
    iid = _idea(user, {"title": "Parliament passes the data bill", "media_hint": "", "url": "https://news.test/a"})
    table_client = _routes({
        "https://news.test/": httpx.Response(200, text=page, headers={"content-type": "text/html"}),
        "https://i.redd.it/": httpx.Response(200, content=clips["jpg"], headers={"content-type": "image/jpeg"}),
        "https://preview.test/": httpx.Response(200, content=clips["jpg"], headers={"content-type": "image/jpeg"}),
    })
    monkeypatch.setattr(attach_media.httpx, "Client", lambda **kw: table_client)
    _attach(iid)
    with db.conn() as c:
        row = c.execute("select media_state, media from ideas where id = %s", (iid,)).fetchone()
    assert row["media_state"] == "ready" and row["media"][0]["origin"] == "article"
    assert row["media"][0]["credit"] == "news.test"


def test_list_prices_apply_only_to_their_own_model(user):
    costs.record_llm(Usage("gpt-5.7-sol", 10, 10), user_id=user["id"], note="other")   # shares only a prefix
    costs.record_llm(Usage("gpt-4o-mini-2024-07-18", 1_000_000, 0), user_id=user["id"], note="dated")
    with db.conn() as c:
        got = {r["note"]: r["usd_micros"] for r in c.execute(
            "select note, usd_micros from costs where user_id = %s", (user["id"],))}
    assert got == {"other": None, "dated": 150_000}


def test_luna_list_prices_and_cache_writes(user):
    costs.record_llm(Usage("gpt-6-luna", 1_000_000, 1_000_000), user_id=user["id"], note="six")
    costs.record_llm(Usage("gpt-5.6-luna", 1_000_000, 0, cached_input_tokens=200_000, cache_write_tokens=100_000),
                     user_id=user["id"], note="five")
    with db.conn() as c:
        got = {r["note"]: r["usd_micros"] for r in c.execute(
            "select note, usd_micros from costs where user_id = %s", (user["id"],))}
    assert got == {"six": 100_000 + 500_000,                               # $0.10 in + $0.50 out per 1M
                   "five": 700_000 * 0.20 + 200_000 * 0.02 + 100_000 * 0.25}


def test_the_model_list_is_refreshed_from_the_key(user, monkeypatch):
    from types import SimpleNamespace

    import openai
    from corpus import openai_models

    class FakeOpenAI:
        def __init__(self, api_key, **kw):
            assert api_key == "sk-test-key"
            self.models = SimpleNamespace(list=lambda: [SimpleNamespace(id=i) for i in
                                                        ("gpt-6-luna", "gpt-image-2", "gpt-5.6-luna")])
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    assert openai_models.refresh(user["id"]) == ["gpt-5.6-luna", "gpt-6-luna", "gpt-image-2"]
    with db.conn() as c:
        assert c.execute("select openai_models from app_settings where user_id = %s",
                         (user["id"],)).fetchone()["openai_models"] == ["gpt-5.6-luna", "gpt-6-luna", "gpt-image-2"]
