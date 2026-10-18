"""Video looks (how generated shots look, chosen per post), the asset finder (real
photos chosen by Jev), and the cheaper GPU rules (8 s shots, the 5090 first)."""

from __future__ import annotations

import io
import subprocess
import uuid
from datetime import date, timedelta

import httpx
from PIL import Image
from psycopg.types.json import Jsonb

from corpus import finder, jev, looks, templates
from corpus.handlers import plan_shots, render_post
from corpus.media import assemble
from corpus.research import Article, page_images
from corpus.script.llm import Review, ScriptOut, generated_shot, validate
from test_render_pipeline import owner, user  # noqa: F401
from test_sources_media import _routes, public_dns  # noqa: F401


# ── looks ─────────────────────────────────────────────────────────────────────

def test_every_look_loads_and_its_grade_renders(tmp_path):
    reg = looks.registry()
    assert len(reg) == 16 and {"photoreal_cinematic", "documentary_real", "cartoon_2d", "black_and_white_archival",
                                "war_documentary", "stick_figures", "anime", "retro_film"} <= set(reg)
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=704x1280:r=24:d=0.5",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    for lk in reg.values():
        if lk.grade:
            v = tmp_path / f"{lk.look_id}.mp4"
            assemble.build_segment(clip, v, tmp_path / f"{lk.look_id}.wav", grade=lk.grade)
            assert assemble._frames(v) == 12
    bw = tmp_path / "bw.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "0.2", "-i", str(tmp_path / "black_and_white_archival.mp4"),
                    "-frames:v", "1", str(bw)], check=True)
    r, g, b = Image.open(bw).convert("RGB").getpixel((540, 300))
    assert max(r, g, b) - min(r, g, b) <= 12                        # grey: no colour left


class LookJev(jev.Jev):
    pick = ("cartoon_2d", 0.8)
    sensitive = 0.1

    def __init__(self):
        super().__init__("k", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))

    def ask(self, state, questions, images=None):
        return {"look": {"choice": self.pick[0], "confidence": self.pick[1]}, "sensitive": {"noul": self.sensitive}}


def test_a_look_is_the_channels_or_jevs_pick_and_never_playful_for_a_tragedy():
    t = templates.get("mini_news_explainer")
    kw = dict(story="s", category="c", template=t)
    assert looks.choose(None, "anime", **kw) == ("anime", "the channel's look")
    assert looks.choose(None, "format", **kw)[0] == "format"
    assert looks.choose(None, "auto", **kw)[0] == "documentary_real"          # the template's usual
    j = LookJev()
    assert looks.choose(j, "auto", **kw) == ("cartoon_2d", "Jev's pick (80% sure)")
    j.sensitive = 0.9
    assert looks.choose(j, "auto", **kw)[0] == looks.SAFE                       # a tragedy: never a cartoon
    j.pick, j.sensitive = ("anime", 0.1), 0.0
    assert looks.choose(j, "auto", **kw)[0] == "documentary_real"              # unsure: the usual


def test_the_post_look_shapes_generated_shots(owner, user):
    slot = date(2036, 1, 1) + timedelta(days=uuid.uuid4().int % 3000)
    pid = owner.execute("""insert into posts (user_id, topic, slot_date, audio_source, look_id)
                           values (%s, 'look', %s, 'ltx_native', 'photoreal_cinematic') returning id""",
                        (user, slot)).fetchone()["id"]
    sid = owner.execute("""insert into scripts (post_id, version, state, title, shot_plan, style_prompt)
                           values (%s, 1, 'approved', 't', %s, '') returning id""",
                        (pid, Jsonb([generated_shot(seconds=5, visual="A harbour at dawn", audio="gulls",
                                                    narration="").model_dump()]))).fetchone()["id"]
    owner.execute("update posts set status = 'approved', approved_script_id = %s where id = %s", (sid, pid))
    plan_shots.run(plan_shots.JobContext(job={"id": None, "payload": {"script_id": str(sid)}}))
    s = owner.execute("select prompt, negative_prompt, credit from shots where script_id = %s", (sid,)).fetchone()
    lk = looks.get("photoreal_cinematic")
    assert lk.prompt in s["prompt"] and s["negative_prompt"].endswith(lk.avoid) and s["credit"] == "AI-generated"
    owner.execute("delete from jobs where post_id = %s", (pid,))


# ── cheaper GPU use ───────────────────────────────────────────────────────────

def test_generated_shots_are_at_most_8_seconds():
    out = ScriptOut(title="t", hook="h", description="d", hashtags=[], intended_dialogue="", style_prompt="",
                    shots=[generated_shot(seconds=10, visual="v", audio="", narration="")], music_mood="",
                    review=Review(score=8, risks=[], notes=""))
    assert any("make it 3-8s" in p for p in validate(out, 10))


