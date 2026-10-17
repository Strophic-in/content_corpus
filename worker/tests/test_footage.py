"""Phase 2: reels from footage — the post's own clip or picture, stock video, and
generated shots side by side.

Everything external is faked (S3 by moto, Pexels and the post's host by
httpx.MockTransport, OpenAI and Whisper by stand-ins); ffmpeg, the queue, the
trigger that releases assembly, and the schema are real. Media are synthetic.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from corpus import db, storage
from corpus.crypto import encrypt
from corpus.handlers import (analyze_asset, assemble, build_segment, fetch_asset, narrate, plan_shots, prepare_shot,
                             render_post, write_script)
from corpus.ideas import sweep
from corpus.ideas.vision import FootageAnalysis, Moment
from corpus.publish import instagram, youtube
from corpus.runner import Runner
from corpus.script import footage as footage_
from corpus.script.llm import Footage, Review, ScriptOut, Usage, generated_shot, validate
from test_render_pipeline import (as_user, drain, fake_speak, fake_whisper, fakes, gpu, owner, pod_notes,  # noqa: F401
                                  s3, segment_cache, user)
from test_sources_media import _routes, public_dns  # noqa: F401

LINE = "Officials say the bridge had been closed for repairs since spring."   # 11 words


# ── the rules and the prompt (no database) ────────────────────────────────────

FOOTAGE = Footage(assets=[{"n": 1, "kind": "video", "seconds": 20.0, "w": 1280, "h": 720, "credit": "u/a on r/b"},
                          {"n": 2, "kind": "image", "w": 1600, "h": 900, "credit": "news.test"}], stock=False)


def _script(*shots) -> ScriptOut:
    return ScriptOut(title="Bridge falls in storm", hook="h", description="d", hashtags=["#shorts"],
                     intended_dialogue="x", style_prompt="", shots=list(shots), music_mood="", review=Review(score=8, risks=[], notes=""))


def test_footage_shots_must_name_footage_the_reel_has():
    ok = _script(generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="clip", asset=1, start=2, end=6),
                 generated_shot(seconds=4, visual="v", audio="", narration="", source="clip", asset=1, start=8, end=12,
                                keep_audio=True),
                 generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="image", asset=2))
    assert validate(ok, 12, narrated=True, footage=FOOTAGE) == []
    bad = _script(generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="clip", asset=2, start=0, end=3),
                  generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="clip", asset=1, start=15,
                                 end=25),
                  generated_shot(seconds=4, visual="v", audio="", narration="talking over", source="clip", asset=1,
                                 start=0, end=3, keep_audio=True),
                  generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="stock", stock_query="city"),
                  generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="drone"))
    problems = " | ".join(validate(bad, 15, narrated=True, footage=FOOTAGE))
    assert "footage #2, which is not a video" in problems
    assert "outside video #1 (0-20s)" in problems
    assert "keeps the clip's own sound, so its narration must be" in problems
    assert "stock video, which is not available" in problems
    assert 'source "drone"' in problems


def test_a_clip_may_not_repeat_footage_while_some_is_unused():
    """Live, 2026-10-17: five shots cut 0-8, 8-16, 0-8, 8-16, 0-8 of a 25.5 s video."""
    clip = lambda a, b: generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="clip",  # noqa: E731
                                       asset=1, start=a, end=b)
    long = Footage(assets=[{"n": 1, "kind": "video", "seconds": 25.5}])
    problems = validate(_script(clip(0, 8), clip(8, 16), clip(0, 8)), 12, narrated=True, footage=long)
    assert problems == ["shot 3 shows the same part of video #1 as shot 1 (0-8s) while 16-25.5s is unused; "
                        "cut a different window"]
    short = Footage(assets=[{"n": 1, "kind": "video", "seconds": 9.0}])     # nothing else to show: a repeat is fine
    assert validate(_script(clip(0, 8), clip(1, 9)), 8, narrated=True, footage=short) == []


def test_the_writer_sees_the_footage_with_times_and_words():
    assets = [{**FOOTAGE.assets[0], "has_audio": True, "analysis": {
        "summary": "A bridge sags and falls into the river.",
        "moments": [{"at": 3.0, "what": "the middle span sags"}, {"at": 9.5, "what": "it falls"}],
        "transcript": [{"start": 9.6, "end": 11.0, "text": "oh my god"}], "logos_or_watermarks": True,
        "logo_names": ["News 24"]}}, FOOTAGE.assets[1]]
    text = footage_.prompt_section(Footage(assets=assets, stock=True), narrated=True)
    assert "1. video, 20.0 s, landscape 1280×720, own sound: yes — u/a on r/b" in text
    assert "0:03.0 the middle span sags" in text and '0:09.6–0:11.0 "oh my god"' in text
    assert "logo or watermark (News 24)" in text and '"stock"' in text and "2. picture" in text
    none = footage_.prompt_section(Footage(assets=[], stock=False), narrated=True)
    assert '"generate": the AI video model renders' in none and '"chart"' in none
    assert "Footage you may use" not in none
    s = _script(generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="clip", asset=3))
    footage_.normalize(s, Footage(assets=[], stock=False))
    assert (s.shots[0].source, s.shots[0].asset) == ("generate", 0)


def test_publishing_carries_the_credits_and_says_whether_anything_is_generated():
    meta = youtube.metadata("T", "What happened.", ["#shorts"], "25", credits=["u/a on r/b", "Video by C on Pexels"],
                            synthetic=False)
    assert meta["snippet"]["description"] == ("What happened.\n\nFootage: u/a on r/b · Video by C on Pexels"
                                              "\n\n#shorts")
    assert meta["status"]["containsSyntheticMedia"] is False
    cap = instagram.caption("T", "D", ["#news"], ["u/a on r/b"])
    assert cap.index("Footage: u/a on r/b") < cap.index("#news")


# ── a whole reel ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def media(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("footage")

    def ff(*a):
        subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)
    ff("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "8",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(d / "land.mp4"))
    ff("-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=25", "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
       str(d / "stock.mp4"))
    ff("-f", "lavfi", "-i", "testsrc2=size=1600x900", "-frames:v", "1", str(d / "pic.jpg"))
    return {"video": d / "land.mp4", "stock": d / "stock.mp4", "image": d / "pic.jpg"}


class FootageWriter:
    shots: list = []
    systems: list[str] = []

    def __init__(self, key):
        pass

    def write(self, *, model, system, user):
        FootageWriter.systems.append(system)
        return _script(*FootageWriter.shots), Usage(model, 10, 10)


@pytest.fixture
def footage_post(s3, owner, user, media, monkeypatch):
    """A narrated post whose idea brought a video (#1) and a picture (#2), both fetched."""
    monkeypatch.setattr(write_script, "WRITER_FACTORY", FootageWriter)
    owner.execute("insert into user_keys (user_id, name, ciphertext) values (%s, 'pexels_api_key', %s)",
                  (user, encrypt("pexels-test-key")))
    slot = date(2034, 1, 1) + timedelta(days=uuid.uuid4().int % 3000)
    pid = owner.execute("insert into posts (user_id, topic, slot_date, audio_source, target_seconds) "
                        "values (%s, 'Bridge falls in storm', %s, 'kokoro', 10) returning id",
                        (user, slot)).fetchone()["id"]
    for n, kind, path, credit, extra in (
            (1, "video", media["video"], "u/tester on r/videos",
             {"seconds": 8.0, "has_audio": True, "w": 1280, "h": 720,
              "analysis": {"summary": "a bridge falls", "transcript": [{"start": 1.0, "end": 2.5, "text": "look"}]}}),
            (2, "image", media["image"], "news.test", {"w": 1600, "h": 900, "analysis": {"summary": "the river"}})):
        aid = owner.execute("""insert into assets (user_id, post_id, n, kind, origin, credit, rights, state, w, h,
                                                   seconds, has_audio, analysis)
                               values (%s, %s, %s, %s, 'reddit', %s, 'approved', 'ready', %s, %s, %s, %s, %s)
                               returning id""",
                            (user, pid, n, kind, credit, extra["w"], extra["h"], extra.get("seconds"),
                             extra.get("has_audio", False), json.dumps(extra["analysis"]))).fetchone()["id"]
        key = f"u/{user}/posts/{pid}/assets/{aid}.{'mp4' if kind == 'video' else 'jpg'}"
        storage.put_file(key, path, kind="asset", user_id=user, post_id=pid,
                         content_type="video/mp4" if kind == "video" else "image/jpeg")
        owner.execute("update assets set key = %s where id = %s", (key, aid))
    return pid


@pytest.fixture
def pexels(monkeypatch, media):
    body = {"videos": [{"id": 77, "duration": 10, "url": "https://www.pexels.test/video/77/",
                        "user": {"name": "Pexels Tester"},
                        "video_files": [{"file_type": "video/mp4", "width": 720, "height": 1280,
                                         "link": "https://videos.pexels.test/77.mp4"}]}]}
    searches = []

    def search(req):
        searches.append((req.url.params["query"], req.headers.get("authorization")))
        return httpx.Response(200, json=body)
    table = {"https://api.pexels.com/videos/search": search,
             "https://videos.pexels.test/77.mp4": httpx.Response(200, content=media["stock"].read_bytes(),
                                                                 headers={"content-type": "video/mp4"})}
    monkeypatch.setattr(prepare_shot.httpx, "Client", lambda **kw: _routes(table))
    return searches


def cpu_footage() -> Runner:
    return Runner("cpu", {"write_script": write_script.HANDLER, "plan_shots": plan_shots.HANDLER,
                          "narrate": narrate.HANDLER, "prepare_shot": prepare_shot.HANDLER,
                          "build_segment": build_segment.HANDLER, "assemble": assemble.HANDLER})


def _approve(owner, user, pid) -> str:
    as_user(owner, user, "select api.generate_script(%s)", (pid,))
    assert drain(cpu_footage()) == ["write_script"]
    sid = owner.execute("select id from scripts where post_id = %s", (pid,)).fetchone()["id"]
    as_user(owner, user, "select api.approve_script(%s)", (sid,))
    return sid


def test_a_reel_of_footage_is_made_without_a_gpu(s3, owner, user, footage_post, pexels, tmp_path):
    pid = footage_post
    FootageWriter.systems = []
    FootageWriter.shots = [
        generated_shot(seconds=3, visual="the span falls", audio="", narration="", source="clip", asset=1,
                       start=0.5, end=3.5, keep_audio=True),
        generated_shot(seconds=4, visual="the river", audio="", narration=LINE, source="image", asset=2),
        generated_shot(seconds=4, visual="traffic", audio="", narration=LINE, source="stock",
                       stock_query="city traffic at night")]
    sid = _approve(owner, user, pid)
    assert "## Footage you may use" in FootageWriter.systems[0] and "u/tester on r/videos" in FootageWriter.systems[0]
    assert drain(cpu_footage()) == ["plan_shots", "narrate"]
    shots = owner.execute("""select idx, source, num_frames, narration, narration_key, audio_mode, asset_id is not null
                                    as has_asset from shots where script_id = %s order by idx""", (sid,)).fetchall()
    assert [s["source"] for s in shots] == ["clip", "image", "stock"]
    assert shots[0]["num_frames"] == 72 and shots[0]["narration"] is None and shots[0]["audio_mode"] == "keep"
    assert shots[1]["num_frames"] == round((0.3 * 11 + narrate.PAUSE_SECONDS) * 24)       # exact, not 8n+1
    assert shots[2]["audio_mode"] == "mute" and shots[2]["narration_key"]

    job = as_user(owner, user, "select * from api.request_render(%s)", (pid,))
    assert (job["lane"], job["kind"]) == ("cpu", "prepare_shot")
    jobs = owner.execute("select lane, kind, state from jobs where post_id = %s and kind in "
                         "('render_post','prepare_shot','assemble') order by kind", (pid,)).fetchall()
    assert [(j["kind"], j["state"]) for j in jobs] == [("assemble", "blocked")] + [("prepare_shot", "queued")] * 3
    ran = drain(cpu_footage())
    assert ran.count("prepare_shot") == 3 and ran.count("build_segment") == 3 and ran[-1] == "assemble"
    p = owner.execute("select status, final_key, final_duration_s, credits from posts where id = %s", (pid,)).fetchone()
    assert p["status"] == "ready"
    assert p["credits"] == ["u/tester on r/videos", "news.test", "Video by Pexels Tester on Pexels"]
    total = sum(s["num_frames"] for s in owner.execute("select num_frames from shots where script_id = %s", (sid,)))
    assert float(p["final_duration_s"]) == pytest.approx(total / 24, abs=0.05)
    assert pexels == [("city traffic at night", "pexels-test-key")]
    assert owner.execute("select count(*) as n from jobs where post_id = %s and lane = 'gpu'", (pid,)).fetchone()["n"] == 0
    final = storage.get_file(p["final_key"], tmp_path / "final.mp4")
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
                              "-of", "csv=p=0", str(final)], capture_output=True, text=True).stdout
    assert "video,1080,1920" in streams and "audio" in streams


