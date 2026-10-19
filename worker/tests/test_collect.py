"""Collecting a post's assets before its script: the logos and photos of who the story
names, a headline card of each report, the owner's links — and the writer told what
each one is."""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta

import httpx
import pytest
from PIL import Image

from corpus import entities, finder
from corpus.media import headline_card
from corpus.research import Article
from corpus.script import footage
from corpus.script.llm import Footage, _footage_problems, generated_shot
from test_render_pipeline import as_user, owner, s3, user  # noqa: F401
from test_sources_media import _routes, public_dns  # noqa: F401


def _png(color, size=(600, 300), mode="RGBA") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, "PNG")
    return buf.getvalue()


def _wiki(req):
    q = req.url.params.get("gsrsearch", "")
    if q == "Jio Platforms":
        return httpx.Response(200, json={"query": {"pages": {"1": {
            "title": "Jio Platforms", "index": 1, "pageprops": {"wikibase_item": "Q96418672"},
            "pageimage": "Reliance_Jio_Logo.svg"}}}})
    # Wikipedia's best match for an unknown hospital chain is something else.
    return httpx.Response(200, json={"query": {"pages": {"2": {
        "title": "Paras (mountain)", "index": 1, "pageprops": {"wikibase_item": "Q1"}}}}})


ROUTES = {
    entities.WIKIPEDIA: _wiki,
    entities.WIKIDATA: httpx.Response(200, json={"claims": {}}),         # no P154: the article's lead picture
    entities.COMMONS: httpx.Response(200, json={"query": {"pages": {"9": {"imageinfo": [{
        "thumburl": "https://upload.test/jio.png", "descriptionurl": "https://commons.test/File:Jio",
        "extmetadata": {"LicenseShortName": {"value": "Public domain"}}}]}}}}),
}


def test_a_companys_logo_is_found_by_its_wikipedia_article_and_a_wrong_match_is_not(public_dns):
    client = _routes(ROUTES)
    hit = entities.lookup(client, entities.Entity("Jio Platforms", "company", True))
    assert hit["role"] == "logo" and hit["entity"] == "Jio Platforms" and hit["url"] == "https://upload.test/jio.png"
    assert hit["credit"] == "Jio Platforms logo / Wikimedia Commons" and hit["license"] == "cc0"
    assert entities.lookup(client, entities.Entity("Paras Healthcare", "company", False)) is None


def test_a_logo_is_drawn_on_a_card_that_keeps_it_visible(tmp_path):
    dark = Image.open(entities.logo_card(_png((10, 40, 140, 255)), tmp_path / "a.jpg"))
    white = Image.open(entities.logo_card(_png((255, 255, 255, 255)), tmp_path / "b.jpg"))
    assert dark.size == white.size == (1080, 1920)
    assert sum(dark.getpixel((20, 20))) > 600 and sum(white.getpixel((20, 20))) < 120   # light card, dark card
    assert dark.getpixel((540, 960))[2] > 100                                           # the logo, centred


def test_a_headline_card_draws_the_report_and_skips_scripts_its_fonts_lack(tmp_path):
    out = headline_card.render(tmp_path / "h.jpg", headline="Jio Platforms’ ₹30,213-crore IPO leads the week",
                               outlet="The Economic Times", published="2026-10-18T09:10:00+05:30",
                               photo=_png((200, 30, 30), (1200, 800), "RGB"))
    im = Image.open(out)
    assert im.size == (1080, 1920) and im.getpixel((540, 200))[0] > 150      # the report's photo on top
    assert sum(im.getpixel((540, 1800))) < 100                                # the bottom clear for captions
    assert headline_card._date("2026-10-18T09:10:00Z") == "18 October 2026"
    assert headline_card.render(tmp_path / "x.jpg", headline="जियो का आईपीओ", outlet="ET") is None


def _post(owner, uid):
    slot = date(2038, 1, 1) + timedelta(days=uuid.uuid4().int % 3000)
    return owner.execute("insert into posts (user_id, topic, slot_date) values (%s, 'Jio IPO', %s) "
                         "returning id, user_id", (uid, slot)).fetchone()