def test_the_cheapest_gpu_that_fits_goes_first():
    class Race:
        def pods(self):
            return [{"id": 1, "name": "corpus-a", "status": "stopped", "vram": 96},
                    {"id": 2, "name": "corpus-b", "status": "stopped", "vram": 32},
                    {"id": 3, "name": "other", "status": "stopped", "vram": 24}]
    assert render_post._cache_pods(Race()) == [2, 1]
    assert render_post._cache_pods(Race(), big_first=True) == [1, 2]
    assert render_post.HELPER_MIN_SHOTS == 4 and render_post.SMALL_GPU_FRAMES == 193


# ── the asset finder ──────────────────────────────────────────────────────────

def test_an_articles_photos_are_found_without_logos_or_icons():
    html = ("<html><head><meta property='og:image' content='https://n.test/lead.jpg'></head><body><article>"
            "<img src='/logo.png'><figure><img src='/a/flood-1.jpg' width='1200'><figcaption>Water rises in "
            "Patna</figcaption></figure><img src='/tiny.jpg' width='120'>"
            "<img srcset='/b/s.jpg 400w, /b/l.jpg 1600w'></article></body></html>")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    got = page_images(soup, soup.find("article"), "https://n.test/story")
    assert [g["url"] for g in got] == ["https://n.test/lead.jpg", "https://n.test/a/flood-1.jpg",
                                       "https://n.test/b/l.jpg"]
    assert got[1]["caption"] == "Water rises in Patna"


def _jpeg(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (900, 600), color).save(buf, "JPEG")
    return buf.getvalue()


class PhotoJev(jev.Jev):
    """Judges a picture by its colour: red = the event, green = generic, blue = watermarked."""

    def __init__(self, real=0.9):
        super().__init__("k", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
        self.real = real

    def ask(self, state, questions, images=None):
        if "real_event" in questions:
            return {"real_event": {"noul": self.real}}
        r, g, b = Image.open(io.BytesIO(next(iter(images.values())))).getpixel((10, 10))
        shows = 3.0 if r > 200 else 1.0 if g > 200 else 2.5
        return {"shows": {"score": shows}, "usable": {"noul": 0.9}, "watermark": {"noul": 0.9 if b > 200 else 0.05},
                "graphic": {"noul": 0.01}}


def _finder_routes():
    return _routes({
        "https://news.test/event.jpg": httpx.Response(200, content=_jpeg((250, 10, 10)),
                                                      headers={"content-type": "image/jpeg"}),
        "https://news.test/marked.jpg": httpx.Response(200, content=_jpeg((10, 10, 250)),
                                                       headers={"content-type": "image/jpeg"}),
        "https://upload.wikimedia.test/generic.jpg": httpx.Response(200, content=_jpeg((10, 250, 10)),
                                                                    headers={"content-type": "image/jpeg"}),
        finder.COMMONS: httpx.Response(200, json={"query": {"pages": {"1": {"imageinfo": [{
            "thumburl": "https://upload.wikimedia.test/generic.jpg", "descriptionurl": "https://commons.test/f",
            "extmetadata": {"Artist": {"value": "<a>Jane</a>"}, "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}}}}),
        finder.OPENVERSE: httpx.Response(200, json={"results": []}),
    })


def test_the_finder_keeps_real_event_photos_jev_trusts(public_dns):
    arts = [Article("https://news.test/a", "news.test", "Flood in Patna", "text",
                    images=[{"url": "https://news.test/event.jpg"}, {"url": "https://news.test/marked.jpg"}])]
    picked, real = finder.find(PhotoJev(), _finder_routes(), "Flood in Patna as the Ganga rises", arts)
    assert real == 0.9 and [p["url"] for p in picked] == ["https://news.test/event.jpg"]   # generic and marked dropped
    assert picked[0]["credit"] == "news.test"
    # a concept, not an event: no news photos are even considered
    picked, real = finder.find(PhotoJev(real=0.1), _finder_routes(), "How floods form", arts)
    assert real == 0.1 and all(p["origin"] != "article" for p in picked)


def test_picked_photos_become_approved_credited_assets(owner, user):
    slot = date(2037, 1, 1) + timedelta(days=uuid.uuid4().int % 3000)
    post = owner.execute("insert into posts (user_id, topic, slot_date) values (%s, 'f', %s) returning id, user_id",
                         (user, slot)).fetchone()
    picked = [{"url": "https://news.test/event.jpg", "page": "https://news.test/a", "origin": "article",
               "credit": "news.test", "license": "third_party", "shows": 3.0, "usable": 0.9}]
    assert finder.add_to_post(post, picked) == 1
    assert finder.add_to_post(post, picked) == 0                                   # never twice
    a = owner.execute("select n, kind, rights, credit, state from assets where post_id = %s", (post["id"],)).fetchone()
    assert (a["n"], a["kind"], a["rights"], a["credit"], a["state"]) == (1, "image", "approved", "news.test", "pending")
    assert owner.execute("select count(*) as n from jobs where post_id = %s and kind = 'fetch_asset'",
                         (post["id"],)).fetchone()["n"] == 1
    owner.execute("delete from jobs where post_id = %s", (post["id"],))