def test_withdrawn_footage_is_never_rendered(s3, owner, user, footage_post):
    pid = footage_post
    FootageWriter.shots = [
        generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="image", asset=2),
        generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="image", asset=2)]
    _approve(owner, user, pid)
    drain(cpu_footage())                                               # plan + narrate
    owner.execute("update assets set rights = 'rejected' where post_id = %s and n = 2", (pid,))
    with pytest.raises(Exception, match="shot 1 uses footage that is not approved"):
        as_user(owner, user, "select api.request_render(%s)", (pid,))


def test_a_mixed_reel_waits_for_both_the_gpu_and_the_footage(s3, owner, user, footage_post, gpu):
    pid = footage_post
    FootageWriter.shots = [
        generated_shot(seconds=4, visual="a calm river at dawn", audio="birds", narration=LINE),
        generated_shot(seconds=4, visual="the river", audio="", narration=LINE, source="image", asset=2)]
    sid = _approve(owner, user, pid)
    drain(cpu_footage())
    job = as_user(owner, user, "select * from api.request_render(%s)", (pid,))
    assert (job["lane"], job["kind"]) == ("gpu", "render_post")
    assert drain(cpu_footage()) == ["prepare_shot", "build_segment"]         # the footage shot; assembly waits
    assert owner.execute("select state from jobs where kind = 'assemble' and post_id = %s",
                         (pid,)).fetchone()["state"] == "blocked"
    assert Runner("gpu", {"render_post": render_post.HANDLER}).tick()
    assert gpu.rendered == [0]                                               # only the generated shot
    assert drain(cpu_footage()) == ["build_segment", "assemble"]
    p = owner.execute("select status, credits from posts where id = %s", (pid,)).fetchone()
    assert p["status"] == "ready" and p["credits"] == ["news.test"]
    assert owner.execute("select count(*) as n from shots where script_id = %s and state = 'uploaded'",
                         (sid,)).fetchone()["n"] == 2