def test_collect_adds_logo_and_report_cards_once(s3, owner, user, public_dns, monkeypatch):
    post = _post(owner, user)
    monkeypatch.setattr(entities, "lookup", lambda client, e: {
        "url": "https://upload.test/jio.png", "page": "p", "origin": "wikidata", "credit": "Jio Platforms logo",
        "license": "cc0", "role": "logo", "entity": e.name, "central": True})
    client = _routes({"https://upload.test/jio.png": httpx.Response(200, content=_png((10, 40, 140, 255)),
                                                                     headers={"content-type": "image/png"}),
                      "https://news.test/lead.jpg": httpx.Response(200, content=_png((200, 30, 30), (900, 600), "RGB"),
                                                                   headers={"content-type": "image/png"})})
    arts = [Article("https://news.test/a", "news.test", "Jio Platforms' IPO leads the week", "text",
                    images=[{"url": "https://news.test/lead.jpg"}], outlet="ET Markets")]
    names = [entities.Entity("Jio Platforms", "company", True)]
    got = finder.collect(post, None, client, arts, story="s", title="t", topic="Jio IPO", want_before=False,
                         names=names, log=print)
    assert got == {"names": 1, "headlines": 1, "found": 0}
    rows = owner.execute("""select origin, kind, rights, credit, fetch_from from assets where post_id = %s order by n""",
                         (post["id"],)).fetchall()
    assert [(r["origin"], r["fetch_from"]["found"]["role"]) for r in rows] == [("wikidata", "logo"),
                                                                                ("article", "headline")]
    assert all(r["rights"] == "approved" and r["kind"] == "image" for r in rows)
    assert rows[1]["credit"] == "ET Markets" and rows[1]["fetch_from"]["found"]["outlet"] == "ET Markets"
    for r in rows:      # drawn here, stored as an upload: fetch_asset takes it from there
        assert s3.head_object(Bucket="corpus-test-media", Key=r["fetch_from"]["upload_key"])["ContentLength"] > 0
    assert owner.execute("select count(*) as n from jobs where post_id = %s and kind = 'fetch_asset'",
                         (post["id"],)).fetchone()["n"] == 2
    again = finder.collect(post, None, client, arts, story="s", title="t", topic="Jio IPO", want_before=False,
                           names=names, log=print)
    assert again == {"names": 0, "headlines": 0, "found": 0}                       # never twice
    owner.execute("delete from jobs where post_id = %s", (post["id"],))


def test_the_owner_adds_links_and_collects_again(owner, user):
    post = _post(owner, user)
    add = lambda url, kind="auto": as_user(owner, user, "select * from api.add_asset_link(%s, %s, %s)",  # noqa: E731
                                           (post["id"], url, kind))
    img = add("https://cdn.test/photo.JPG?w=1200")
    vid = add("https://www.youtube.com/watch?v=abc")
    page = add("https://news.test/story")
    forced = add("https://news.test/live", "video")
    assert (img["kind"], img["fetch_from"]["item"]["image_url"]) == ("image", "https://cdn.test/photo.JPG?w=1200")
    assert (vid["kind"], vid["credit"], vid["fetch_from"]["item"]["page_url"]) == ("video", "youtube.com",
                                                                                   "https://www.youtube.com/watch?v=abc")
    assert (page["kind"], page["fetch_from"]["item"]["media_hint"]) == ("image", "page")
    assert forced["kind"] == "video"
    assert {img["rights"], vid["origin"]} == {"approved", "link"}
    with pytest.raises(Exception, match="already one of this post"):
        add("https://news.test/story")
    with pytest.raises(Exception, match="full link"):
        add("not a link")
    assert owner.execute("select count(*) as n from jobs where post_id = %s and kind = 'fetch_asset'",
                         (post["id"],)).fetchone()["n"] == 4

    assert as_user(owner, user, "select api.collect_assets(%s) as r", (post["id"],))["r"] == "collecting"
    job = owner.execute("select id, state from jobs where dedupe_key = %s", (f"research_post:{post['id']}",)).fetchone()
    assert job["state"] == "queued"
    assert owner.execute("select research_state from posts where id = %s", (post["id"],)).fetchone()["research_state"] \
        == "pending"
    owner.execute("update jobs set state = 'succeeded' where id = %s", (job["id"],))
    as_user(owner, user, "select api.collect_assets(%s)", (post["id"],))          # again: the finished job revives
    assert owner.execute("select state from jobs where id = %s", (job["id"],)).fetchone()["state"] == "queued"
    owner.execute("delete from jobs where post_id = %s", (post["id"],))


def test_the_writer_is_told_what_each_asset_is_and_never_animates_a_logo():
    logo = {"n": 1, "kind": "image", "w": 1080, "h": 1920, "credit": "Jio logo", "origin": "wikidata",
            "role": "logo", "entity": "Jio Platforms"}
    card = {**logo, "n": 2, "role": "headline", "outlet": "ET Markets", "entity": "https://news.test/a"}
    assert "LOGO of Jio Platforms" in footage._describe(logo)
    assert "HEADLINE CARD of ET Markets" in footage._describe(card)
    fx = Footage(assets=[logo, card])
    assert "Real assets come first" in footage.prompt_section(fx, narrated=True)
    shot = lambda **kw: generated_shot(**{"seconds": 4, "visual": "v", "audio": "", "narration": "x", **kw})  # noqa: E731
    assert "warps its letters" in _footage_problems(1, shot(asset=1), fx, True)[0]
    assert not _footage_problems(1, shot(source="image", asset=1), fx, True)
