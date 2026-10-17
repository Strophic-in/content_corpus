"""Bluesky, Mastodon, Lemmy, Hacker News and YouTube's chart as idea sources.

All answers are synthetic (no real accounts or posts in a public repository),
shaped like each API's real responses; HLS and MP4 media are real files made by
ffmpeg, served through httpx.MockTransport.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date, timedelta

import httpx
import pytest

from corpus import db
from corpus.handlers import attach_media, write_script
from corpus.ideas import feeds, select, social, sources

from test_sources_media import (FakeVision, NOW, _attach, _idea, _routes, clips, no_waiting,  # noqa: F401
                                 public_dns, s3, user)

ISO = NOW.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _json(data, status=200):
    return httpx.Response(status, content=json.dumps(data).encode(), headers={"content-type": "application/json"})


# ── Bluesky ───────────────────────────────────────────────────────────────────

def _bsky(n, text, embed=None, labels=(), likes=10):
    return {"post": {"uri": f"at://did:plc:author{n}/app.bsky.feed.post/rk{n}",
                     "author": {"did": f"did:plc:author{n}", "handle": f"author{n}.test", "labels": []},
                     "record": {"text": text, "createdAt": ISO}, "embed": embed, "likeCount": likes,
                     "replyCount": 2, "repostCount": 3, "labels": [{"val": v} for v in labels]}}


BSKY_FEED = {"feed": [
    _bsky(1, "Flood waters reach the old town square. Residents moved to the school.",
          {"$type": "app.bsky.embed.video#view", "playlist": "https://video.test/watch/v1/playlist.m3u8",
           "thumbnail": "https://video.test/watch/v1/thumbnail.jpg"}, likes=900),
    _bsky(2, "A rare comet over the mountains tonight",
          {"$type": "app.bsky.embed.images#view",
           "images": [{"thumb": "https://cdn.test/thumb/c.jpg", "fullsize": "https://cdn.test/full/c.jpg",
                       "alt": "a comet"}]}),
    _bsky(3, "", {"$type": "app.bsky.embed.external#view",
                  "external": {"uri": "https://news.test/a", "title": "Court bans fake medicine",
                               "thumb": "https://cdn.test/thumb/a.jpg"}}),
    _bsky(4, "Not for the deck", labels=("porn",)),
    _bsky(5, "Author asked not to be shown logged out", labels=("!no-unauthenticated",)),
]}


def test_bluesky_posts_become_items_with_their_media_and_skip_labelled_ones():
    client = _routes({"https://public.api.bsky.app/xrpc/app.bsky.feed.getFeed": _json(BSKY_FEED)})
    items = social.bluesky(client, "whats-hot")
    assert [i.media_hint for i in items] == ["video", "image", "link"]
    v, img, link = items
    assert v.title == "Flood waters reach the old town square." and v.summary.startswith("Residents")
    assert v.extra["hls_url"].endswith("playlist.m3u8") and v.extra["score"] == 900
    assert v.url == "https://bsky.app/profile/author1.test/post/rk1" and v.extra["author"] == "@author1.test"
    assert img.extra["image_url"] == "https://cdn.test/full/c.jpg"
    assert link.title == "Court bans fake medicine" and link.extra["link"] == "https://news.test/a"


def test_a_bluesky_feed_link_is_resolved_through_its_owners_handle():
    seen = []

    def feed(req):
        seen.append(req.url.params["feed"])
        return _json({"feed": []})
    client = _routes({
        "https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle": _json({"did": "did:plc:feedowner"}),
        "https://public.api.bsky.app/xrpc/app.bsky.feed.getFeed": feed,
    })
    social.bluesky(client, "https://bsky.app/profile/feeds.test/feed/science")
    assert seen == ["at://did:plc:feedowner/app.bsky.feed.generator/science"]


# ── Mastodon, Lemmy, Hacker News ──────────────────────────────────────────────

def _toot(n, html, media=None, card=None, sensitive=False, boosts=1, favs=1):
    return {"id": str(n), "created_at": ISO, "sensitive": sensitive, "spoiler_text": "", "visibility": "public",
            "url": f"https://masto.test/@u{n}/{n}", "content": html, "replies_count": 0, "reblogs_count": boosts,
            "favourites_count": favs, "account": {"acct": f"u{n}", "noindex": False},
            "media_attachments": media or [], "card": card}


def test_mastodon_trends_bring_posts_and_links_and_a_hashtag_is_ranked_by_shares():
    client = _routes({
        "https://masto.test/api/v1/trends/statuses": _json([
            _toot(1, "<p>Bridge reopens after <b>two years</b></p>",
                  media=[{"type": "video", "url": "https://files.test/b.mp4", "preview_url": "https://files.test/b.jpg",
                          "meta": {"original": {"duration": 12.5}}}]),
            _toot(2, "<p>Hidden</p>", sensitive=True)]),
        "https://masto.test/api/v1/trends/links": _json([
            {"url": "https://news.test/x", "title": "Parliament passes the data bill", "description": "d",
             "provider_name": "News Test", "image": "https://files.test/x.jpg", "published_at": ISO}]),
        "https://masto.test/api/v1/timelines/tag/science": _json([
            _toot(3, "<p>Quiet one</p>", boosts=0, favs=1), _toot(4, "<p>Loud one</p>", boosts=50, favs=90)]),
    })
    items = social.mastodon(client, "masto.test")
    assert [(i.title, i.media_hint) for i in items] == [("Bridge reopens after two years", "video"),
                                                       ("Parliament passes the data bill", "link")]
    assert items[0].extra["video_url"] == "https://files.test/b.mp4" and items[0].extra["author"] == "@u1@masto.test"
    assert [i.title for i in social.mastodon(client, "#science@masto.test")] == ["Loud one", "Quiet one"]


def test_lemmy_posts_keep_their_media_kind_and_skip_nsfw():
    def pv(n, name, url="", ctype=None, nsfw=False):
        return {"post": {"name": name, "url": url, "url_content_type": ctype, "nsfw": nsfw, "body": "",
                         "ap_id": f"https://lemmy.test/post/{n}", "published": ISO, "thumbnail_url": None},
                "community": {"name": "pics", "nsfw": False}, "creator": {"name": f"user{n}"},
                "counts": {"score": 100 - n, "comments": 4}}
    client = _routes({"https://lemmy.test/api/v3/post/list": _json({"posts": [
        pv(1, "A heron catches a fish", "https://img.test/h.jpg", "image/jpeg"),
        pv(2, "Timelapse of the storm", "https://img.test/s.mp4", "video/mp4"),
        pv(3, "City votes to ban cars downtown", "https://news.test/cars"),
        pv(4, "Nope", nsfw=True)]})})
    items = social.lemmy(client, "pics@lemmy.test")
    assert [i.media_hint for i in items] == ["image", "video", "link"]
    assert items[0].source == "c/pics" and items[0].extra["author"] == "u/user1"


def test_hacker_news_front_page_is_ordered_by_points():
    client = _routes({"https://hn.algolia.com/api/v1/search": _json({"hits": [
        {"title": "Small", "url": "https://a.test", "points": 10, "objectID": "1", "created_at": ISO},
        {"title": "Ask HN: big one", "url": None, "points": 500, "objectID": "2", "created_at": ISO}]})})
    items = social.hackernews(client, "front_page")
    assert [i.title for i in items] == ["Ask HN: big one", "Small"]
    assert items[0].media_hint == "self" and items[0].url == "https://news.ycombinator.com/item?id=2"


# ── YouTube ───────────────────────────────────────────────────────────────────

def test_youtube_trending_sends_the_key_in_a_header_and_skips_age_restricted_videos():
    seen = {}

    def chart(req):
        seen["url"], seen["key"] = str(req.url), req.headers.get("x-goog-api-key")
        return _json({"items": [
            {"id": "v1", "snippet": {"title": "Launch day", "channelTitle": "Space Test", "publishedAt": ISO,
                                     "thumbnails": {"high": {"url": "https://i.ytimg.test/v1/hq.jpg"}}},
             "statistics": {"viewCount": "120000", "likeCount": "5000"}, "contentDetails": {"duration": "PT8M"}},
            {"id": "v2", "snippet": {"title": "Adults only"},
             "contentDetails": {"contentRating": {"ytRating": "ytAgeRestricted"}}}]})
    client = _routes({"https://www.googleapis.com/youtube/v3/videos": chart})
    items = social.youtube(client, "IN:28", "AIza-test-key")
    assert seen["key"] == "AIza-test-key" and "AIza" not in seen["url"]
    assert "regionCode=IN" in seen["url"] and "videoCategoryId=28" in seen["url"]
    assert [i.title for i in items] == ["Launch day"]
    assert items[0].extra["views"] == 120000 and items[0].media_hint == "image"
    assert items[0].source == "YouTube trending IN · Science & Technology"
    with pytest.raises(social.SourceError, match="YouTube API key"):
        social.youtube(client, "IN", None)


def test_a_source_that_fails_says_why_in_plain_words(no_waiting):
    rows = [{"id": "y", "kind": "youtube", "value": "IN", "options": {}},
            {"id": "h", "kind": "hackernews", "value": "front_page", "options": {}}]
    client = _routes({"https://www.googleapis.com/youtube/v3/videos": _json({"error": {}}, status=403),
                       "https://hn.algolia.com/": _json({"hits": [{"title": "T", "url": "https://a.test",
                                                                    "objectID": "1", "created_at": ISO}]})})
    items, outcomes = sources.fetch(rows, client=client, youtube_key="AIza-secret", log=lambda m: None)
    got = {o.source_id: o for o in outcomes}
    assert got["h"].ok and len(items) == 1
    assert not got["y"].ok and got["y"].error.startswith("HTTP 403 from www.googleapis.com")
    assert "AIza-secret" not in got["y"].error


def test_after_reddits_feeds_end_its_sources_say_so_without_retrying_each(no_waiting, monkeypatch):
    monkeypatch.setattr(sources, "REDDIT_RSS_END", date.today() - timedelta(days=1))
    calls = []

    def gone(req):
        calls.append(str(req.url))
        return httpx.Response(403)
    client = _routes({"https://www.reddit.com/": gone})
    rows = [{"id": "a", "kind": "reddit", "value": "videos", "options": {}},
            {"id": "b", "kind": "reddit", "value": "pics", "options": {}}]
    _, outcomes = sources.fetch(rows, client=client, log=lambda m: None)
    assert len(calls) == 1 and all("ended its public feeds" in o.error for o in outcomes)


def test_votes_on_any_open_platform_lift_an_item_like_reddits_do():
    voted = feeds.Item("Bluesky · What's Hot", "Minister resigns over leaked tapes", "", "u1", NOW, 0, "self",
                       {"platform": "bluesky"})
    plain = feeds.Item("site", "Minister resigns over leaked tapes", "", "u2", NOW, 0, "")
    assert select.score(voted) > select.score(plain)
    assert "votes" in feeds.as_prompt([feeds.Item("x", "t", "", "u", NOW, 0, "", {"score": 900})])


def test_the_category_prompt_reaches_the_script_writer():
    assert write_script._category_note(None) == ""
    note = write_script._category_note({"name": "Crime", "brief": "Never name victims."})
    assert "## Category: Crime" in note and "Never name victims." in note


# ── card media from the open platforms ───────────────────────────────────────

@pytest.fixture(scope="module")
def hls(tmp_path_factory):
    """Two 2-second MPEG-TS segments of a portrait test clip, as a Bluesky-style HLS stream."""
    d = tmp_path_factory.mktemp("hls")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=330", "-t", "4", "-c:v", "libx264", "-g", "48", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-f", "hls", "-hls_time", "2", "-hls_segment_filename", str(d / "seg%d.ts"),
                    str(d / "media.m3u8")], check=True)
    return {p.name: p.read_bytes() for p in d.iterdir()}


@pytest.fixture
def open_web(monkeypatch, clips, hls):
    FakeVision.flagged, FakeVision.described = [], 0
    monkeypatch.setattr(attach_media, "VISION", FakeVision)
    mpegurl = {"content-type": "application/vnd.apple.mpegurl"}
    master = ("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=900000,RESOLUTION=360x640\n360p/video.m3u8?s=1\n"
              "#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=720x1280\n720p/video.m3u8?s=1\n")
    table = {
        "https://video.test/watch/v1/playlist.m3u8": httpx.Response(200, text=master, headers=mpegurl),
        "https://video.test/watch/v1/360p/video.m3u8": httpx.Response(200, content=hls["media.m3u8"], headers=mpegurl),
        "https://video.test/watch/v1/720p/": httpx.Response(500),             # never asked for
        "https://files.test/b.mp4": httpx.Response(200, content=clips["video"], headers={"content-type": "video/mp4"}),
        "https://files.test/broken.mp4": httpx.Response(404),
    }
    for name, body in hls.items():
        if name.endswith(".ts"):
            table[f"https://video.test/watch/v1/360p/{name}"] = httpx.Response(
                200, content=body, headers={"content-type": "video/mp2t"})
    for host in ("https://video.test/watch/v1/thumbnail.jpg", "https://files.test/b.jpg"):
        table[host] = httpx.Response(200, content=clips["jpg"], headers={"content-type": "image/jpeg"})
    monkeypatch.setattr(attach_media.httpx, "Client", lambda **kw: _routes(table))


def test_a_bluesky_video_is_read_from_its_stream_into_a_card_preview(s3, user, open_web):
    iid = _idea(user, {"title": "Flood waters reach the square", "media_hint": "video", "platform": "bluesky",
                       "author": "@author1.test", "url": "https://bsky.app/profile/author1.test/post/rk1",
                       "hls_url": "https://video.test/watch/v1/playlist.m3u8",
                       "thumbnail": "https://video.test/watch/v1/thumbnail.jpg"})
    _attach(iid)
    with db.conn() as c:
        row = c.execute("select media_state, media from ideas where id = %s", (iid,)).fetchone()
    m = row["media"][0]
    assert row["media_state"] == "ready" and m["type"] == "video" and m["has_audio"]
    assert (m["origin"], m["credit"]) == ("bluesky", "@author1.test on Bluesky")
    assert min(m["w"], m["h"]) <= 480 and m["seconds"] >= 3.5
    data = s3.get_object(Bucket="corpus-test-media", Key=m["key"])["Body"].read()
    assert data.index(b"moov") < data.index(b"mdat")                          # faststart


def test_a_mastodon_video_and_a_failed_one_falling_back_to_its_thumbnail(s3, user, open_web):
    ok = _idea(user, {"title": "Bridge reopens", "media_hint": "video", "platform": "mastodon", "author": "@u1@m.test",
                      "video_url": "https://files.test/b.mp4", "thumbnail": "https://files.test/b.jpg",
                      "url": "https://m.test/@u1/1"})
    broken = _idea(user, {"title": "Storm timelapse", "media_hint": "video", "platform": "lemmy", "author": "u/x",
                          "community": "pics", "video_url": "https://files.test/broken.mp4",
                          "thumbnail": "https://files.test/b.jpg", "url": "https://l.test/post/2"})
    _attach(ok)
    _attach(broken)
    with db.conn() as c:
        got = {r["id"]: r for r in c.execute("select id, media, analysis from ideas where id = any(%s)",
                                             ([ok, broken],))}
    assert got[ok]["media"][0]["type"] == "video" and got[ok]["media"][0]["origin"] == "mastodon"
    fallback = got[broken]["media"][0]
    assert fallback["type"] == "image" and fallback["credit"] == "u/x on c/pics"
    assert "video_error" in got[broken]["analysis"]