def test_a_failed_footage_shot_keeps_assembly_waiting(s3, owner, user, footage_post, monkeypatch):
    pid = footage_post
    FootageWriter.shots = [
        generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="image", asset=2),
        generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="stock", stock_query="rain")]
    _approve(owner, user, pid)
    drain(cpu_footage())
    owner.execute("delete from user_keys where user_id = %s and name = 'pexels_api_key'", (user,))   # stock fails
    as_user(owner, user, "select api.request_render(%s)", (pid,))
    drain(cpu_footage())
    p = owner.execute("select status, error from posts where id = %s", (pid,)).fetchone()
    assert p["status"] == "failed" and "Pexels API key" in p["error"]["message"]
    assert owner.execute("select state from jobs where kind = 'assemble' and post_id = %s",
                         (pid,)).fetchone()["state"] == "blocked"


# ── fetching and logging a post's footage ─────────────────────────────────────

class FakeLogger:
    def __init__(self, key):
        pass

    def analyze(self, model, sheet, title, times=None, transcript=""):
        assert sheet.stat().st_size > 0 and (times is None or len(times) == 16)
        return (FootageAnalysis(summary="A bridge falls.", moments=[Moment(at=2.0, what="it sags")] if times else [],
                                on_screen_text=[], logos_or_watermarks=False, logo_names=[], identifiable_people=False,
                                graphic=False), Usage(model, 900, 80))


