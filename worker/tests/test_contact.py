"""The contact page's messages: kept for the owner, checked, and rate-limited."""

from __future__ import annotations

import uuid

import pytest

from test_render_pipeline import owner  # noqa: F401


def _send(owner, sender, email="reader@example.test", message="Hello, I run a news channel."):
    return owner.execute("select api.contact_message(%s, %s, %s, %s, %s) as id",
                         ("Asha", email, "Partnership", message, sender)).fetchone()["id"]


def test_a_message_is_kept_and_a_bad_one_refused(owner):
    sender = uuid.uuid4().hex
    mid = _send(owner, sender)
    row = owner.execute("select name, email, topic, message, emailed, read_at from contact_messages where id = %s",
                        (mid,)).fetchone()
    assert (row["name"], row["email"], row["topic"], row["emailed"], row["read_at"]) == \
        ("Asha", "reader@example.test", "Partnership", False, None)
    owner.execute("select api.contact_emailed(%s)", (mid,))
    assert owner.execute("select emailed from contact_messages where id = %s", (mid,)).fetchone()["emailed"]
    with pytest.raises(Exception, match="email address we can reply to"):
        _send(owner, sender, email="not-an-email")
    with pytest.raises(Exception, match="write a message"):
        _send(owner, sender, message=" ")
    owner.execute("delete from contact_messages where sender = %s", (sender,))


def test_one_sender_is_limited_to_a_few_an_hour(owner):
    sender = uuid.uuid4().hex
    for _ in range(5):
        _send(owner, sender)
    with pytest.raises(Exception, match="too many messages"):
        _send(owner, sender)
    _send(owner, uuid.uuid4().hex)            # someone else still can
    owner.execute("delete from contact_messages where sender = %s or created_at > now() - interval '1 minute'", (sender,))
