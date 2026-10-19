"""Moving a post to another day (the calendar's drag and drop)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from test_render_pipeline import as_user, owner, user  # noqa: F401


def _post(owner, uid, status="draft"):
    slot = date.today() + timedelta(days=30 + uuid.uuid4().int % 300)
    return owner.execute("""insert into posts (user_id, topic, slot_date, status, publish_tz, publish_at)
                            values (%s, 'm', %s, %s, 'Asia/Kolkata', (%s::date + time '18:30') at time zone 'Asia/Kolkata')
                            returning id, slot_date""", (uid, slot, status, slot)).fetchone()


def test_a_post_moves_with_its_time_of_day_and_its_scheduled_publishing(owner, user):
    p = _post(owner, user)
    to = p["slot_date"] + timedelta(days=3)
    assert as_user(owner, user, "select api.move_post(%s, %s) as r", (p["id"], to))["r"] == "moved"
    row = owner.execute("""select slot_date, to_char(publish_at at time zone publish_tz, 'HH24:MI') as t
                             from posts where id = %s""", (p["id"],)).fetchone()
    assert row["slot_date"] == to and row["t"] == "18:30"
    assert as_user(owner, user, "select api.move_post(%s, %s) as r", (p["id"], to))["r"] == "unchanged"

    s = _post(owner, user, "scheduled")
    owner.execute("""select private.enqueue_job(%s, 'publish', 'publish_post', %s, '{}'::jsonb, %s,
                                                p_not_before => now() + interval '30 days')""",
                  (user, f"publish:{s['id']}:youtube", s["id"]))
    later = s["slot_date"] + timedelta(days=1)
    as_user(owner, user, "select api.move_post(%s, %s)", (s["id"], later))
    job = owner.execute("""select (not_before at time zone 'Asia/Kolkata')::date as d,
                                  to_char(not_before at time zone 'Asia/Kolkata', 'HH24:MI') as t
                             from jobs where dedupe_key = %s""", (f"publish:{s['id']}:youtube",)).fetchone()
    assert (job["d"], job["t"]) == (later, "18:30")
    owner.execute("delete from jobs where post_id = %s", (s["id"],))


def test_not_into_the_past_and_not_once_posted(owner, user):
    p = _post(owner, user)
    with pytest.raises(Exception, match="today or a later day"):
        as_user(owner, user, "select api.move_post(%s, %s)", (p["id"], date.today() - timedelta(days=2)))
    done = _post(owner, user, "published")
    with pytest.raises(Exception, match="can't be moved"):
        as_user(owner, user, "select api.move_post(%s, %s)", (done["id"], done["slot_date"] + timedelta(days=1)))