def test_accepted_footage_is_fetched_whole_then_logged(s3, owner, user, media, monkeypatch, tmp_path):
    monkeypatch.setattr(analyze_asset, "VISION", FakeLogger)
    monkeypatch.setattr(analyze_asset, "TRANSCRIBE", lambda path: [{"start": 0.5, "end": 1.5, "text": "look at it"}])
    owner.execute("update app_settings set vision_model = 'gpt-4.1-nano' where user_id = %s", (user,))
    ch = owner.execute("insert into channels (user_id, name) values (%s, 'n') returning id", (user,)).fetchone()["id"]
    owner.execute("insert into formats (user_id, channel_id, name, idea_prompt, script_prompt, is_default) "
                  "values (%s, %s, 'f', 'i', 's', true)", (user, ch))
    cat = owner.execute("select id from categories where channel_id = %s", (ch,)).fetchone()["id"]
    preview = f"u/{user}/ideas/x/image.jpg"
    storage.put_file(preview, media["image"], kind="idea_media", user_id=user, content_type="image/jpeg")
    items = [{"title": "Bridge", "url": "https://m.test/@a/1", "media_hint": "video", "platform": "mastodon",
              "author": "@a@m.test", "video_url": "https://files.m.test/b.mp4"},
             {"title": "River", "url": "https://l.test/post/2", "media_hint": "image", "platform": "lemmy",
              "image_url": "https://img.l.test/gone.jpg"}]
    media_json = [{"type": "video", "key": "u/x/v.mp4", "w": 270, "h": 480, "seconds": 3, "has_audio": True,
                   "origin": "mastodon", "source_url": "https://m.test/@a/1", "credit": "@a@m.test on Mastodon"},
                  {"type": "image", "key": preview, "w": 640, "h": 360, "origin": "lemmy",
                   "source_url": "https://l.test/post/2", "credit": "u/x on c/pics"}]
    iid = owner.execute("""insert into ideas (user_id, channel_id, category_id, title, brief, items, media, media_state)
                           values (%s, %s, %s, 'Bridge falls', 'b', %s, %s, 'ready') returning id""",
                        (user, ch, cat, json.dumps(items), json.dumps(media_json))).fetchone()["id"]
    as_user(owner, user, "select api.decide_idea_v2(%s, true, now() + interval '1 day', null, null, true)", (iid,))
    post = owner.execute("select id, media_choice from posts where id = (select post_id from ideas where id = %s)",
                         (iid,)).fetchone()
    assets = owner.execute("select id, n, kind, rights, state, credit from assets where post_id = %s order by n",
                           (post["id"],)).fetchall()
    assert post["media_choice"] == "original"
    assert [(a["kind"], a["rights"], a["state"]) for a in assets] == [("video", "approved", "pending"),
                                                                       ("image", "approved", "pending")]
    table = {"https://files.m.test/b.mp4": httpx.Response(200, content=media["video"].read_bytes(),
                                                          headers={"content-type": "video/mp4"}),
             "https://img.l.test/": httpx.Response(404)}
    monkeypatch.setattr(fetch_asset.httpx, "Client", lambda **kw: _routes(table))
    ideas = Runner("ideas", {"fetch_asset": fetch_asset.HANDLER})
    assert drain(ideas) == ["fetch_asset", "fetch_asset"]
    assert drain(Runner("cpu", {"analyze_asset": analyze_asset.HANDLER})) == ["analyze_asset", "analyze_asset"]
    got = {a["n"]: a for a in owner.execute("select n, state, key, w, h, seconds, has_audio, analysis, error "
                                            "from assets where post_id = %s", (post["id"],)).fetchall()}
    v, im = got[1], got[2]
    assert v["state"] == "ready" and (v["w"], v["h"]) == (1280, 720) and float(v["seconds"]) == pytest.approx(8, abs=0.1)
    assert v["analysis"]["transcript"][0]["text"] == "look at it" and v["analysis"]["moments"][0]["at"] == 2.0
    assert im["state"] == "ready" and "card's preview" in im["error"] and (im["w"], im["h"]) == (1600, 900)
    costs = owner.execute("select note from costs where post_id = %s", (post["id"],)).fetchall()
    assert [c["note"] for c in costs] == ["footage log", "footage log"]


