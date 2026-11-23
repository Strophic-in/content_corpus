"""Hooks in the script, the cover and the caption, and picking the spicier story.
DB-free: nothing here touches the database."""

from __future__ import annotations

from corpus import packaging
from corpus.handlers import auto_pick, write_script
from corpus.ideas import decide
from corpus.ideas.feeds import Item
from corpus.script.llm import HOOK_RULES
from corpus.script.review import INSTRUCTIONS


def test_hook_rules_are_appended_even_to_a_prompt_the_owner_saved():
    fmt = {"template_id": "full_screen_text_overlay", "script_prompt": "My own prompt for {channel_name}.",
           "visual_style": ""}
    system = write_script._system_prompt({"channel_name": "Desk"}, 40, "", "kokoro", fmt=fmt)
    assert system.startswith("My own prompt for Desk.") and system.endswith(HOOK_RULES)
    assert "Did you know" in system and "supported by the collected" in system
    # and to a prompt that comes from a file
    assert HOOK_RULES in write_script._system_prompt({}, 40, "", "kokoro", speed=1.1)


def test_the_desk_editor_checks_the_hook():
    assert "hook" in INSTRUCTIONS and "never pays off" in INSTRUCTIONS


class _Stub:
    """A Jev that answers from a table keyed by words in the item's title."""

    def __init__(self, pull, trending=None):
        self.pull, self.trending = pull, trending or {}

    def many(self, calls):
        out = []
        for state, _ in calls:
            title = state["item"]
            find = lambda table, d: next((v for k, v in table.items() if k in title), d)  # noqa: E731
            out.append({"fits": {"score": 2.5}, "trending": {"score": find(self.trending, 2.0)},
                        "genuine": {"noul": 1.0}, "pull": {"score": find(self.pull, 0.0)}})
        return out


def _it(title):
    return Item("Wire", title, "", f"https://x.test/{abs(hash(title))}")


def test_pull_weighs_2_5_so_a_spicy_story_beats_a_routine_one_that_trends_harder():
    assert decide.PULL_WEIGHT == 2.5
    cands = [_it("routine update"), _it("weird twist")]
    ranked = decide.rank_scored(_Stub({"routine": 1.5, "weird": 2.5}, {"routine": 3.0, "weird": 1.0}), cands, {"name": "N"})
    assert [it.title for _, it in ranked] == ["weird twist", "routine update"]
    # fit + 0.8 trending + 1.5 genuine + 2.5 pull
    assert ranked[0][0] == 2.5 + 0.8 * 1.0 + 1.5 + 2.5 * 2.5
    # under the old weight (1.5) the routine story would have won
    old = lambda trend, pull: 2.5 + 0.8 * trend + 1.5 + 1.5 * pull  # noqa: E731
    assert old(3.0, 1.5) > old(1.0, 2.5)


def test_pull_question_rewards_spice_and_penalises_dry_releases():
    ask = decide.RANK_QUESTIONS["pull"]["instructions"]
    for word in ("spicy", "weird", "stand-out", "irony", "big or striking number", "dry press"):
        assert word in ask


def test_a_category_is_not_left_empty_by_spicier_stories_elsewhere():
    sc = [(9.0, _it("Spicy A1"), {"id": "a"}), (8.8, _it("Spicy A2"), {"id": "a"}),
          (5.0, _it("Quiet B"), {"id": "b"})]
    assert [t.title for _, t, _ in auto_pick._choose(sc, 2)] == ["Spicy A1", "Quiet B"]


def test_packaging_asks_for_a_hook_cover_and_passes_the_scripts_hook():
    s = packaging.SYSTEM
    assert "punchy curiosity hook" in s and "ALL CAPS" in s and "2-5 words" in s
    assert "first line is hook_line" in s and 'taps "more"' in s
    brief = packaging._brief({"title": "T", "hook": "The spire fell in four minutes", "shot_plan": []})
    assert "The spire fell in four minutes" in brief and "cover text must" in brief
