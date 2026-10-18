"""The Library's "Approve & render" (posts.go_ahead, migration 0024): one click takes
a post the rest of the way — script written, approved, voiced, rendered."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from test_render_pipeline import (  # noqa: F401
    as_user, cpu, fake_whisper, fakes, owner, pod_notes, s3, segment_cache, user,
)


def _draft(owner, uid) -> str:
    slot = date(2039, 1, 1) + timedelta(days=uuid.uuid4().int % 3000)
    return owner.execute("insert into posts (user_id, topic, slot_date, audio_source, target_seconds) "
                         "values (%s, 'glow', %s, 'kokoro', 15) returning id", (uid, slot)).fetchone()["id"]


def _post(owner, pid):
    return owner.execute("select status, go_ahead from posts where id = %s", (pid,)).fetchone()


def test_a_draft_goes_all_the_way_to_the_gpu(s3, owner, user):
    pid = _draft(owner, user)
    assert as_user(owner, user, "select api.go_ahead(%s) as r", (pid,))["r"] == "writing the script"
    assert _post(owner, pid) == {"status": "scripting", "go_ahead": True}
    cpu().tick()                                                       # write_script: approved as written
    assert _post(owner, pid)["status"] == "approved"
    assert owner.execute("select approved_by from scripts where post_id = %s", (pid,)).fetchone()["approved_by"] \
        == "system:go_ahead"
    cpu().tick()                                                       # plan_shots
    cpu().tick()                                                       # narrate → the render starts itself
    assert _post(owner, pid) == {"status": "queued_for_render", "go_ahead": False}
    assert owner.execute("select count(*) as n from jobs where post_id = %s and kind = 'render_post'",
                         (pid,)).fetchone()["n"] == 1
    owner.execute("delete from jobs where post_id = %s", (pid,))


def test_a_script_waiting_for_review_is_approved_and_renders_when_voiced(s3, owner, user):
    pid = _draft(owner, user)
    as_user(owner, user, "select api.generate_script(%s)", (pid,))
    cpu().tick()                                                       # written; waits for the owner
    assert _post(owner, pid) == {"status": "awaiting_approval", "go_ahead": False}
    assert as_user(owner, user, "select api.go_ahead(%s) as r", (pid,))["r"] == "approved"
    cpu().tick()                                                       # plan_shots
    # Not voiced yet: "Render" now leaves the go-ahead for the worker.
    assert as_user(owner, user, "select api.go_ahead(%s) as r", (pid,))["r"] == "will render when its shots are ready"
    assert _post(owner, pid) == {"status": "approved", "go_ahead": True}
    cpu().tick()                                                       # narrate
    assert _post(owner, pid) == {"status": "queued_for_render", "go_ahead": False}
    owner.execute("delete from jobs where post_id = %s", (pid,))


def test_without_a_go_ahead_nothing_renders_on_its_own_and_a_finished_post_refuses(s3, owner, user):
    pid = _draft(owner, user)
    as_user(owner, user, "select api.generate_script(%s)", (pid,))
    cpu().tick()
    sid = owner.execute("select id from scripts where post_id = %s", (pid,)).fetchone()["id"]
    as_user(owner, user, "select api.approve_script(%s)", (sid,))
    cpu().tick()
    cpu().tick()                                                       # voiced, and it waits for the owner
    assert _post(owner, pid) == {"status": "approved", "go_ahead": False}
    owner.execute("update posts set status = 'cancelled' where id = %s", (pid,))
    with pytest.raises(Exception, match="nothing to do: it is cancelled"):
        as_user(owner, user, "select api.go_ahead(%s)", (pid,))
    # Someone else's post: not found.
    other = f"test-{uuid.uuid4().hex[:10]}"
    owner.execute('insert into "user" (id, name, email, "emailVerified") values (%s,%s,%s,true)',
                  (other, other, f"{other}@example.test"))
    with pytest.raises(Exception):
        as_user(owner, other, "select api.go_ahead(%s)", (pid,))
    owner.execute('delete from "user" where id = %s', (other,))
    owner.execute("delete from jobs where post_id = %s", (pid,))
