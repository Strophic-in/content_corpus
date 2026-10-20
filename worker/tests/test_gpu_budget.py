"""At most N shots of a video on the GPU (owner, 2026-10-19: two are enough); the rest
from the pictures and footage collected, moving on screen."""

from __future__ import annotations

from corpus.media import footage as media_footage
from corpus.script import footage
from corpus.script.llm import Footage, Review, ScriptOut, generated_shot, validate

PIC = {"n": 1, "kind": "image", "w": 1600, "h": 1000, "credit": "x", "origin": "article"}


def _shot(**kw):
    return generated_shot(**{"seconds": 5, "visual": "v", "audio": "", "narration": "A line.", **kw})


def _script(*shots) -> ScriptOut:
    return ScriptOut(title="t", hook="h", description="d", hashtags=["#shorts"], intended_dialogue="",
                     shots=list(shots), style_prompt="s", music_mood="", review=Review(score=8, risks=[], notes=""))


def test_more_generated_shots_than_the_budget_is_sent_back():
    fx = Footage(assets=[PIC], gpu_cap=2)
    three = _script(_shot(), _shot(), _shot(), _shot(source="image", asset=1))
    problems = validate(three, 20, narrated=True, footage=fx)
    assert any("3 shots (1, 2, 3)" in p and "at most 2" in p for p in problems)
    ok = _script(_shot(), _shot(source="image", asset=1), _shot(source="image", asset=1), _shot())
    assert not any("at most 2" in p for p in validate(ok, 20, narrated=True, footage=fx))
    # animating a picture is a GPU shot too
    i2v = _script(_shot(), _shot(asset=1), _shot())
    assert any("at most 2" in p for p in validate(i2v, 20, narrated=True, footage=fx))
    # no budget: no limit
    assert not any("at most" in p for p in validate(three, 20, narrated=True, footage=Footage(assets=[PIC])))


def test_the_writer_is_told_the_budget_and_how_pictures_move():
    text = footage.prompt_section(Footage(assets=[PIC], gpu_cap=2), narrated=True)
    assert "GPU budget: at most 2 generated shots" in text and "scroll down a tall one" in text
    assert "No shot may be" in footage.prompt_section(Footage(assets=[PIC], gpu_cap=0), narrated=True)
    assert "GPU budget" not in footage.prompt_section(Footage(assets=[PIC]), narrated=True)


def test_pictures_move_in_turn():
    W, H = 1080, 1920
    assert media_footage.choose_move(800, 3000, 0) == "scroll_down"           # a tall picture scrolls
    assert [media_footage.choose_move(3000, 1000, i) for i in range(4)] == ["zoom_in", "pan_right", "zoom_out",
                                                                            "pan_left"]
    assert media_footage.choose_move(1080, 1920, 1) == "zoom_out"              # the frame's own shape: zoom
    assert media_footage.choose_move(3000, 1000, 1, layout="blur_pad") == "zoom_out"   # a set layout is kept
    assert (W, H) == (media_footage.W, media_footage.H)


def test_the_narration_never_names_the_outlet():
    from corpus.handlers.write_script import outlet_names, outlet_problems
    names = outlet_names({"articles": [{"site": "bbc.co.uk"}, {"site": "nature.com"}]})
    assert "BBC News" in names and "BBC" in names and "nature" not in names
    bad = _script(_shot(narration="The BBC reports that the spire fell."), _shot(narration="It fell in minutes."))
    probs = outlet_problems(bad, names)
    assert len(probs) == 1 and probs[0].startswith("shot 1 names BBC")
    ok = _script(_shot(narration="Police say the fire began in the roof; ani-mated crowds watched."))
    assert outlet_problems(ok, names) == []


def test_a_picture_with_words_in_it_goes_above_the_captions():
    from corpus.handlers.plan_shots import _split_if_worded
    worded = {"role": "photo", "words": ["BREAKING NEWS", "Brent hits $95"]}
    assert _split_if_worded({}, worded) == {"layout": "split"}
    assert _split_if_worded({}, {"role": "headline", "words": ["Jio IPO leads the week"]}) == {}   # card leaves room
    assert _split_if_worded({}, {"role": "photo", "words": ["AI"]}) == {}                          # a word or two
    assert _split_if_worded({"layout": "full"}, worded) == {"layout": "full"}                      # the writer's choice


def test_the_storys_shape_picks_the_format():
    from corpus.ideas.decide import by_shape
    here = ["mini_news_explainer", "cinematic_3d_explainer", "full_screen_text_overlay", "top_bottom_split_screen",
            "myth_vs_fact"]
    noul = lambda v: {"noul": v}  # noqa: E731
    assert by_shape({"moment": noul(0.9), "explain": noul(0.7)}, here)[:1] == (2,)        # footage and text
    assert by_shape({"numbers": noul(0.8)}, here)[0] == 3                                  # split screen
    assert by_shape({"myth": noul(0.9), "moment": noul(0.9)}, here)[0] == 4
    assert by_shape({"explain": noul(0.8), "concept": noul(0.9)}, here)[0] == 1            # 3D explainer
    assert by_shape({"explain": noul(0.8), "concept": noul(0.1)}, here)[0] == 0            # news explainer
    assert by_shape({"list": noul(0.9)}, here) == (None, 0.0, "")                          # no countdown here


def test_dashes_never_reach_the_screen():
    from corpus.style import undash
    assert undash("A spire fell — in four minutes.") == "A spire fell, in four minutes."
    assert undash("Prices rose 2019–2024") == "Prices rose 2019-2024"
    assert undash("— Breaking: rain") == "Breaking: rain"
    assert undash("no dash here") == "no dash here"
