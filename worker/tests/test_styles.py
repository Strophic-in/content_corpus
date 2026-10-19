"""Caption styles and cover styles: every preset draws, Jev picks among those switched
on for the post's kind, and a cover never claims what its pictures can't show."""

from __future__ import annotations

import httpx
from PIL import Image

from corpus import jev, styles
from corpus.media import assemble, thumbnail


def test_every_caption_style_builds_captions():
    words = [(0.0, 0.3, "A"), (0.3, 0.7, "SPIRE"), (0.7, 1.1, "FELL")]
    assert len(styles.captions()) >= 10
    for sid in styles.captions():
        st = styles.caption_style(sid)
        doc = assemble.captions_ass(words, set(), st)
        assert "Style: Cap," in doc and doc.count("Dialogue:") == 3, sid
    assert ",3," in assemble.caption_style_line(styles.caption_style("news_box"))       # a box
    dim = assemble.caption_events(words, set(), styles.caption_style("highlight_dim"))
    assert "1a&H8C&" in dim[1]                                                           # the others faded
    assert "\\t(0,110" in assemble.caption_events(words, set(), styles.caption_style("bold_pop"))[0]   # pop


def test_every_cover_style_draws(tmp_path):
    pic = tmp_path / "p.jpg"
    Image.new("RGB", (1600, 1000), (90, 60, 40)).save(pic)
    assert len(styles.thumbs()) >= 10 and set(styles.thumbs()) <= set(thumbnail.STYLES)
    for sid in thumbnail.STYLES:
        out = thumbnail.render(tmp_path / f"{sid}.jpg", line="1,200 arrested as the spire falls", kicker="Breaking",
                               picture=pic, before=pic if sid == "before_now" else None, brand="T", style=sid)
        assert Image.open(out).size == (1080, 1920) and out.stat().st_size < 2_000_000, sid


class PickJev(jev.Jev):
    def __init__(self, choice="c1", sure=0.9):
        super().__init__("k", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
        self.choice, self.sure, self.asked = choice, sure, None

    def ask(self, state, questions, images=None):
        self.asked = questions["style"]["criteria"]
        return {"style": {"choice": self.choice, "confidence": self.sure}}


def test_jev_picks_among_the_styles_switched_on_for_the_posts_kind():
    j = PickJev("c1")
    sid, why = styles.choose_caption(j, ["bold_pop", "news_box", "meme_impact"], story="Floods in Assam")
    assert sid == "news_box" and why.startswith("Jev's pick") and len(j.asked) == 2     # no meme style for news
    sid, _ = styles.choose_caption(PickJev("c0"), None, story="lol", template="meme_reaction")
    assert styles.captions()[sid]["families"] == ["meme"] or "meme" in styles.captions()[sid]["families"]
    assert styles.choose_caption(PickJev(sure=0.1), ["news_box", "bold_pop"], story="x")[0] == "bold_pop"


def test_a_cover_claims_only_what_it_can_show():
    j = PickJev("c0")
    styles.choose_thumb(j, None, title="t", line="Spire falls", story="s")
    offered = j.asked
    assert not any("Before / Now" in v or "Big number" in v for v in offered.values())
    j = PickJev("c0")
    styles.choose_thumb(j, None, title="t", line="1,200 arrested", story="s", has_before=True, has_number=True)
    assert any("Before / Now" in v for v in j.asked.values()) and any("Big number" in v for v in j.asked.values())
