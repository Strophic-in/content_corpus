"""Templates: the registry, the scripts each asks for, how they render, carousels
and cards (slides, slideshow, Instagram), the agent's pick of a format, websites
without feeds, and the owner's uploads.

ffmpeg, Pillow, the queue and the schema are real; S3 is moto, OpenAI and
Instagram are stand-ins, media are synthetic.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from PIL import Image
from psycopg.types.json import Jsonb

from corpus import db, storage, templates
from corpus.handlers import fetch_asset, plan_shots, render_slides, suggest_ideas, write_script
from corpus.ideas import sites, sources
from corpus.ideas.agent import Idea, IdeasOut
from corpus.media import assemble, footage, overlays, slides
from corpus.publish import instagram
from corpus.runner import Runner
from corpus.script import carousel as carousel_
from corpus.script import structure
from corpus.script.llm import Footage, Review, ScriptOut, Usage, generated_shot, validate
from test_render_pipeline import as_user, drain, owner, s3, user  # noqa: F401
from test_sources_media import _routes, public_dns  # noqa: F401


def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)


def frames(p: Path) -> int:
    return assemble._frames(p)


def _s(*shots) -> ScriptOut:
    return ScriptOut(title="t", hook="h", description="d", hashtags=["#shorts"], intended_dialogue="",
                     style_prompt="", shots=list(shots), music_mood="", review=Review(score=8, risks=[], notes=""))


def shot(**kw):
    return generated_shot(**{"seconds": 4, "visual": "v", "audio": "", "narration": "", **kw})


# ── the registry ──────────────────────────────────────────────────────────────

def test_every_template_loads_and_the_database_knows_each_one(owner):
    reg = templates.registry()
    assert len(reg) == 22
    rows = {r["template_id"]: r["content_type"] for r in owner.execute("select * from templates").fetchall()}
    assert rows == {k: t.content_type for k, t in reg.items()}
    for t in reg.values():
        assert t.guide.startswith("## Template:") and (templates.settings().prompts_dir / t.base_prompt).exists()
        assert all(m in templates.MOODS for m in t.music_mood)
    assert {t.template_id for t in reg.values() if not t.ai_pick} == {
        "podcast_interview_clip", "screen_recording_tutorial", "photo_dump_collage"}


def test_a_broken_template_is_an_error_not_skipped(tmp_path, monkeypatch):
    good = templates.templates_dir() / "seamless_loop.json"
    bad = json.loads(good.read_text(encoding="utf-8"))
    bad["render"]["transition"] = "whip"                     # not one of its own transitions
    (tmp_path / "seamless_loop.json").write_text(json.dumps(bad), encoding="utf-8")
    (tmp_path / "seamless_loop.md").write_text("## Template: x", encoding="utf-8")
    monkeypatch.setattr(templates, "templates_dir", lambda: tmp_path)
    templates.registry.cache_clear()
    try:
        with pytest.raises(templates.TemplateError, match="default transition whip"):
            templates.registry()
    finally:
        monkeypatch.undo()
        templates.registry.cache_clear()


def test_params_are_checked_and_resolve_into_a_look():
    kept, problems = templates.clean_params({"transition": "whip", "accent_color": "red", "slide_count": 3, "x": 1},
                                            templates.get("ranked_countdown"))
    assert kept == {"transition": "whip"}
    assert any("accent_color" in p for p in problems) and any("slide_count" in p for p in problems)
    lk = templates.look("educational_carousel", {"slide_count": 6, "slide_aspect": "1:1", "brand_text": "@x"})
    assert (lk.slides.count, lk.slides.aspect, lk.brand_text) == ((6, 6), "1:1", "@x")
    assert templates.look("top_bottom_split_screen").layout == "split"
    assert templates.look("seamless_loop").loop and templates.look("kinetic_typography").captions == "kinetic"


# ── the scripts templates ask for ─────────────────────────────────────────────

def _check(tid: str, out: ScriptOut, audio: str = "kokoro", target: int = 12, fp: Footage | None = None):
    t = templates.get(tid)
    lk = templates.look(tid)
    structure.normalize(out, t, lk, audio)
    return validate(out, target, narrated=audio == "kokoro", dialogue=audio == "ltx_native", footage=fp,
                    template=t, look=lk)


def test_text_beats_are_required_and_must_fit_and_be_readable():
    out = _s(shot(role="hook", source="plain", seconds=4, text="Octopuses have three hearts."),
             shot(role="beat", source="plain", seconds=4, text=""),
             shot(role="reveal", source="plain", seconds=4, text=" ".join(["unbelievably"] * 30)))
    problems = " | ".join(_check("full_screen_text_overlay", out, audio="none"))
    assert "shots 2 have no text" in problems and "shot 3's text is too long to fit" in problems
    out = _s(shot(role="hook", source="plain", seconds=3, text="One two three four five six seven eight nine ten"))
    assert any("on screen for 3s" in p for p in _check("full_screen_text_overlay", out, audio="none", target=3))


def test_myth_needs_fact_and_a_countdown_counts_down_to_one():
    myth = _s(shot(role="myth", label="Myth", text="We use 10% of our brain", narration="You have heard this."),
              shot(role="evidence", label="", narration="Scans show every part at work."))
    assert any("Fact" in p for p in _check("myth_vs_fact", myth, target=8))
    myth.shots[1].label = "Fact"
    assert _check("myth_vs_fact", myth, target=8) == []
    up = _s(*(shot(role="item", label=f"#{n}", text="x", narration="Number this one.") for n in (1, 2, 3)))
    assert any("count down by one to #1" in p for p in _check("ranked_countdown", up))
    down = _s(*(shot(role="item", label=f"#{n}", text="x", narration="Number this one.") for n in (3, 2, 1)))
    assert _check("ranked_countdown", down) == []


def test_fields_a_template_does_not_draw_are_emptied_and_others_checked():
    out = _s(shot(role="Hook", source="plain", seconds=4, text="A beat", label="Myth", layout="split",
                  focus={"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}, timelapse=True, transition="zoom"))
    _check("full_screen_text_overlay", out, audio="none", target=4)
    s = out.shots[0]
    assert (s.role, s.label, s.layout, s.focus.w, s.timelapse, s.transition) == ("hook", "", "", 0, False, "")
    gen = _s(shot(role="hook", source="stock", stock_query="sky", narration="Look up."))
    assert any('source "stock"' in p for p in _check("pov_immersive_scenario", gen, audio="none", target=4)) is False
    loud = _s(shot(role="pov_hook", text="POV: you are late", audio='He shouts "run"'))
    assert any("nobody speaks in this format" in p for p in _check("pov_immersive_scenario", loud, audio="none",
                                                                     target=4))


def test_the_writer_is_told_its_template_and_its_voice():
    t, lk = templates.get("ranked_countdown"), templates.look("ranked_countdown")
    text = structure.writer_section(t, lk, "kokoro")
    assert "## Template: Ranked List / Countdown" in text and "`label`: a 1-2 word chip" in text
    assert "how the shot begins" in text and "whip" in text and "Use only these shot sources" in text
    assert "no voice" in structure.voice_rules("none", 20, 2.8) and "at most 20 words" in structure.voice_rules(
        "kokoro", 20, 2.8)


# ── carousels and cards ───────────────────────────────────────────────────────

def _slide(heading="A heading", body="A short body.", source="none", **v) -> carousel_.Slide:
    visual = {"source": source, "asset": 0, "prompt": "", "chart": {"kind": "", "title": "", "labels": [],
                                                                    "values": [], "unit": ""}, **v}
    return carousel_.Slide(role="concept", heading=heading, body=body, visual=carousel_.SlideVisual(**visual))


def _deck(*slides_) -> carousel_.CarouselOut:
    return carousel_.CarouselOut(title="t", hook="h", description="d", hashtags=["#x"], slides=list(slides_),
                                 music_mood="", review=Review(score=8, risks=[], notes=""))


def test_a_carousel_must_have_its_slides_and_fit_them():
    t, lk = templates.get("educational_carousel"), templates.look("educational_carousel")
    fp = Footage(assets=[{"n": 1, "kind": "image", "credit": "x"}])
    few = _deck(_slide(), _slide())
    assert any("make 5-8 slides" in p for p in carousel_.problems(few, t, lk, fp))
    deck = _deck(_slide(source="ai_image", prompt="a phone glowing"), _slide(source="asset", asset=1),
                 _slide(source="ai_image", prompt="more"), _slide(heading=" ".join(["Battery"] * 40)),
                 _slide(source="chart", chart={"kind": "bar", "title": "Use", "labels": ["a", "b"], "values": [3, 1],
                                               "unit": "%"}))
    problems = " | ".join(carousel_.problems(deck, t, lk, fp))
    assert "slide 3 asks for an AI picture" in problems and "slide 4: the heading is too long" in problems
    deck.slides[2] = _slide()
    deck.slides[3] = _slide()
    assert carousel_.problems(deck, t, lk, fp) == []


def test_slides_are_drawn_in_each_layout(tmp_path):
    pic = tmp_path / "pic.jpg"
    ff("-f", "lavfi", "-i", "testsrc2=s=1600x1000", "-frames:v", "1", str(pic))
    edu = templates.look("educational_carousel", {"brand_text": "@x"})
    s = {"heading": "Five things", "body": "Number four surprised us.", "visual": {"source": "asset"}}
    out = slides.render(s, 0, 5, layout="educational", look=edu, out=tmp_path / "a.jpg", picture=pic, credit="c")
    assert Image.open(out).size == (1080, 1350)
    chart = {"heading": "Use", "body": "", "visual": {"source": "chart", "chart": {
        "kind": "line", "title": "GW", "labels": ["2019", "2022", "2025"], "values": [35, 60, 105], "unit": ""}}}
    square = templates.look("educational_carousel", {"slide_aspect": "1:1"})
    assert Image.open(slides.render(chart, 2, 5, layout="educational", look=square,
                                    out=tmp_path / "b.jpg")).size == (1080, 1080)
    card = templates.look("picture_above_text_below")
    out = slides.render({"heading": "Court bans syrup", "body": "Three brands.", "visual": {}}, 0, 1, layout="card",
                        look=card, out=tmp_path / "c.jpg", picture=pic, credit="Reuters")
    assert Image.open(out).getpixel((540, 1300))[:3] == (15, 23, 42)       # the card's background below the text
    with pytest.raises(slides.Overflow):
        slides.plan({"heading": "word " * 200, "body": ""}, 1, 5, "educational", "4:5", "Montserrat", False)


# ── what templates draw ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def clip(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("tpl")
    p = d / "clip.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=s=704x1280:r=24:d=2", "-f", "lavfi", "-i", "sine=d=2", "-shortest",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p))
    return p


def test_a_split_screen_with_a_rank_and_headline_keeps_every_frame(clip, tmp_path):
    lk = templates.look("ranked_countdown", {"panel_color": "#102030"})
    v, a = tmp_path / "s.mp4", tmp_path / "s.wav"
    assemble.build_segment(clip, v, a, words=[(0.2, 0.8, "Number"), (0.8, 1.4, "two.")], look=lk,
                           extras={"label": "#2", "text": "Ladakh in winter", "layout": "split"})
    assert frames(v) == frames(clip)
    png = tmp_path / "f.png"
    ff("-ss", "1.5", "-i", str(v), "-frames:v", "1", str(png))
    r, g, b = Image.open(png).convert("RGB").getpixel((8, 1910))
    assert abs(r - 0x10) < 8 and abs(g - 0x20) < 8 and abs(b - 0x30) < 8     # the bottom panel
    events = overlays.label("#2", lk, 2.0) + overlays.headline("Ladakh in winter", lk, 2.0, True)
    assert "#2" in events[0] and "Ladakh in winter" in events[1]


def test_text_beats_sit_at_the_bottom_under_what_the_picture_says():
    """Live 2026-10-24: a beat in the middle wrote over a headline card's headline."""
    lk = templates.look("full_screen_text_overlay")
    assert lk.caption_position == "bottom"
    line = "Amber warning issued as Storm Boelo approaches"
    low = overlays.beat(line, lk, 3.0, split=False)[0]
    assert rf"\an2\pos(540,{overlays.LOW_BOTTOM})" in low
    assert r"\an5\pos(540,1440)" in overlays.beat(line, lk, 3.0, split=True)[0]      # a split: its panel
    assert r"\an5\pos(540,960)" in overlays.beat(line, lk, 3.0, split=False, bare=True)[0]   # plain: middle
    mid = lk.model_copy(update={"caption_position": "middle"})
    assert r"\an5\pos(540,960)" in overlays.beat(line, mid, 3.0, split=False)[0]
    assert r"\an2" in overlays.kinetic(overlays.even_words("Storm BOELO", 2.0), lk, 2.0, split=False)[0]
    # The script check measures a bottom beat in its smaller space: 5 lines fit the middle, not the bottom.
    long = "Amber warnings now cover most of Scotland, Northern Ireland and northern England through Sunday night"
    out = _s(shot(role="hook", source="image", asset=1, seconds=12, text=long))
    fp = Footage(assets=[{"n": 1, "kind": "image", "w": 1080, "h": 1920, "credit": "x"}])
    assert any("text is too long to fit on screen (3 lines)" in p
               for p in _check("full_screen_text_overlay", out, audio="none", target=12, fp=fp))
    out.shots[0].source, out.shots[0].asset = "plain", 0
    assert not any("too long to fit" in p for p in _check("full_screen_text_overlay", out, audio="none", target=12))


