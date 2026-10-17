"""Phase 4: sources read in full, charts, background music, the storage sweep,
stats read back, and the health checks.

Everything external is faked (pages, Bing, Freesound and YouTube by
httpx.MockTransport or stand-ins; S3 by moto); ffmpeg, the queue and the schema
are real. Pages and media are synthetic.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from corpus import db, health, music, research, stats, storage
from corpus.crypto import encrypt
from corpus.handlers import assemble, research_post, suggest_ideas, write_script
from corpus.ideas import feeds, sweep
from corpus.runner import Defer, JobContext, Runner
from corpus.script.llm import Chart, Footage, generated_shot, validate
from test_footage import (LINE, FootageWriter, _approve, _script, cpu_footage, footage_post,  # noqa: F401
                          media)
from test_render_pipeline import (as_user, drain, fake_whisper, fakes, gpu, owner, pod_notes, s3,  # noqa: F401
                                  segment_cache, user)
from test_sources_media import _routes, public_dns  # noqa: F401

ARTICLE = """<html><head><meta property="og:title" content="City council bans cars downtown"></head><body>
<nav>Home News Sport</nav>
<article class="story-body">
<p>The city council voted 7-2 on Tuesday to ban private cars from the old town from January, the mayor said.</p>
<p>Sign up for our newsletter to get the latest updates every morning. Delivery vans will still be allowed before 10am.</p>
<p>Advertisement</p>
<p>Shop owners say the ban could cut footfall by a third; the council expects cleaner air within a year.</p>
<div class="related-stories"><p>Related: another city that tried this in 2019 and gave up after six months.</p></div>
<p>Jane Doe is a reporter who covers city hall for the paper and has written about transport for 10 years.</p>
</article><footer>All rights reserved</footer></body></html>"""


def test_an_article_is_read_without_its_chrome():
    title, text, _, _ = research.extract(ARTICLE, "https://news.test/a")
    assert title == "City council bans cars downtown"
    assert "voted 7-2" in text and "Delivery vans will still be allowed" in text and "footfall" in text
    for junk in ("newsletter", "Advertisement", "another city that tried", "is a reporter", "rights reserved"):
        assert junk not in text


# ── research before the script ───────────────────────────────────────────────

def _idea(owner, user, items, title="City bans cars downtown") -> tuple[str, str]:
    ch = owner.execute("insert into channels (user_id, name) values (%s, %s) returning id",
                       (user, f"c-{uuid.uuid4().hex[:6]}")).fetchone()["id"]
    fmt = owner.execute("insert into formats (user_id, channel_id, name, idea_prompt, script_prompt, is_default) "
                        "values (%s, %s, 'f', 'i', 's', true) returning id", (user, ch)).fetchone()["id"]
    cat = owner.execute("select id from categories where channel_id = %s", (ch,)).fetchone()["id"]
    iid = owner.execute("""insert into ideas (user_id, channel_id, format_id, category_id, title, brief, items)
                           values (%s, %s, %s, %s, %s, 'b', %s) returning id""",
                        (user, ch, fmt, cat, title, json.dumps(items))).fetchone()["id"]
    return iid, ch


def test_an_accepted_ideas_sources_are_read_before_its_script(s3, owner, user, monkeypatch):
    other = ARTICLE.replace("7-2", "seven votes to two").replace("story-body", "article-body")
    monkeypatch.setattr(research_post.httpx, "Client", lambda **kw: _routes({
        "https://news.test/a": httpx.Response(200, text=ARTICLE, headers={"content-type": "text/html"}),
        "https://other.test/b": httpx.Response(200, text=other, headers={"content-type": "text/html"}),
    }))
    monkeypatch.setattr(research_post, "SEARCH", lambda client, q, count=12: [
        feeds.Item("news.test", "dup", "", "https://news.test/a"),
        feeds.Item("other.test", "Council votes to ban cars", "", "https://other.test/b")])
    iid, _ = _idea(owner, user, [{"title": "Council bans cars", "url": "https://mastodon.test/@x/1",
                                  "platform": "mastodon", "link": "https://news.test/a"}])
    as_user(owner, user, "select api.decide_idea_v2(%s, true, now() + interval '1 day')", (iid,))
    pid = owner.execute("select post_id from ideas where id = %s", (iid,)).fetchone()["post_id"]
    assert owner.execute("select research_state from posts where id = %s", (pid,)).fetchone()["research_state"] == \
        "pending"
    as_user(owner, user, "select api.generate_script(%s)", (pid,))
    job = db.claim("cpu", "test", ["write_script"])
    with pytest.raises(Defer, match="sources to be read"):
        write_script.run(JobContext(job=job))
    owner.execute("update jobs set state = 'queued', claimed_by = null where id = %s", (job["id"],))

    assert drain(Runner("ideas", {"research_post": research_post.HANDLER})) == ["research_post"]
    r = owner.execute("select research_state, research from posts where id = %s", (pid,)).fetchone()
    assert r["research_state"] == "ready"
    got = {a["site"]: a for a in r["research"]["articles"]}
    assert set(got) == {"news.test", "other.test"} and got["news.test"]["from_idea"] and not got["other.test"]["from_idea"]

    FootageWriter.systems, seen = [], []
    real = FootageWriter.write

    def capture(self, *, model, system, user):
        seen.append(user)
        return real(self, model=model, system=system, user=user)
    monkeypatch.setattr(FootageWriter, "write", capture)
    monkeypatch.setattr(write_script, "WRITER_FACTORY", FootageWriter)
    FootageWriter.shots = [generated_shot(seconds=4, visual="v", audio="", narration=LINE),
                           generated_shot(seconds=4, visual="v", audio="", narration=LINE)]
    owner.execute("update posts set target_seconds = 10 where id = %s", (pid,))
    assert drain(Runner("cpu", {"write_script": write_script.HANDLER})) == ["write_script"]
    assert "## What the sources report" in seen[0] and "voted 7-2" in seen[0] and "seven votes to two" in seen[0]


# ── charts ───────────────────────────────────────────────────────────────────

def test_a_chart_needs_a_title_and_matching_labels_and_values():
    good = generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="chart",
                          chart=Chart(title="Votes", labels=["For", "Against"], values=[7, 2], unit=""))
    bad = generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="chart",
                         chart=Chart(title="", labels=["For"], values=[7, 2], unit=""))
    assert validate(_script(good, good), 8, narrated=True, footage=Footage(assets=[])) == []
    assert "give it a title and 2-6 labels" in validate(_script(bad, good), 8, narrated=True,
                                                        footage=Footage(assets=[]))[0]


def test_a_chart_shot_is_drawn_on_the_server(s3, owner, user, footage_post):
    FootageWriter.shots = [
        generated_shot(seconds=4, visual="the vote", audio="", narration=LINE, source="chart",
                       chart=Chart(title="Council vote", labels=["For", "Against"], values=[7, 2], unit="")),
        generated_shot(seconds=4, visual="the river", audio="", narration=LINE, source="image", asset=2)]
    sid = _approve(owner, user, footage_post)
    drain(cpu_footage())
    as_user(owner, user, "select api.request_render(%s)", (footage_post,))
    assert drain(cpu_footage())[-1] == "assemble"
    shot = owner.execute("select source, chart, state from shots where script_id = %s and idx = 0", (sid,)).fetchone()
    assert shot["source"] == "chart" and shot["chart"]["values"] == [7.0, 2.0] and shot["state"] == "uploaded"


# ── music ────────────────────────────────────────────────────────────────────

def test_a_reel_gets_a_cc0_track_under_it_and_credits_it(s3, owner, user, footage_post, monkeypatch, tmp_path):
    owner.execute("insert into user_keys (user_id, name, ciphertext) values (%s, 'freesound_api_key', %s)",
                  (user, encrypt("freesound-test-key")))
    track = tmp_path / "track.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=660", "-t", "2",
                    "-c:a", "libmp3lame", str(track)], check=True)
    asked = []

    def fake_find(client, key, mood, exclude, dest, min_seconds=20):
        asked.append((key, mood, exclude))
        dest.write_bytes(track.read_bytes())
        return music.Track(4242, "Calm Waters", "composer1", "https://freesound.test/s/4242", dest)
    monkeypatch.setattr(assemble.music, "find", fake_find)
    FootageWriter.shots = [generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="image", asset=2),
                           generated_shot(seconds=4, visual="v", audio="", narration=LINE, source="image", asset=2)]
    real_write = FootageWriter.write

    def with_mood(self, *, model, system, user):
        assert "`music_mood`: the background track's mood" in system
        out, usage = real_write(self, model=model, system=system, user=user)
        out.music_mood = "uplifting"
        return out, usage
    monkeypatch.setattr(FootageWriter, "write", with_mood)
    sid = _approve(owner, user, footage_post)
    assert owner.execute("select music_mood from scripts where id = %s", (sid,)).fetchone()["music_mood"] == "uplifting"
    drain(cpu_footage())
    as_user(owner, user, "select api.request_render(%s)", (footage_post,))
    assert drain(cpu_footage())[-1] == "assemble"
    p = owner.execute("select music, credits from posts where id = %s", (footage_post,)).fetchone()
    assert p["music"]["id"] == 4242 and p["music"]["mood"] == "uplifting"
    assert p["credits"][-1] == "Music: “Calm Waters” by composer1 (Freesound, CC0)"
    assert asked == [("freesound-test-key", "uplifting", set())]


# ── housekeeping, stats, health ──────────────────────────────────────────────

def test_a_replaced_scripts_shots_are_swept_after_a_week(s3, owner, user, footage_post, media):
    pid = footage_post
    old = owner.execute("insert into scripts (post_id, version, state) values (%s, 1, 'superseded') returning id",
                        (pid,)).fetchone()["id"]
    shot = owner.execute("""insert into shots (post_id, script_id, idx, prompt, seed, width, height, num_frames)
                            values (%s, %s, 0, 'p', 1, 704, 1280, 97) returning id""", (pid, old)).fetchone()["id"]
    key = f"u/{user}/p/{pid}/shots/{old}/0.mp4"
    storage.put_file(key, media["stock"], kind="shot", user_id=user, post_id=pid, shot_id=shot,
                     content_type="video/mp4")
    assert sweep.sweep_intermediates(lambda m: None) == 0                   # too fresh
    owner.execute("update storage_objects set created_at = now() - interval '8 days' where key = %s", (key,))
    assert sweep.sweep_intermediates(lambda m: None) >= 1
    assert owner.execute("select state from storage_objects where key = %s", (key,)).fetchone()["state"] == "deleted"


def test_published_reels_numbers_are_read_back_and_shown_to_the_idea_agent(s3, owner, user, footage_post, monkeypatch):
    pid = footage_post
    ch = owner.execute("insert into channels (user_id, name) values (%s, 'stats') returning id", (user,)).fetchone()["id"]
    owner.execute("update posts set channel_id = %s, status = 'published' where id = %s", (ch, pid))
    owner.execute("""insert into publish_attempts (post_id, platform, state, remote_id)
                     values (%s, 'youtube', 'live', 'vid123')""", (pid,))
    owner.execute("insert into user_keys (user_id, name, ciphertext) values (%s, 'youtube_api_key', %s)",
                  (user, encrypt("AIza-stats-key")))
    seen = {}

    def yt(req):
        seen["key"], seen["ids"] = req.headers.get("x-goog-api-key"), req.url.params["id"]
        return httpx.Response(200, json={"items": [{"id": "vid123", "statistics": {
            "viewCount": "15000", "likeCount": "900", "commentCount": "41"}}]})
    with _routes({"https://www.googleapis.com/youtube/v3/videos": yt}) as client:
        assert stats.read_back(client, log=lambda m: None) >= 1
    assert seen == {"key": "AIza-stats-key", "ids": "vid123"}
    row = owner.execute("select views, likes, comments from post_stats where post_id = %s", (pid,)).fetchone()
    assert row == {"views": 15000, "likes": 900, "comments": 41}
    with db.conn() as c:
        text = stats.summary(c, ch)
    assert "15,000 views, 900 likes, 41 comments" in text


def test_health_checks_are_recorded_without_failing_each_other(monkeypatch):
    def broken():
        raise RuntimeError("no route to host")
    monkeypatch.setattr(health, "CHECKS", {"test: fine": lambda: (True, "all good"), "test: broken": broken})
    assert health.run_all(lambda m: None) == {"test: fine": True, "test: broken": False}
    with db.conn() as c:
        rows = {r["name"]: r for r in c.execute("select name, ok, detail from health_checks where name like 'test:%%'")}
        c.execute("delete from health_checks where name like 'test:%%'")
    assert rows["test: broken"]["ok"] is False and "no route to host" in rows["test: broken"]["detail"]


# ── members (Phase 5) ────────────────────────────────────────────────────────

def test_allowed_emails_become_owners_and_a_spent_limit_stops_scripts(owner, user, monkeypatch):
    from corpus import upkeep
    from corpus.runner import Permanent

    monkeypatch.setenv("AUTH_ALLOWED_EMAILS", f"someone@else.test, {user}@example.test")
    owner.execute("update memberships set role = 'member' where user_id = %s", (user,))
    upkeep._promote_owners()
    assert owner.execute("select role, status from memberships where user_id = %s", (user,)).fetchone() == \
        {"role": "owner", "status": "active"}

    owner.execute("update memberships set monthly_limit_paise = 0 where user_id = %s", (user,))
    pid = owner.execute("insert into posts (user_id, topic, slot_date) values (%s, 't', '2033-04-04') returning id",
                        (user,)).fetchone()["id"]
    as_user(owner, user, "select api.ensure_settings()")
    with pytest.raises(Exception, match="spending limit"):
        as_user(owner, user, "select api.generate_script(%s)", (pid,))
    owner.execute("update posts set status = 'scripting' where id = %s", (pid,))
    job = {"id": None, "post_id": pid, "payload": {"version": 1}}
    with pytest.raises(Permanent, match="spending limit"):
        write_script.run(JobContext(job=job))


def test_other_reports_must_be_about_the_same_story():
    """Live, 2026-10-17: a search for a Yale stress-and-memory study returned a trauma
    explainer and a screen-time piece, which shared only the word "brain"."""
    story = ("Yale scientists discover how stress changes the brain to make memories stronger "
             "What Does Stress Do to Your Brain’s Memory Switch?")
    assert not research.same_story("Trauma rewires the brain: what does the healing process look like?", story)
    assert not research.same_story("Your phone is rewiring your brain.", story)
    assert research.same_story("Stress hormone cortisol strengthens emotional memories, Yale study finds", story)
    assert research.same_story("Council votes to ban cars", "City council bans cars downtown")
