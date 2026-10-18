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

The Library's "Make it" (posts.go_ahead, migration 0024) does the render step for
one post in any mode, as the owner's own request (actor 'system:go_ahead': the
automatic daily spending cap does not apply; the monthly limit does).
"""

from __future__ import annotations

from typing import Callable

import psycopg

from . import db, templates


def _note(post_id, reason: str) -> None:
    with db.conn() as c:
        st = c.execute("select status from posts where id = %s", (post_id,)).fetchone()
        if st:
            db.log_event(c, post_id, st["status"], st["status"], "system:auto", reason)


def _refused(post_id, why: str, log: Callable[[str], None]) -> None:
    log(f"automatic render not started: {why}")
    _note(post_id, f"automatic render not started: {why}")
    # A go-ahead ends with its refusal: the owner decides again from the post page.
    with db.tx() as c:
        c.execute("update posts set go_ahead = false where id = %s and go_ahead", (post_id,))


def _auto(post_id) -> dict | None:
    return db.one("""select id, status, pipeline_mode, go_ahead, channel_id, platforms, publish_at
                       from posts where id = %s""", (post_id,))


def request_render(post_id, log: Callable[[str], None] = print) -> bool:
    p = _auto(post_id)
    if not p or not (p["pipeline_mode"] == "auto" or p["go_ahead"]) or p["status"] not in ("approved", "failed"):
        return False
    actor = "system:go_ahead" if p["go_ahead"] else "system:auto"
    owner = db.one("select user_id from posts where id = %s", (post_id,))["user_id"]
    if why := db.over_quota(owner):
        _refused(post_id, why, log)
        return False
    try:
        with db.tx() as c:
            c.execute("select private.request_render(%s, %s)", (post_id, actor))
    except psycopg.Error as e:
        _refused(post_id, (e.diag.message_primary or str(e)).strip(), log)
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
    with db.conn() as c:
        post = c.execute("select format_id, audio_source from posts where id = %s", (post_id,)).fetchone()
        mode = templates.look_for_post(c, post).music_source_mode
    if mode == "platform_native":
        _note(post_id, "ready — not posted automatically: its format leaves the music to you; add a song in the app "
                       "and post it from there, or post it here as it is")
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