def test_a_voice_longer_than_its_picture_slows_the_picture_to_hold_it(clip, tmp_path):
    nar = tmp_path / "nar.wav"
    ff("-f", "lavfi", "-i", "sine=f=300:d=1.9", str(nar))          # 1.9 s of voice over a 2 s picture
    out = assemble.build_segment(clip, tmp_path / "v.mp4", tmp_path / "a.wav", narration=nar)
    assert out["seconds"] == pytest.approx(2.25, abs=0.05)         # 1.9 + lead-in + tail: 12% slower
    assert assemble.probe_duration(tmp_path / "a.wav") == pytest.approx(out["seconds"], abs=0.05)
    long = tmp_path / "long.wav"
    ff("-f", "lavfi", "-i", "sine=f=300:d=4", str(long))
    assert assemble.build_segment(clip, tmp_path / "v2.mp4", tmp_path / "a2.wav",
                                  narration=long)["seconds"] == pytest.approx(2.3, abs=0.05)   # capped


def test_transitions_blend_and_a_loop_keeps_its_length(clip, tmp_path):
    lk = templates.look("kinetic_typography")
    segs = []
    for k in range(3):
        v, a = tmp_path / f"{k}.mp4", tmp_path / f"{k}.wav"
        assemble.build_segment(clip, v, a, look=lk, extras={"text": f"WORD {k}"})
        segs.append((v, a))
    each = frames(segs[0][0])
    out = tmp_path / "joined.mp4"
    info = assemble.join_segments(segs, out, transitions=["", "whip", "fade"])
    whip, fade = assemble.XFADE["whip"][1], assemble.XFADE["fade"][1]
    assert info["join"] == "blend" and frames(out) == 3 * each - whip - fade
    looped = tmp_path / "loop.mp4"
    assemble.join_segments(segs[:2], looped, transitions=["", "crossfade"], loop=True)
    assert frames(looped) == 2 * each - assemble.XFADE["crossfade"][1]
    cuts = assemble.join_segments(segs, tmp_path / "cuts.mp4", transitions=["", "cut", ""])
    assert cuts["join"] == "copy"


