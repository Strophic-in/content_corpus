"""publish_attempts bookkeeping: where a post to one platform has got to.

At most one attempt per (post, platform) is in flight or live (a unique index in
0002), so `current` is the one to resume, and `start` fails rather than open a
second while one is open.
"""

from __future__ import annotations

from psycopg.types.json import Jsonb

from .. import db

OPEN = ("started", "uploading", "uploaded", "scheduled", "live")
_COLUMNS = {"state", "upload_session_uri", "remote_id", "remote_url", "privacy", "response", "error"}


def current(post_id, platform: str) -> dict | None:
    return db.one("""select * from publish_attempts
                      where post_id = %s and platform = %s and state = any(%s)
                      order by created_at desc limit 1""", (post_id, platform, list(OPEN)))


def start(post_id, platform: str) -> dict:
    return db.one("insert into publish_attempts (post_id, platform) values (%s, %s) returning *",
                  (post_id, platform))


def update(attempt: dict, **fields) -> dict:
    """Write fields to the attempt row and return it updated (in memory too)."""
    unknown = set(fields) - _COLUMNS
    if unknown:
        raise ValueError(f"not attempt columns: {sorted(unknown)}")
    sets = ", ".join(f"{k} = %s" for k in fields)
    vals = [Jsonb(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
    with db.conn() as c:
        c.execute(f"update publish_attempts set {sets} where id = %s", (*vals, attempt["id"]))
    attempt.update(fields)
    return attempt
