"""Jev: fast typed decisions — ranking trend items, picking each idea's format,
"same story?" — and the fallbacks when there is no key or Jev fails."""

from __future__ import annotations

import json
import uuid

import httpx

from corpus import costs, db, jev, research
from corpus.crypto import encrypt
from corpus.handlers import suggest_ideas
from corpus.ideas import decide
from corpus.ideas.agent import Idea, IdeasOut
from corpus.ideas.feeds import Item
from corpus.script.llm import Usage
from test_render_pipeline import owner, user  # noqa: F401
from test_templates import _channel_with


def _item(title, source="Reuters", hint="") -> Item:
    return Item(source=source, title=title, summary="", url=f"https://x.test/{uuid.uuid4().hex[:6]}", media_hint=hint)


class FakeJev(jev.Jev):
    """Answers from tables keyed by words in the state; counts its calls."""

    fits = {"ad": 0.2, "cricket": 2.6, "budget": 2.9, "flood": 2.4}
    trending = {"budget": 2.8, "cricket": 1.0, "flood": 2.6}
    format_for: dict = {}
    fail_on: set = set()

    def __init__(self, key="k", client=None):
        super().__init__(key, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
        self.calls = 0

    def ask(self, state, questions):
        self.calls += 1
        text = json.dumps(state).lower()
        if any(w in text for w in self.fail_on):
            raise jev.JevError("boom")
        self.input_tokens += 100
        out = {}
        if "fits" in questions:
            out["fits"] = {"score": next((v for w, v in self.fits.items() if w in text), 1.5)}
            out["trending"] = {"score": next((v for w, v in self.trending.items() if w in text), 1.0)}
            out["genuine"] = {"noul": 0.1 if "ad" in text.split() else 0.9}
        if "format" in questions:
            pick = next((v for w, v in self.format_for.items() if w in text), None)
            if pick:
                out["format"] = {"choice": pick[0], "confidence": pick[1]}
        if "place_changed" in questions:
            out["place_changed"] = {"noul": 0.9 if "spire" in text else 0.1}
        if "same" in questions:
            out["same"] = {"noul": 0.9 if "budget" in text and "budget" in state["report"].lower() else 0.1}
        return out


def test_items_are_ranked_and_off_topic_ones_dropped():
    j = FakeJev()
    cands = [_item("Buy now ad of the week"), _item("Cricket score update"), _item("Union budget cuts income tax"),
             _item("Floods hit Assam"), _item("Mystery story")]
    FakeJev.fail_on = {"mystery"}
    try:
        out, info = decide.rank(j, cands, {"name": "News", "brief": "India news"}, keep=3)
    finally:
        FakeJev.fail_on = set()
    assert [i.title for i in out] == ["Union budget cuts income tax", "Floods hit Assam", "Cricket score update"]
    assert info == {"judged": 4, "dropped_off_topic": 1, "kept": 3}
    # an item Jev couldn't judge isn't lost: it goes after the judged ones
    FakeJev.fail_on = {"mystery"}
    try:
        out, _ = decide.rank(FakeJev(), cands, {"name": "N"}, keep=10)
    finally:
        FakeJev.fail_on = set()
    assert out[-1].title == "Mystery story"


def test_jev_overrides_the_writers_format_only_when_sure():
    fmts = [{"id": "a", "name": "News explainer", "template_id": "mini_news_explainer"},
            {"id": "b", "name": "Picture card", "template_id": "picture_above_text_below"}]
    FakeJev.format_for = {"budget": ("f1", 0.9), "flood": ("f1", 0.2)}
    try:
        picks = decide.pick_format(FakeJev(), [{"title": "Budget", "hook": "", "brief": ""},
                                               {"title": "Flood", "hook": "", "brief": ""}], [[], []], fmts, {})
    finally:
        FakeJev.format_for = {}
    assert picks == [(1, 0.9), (1, 0.2)] and 0.2 < decide.SURE <= 0.9
    assert decide.pick_format(FakeJev(), [{"title": "x", "hook": "", "brief": ""}], [[]], fmts[:1], {}) == [(None, 0.0)]


def test_same_story_is_judged_by_jev_and_falls_back_to_words():
    j = FakeJev()
    assert research.same_event(j, "Budget cuts income tax for the middle class", "Union budget 2026 tax cuts")
    assert not research.same_event(j, "Tax cuts debated in Germany", "Union budget 2026 tax cuts")
    calls = j.calls
    assert not research.same_event(j, "Cricket final tonight", "Union budget 2026 tax cuts")   # no shared word
    assert j.calls == calls                                                                   # so not asked
    FakeJev.fail_on = {"budget"}
    try:
        assert research.same_event(FakeJev(), "Union budget tax cuts explained", "Union budget 2026 tax cuts")
    finally:
        FakeJev.fail_on = set()
    assert research.same_event(None, "Union budget tax cuts explained", "Union budget 2026 tax cuts")


def test_the_client_retries_falls_back_to_the_alias_and_counts_tokens():
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body["model"])
        if body["model"] == jev.MODEL:
            return httpx.Response(400, json={"detail": {"message": "Unknown model: x"}})
        if len(seen) == 2:
            return httpx.Response(529, json={})
        return httpx.Response(200, json={"model": "jev-1.15.0", "answers": {"q": {"noul": 0.7}},
                                         "usage": {"input_tokens": 300}})

    j = jev.Jev("k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert j.ask("s", {"q": {"type": "noul", "instructions": "?"}}) == {"q": {"noul": 0.7}}
    assert seen == [jev.MODEL, jev.FALLBACK, jev.FALLBACK] and j.input_tokens == 300 and j.model == "jev-1.15.0"


def test_jev_is_priced(owner, user):
    with db.conn() as c:
        p = costs._price(c, user, "jev-1.14.0")
    assert (p["input_per_m"], p["output_per_m"]) == (0.042, 0.0)


class Writer:
    seen: list[str] = []

    def __init__(self, key):
        pass

    def write(self, *, model, system, user):
        Writer.seen.append(system)
        return IdeasOut(ideas=[Idea(title="Budget cuts income tax", hook="h", brief="b", why_now="today", items=[1],
                                    format=1, format_why="the writer's reason")]), Usage(model, 1000, 100)


def test_a_batch_uses_jev_for_items_and_formats_and_records_its_cost(owner, user, monkeypatch):
    owner.execute("insert into user_keys (user_id, name, ciphertext) values (%s, 'jev_api_key', %s)",
                  (user, encrypt("jev-key")))
    made = []

    def factory(key):
        assert key == "jev-key"
        made.append(FakeJev())
        return made[-1]

    monkeypatch.setattr(jev, "FACTORY", factory)
    monkeypatch.setattr(suggest_ideas, "WRITER_FACTORY", Writer)
    items = [_item("Union budget cuts income tax"), _item("Buy now ad of the week"), _item("Floods hit Assam"),
             _item("Cricket score update")]
    monkeypatch.setattr(suggest_ideas, "FETCH", lambda rows, **kw: (items, []))
    monkeypatch.setattr(suggest_ideas, "EMBED", lambda texts: [__import__("numpy").eye(8)[k] for k in range(len(texts))])

    class Mem:
        def nearest(self, channel, v):
            return 0.0, ""

        def remember(self, rows):
            pass

        def forget(self, ids):
            pass

    monkeypatch.setattr(suggest_ideas, "MEMORY", lambda log: Mem())
    ch, (news, card) = _channel_with(owner, user, "mini_news_explainer", "picture_above_text_below")
    cat = owner.execute("""insert into categories (user_id, channel_id, name, brief, format_ids, ideas_per_batch)
                           values (%s, %s, 'News', 'India news', %s, 1) returning id""",
                        (user, ch, [news, card])).fetchone()["id"]
    FakeJev.format_for = {"budget": ("f1", 0.88)}
    try:
        suggest_ideas.run(suggest_ideas.JobContext(job={"id": None, "payload": {"category_id": str(cat)}}))
    finally:
        FakeJev.format_for = {}
    prompt = Writer.seen[-1]
    assert "Buy now ad" not in prompt and prompt.index("Union budget") < prompt.index("Floods hit Assam")
    idea = owner.execute("select format_id, format_why from ideas where category_id = %s", (cat,)).fetchone()
    assert idea["format_id"] == card and idea["format_why"] == "Jev's pick (88% sure)"
    row = owner.execute("select model, quantity, usd_micros, note from costs where category_id = %s and note like 'Jev%%'",
                        (cat,)).fetchone()
    assert row["note"] == "Jev decisions: News" and row["usd_micros"] is not None
    assert len(made) == 1                                                  # one client for the whole batch


def test_without_a_key_there_is_no_jev(owner, user):
    assert jev.for_user(user) is None


def test_a_place_that_changed_goes_to_before_and_now_when_jev_is_sure():
    fmts = [{"id": "a", "name": "News explainer", "template_id": "mini_news_explainer"},
            {"id": "b", "name": "Before vs Now", "template_id": "before_after_comparison"}]
    FakeJev.format_for = {"spire": ("f0", 0.8), "budget": ("f0", 0.9)}
    try:
        picks = decide.pick_format(FakeJev(), [{"title": "Town hall spire falls in a fire", "hook": "", "brief": ""},
                                               {"title": "Budget", "hook": "", "brief": ""}], [[], []], fmts, {})
    finally:
        FakeJev.format_for = {}
    assert picks == [(1, 0.9), (0, 0.9)]

