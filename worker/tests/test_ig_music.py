"""Instagram song candidates: trending first, then Hindi, meme and mood searches.

Pure unit tests against a fake Graph API (httpx.MockTransport); no database.

    bash db/dev/test.sh worker/tests/test_ig_music.py -q
"""

from __future__ import annotations

import httpx
import pytest

from corpus import ig_music
from corpus.music import MOODS
from corpus.publish import instagram

GRAPH = "https://graph.facebook.com/v27.0"


def fake_audio(replies: dict):          # search_query or "" → list of audio dicts, or an int status
    def handler(req):
        assert req.url.path == "/v27.0/ig_audio" and req.url.params["audio_type"] == "music"
        r = replies.get(req.url.params.get("search_query", ""), [])
        return httpx.Response(r, json={"error": {"message": "x", "code": 2}}) if isinstance(r, int) \
            else httpx.Response(200, json={"audio": r})
    return httpx.Client(transport=httpx.MockTransport(handler))


def a(i, title="Song", artist="Artist", ms=30000):
    return {"audio_id": str(i), "title": f"{title} {i}", "display_artist": artist, "duration_in_ms": ms}


def test_candidates_rank_trending_then_add_searches_without_repeats():
    c = fake_audio({"": [a(1), a(2)], "hindi trending": [a(2), a(3)], "bollywood": [a(4)]})
    got = ig_music.candidates(c, graph=GRAPH, token="t", ig_user_id="178", mood="somber", exclude={"4"})
    assert [t.audio_id for t in got] == ["1", "2", "3"]
    assert [t.trending_rank for t in got] == [1, 2, None]
    assert got[2].found_by == "hindi trending"


def test_trending_leaves_room_for_searches_and_the_cap_holds():
    c = fake_audio({"": [a(i) for i in range(50)], "hindi trending": 500,
                    "bollywood": [a(100 + i) for i in range(50)]})
    got = ig_music.candidates(c, graph=GRAPH, token="t", ig_user_id="178", mood=None, exclude=set())
    assert len(got) == 40
    assert sum(t.found_by == "trending" for t in got) == 15
    assert sum(t.found_by == "bollywood" for t in got) == 25         # the failing search was skipped


def test_candidates_are_empty_when_instagram_has_nothing():
    c = fake_audio({"": 500})
    assert ig_music.candidates(c, graph=GRAPH, token="t", ig_user_id="178", mood="playful", exclude=set()) == []


def test_an_expired_token_raises_auth_expired():
    def handler(req):
        return httpx.Response(400, json={"error": {"message": "expired", "code": 190}})
    c = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(instagram.AuthExpired):
        ig_music.candidates(c, graph=GRAPH, token="t", ig_user_id="178", mood=None, exclude=set())


def test_searches_put_hindi_first_and_include_meme_sounds():
    s = ig_music.searches("somber")
    assert s[:2] == ["hindi trending", "bollywood"] and "viral meme song" in s
    assert ig_music.searches("no-such-mood") == ig_music.searches("neutral-corporate")


def test_mood_searches_cover_every_music_mood():
    assert set(ig_music.MOOD_SEARCHES) == set(MOODS)
    assert all(len(v) == 2 for v in ig_music.MOOD_SEARCHES.values())


def test_rule_pick_prefers_the_moods_search_then_trending():
    t1 = ig_music.Track("1", "A", "x", 1, 1, "trending")
    t2 = ig_music.Track("2", "B", "y", 1, None, ig_music.MOOD_SEARCHES["somber"][0])
    assert ig_music.rule_pick([t1, t2], "somber").audio_id == "2"
    assert ig_music.rule_pick([t1], "somber").audio_id == "1"


def test_volumes():
    assert ig_music.volumes(True) == {"audio_volume": 25, "video_volume": 100}
    assert ig_music.volumes(False) == {"audio_volume": 100, "video_volume": 40}
