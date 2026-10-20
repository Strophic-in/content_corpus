"""The idea agent: feeds → model → only new ideas, remembered per channel."""

from __future__ import annotations

import hashlib
import re
import uuid

import numpy as np
import pytest

from corpus import db
from corpus.crypto import encrypt
from corpus.handlers import suggest_ideas
from corpus.ideas import feeds, memory
from corpus.ideas.agent import Idea, IdeasOut
from corpus.runner import JobContext
from corpus.script.llm import Usage


def fake_embed(texts):
    """Bag of words → unit vector: same words ≈ same subject, enough for these tests."""
    out = np.zeros((len(texts), 384), dtype=np.float32)
    for row, t in enumerate(texts):
        for w in re.findall(r"[a-z]{4,}", t.lower()):
            out[row, int(hashlib.md5(w.encode()).hexdigest(), 16) % 384] += 1
    return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)


class FakeMemory:
    def __init__(self):
        self.points = {}

    def nearest(self, channel_id, vector):
        best = (0.0, "")
        for p in self.points.values():
            if p["channel_id"] == channel_id:
                best = max(best, (float(np.dot(p["vector"], vector)), p["title"]))
        return best

    def remember(self, points):
        for p in points:
            self.points[str(p["id"])] = p

    def forget(self, ids):
        for i in ids:
            self.points.pop(str(i), None)


def idea(title, brief="An explainer.", items=()):
    return Idea(title=title, hook=f"{title}?", brief=brief, why_now="Evergreen", items=list(items),
                format=1, format_why="")


class FakeWriter:
    outputs: list[list[Idea]] = []
    systems: list[str] = []

    def __init__(self, key):
        assert key == "sk-test-key"

    def write(self, *, model, system, user):
        FakeWriter.systems.append(system)
        return IdeasOut(ideas=FakeWriter.outputs.pop(0)), Usage(model, 10, 20)


@pytest.fixture
def mem(monkeypatch):
    m = FakeMemory()
    FakeWriter.outputs, FakeWriter.systems = [], []
    monkeypatch.setattr(suggest_ideas, "WRITER_FACTORY", FakeWriter)
    monkeypatch.setattr(suggest_ideas, "EMBED", fake_embed)
    monkeypatch.setattr(suggest_ideas, "MEMORY", lambda log: m)
    monkeypatch.setattr(suggest_ideas, "FETCH", lambda rows, **kw: ([
        feeds.Item("ScienceDaily", "Microplastics found in placentas", "A study found...", "https://x.test/a")], []))
    return m


@pytest.fixture
def channel():
    uid = f"test-{uuid.uuid4().hex[:10]}"
    with db.conn() as c:
        c.execute("delete from jobs where state in ('queued','claimed')")
        c.execute('insert into "user" (id, name, email, "emailVerified") values (%s,%s,%s,true)',
                  (uid, uid, f"{uid}@example.test"))
        c.execute("insert into app_settings (user_id, script_model) values (%s, 'test-model')", (uid,))
        c.execute("insert into user_keys (user_id, name, ciphertext) values (%s, 'openai', %s)",
                  (uid, encrypt("sk-test-key")))
        ch = c.execute("insert into channels (user_id, name, niche, is_default) values (%s, 'Cutaway', "
                       "'3D explainers', true) returning id", (uid,)).fetchone()["id"]
        fid = c.execute("""insert into formats (user_id, channel_id, name, idea_prompt, script_prompt, is_default,
                                                ideas_per_batch)
                           values (%s, %s, '3D explainer', %s, 's', true, 3) returning id""",
                        (uid, ch, "Ideas for {channel_name} ({channel_niche}). Trends:\n{trends}\n"
                                  "Avoid:\n{avoid}\nSkipped:\n{rejected}\nGive {count}. JSON like {\"x\": 1}")
                        ).fetchone()["id"]
        c.execute("update categories set ideas_per_batch = 3 where channel_id = %s", (ch,))  # "General", by trigger
    yield uid, ch, fid
    with db.conn() as c:
        c.execute('delete from "user" where id = %s', (uid,))


def run_batch(owner_user, fid):
    """This format's batch, run directly: a worker tick would also pick up other
    channels' daily batches in a shared test database."""
    with db.conn() as c:
        job = db.enqueue(c, user_id=owner_user, lane="cpu", kind="suggest_ideas",
                         dedupe_key=f"suggest_ideas:test:{uuid.uuid4()}", payload={"format_id": str(fid)})
    suggest_ideas.HANDLER.run(JobContext(job=job))


def ideas_of(ch):
    with db.conn() as c:
        return c.execute("select title, status from ideas where channel_id = %s order by created_at, title",
                         (ch,)).fetchall()


