"""The day's post when the owner picked none: the single best story across the
channel's categories, made and posted on autopilot today — no idea batch."""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from corpus import db
from corpus.handlers import auto_pick, suggest_ideas
from corpus.ideas import feeds
from corpus.runner import JobContext
from test_ideas import channel  # noqa: F401


class Judge:
    def record(self, *a, **kw):
        pass


def _setup(ch, monkeypatch, titles_by_cat: dict[str, list[str]], scores: dict[str, float]):
    with db.conn() as c:
        c.execute("update channels set daily_auto_post = true, timezone = 'Asia/Kolkata' where id = %s", (ch,))
        uid = c.execute("select user_id from channels where id = %s", (ch,)).fetchone()["user_id"]
        cats = {}
        for name in titles_by_cat:
            cid = (c.execute("select id from categories where channel_id = %s and name = %s", (ch, name)).fetchone()
                   or c.execute("insert into categories (user_id, channel_id, name) values (%s, %s, %s) returning id",
                                (uid, ch, name)).fetchone())["id"]
            c.execute("insert into category_sources (user_id, category_id, kind, value) values (%s, %s, 'rss', %s)",
                      (uid, cid, f"https://{name.lower()}.test/feed"))
            cats[str(cid)] = name
    by_url = {f"https://{n.lower()}.test/feed": t for n, t in titles_by_cat.items()}

    def fetch(rows, **kw):
        out = []
        for r in rows:
            out += [feeds.Item("Wire", t, f"{t}. More detail.", f"https://news.test/{uuid.uuid4().hex[:6]}")
                    for t in by_url.get(r["value"], [])]
        return out, []
    monkeypatch.setattr(suggest_ideas, "FETCH", fetch)
    monkeypatch.setattr(auto_pick.jev, "for_user", lambda uid: Judge())
    monkeypatch.setattr(auto_pick.decide, "rank_scored",
                        lambda j, cands, cat, audience="": sorted(((scores.get(it.title, 0.0), it) for it in cands),
                                                                  key=lambda x: x[0], reverse=True))
    return uid


def _run(ch):
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    with db.conn() as c:
        uid = c.execute("select user_id from channels where id = %s", (ch,)).fetchone()["user_id"]
        job = db.enqueue(c, user_id=uid, lane="ideas", kind="auto_pick", dedupe_key=f"auto_pick:test:{uuid.uuid4()}",
                         payload={"channel_id": str(ch), "day": str(today)})
    return auto_pick.HANDLER.run(JobContext(job=job)), today


def test_the_days_best_story_is_made_and_posted_on_autopilot(channel, monkeypatch):
    _, ch, _ = channel
    _setup(ch, monkeypatch, {"General": ["Council approves a routine budget"],
                             "Science": ["ISRO's reusable rocket lands itself", "A new moth species"]},
           {"ISRO's reusable rocket lands itself": 9.1, "Council approves a routine budget": 4.0,
            "A new moth species": 5.5})
    out, today = _run(ch)
    assert out["picked"] == ["ISRO's reusable rocket lands itself"] and out["posts"][0]["category"] == "Science"
    out = out["posts"][0]
    with db.conn() as c:
        p = c.execute("""select topic, slot_date, pipeline_mode, go_ahead, status,
                                (publish_at at time zone 'Asia/Kolkata')::date as on_day,
                                publish_at - now() as lead from posts where id = %s""", (out["post_id"],)).fetchone()
        i = c.execute("select status, why_now from ideas where post_id = %s", (out["post_id"],)).fetchone()
    # Today at the posting time — or two hours from now when that time is too close (late at night,
    # just past midnight).
    assert p["slot_date"] == p["on_day"] and (p["on_day"] - today).days in (0, 1)
    assert p["lead"].total_seconds() >= 85 * 60
    assert p["pipeline_mode"] == "auto" and p["status"] == "scripting"
    assert (i["status"], i["why_now"]) == ("accepted", "Today's top story")
    # A second run the same day stands aside: the day's post is on its way.
    again, _ = _run(ch)
    assert "already on their way" in again["skipped"]


def test_a_story_covered_lately_is_passed_over_and_off_means_nothing(channel, monkeypatch):
    _, ch, _ = channel
    _setup(ch, monkeypatch, {"General": ["ISRO reusable rocket lands itself again", "Floods hit Assam villages"]},
           {"ISRO reusable rocket lands itself again": 9.0, "Floods hit Assam villages": 6.0})
    with db.conn() as c:
        uid = c.execute("select user_id from channels where id = %s", (ch,)).fetchone()["user_id"]
        c.execute("""insert into posts (user_id, channel_id, topic, slot_date) values (%s, %s,
                     'ISRO reusable rocket lands itself', current_date - 3)""", (uid, ch))
    out, _ = _run(ch)
    assert out["picked"] == ["Floods hit Assam villages"]
    with db.conn() as c:
        c.execute("update channels set daily_auto_post = false where id = %s", (ch,))
    off, _ = _run(ch)
    assert off == {"skipped": "automatic daily post is off"}


def test_several_a_day_from_different_categories_topping_up_the_owners_picks(channel, monkeypatch):
    _, ch, _ = channel
    _setup(ch, monkeypatch, {"General": ["Budget cuts income tax", "Metro fares rise"],
                             "Science": ["Rocket lands itself", "New moth species"]},
           {"Budget cuts income tax": 9.0, "Metro fares rise": 8.5, "Rocket lands itself": 7.0, "New moth species": 3.0})
    with db.conn() as c:
        c.execute("update channels set daily_auto_count = 3 where id = %s", (ch,))
        uid = c.execute("select user_id from channels where id = %s", (ch,)).fetchone()["user_id"]
        # the owner picked one for today in Discover: it counts towards the three
        c.execute("""insert into posts (user_id, channel_id, topic, slot_date, status, publish_tz)
                     values (%s, %s, 'Owner pick', (now() at time zone 'Asia/Kolkata')::date, 'scripting', 'Asia/Kolkata')""",
                  (uid, ch))
    out, _ = _run(ch)
    # two more: the best of each category first, then the next best overall
    assert out["wanted"] == 2 and out["picked"] == ["Budget cuts income tax", "Rocket lands itself"]
    times = [p["publish_at"] for p in out["posts"]]
    from datetime import datetime as dt
    gap = (dt.fromisoformat(times[1]) - dt.fromisoformat(times[0])).total_seconds()
    assert gap == 90 * 60
    full, _ = _run(ch)
    assert "already on their way" in full["skipped"] and "takes 3" in full["skipped"]
