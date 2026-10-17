"""Phase 3: AI versions of a post's media — a picture redrawn by OpenAI, a video
recreated on the GPU, and pictures animated by image-to-video.

OpenAI, Whisper, Race and ComfyUI are stand-ins; S3 is moto; ffmpeg, the queue
and the schema are real. Media are synthetic.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

from corpus import storage
from corpus.gpu import ltx25
from corpus.handlers import analyze_asset, fetch_asset, make_ai_image, render_post
from corpus.ideas import media as card_media
from corpus.runner import Runner
from corpus.script import footage as footage_
from corpus.script.llm import Footage, Usage, generated_shot, validate
from test_footage import (LINE, FakeLogger, FootageWriter, _approve, _script, cpu_footage, footage_post,  # noqa: F401
                          media)
from test_render_pipeline import (as_user, drain, fake_whisper, fakes, gpu, owner, pod_notes, s3,  # noqa: F401
                                  segment_cache, user)
from test_sources_media import _routes, public_dns  # noqa: F401


# ── the graph and the rules ───────────────────────────────────────────────────

def test_image_to_video_writes_the_picture_into_both_latents():
    shot = {"width": 704, "height": 1280, "prompt": "p", "negative": "n", "seed": 1}
    plain = ltx25.nodes(shot, 97, "render/shot0")
    guided = ltx25.nodes(shot, 97, "render/shot0", "corpus_x.png")
    assert "img" not in plain and plain["lat_av"][1]["video_latent"] == ["lat_v", 0]
    assert guided["img"] == ("LoadImage", {}, ["corpus_x.png"])
    assert guided["i2v1"][1] == {"vae": ["vvae", 0], "image": ["pre", 0], "latent": ["lat_v", 0]}
    assert guided["i2v2"][1]["latent"] == ["up", 0] and guided["i2v2"][2] == [1.0, False]
    assert guided["lat_av"][1]["video_latent"] == ["i2v1", 0]
    assert guided["lat_av2"][1]["video_latent"] == ["i2v2", 0]


def test_a_generated_shot_may_animate_a_picture_only():
    footage = Footage(assets=[{"n": 1, "kind": "video", "seconds": 10}, {"n": 2, "kind": "image"}])
    ok = _script(generated_shot(seconds=5, visual="the river flows", audio="", narration=LINE, asset=2))
    assert validate(ok, 5, narrated=True, footage=footage) == []
    bad = _script(generated_shot(seconds=5, visual="v", audio="", narration=LINE, asset=1))
    assert "not a picture in the footage list" in validate(bad, 5, narrated=True, footage=footage)[0]


def test_an_original_the_owner_wont_show_is_described_to_be_recreated():
    ref = {"n": 1, "kind": "video", "seconds": 12.0, "w": 1280, "h": 720, "credit": "u/a on r/b", "has_audio": False,
           "analysis": {"summary": "A bridge sags and falls.", "moments": [{"at": 4.0, "what": "it falls"}]}}
    text = footage_.prompt_section(Footage(assets=[], references=[ref]), narrated=True)
    assert "## Footage you may not show — recreate it" in text and '"AI reconstruction"' in text
    assert "Original video: video, 12.0 s" in text and "0:04.0 it falls" in text
    assert "## Footage you may use" not in text


# ── an AI picture, start to finish ────────────────────────────────────────────

class FakeImages:
    prompts: list[str] = []

    def __init__(self, key):
        pass

    def generate(self, *, model, prompt, quality="medium"):
        FakeImages.prompts.append(prompt)
        png = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x285aa0:s=1024x1536",
                              "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                             capture_output=True, check=True).stdout
        return png, Usage(model, 120, 1584)


def _idea_with_picture(owner, user, media):
    ch = owner.execute("insert into channels (user_id, name) values (%s, %s) returning id",
                       (user, f"c-{uuid.uuid4().hex[:6]}")).fetchone()["id"]
    fmt = owner.execute("insert into formats (user_id, channel_id, name, idea_prompt, script_prompt, visual_style, "
                        "is_default) values (%s, %s, 'f', 'i', 's', 'warm paper cut-out style', true) returning id",
                        (user, ch)).fetchone()["id"]
    cat = owner.execute("select id from categories where channel_id = %s", (ch,)).fetchone()["id"]
    preview = f"u/{user}/ideas/x/{uuid.uuid4().hex}.jpg"
    storage.put_file(preview, media["image"], kind="idea_media", user_id=user, content_type="image/jpeg")
    items = [{"title": "Flooded street", "url": "https://l.test/post/1", "media_hint": "image", "platform": "lemmy",
              "image_url": "https://img.l.test/flood.jpg"}]
    m = [{"type": "image", "key": preview, "w": 1600, "h": 900, "origin": "lemmy",
          "source_url": "https://l.test/post/1", "credit": "u/x on c/pics"}]
    return owner.execute("""insert into ideas (user_id, channel_id, format_id, category_id, title, brief, items, media,
                                              media_state)
                            values (%s, %s, %s, %s, 'Streets flood after storm', 'b', %s, %s, 'ready') returning id""",
                         (user, ch, fmt, cat, json.dumps(items), json.dumps(m))).fetchone()["id"]


def test_an_ai_version_of_a_picture_is_drawn_and_only_it_is_shown(s3, owner, user, media, monkeypatch):
    monkeypatch.setattr(analyze_asset, "VISION", FakeLogger)
    monkeypatch.setattr(make_ai_image, "IMAGES", FakeImages)
    owner.execute("update app_settings set vision_model = 'gpt-4.1-nano' where user_id = %s", (user,))
    iid = _idea_with_picture(owner, user, media)
    as_user(owner, user, "select api.decide_idea_v2(%s, true, now() + interval '1 day', null, null, false, 'ai')",
            (iid,))
    pid = owner.execute("select post_id from ideas where id = %s", (iid,)).fetchone()["post_id"]
    assert owner.execute("select media_choice from posts where id = %s", (pid,)).fetchone()["media_choice"] == "ai"
    rows = owner.execute("select n, origin, rights, state, made_from is not null as twin from assets where post_id = %s "
                         "order by n", (pid,)).fetchall()
    assert [(r["n"], r["origin"], r["rights"], r["state"], r["twin"]) for r in rows] == [
        (1, "lemmy", "needs_review", "pending", False), (2, "ai", "approved", "pending", True)]

    monkeypatch.setattr(fetch_asset.httpx, "Client", lambda **kw: _routes({
        "https://img.l.test/": __import__("httpx").Response(200, content=media["image"].read_bytes(),
                                                           headers={"content-type": "image/jpeg"})}))
    assert drain(Runner("ideas", {"fetch_asset": fetch_asset.HANDLER})) == ["fetch_asset"]
    cpu = Runner("cpu", {"analyze_asset": analyze_asset.HANDLER, "make_ai_image": make_ai_image.HANDLER})
    assert drain(cpu) == ["analyze_asset", "make_ai_image"]
    twin = owner.execute("select state, key, w, h, credit, analysis from assets where post_id = %s and n = 2",
                         (pid,)).fetchone()
    assert twin["state"] == "ready" and (twin["w"], twin["h"]) == (1024, 1536) and twin["credit"] == "AI illustration"
    assert "A bridge falls." in FakeImages.prompts[-1] and "warm paper cut-out style" in FakeImages.prompts[-1]
    cost = owner.execute("select kind, model, usd_micros from costs where post_id = %s and kind = 'image'",
                         (pid,)).fetchone()
    assert cost == {"kind": "image", "model": "gpt-image-1-mini", "usd_micros": round(120 * 2.0 + 1584 * 8.0)}
    with owner.cursor() as c:
        fx = footage_.load(c, pid, stock=False)[0]
    assert [a["n"] for a in fx.assets] == [2] and [a["n"] for a in fx.references] == [1]   # the original never shown


# ── animating a picture on the GPU, and the reconstruction label ──────────────

def test_a_picture_is_animated_from_its_first_frame(s3, owner, user, footage_post, gpu, monkeypatch):
    pid = footage_post
    seen: list[dict] = []
    real_render = render_post.RENDER

    def spy(base, queue, out_dir, on_done, keep_going, log, *, who):
        for s in queue.left():                                          # while the render runs
            if s.get("guide_path"):
                g = card_media.probe(Path(s["guide_path"]))
                seen.append({"idx": s["idx"], "size": (g.w, g.h)})
        return real_render(base, queue, out_dir, on_done, keep_going, log, who=who)
    monkeypatch.setattr(render_post, "RENDER", spy)
    FootageWriter.shots = [
        generated_shot(seconds=4, visual="the river begins to flow", audio="water", narration=LINE, asset=2),
        generated_shot(seconds=4, visual="the river", audio="", narration=LINE, source="image", asset=2)]
    sid = _approve(owner, user, pid)
    drain(cpu_footage())                                                 # plan + narrate
    shot = owner.execute("select guide_kind, guide_key, credit, asset_id is not null as has_asset from shots "
                         "where script_id = %s and idx = 0", (sid,)).fetchone()
    assert shot["guide_kind"] == "first_frame" and shot["guide_key"] and shot["credit"] == "news.test"
    as_user(owner, user, "select api.request_render(%s)", (pid,))
    assert Runner("gpu", {"render_post": render_post.HANDLER}).tick()
    assert seen == [{"idx": 0, "size": (704, 1280)}]                     # cut to the shot's own size
    assert drain(cpu_footage())[-1] == "assemble"
    p = owner.execute("select status, credits from posts where id = %s", (pid,)).fetchone()
    assert p["status"] == "ready" and p["credits"] == ["news.test"]


def test_generated_shots_recreating_a_video_say_so(s3, owner, user, footage_post):
    pid = footage_post
    owner.execute("update assets set rights = 'needs_review' where post_id = %s and kind = 'video'", (pid,))
    FootageWriter.shots = [generated_shot(seconds=4, visual="a bridge sways in the wind", audio="wind", narration=LINE),
                           generated_shot(seconds=4, visual="the span falls into the river", audio="", narration=LINE)]
    sid = _approve(owner, user, pid)
    assert "## Footage you may not show — recreate it" in FootageWriter.systems[-1]
    drain(cpu_footage())
    assert owner.execute("select credit from shots where script_id = %s", (sid,)).fetchone()["credit"] == \
        "AI reconstruction"