def test_a_published_reels_footage_is_swept_after_two_weeks(s3, owner, user, footage_post):
    pid = footage_post
    owner.execute("update posts set status = 'published' where id = %s", (pid,))
    owner.execute("""insert into post_events (post_id, from_state, to_state, actor, reason, at)
                     values (%s, 'scheduled', 'published', 'system', 'posted', now() - interval '15 days')""", (pid,))
    assert sweep.sweep_assets(lambda m: None) >= 2
    rows = owner.execute("select key, error from assets where post_id = %s", (pid,)).fetchall()
    assert all(r["key"] is None and "removed after publishing" in r["error"] for r in rows)


def test_a_picture_shot_may_hold_a_line_longer_than_a_generated_shot(s3, owner, user, footage_post, monkeypatch):
    """Live, 2026-10-17: a 13.8 s line on a picture shot failed narration against the
    12 s limit of a generated (LTX) shot; footage shots hold up to MAX_CLIP_SECONDS."""
    from corpus.handlers import narrate as narrate_
    from test_render_pipeline import fake_speak

    def slow(text, voice, speed, out):
        fake_speak(text, voice, speed, out)
        return 13.8
    monkeypatch.setattr(narrate_, "SPEAK", slow)
    FootageWriter.shots = [generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="image", asset=2),
                           generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="image", asset=2)]
    sid = _approve(owner, user, footage_post)
    drain(cpu_footage())
    rows = owner.execute("select num_frames, narration_key from shots where script_id = %s", (sid,)).fetchall()
    assert all(r["narration_key"] for r in rows) and {r["num_frames"] for r in rows} == {round((13.8 + 0.35) * 24)}
