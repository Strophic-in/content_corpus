"""Instagram song candidates: trending first, then Hindi, meme and mood searches.

Pure unit tests against a fake Graph API (httpx.MockTransport); no database.

    bash db/dev/test.sh worker/tests/test_ig_music.py -q
"""

from __future__ import annotations

import json

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


def test_excluded_trending_songs_do_not_use_up_slots():
    c = fake_audio({"": [a(i) for i in range(20)], "bollywood": [a(100)]})
    got = ig_music.candidates(c, graph=GRAPH, token="t", ig_user_id="178", mood=None,
                              exclude={"0", "1", "2", "3", "4"})
    trending = [t.audio_id for t in got if t.found_by == "trending"]
    assert trending == [str(i) for i in range(5, 20)]               # 15 kept, all past the excluded five
    assert "100" in [t.audio_id for t in got]                        # the search still gets reached


def test_a_non_numeric_duration_counts_as_zero():
    c = fake_audio({"": [{"audio_id": "7", "title": "T", "display_artist": "A", "duration_in_ms": "long"}]})
    got = ig_music.candidates(c, graph=GRAPH, token="t", ig_user_id="178", mood=None, exclude=set())
    assert got[0].duration_ms == 0


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


TRACKS = [ig_music.Track("1", "Party Song", "DJ", 30000, 1, "trending"),
          ig_music.Track("2", "Dil Udaas", "Arijit", 40000, None, ig_music.MOOD_SEARCHES["somber"][0])]
REEL = {"title": "Flood kills 12", "hook": "Water rose overnight", "category": "News", "mood": "somber",
        "narrated": True}


def fake_decisions(reply, seen):          # dict → 200 JSON; int → bare status
    def handler(req):
        seen.append(json.loads(req.content))
        assert req.url == ig_music.DECISIONS
        assert req.headers["authorization"] == "Bearer sk"
        return httpx.Response(200, json=reply) if isinstance(reply, dict) else httpx.Response(reply)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_decide_sends_one_choice_question_and_returns_the_pick():
    seen = []
    c = fake_decisions({"answers": [{"type": "choice", "name": "song", "choice": "Dil Udaas — Arijit",
                                     "confidence": 0.8}],
                        "usage": {"input_tokens": 900, "input_tokens_details": {"cached_tokens": 0}}}, seen)
    track, conf, usage, by = ig_music.decide(c, "sk", REEL, TRACKS)
    assert track.audio_id == "2" and conf == 0.8 and by == "decisions"
    assert usage.input_tokens == 900 and usage.output_tokens == 0
    body = seen[0]
    assert body["model"] == "gpt-6-luna" and body["questions"][0]["type"] == "choice"
    assert [ch["value"] for ch in body["questions"][0]["choices"]] == ["Party Song — DJ", "Dil Udaas — Arijit"]
    assert "Prefer Hindi songs" in body["questions"][0]["instructions"]


def test_decide_falls_back_to_the_rule_pick():
    for reply in (500, {"answers": [{"type": "refusal", "name": "song"}]},
                  {"answers": [{"type": "choice", "name": "song", "choice": "Not offered"}]}):
        track, conf, _, by = ig_music.decide(fake_decisions(reply, []), "sk", REEL, TRACKS)
        assert track.audio_id == "2" and conf is None and by == "rule"
    assert ig_music.decide(None, None, REEL, TRACKS)[0].audio_id == "2"     # no key: no call at all
    assert ig_music.decide(None, "sk", REEL, TRACKS[:1])[3] == "only"       # one song: nothing to decide


def test_duplicate_labels_are_made_unique():
    twins = [ig_music.Track("1", "Same", "A", 1, 1, "trending"), ig_music.Track("2", "Same", "A", 1, 2, "trending")]
    seen = []
    ig_music.decide(fake_decisions({"answers": [{"type": "choice", "name": "song", "choice": "Same — A (2)",
                                                 "confidence": 0.5}]}, seen), "sk", REEL, twins)
    assert [ch["value"] for ch in seen[0]["questions"][0]["choices"]] == ["Same — A", "Same — A (2)"]


def test_a_malformed_answer_falls_back_to_the_rule_pick():
    for answer in ({"type": "choice", "name": "song", "choice": "Party Song — DJ", "confidence": "high"},
                   {"type": "choice", "name": "song", "choice": ["Party Song — DJ"], "confidence": 0.9}):
        track, conf, _, by = ig_music.decide(fake_decisions({"answers": [answer]}, []), "sk", REEL, TRACKS)
        assert track.audio_id == "2" and conf is None and by == "rule"


def test_malformed_usage_keeps_a_valid_pick():
    reply = {"answers": [{"type": "choice", "name": "song", "choice": "Party Song — DJ", "confidence": 0.7}],
             "usage": {"input_tokens": "lots"}}
    track, conf, usage, by = ig_music.decide(fake_decisions(reply, []), "sk", REEL, TRACKS)
    assert track.audio_id == "1" and conf == 0.7 and by == "decisions" and usage is None


def test_a_400_is_logged_with_its_status(caplog):
    with caplog.at_level("WARNING", logger="corpus.ig_music"):
        track, _, _, by = ig_music.decide(fake_decisions(400, []), "sk", REEL, TRACKS)
    assert track.audio_id == "2" and by == "rule"
    assert any(r.levelname == "WARNING" and "400" in r.getMessage() for r in caplog.records)
