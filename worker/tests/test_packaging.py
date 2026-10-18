"""What a reel goes out with: title, caption with sources, hashtags, first comment and
cover (packaging.py), and how posting uses them (publish/youtube.finish, instagram)."""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import date, timedelta
from pathlib import Path

import httpx
from PIL import Image
from psycopg.types.json import Jsonb

from corpus import packaging, storage
from corpus.publish import instagram, youtube
from corpus.script.llm import Usage, generated_shot
from test_render_pipeline import owner, s3, user  # noqa: F401

PKG = {"title": "Limoges town hall spire falls during France protests", "hook_line": "A 19th-century spire fell in minutes.",
       "caption": "Over 1,200 were arrested across France.\nWhat happens to the building next?",
       "hashtags": ["#Limoges", "#France", "#news"], "first_comment": "Should it be rebuilt exactly as it was?",
       "thumbnail_text": "SPIRE GONE", "kicker": "BREAKING",
       "sources": [{"site": "BBC News", "title": "Protests in France", "url": "https://www.bbc.co.uk/news/x"}]}


def test_the_caption_carries_sources_credits_and_hashtags():
    yt = packaging.youtube_description(PKG, ["BBC"])
    assert yt.startswith("A 19th-century spire fell in minutes.")
    assert "Sources:\n• BBC News: https://www.bbc.co.uk/news/x" in yt and "Footage: BBC" in yt
    assert yt.endswith("#Limoges #France #news")
    ig = packaging.instagram_caption(PKG, [])
    assert "Sources: BBC News (links in the first comment)" in ig and "https://" not in ig
    assert packaging.first_comment(PKG, "instagram").endswith("BBC News: https://www.bbc.co.uk/news/x")
    assert "https://" not in packaging.first_comment(PKG, "youtube")
    assert packaging._tags(["#Paris Fire", "news", "#news", "#"]) == ["#ParisFire", "#news"]


class FakeCopywriter:
    def __init__(self, key):
        pass

    def write(self, *, model, system, user):
        FakeCopywriter.seen = user
        return packaging.PostCopy(**{k: v for k, v in PKG.items() if k != "sources"}), Usage("test-model", 900, 200)


def test_a_finished_reel_gets_its_package_and_cover(s3, owner, user, tmp_path, monkeypatch):
    monkeypatch.setattr(packaging, "COPYWRITER", FakeCopywriter)
    clip = tmp_path / "final.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=720x1280:r=24:d=2",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    slot = date(2038, 1, 1) + timedelta(days=uuid.uuid4().int % 3000)
    pid = owner.execute("insert into posts (user_id, topic, slot_date, research) values (%s, 'spire', %s, %s) "
                        "returning id", (user, slot, Jsonb({"articles": [
                            {"url": "https://www.bbc.co.uk/news/x", "site": "bbc.co.uk", "title": "Protests in France",
                             "text": "", "from_idea": True}]}))).fetchone()["id"]
    sid = owner.execute("""insert into scripts (post_id, version, state, title, shot_plan, style_prompt)
                           values (%s, 1, 'approved', 'Spire falls', %s, '') returning id""",
                        (pid, Jsonb([generated_shot(seconds=5, visual="v", audio="",
                                                    narration="The spire fell in minutes.").model_dump()]))).fetchone()["id"]
    key = f"u/{user}/p/{pid}/final/{sid}.mp4"
    storage.put_file(key, clip, kind="final", user_id=user, post_id=pid, content_type="video/mp4")
    owner.execute("update posts set approved_script_id = %s, final_key = %s where id = %s", (sid, key, pid))

    pkg = packaging.ensure(pid)
    assert pkg["title"] == PKG["title"] and pkg["sources"][0]["site"] == "BBC News"
    assert "The spire fell in minutes." in FakeCopywriter.seen and "BBC News - Protests in France" in FakeCopywriter.seen
    cover = storage.get_file(pkg["thumbnail_key"], tmp_path / "cover.jpg")
    assert Image.open(cover).size == (1080, 1920) and cover.stat().st_size < 2_000_000
    assert packaging.ensure(pid)["made_at"] == pkg["made_at"]          # kept, not written again
    assert owner.execute("select count(*) as n from costs where post_id = %s", (pid,)).fetchone()["n"] == 1


def test_posting_adds_the_thumbnail_and_comment_and_says_what_it_could_not(tmp_path, monkeypatch):
    cover = tmp_path / "c.jpg"
    Image.new("RGB", (1080, 1920), (200, 0, 0)).save(cover)
    monkeypatch.setattr(youtube, "access_token", lambda client, rt: "tok")

    def yt(req: httpx.Request):
        if "thumbnails/set" in str(req.url):
            assert req.url.params["videoId"] == "vid1" and req.headers["content-type"] == "image/jpeg"
            return httpx.Response(200, json={"items": []})
        assert json.loads(req.content)["snippet"]["topLevelComment"]["snippet"]["textOriginal"] == "Rebuild it?"
        return httpx.Response(403, json={"error": {"errors": [{"reason": "insufficientPermissions"}], "message": "x"}})

    out = youtube.finish(httpx.Client(transport=httpx.MockTransport(yt)), refresh_token="r", video_id="vid1",
                         cover=cover, comment="Rebuild it?")
    assert out == {"thumbnail": "set",
                   "comment": "not posted: reconnect YouTube on the channel page to allow comments"}

    def ig(req: httpx.Request):
        assert str(req.url).endswith("/m1/comments") and b"message=Rebuild" in req.content
        return httpx.Response(200, json={"id": "c9"})

    assert instagram.comment(httpx.Client(transport=httpx.MockTransport(ig)), token="t", media_id="m1",
                             text="Rebuild it?") == "posted c9"


def test_a_reel_is_created_with_its_cover():
    seen = {}

    def ig(req: httpx.Request):
        seen.update(dict(httpx.QueryParams(req.content.decode())))
        return httpx.Response(200, json={"id": "cont1"})

    instagram._create(httpx.Client(transport=httpx.MockTransport(ig)), "t", "u1", "https://x/v.mp4", "cap",
                      cover_url="https://x/cover.jpg")
    assert seen["cover_url"] == "https://x/cover.jpg" and seen["media_type"] == "REELS"
    assert Path(packaging.__file__).exists()