def test_only_new_ideas_are_kept_and_remembered(mem, channel):
    uid, ch, fid = channel
    FakeWriter.outputs = [[idea("Why placentas collect microplastics"),
                           idea("Why placentas collect microplastics"),          # same as the first
                           idea("How chitosan cleaners trap plastic particles"),
                           idea("What happens inside a black hole"),
                           idea("How octopus arms think on their own")]]
    run_batch(uid, fid)
    titles = [r["title"] for r in ideas_of(ch)]
    assert titles == sorted(["Why placentas collect microplastics", "How chitosan cleaners trap plastic particles",
                             "What happens inside a black hole"])                 # 3 = ideas_per_batch
    assert {p["kind"] for p in mem.points.values()} == {"idea"} and len(mem.points) == 3
    system = FakeWriter.systems[0]
    assert "Ideas for Cutaway (3D explainers)" in system and "Microplastics found in placentas" in system
    assert "Give 6" in system and '{"x": 1}' in system            # count + extra; other braces left alone
    assert "## Category: General" in system and "`items` lists the numbers" in system   # added to old prompts


def test_a_later_batch_never_repeats_and_learns_from_skips(mem, channel):
    uid, ch, fid = channel
    FakeWriter.outputs = [[idea("What happens inside a black hole"), idea("How bees see ultraviolet")]]
    run_batch(uid, fid)
    with db.conn() as c:
        c.execute("update ideas set status = 'rejected', reject_reason = 'too abstract' "
                  "where title = 'What happens inside a black hole'")
    FakeWriter.outputs = [[idea("What happens inside a black hole"),                 # asked again: a repeat
                           idea("How whales sleep while swimming")]]
    run_batch(uid, fid)
    assert [r["title"] for r in ideas_of(ch)].count("What happens inside a black hole") == 1
    assert "How whales sleep while swimming" in [r["title"] for r in ideas_of(ch)]
    second = FakeWriter.systems[1]
    assert "What happens inside a black hole — too abstract" in second            # the skip and its reason
    assert "How bees see ultraviolet" in second                                    # recent ideas to avoid


def test_old_suggestions_are_forgotten_but_accepted_ones_stay(mem, channel):
    uid, ch, fid = channel
    FakeWriter.outputs = [[idea("Why the sky is blue"), idea("How magnets work")]]
    run_batch(uid, fid)
    with db.conn() as c:
        c.execute("update ideas set created_at = now() - interval '31 days' where channel_id = %s", (ch,))
        c.execute("update ideas set status = 'accepted' where title = 'How magnets work'")
    FakeWriter.outputs = [[idea("How volcanoes form islands")]]
    run_batch(uid, fid)
    titles = {r["title"] for r in ideas_of(ch)}
    assert titles == {"How magnets work", "How volcanoes form islands"}
    assert "Why the sky is blue" not in {p["title"] for p in mem.points.values()}


def test_posts_made_by_hand_count_as_done(mem, channel):
    uid, ch, fid = channel
    with db.conn() as c:
        c.execute("insert into posts (user_id, channel_id, topic, slot_date) values (%s, %s, "
                  "'How octopus arms think on their own', '2031-01-01')", (uid, ch))
    FakeWriter.outputs = [[idea("Why ice floats on water")]]
    run_batch(uid, fid)
    assert any(p["kind"] == "post" for p in mem.points.values())
    FakeWriter.outputs = [[idea("How octopus arms think on their own"), idea("How tides follow the moon")]]
    run_batch(uid, fid)
    assert "How octopus arms think on their own" not in {r["title"] for r in ideas_of(ch)}


def test_unreachable_memory_still_gives_ideas(channel, monkeypatch):
    uid, ch, fid = channel
    FakeWriter.outputs, FakeWriter.systems = [[idea("How lightning finds its path")]], []
    monkeypatch.setattr(suggest_ideas, "WRITER_FACTORY", FakeWriter)
    monkeypatch.setattr(suggest_ideas, "EMBED", fake_embed)
    monkeypatch.setattr(suggest_ideas, "FETCH", lambda rows, **kw: ([], []))
    monkeypatch.setattr(suggest_ideas, "MEMORY",
                        lambda log: memory.connect("http://127.0.0.1:9", "k", log))   # nothing listens there
    run_batch(uid, fid)
    assert [r["title"] for r in ideas_of(ch)] == ["How lightning finds its path"]
    assert "no trend feeds answered today" in FakeWriter.systems[0]


# ── the owner's own asks: a YouTube video, or "Your idea" (owner, 2026-10-20) ──

def run_ask(owner_user, ch, kind, payload):
    with db.conn() as c:
        cat = c.execute("select id from categories where channel_id = %s", (ch,)).fetchone()["id"]
        job = db.enqueue(c, user_id=owner_user, lane="ideas", kind=kind,
                         dedupe_key=f"{kind}:test:{uuid.uuid4()}", payload={"category_id": str(cat), **payload})
    return suggest_ideas.HANDLER.run(JobContext(job=job))