def test_plain_backgrounds_punch_ins_timelapses_and_charts(tmp_path):
    src = tmp_path / "src.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=12", "-pix_fmt", "yuv420p", str(src))
    (tmp_path / "p").mkdir()
    info = footage.plain(tmp_path / "p" / "o.mp4", seconds=2, look=templates.look("kinetic_typography"))
    assert info["frames"] == 48
    (tmp_path / "t").mkdir()
    lapse = footage.compose_clip(src, tmp_path / "t" / "o.mp4", seconds=2, start=0, end=10, timelapse=True)
    assert lapse["speed"] == 5.0 and not lapse["sound"] and frames(tmp_path / "t" / "o.mp4") == 48
    (tmp_path / "f").mkdir()
    half = footage.compose_clip(src, tmp_path / "f" / "o.mp4", seconds=1, size=(1080, 960),
                                focus={"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5})
    assert half["focus"] and footage.info(tmp_path / "f" / "o.mp4").h == 960
    for kind, labels, values in (("stat", ["people"], [1.4e6]), ("compare", ["a", "b"], [3, 9]),
                                 ("line", ["1", "2", "3"], [1, 4, 2]), ("bar", ["a", "b"], [5, 2])):
        p = footage.chart_still({"kind": kind, "title": "T", "labels": labels, "values": values, "unit": ""},
                                tmp_path / f"{kind}.png")
        assert Image.open(p).size == (1080, 1920)


# ── a carousel post, end to end ───────────────────────────────────────────────

class CarouselWriter:
    calls = 0

    def __init__(self, api_key):
        pass

    def write(self, *, model, system, user):
        CarouselWriter.calls += 1
        assert "## Template: Educational Carousel" in system and "5-8 slides" in system
        deck = _deck(_slide(heading="5 settings that drain your battery", source="ai_image", prompt="a tired phone"),
                     _slide(heading="Always-on display"), _slide(heading="Background refresh"),
                     _slide(heading="Battery used", source="chart",
                            chart={"kind": "bar", "title": "Overnight", "labels": ["on", "off"], "values": [14, 4],
                                   "unit": "%"}),
                     _slide(heading="Check tonight", body="Which one surprised you?"))
        deck.slides[0].role = "cover"
        return deck, Usage(model, 300, 200)


class FakeImages:
    calls = 0

    def __init__(self, key):
        pass

    def generate(self, *, model, prompt, quality):
        FakeImages.calls += 1
        assert "No text" in prompt and "a tired phone" in prompt
        out = Path(prompt and __file__).parent / "_drawn.png"
        Image.new("RGB", (1024, 1536), (40, 90, 160)).save(out)
        data = out.read_bytes()
        out.unlink()
        return data, Usage(model, 50, 4000)


def _channel_with(owner, uid, *templates_) -> tuple:
    ch = owner.execute("insert into channels (user_id, name) values (%s, %s) returning id",
                       (uid, f"ch-{uuid.uuid4().hex[:6]}")).fetchone()["id"]
    ids = [owner.execute("""insert into formats (user_id, channel_id, name, idea_prompt, script_prompt, template_id)
                            values (%s, %s, %s, 'Find ideas about {category_name}. {trends}', '', %s) returning id""",
                         (uid, ch, f"f{k}-{t}"[:60], t)).fetchone()["id"] for k, t in enumerate(templates_)]
    return ch, ids


def test_a_carousel_is_written_drawn_and_made_into_a_slideshow(s3, owner, user, monkeypatch):
    monkeypatch.setattr(write_script, "CAROUSEL_FACTORY", CarouselWriter)
    monkeypatch.setattr(render_slides, "IMAGES", FakeImages)
    ch, (fid,) = _channel_with(owner, user, "educational_carousel")
    slot = date(2034, 1, 1) + timedelta(days=uuid.uuid4().int % 3000)
    pid = owner.execute("""insert into posts (user_id, channel_id, format_id, topic, slot_date, audio_source)
                           values (%s, %s, %s, 'Battery drain', %s, 'kokoro') returning id""",
                        (user, ch, fid, slot)).fetchone()["id"]
    assert owner.execute("select format, audio_source from posts where id = %s", (pid,)).fetchone() == {
        "format": "carousel", "audio_source": "none"}
    as_user(owner, user, "select api.generate_script(%s)", (pid,))
    cpu = Runner("cpu", {"write_script": write_script.HANDLER, "plan_shots": plan_shots.HANDLER,
                         "render_slides": render_slides.HANDLER})
    drain(cpu)
    sc = owner.execute("select id, slides, shot_plan from scripts where post_id = %s", (pid,)).fetchone()
    assert len(sc["slides"]) == 5 and sc["shot_plan"] == []
    as_user(owner, user, "select api.approve_script(%s)", (sc["id"],))
    drain(cpu)                                                     # plan_shots: nothing to plan for slides
    as_user(owner, user, "select api.request_render(%s)", (pid,))
    assert drain(cpu) == ["render_slides"]
    p = owner.execute("select status, slides, final_key, final_duration_s from posts where id = %s", (pid,)).fetchone()
    assert p["status"] == "ready" and len(p["slides"]) == 5 and p["final_key"].endswith(".mp4")
    assert 15 < float(p["final_duration_s"]) < 40
    assert FakeImages.calls == 1
    assert owner.execute("select count(*) as n from costs where post_id = %s and kind = 'image'",
                         (pid,)).fetchone()["n"] == 1
    # A retry draws nothing again: the AI picture is kept.
    owner.execute("update posts set status = 'approved', final_key = null where id = %s", (pid,))
    render_slides.run(render_slides.JobContext(job={"id": None, "payload": {"script_id": str(sc["id"])}}))
    assert FakeImages.calls == 1


def test_instagram_posts_a_carousel_or_a_picture():
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, dict(httpx.QueryParams(req.content.decode()))
                     if req.method == "POST" else dict(req.url.params)))
        if req.method == "GET" and "fields" in req.url.params and "status_code" in req.url.params["fields"]:
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if req.url.path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "post1"})
        if req.method == "GET":
            return httpx.Response(200, json={"permalink": "https://instagram.test/p/1"})
        return httpx.Response(200, json={"id": f"c{len(seen)}"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    saved = []
    out = instagram.publish(client, token="t", ig_user_id="u", caption="cap", attempt={},
                            save=lambda **f: saved.append(f), sleep=lambda s: None,
                            image_urls=["https://r2.test/1.jpg", "https://r2.test/2.jpg"])
    assert out["remote_id"] == "post1"
    posts = [b for m, path, b in seen if m == "POST" and path.endswith("/media")]
    assert [b.get("is_carousel_item") for b in posts[:2]] == ["true", "true"]
    assert posts[2]["media_type"] == "CAROUSEL" and posts[2]["children"].count(",") == 1
    seen.clear()
    instagram.publish(client, token="t", ig_user_id="u", caption="cap", attempt={}, save=lambda **f: None,
                      sleep=lambda s: None, image_urls=["https://r2.test/card.jpg"])
    first = next(b for m, path, b in seen if m == "POST" and path.endswith("/media"))
    assert first["image_url"] == "https://r2.test/card.jpg" and "media_type" not in first


# ── the agent picks a format ──────────────────────────────────────────────────

class PickingWriter:
    system = ""

    def __init__(self, key):
        pass

    def write(self, *, model, system, user):
        PickingWriter.system = system
        return IdeasOut(ideas=[
            Idea(title="Five battery myths", hook="h", brief="b", why_now="w", items=[], format=2,
                 format_why="a list reads well as slides"),
            Idea(title="Why phones get hot", hook="h", brief="b", why_now="w", items=[], format=1, format_why="x")]), \
            Usage(model, 100, 50)


def test_the_agent_picks_a_format_for_each_idea(owner, user, monkeypatch):
    monkeypatch.setattr(suggest_ideas, "WRITER_FACTORY", PickingWriter)
    monkeypatch.setattr(suggest_ideas, "FETCH", lambda rows, **kw: ([], []))
    monkeypatch.setattr(suggest_ideas, "EMBED", lambda texts: [__import__("numpy").eye(8)[k] for k in range(len(texts))])

    class Mem:
        def nearest(self, channel, v):
            return 0.0, ""

        def remember(self, rows):
            pass

        def forget(self, ids):
            pass

    monkeypatch.setattr(suggest_ideas, "MEMORY", lambda log: Mem())
    ch, (reel, slides_, podcast) = _channel_with(owner, user, "cinematic_3d_explainer", "educational_carousel",
                                                 "podcast_interview_clip")
    cat = owner.execute("""insert into categories (user_id, channel_id, name, format_ids, ideas_per_batch)
                           values (%s, %s, 'Tech', %s, 2) returning id""",
                        (user, ch, [reel, slides_, podcast])).fetchone()["id"]
    suggest_ideas.run(suggest_ideas.JobContext(job={"id": None, "payload": {"category_id": str(cat)}}))
    assert "## Formats you can make an idea in" in PickingWriter.system
    assert "Educational Carousel" in PickingWriter.system and "Podcast" not in PickingWriter.system  # owner's pick
    rows = {r["title"]: r for r in owner.execute("select title, format_id, format_why from ideas where category_id = %s",
                                                 (cat,)).fetchall()}
    assert rows["Five battery myths"]["format_id"] == slides_
    assert rows["Five battery myths"]["format_why"] == "a list reads well as slides"
    assert rows["Why phones get hot"]["format_id"] == reel


# ── a website without a feed ──────────────────────────────────────────────────

def test_a_website_without_a_feed_gives_its_homepage_headlines(public_dns):
    home = ("<html><nav><a href='/about-us-and-more'>About the people who write this site</a></nav>"
            "<article><h2><a href='/2026/10/dam-release-what-we-know'>Dam release: what we know about the flood</a>"
            "</h2></article><a href='https://elsewhere.test/a-long-story-path'>Someone else's long story here</a>"
            "<a href='/news/markets-close-higher-today'>Markets close higher as the bank holds rates</a></html>")
    client = _routes({"https://smallnews.test": httpx.Response(200, html=home)})
    items = sources._one({"kind": "site", "value": "smallnews.test"}, client)
    assert [i.title for i in items] == ["Dam release: what we know about the flood",
                                        "Markets close higher as the bank holds rates"]
    with pytest.raises(RuntimeError, match="no headlines"):
        sites.homepage_headlines(_routes({"https://empty.test": httpx.Response(200, html="<p>hi</p>")}), "empty.test")


# ── the owner's uploads ───────────────────────────────────────────────────────

def test_an_upload_is_normalised_then_analysed(s3, owner, user, tmp_path):
    slot = date(2035, 1, 1) + timedelta(days=uuid.uuid4().int % 3000)
    pid = owner.execute("insert into posts (user_id, topic, slot_date) values (%s, 'mine', %s) returning id",
                        (user, slot)).fetchone()["id"]
    raw = tmp_path / "talk.webm"
    ff("-f", "lavfi", "-i", "testsrc2=s=2560x1440:r=30:d=2", "-f", "lavfi", "-i", "sine=d=2", "-shortest",
       "-c:v", "libvpx-vp9", "-b:v", "1M", "-c:a", "libopus", str(raw))
    a = as_user(owner, user, "select * from api.start_upload(%s, 'video', %s, 'webm', 'talk.webm')",
                (pid, raw.stat().st_size))
    key = a["fetch_from"]["upload_key"]
    storage.client().upload_file(str(raw), storage.bucket(), key)
    as_user(owner, user, "select api.finish_upload(%s)", (a["id"],))
    ideas = Runner("ideas", {"fetch_asset": fetch_asset.HANDLER})
    assert drain(ideas) == ["fetch_asset"]
    got = owner.execute("select key, w, h, seconds, has_audio, state from assets where id = %s", (a["id"],)).fetchone()
    assert got["key"].endswith(f"/assets/{a['id']}.mp4") and (got["w"], got["h"]) == (1920, 1080)
    assert got["has_audio"] and got["state"] == "pending"                 # analysis is next
    assert owner.execute("select state from storage_objects where key = %s", (key,)).fetchone()["state"] == "deleted"
    assert owner.execute("select kind from jobs where post_id = %s and kind = 'analyze_asset'",
                         (pid,)).fetchone() is not None
    owner.execute("delete from jobs where post_id = %s", (pid,))
