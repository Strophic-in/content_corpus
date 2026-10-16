"""Automatic mode: the worker takes the next step itself.

A post created while the owner's setting was Automatic carries
posts.pipeline_mode = 'auto' (a snapshot: flipping the setting later never
changes posts already made). For those posts:

    shots voiced (narrated) or planned (dialogue) → render
    reel assembled                                 → post at the time picked on the swipe

Each step runs in its own transaction, after the handler's own work has
committed, through the same private functions the buttons use
(private.request_render / private.request_publish, actor 'system:auto'). A
refusal — today's spending limit reached, an account disconnected — is written
to the post's activity and never undoes the work that came before it.
"""

from __future__ import annotations

from typing import Callable

import psycopg

from . import db


def _note(post_id, reason: str) -> None:
    with db.conn() as c:
        st = c.execute("select status from posts where id = %s", (post_id,)).fetchone()
        if st:
            db.log_event(c, post_id, st["status"], st["status"], "system:auto", reason)


def _auto(post_id) -> dict | None:
    return db.one("""select id, status, pipeline_mode, channel_id, platforms, publish_at
                       from posts where id = %s""", (post_id,))


def request_render(post_id, log: Callable[[str], None] = print) -> bool:
    p = _auto(post_id)
    if not p or p["pipeline_mode"] != "auto" or p["status"] not in ("approved", "failed"):
        return False
    try:
        with db.tx() as c:
            c.execute("select private.request_render(%s, 'system:auto')", (post_id,))
    except psycopg.Error as e:
        msg = (e.diag.message_primary or str(e)).strip()
        log(f"automatic render not started: {msg}")
        _note(post_id, f"automatic render not started: {msg}")
        return False
    db.note_enqueued("gpu")
    db.note_enqueued("cpu")
    return True


def request_publish(post_id, log: Callable[[str], None] = print) -> bool:
    p = _auto(post_id)
    if not p or p["pipeline_mode"] != "auto" or p["status"] != "ready":
        return False
    with db.conn() as c:
        connected = {r["platform"] for r in c.execute(
            "select platform from channel_accounts where channel_id = %s and status = 'connected'",
            (p["channel_id"],)).fetchall()}
    platforms = [pf for pf in (p["platforms"] or []) if pf in connected]
    if not platforms:
        _note(post_id, "not posted automatically: none of its platforms is connected")
        return False
    try:
        with db.tx() as c:
            c.execute("select count(*) from private.request_publish(%s, %s, %s, null, 'system:auto')",
                      (post_id, platforms, p["publish_at"]))
    except psycopg.Error as e:
        msg = (e.diag.message_primary or str(e)).strip()
        log(f"automatic posting not scheduled: {msg}")
        _note(post_id, f"automatic posting not scheduled: {msg}")
        return False
    db.note_enqueued("publish")
    return True