def test_a_picked_video_always_becomes_a_card_even_as_a_repeat(mem, channel):
    uid, ch, _ = channel
    video = {"id": "dQw4w9WgXcQ", "title": "Why octopus arms think on their own", "description": "Each arm decides."}
    FakeWriter.outputs = [[]]                                       # the writer gave none
    assert run_ask(uid, ch, "idea_from_video", {"video": video})["ideas"] == 1
    assert [r["title"] for r in ideas_of(ch)] == ["Why octopus arms think on their own"]
    FakeWriter.outputs = [[idea("Why octopus arms think on their own")]]     # asked again: kept anyway
    assert run_ask(uid, ch, "idea_from_video", {"video": video})["ideas"] == 1
    assert len(ideas_of(ch)) == 2


def test_your_own_idea_reads_the_link_and_the_news_about_it(mem, channel, monkeypatch):
    uid, ch, _ = channel
    from corpus.research import Article
    searched = []
    monkeypatch.setattr(suggest_ideas, "READ", lambda client, url: Article(
        url, "news.test", "Metro fares cut by half on Sundays", "The city cut fares — from Sunday."))
    monkeypatch.setattr(suggest_ideas, "SEARCH", lambda client, q, count: searched.append(q) or [
        feeds.Item("paper.test", "Sunday metro fares halved", "Riders save.", "https://paper.test/m")])
    users = []
    real_write = FakeWriter.write
    monkeypatch.setattr(FakeWriter, "write", lambda self, **kw: users.append(kw["user"]) or real_write(self, **kw))
    FakeWriter.outputs = [[idea("Half-price metro Sundays — what changes", items=[1, 2])]]
    run_ask(uid, ch, "idea_from_topic", {"topic": "https://news.test/metro", "url": "https://news.test/metro"})
    assert searched == ["Metro fares cut by half on Sundays"]        # only a link: its headline is the topic
    assert "Metro fares cut by half on Sundays" in users[0] and "Make exactly one idea" in users[0]
    with db.conn() as c:
        row = c.execute("select title, sources from ideas where channel_id = %s", (ch,)).fetchone()
    assert row["title"] == "Half-price metro Sundays, what changes"          # no dashes
    assert [s["url"] for s in row["sources"]] == ["https://news.test/metro", "https://paper.test/m"]


def test_your_own_idea_is_made_from_your_words_when_nothing_is_found(mem, channel, monkeypatch):
    uid, ch, _ = channel
    monkeypatch.setattr(suggest_ideas, "SEARCH", lambda client, q, count: (_ for _ in ()).throw(RuntimeError("down")))
    FakeWriter.outputs = [[]]
    run_ask(uid, ch, "idea_from_topic", {"topic": "A tiger was seen near the Pune ring road"})
    assert [r["title"] for r in ideas_of(ch)] == ["A tiger was seen near the Pune ring road"]


# ── captions first: most reels without a narrator (owner, 2026-10-20) ─────────

def test_the_voice_share_lets_one_narrated_reel_in_four():
    from corpus.ideas import voice
    talk = {"id": "t", "content_type": "video", "audio_source": "kokoro"}
    quiet = {"id": "q", "content_type": "video", "audio_source": "none"}
    cards = {"id": "c", "content_type": "carousel", "audio_source": "none"}
    b = voice.Budget(25, 0, 0)
    picks = [b.fit(talk, [talk, cards, quiet], "")[0]["id"] for _ in range(8)]
    assert picks == ["q", "q", "q", "t", "q", "q", "q", "t"]
    assert voice.Budget(100, 50, 50).fit(talk, [talk, quiet], "x") == (talk, "x")
    assert voice.Budget(0, 0, 0).fit(talk, [talk], "x") == (talk, "x")          # no captions-only reel to use
    assert voice.Budget(0, 0, 9).fit(cards, [talk, quiet], "x") == (cards, "x")  # cards have no voice anyway


def test_a_batch_that_wanted_every_reel_narrated_gets_mostly_captions(mem, channel):
    uid, ch, fid = channel
    with db.conn() as c:
        c.execute("""insert into formats (user_id, channel_id, name, idea_prompt, script_prompt, template_id,
                                          audio_source)
                     values (%s, %s, 'Footage & text', 'i', 's', 'full_screen_text_overlay', 'none')""", (uid, ch))
        assert c.execute("select audio_source from formats where id = %s", (fid,)).fetchone()["audio_source"] != "none"
    FakeWriter.outputs = [[idea("How bees see ultraviolet"), idea("Why ice floats on water"),
                           idea("How tides follow the moon")]]                  # format 1: the narrated explainer
    run_batch(uid, fid)
    with db.conn() as c:
        got = c.execute("""select f.audio_source, i.format_why from ideas i join formats f on f.id = i.format_id
                            where i.channel_id = %s""", (ch,)).fetchall()
    assert sorted(r["audio_source"] for r in got).count("none") == 3                # 0 of 3 within 25%
    assert all("Captions only" in r["format_why"] for r in got)
    assert "## Voice" in FakeWriter.systems[0] and "about 25 in 100" in FakeWriter.systems[0]
