"""Card media housekeeping: previews live only as long as someone may still look.

  rejected ideas      → media deleted a day after the swipe
  never swiped        → media deleted after UNSWIPED_DAYS (the card stays, text only)
  accepted            → kept (a post may use it), unless that post was deleted
  orphaned            → deleted (its idea, category or channel is gone)

Media is found through storage_objects (kind idea_media, key u/<user>/ideas/<idea>/…),
so nothing is missed when ideas are deleted in bulk. evict() frees room early,
oldest unswiped first, when the idea-media budget is full.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from psycopg.types.json import Jsonb

from .. import db, storage

UNSWIPED_DAYS = 7
REJECTED_DAYS = 1

_IDEA_OF_KEY = "nullif(substring(s.key from '/ideas/([0-9a-f-]{36})/'), '')::uuid"


def _delete(keys: list[str], log: Callable[[str], None]) -> int:
    n = 0
    for k in keys:
        try:
            storage.delete(k)
            n += 1
        except Exception as e:  # noqa: BLE001 - try again next sweep
            log(f"could not delete {k}: {e}")
    return n


def _expire(idea_ids: list) -> None:
    if idea_ids:
        with db.conn() as c:
            c.execute("""update ideas set media = '[]'::jsonb, media_state = 'expired'
                          where id = any(%s) and media_state = 'ready'""", (idea_ids,))


def sweep(log: Callable[[str], None] = print) -> int:
    with db.conn() as c:
        rows = c.execute(f"""
            select s.key, i.id as idea_id, i.status, i.created_at, i.decided_at, i.post_id
              from storage_objects s
              left join ideas i on i.id = {_IDEA_OF_KEY}
             where s.kind = 'idea_media' and s.state = 'stored'""").fetchall()
    gone, expired = [], []
    for r in rows:
        if r["idea_id"] is None:
            gone.append(r["key"])                                  # orphaned
        elif r["status"] == "rejected" and r["decided_at"] and \
                c_days(r["decided_at"]) >= REJECTED_DAYS:
            gone.append(r["key"])
        elif r["status"] == "new" and c_days(r["created_at"]) >= UNSWIPED_DAYS:
            gone.append(r["key"])
            expired.append(r["idea_id"])
        elif r["status"] == "accepted" and r["post_id"] is None and r["decided_at"] and \
                c_days(r["decided_at"]) >= UNSWIPED_DAYS:
            gone.append(r["key"])                                  # its post was deleted
    n = _delete(gone, log)
    _expire(list(dict.fromkeys(expired)))
    if n:
        log(f"swept {n} card media file(s)")
    return n


ASSET_KEEP_DAYS = 14


def sweep_assets(log: Callable[[str], None] = print) -> int:
    """A post's footage files (kind asset): kept while the reel may still be remade,
    deleted ASSET_KEEP_DAYS after it is published, or at once when the post is gone."""
    with db.conn() as c:
        rows = c.execute("""
            select s.key, a.id as asset_id, p.status,
                   (select max(e.at) from post_events e
                     where e.post_id = p.id and e.to_state = 'published') as published_at
              from storage_objects s
              left join assets a on a.key = s.key
              left join posts p on p.id = a.post_id
             where s.kind = 'asset' and s.state = 'stored'""").fetchall()
    gone, done = [], []
    for r in rows:
        if r["asset_id"] is None:
            gone.append(r["key"])                                  # its post (and asset row) was deleted
        elif r["status"] == "published" and r["published_at"] and c_days(r["published_at"]) >= ASSET_KEEP_DAYS:
            gone.append(r["key"])
            done.append(r["asset_id"])
    n = _delete(gone, log)
    if done:
        with db.conn() as c:
            c.execute("update assets set key = null, error = 'file removed after publishing' where id = any(%s)",
                      (done,))
    if n:
        log(f"swept {n} footage file(s)")
    return n


def evict(bytes_needed: int, log: Callable[[str], None] = print) -> int:
    """Free at least bytes_needed of card media, oldest unswiped ideas first."""
    with db.conn() as c:
        rows = c.execute(f"""
            select s.key, s.bytes, i.id as idea_id
              from storage_objects s join ideas i on i.id = {_IDEA_OF_KEY}
             where s.kind = 'idea_media' and s.state = 'stored' and i.status = 'new'
             order by i.created_at""").fetchall()
    freed, keys, ideas = 0, [], []
    for r in rows:
        if freed >= bytes_needed and r["idea_id"] not in ideas:
            break
        keys.append(r["key"])
        ideas.append(r["idea_id"])
        freed += int(r["bytes"])
    _delete(keys, log)
    _expire(list(dict.fromkeys(ideas)))
    log(f"made room for card media: freed {freed / 1e6:.1f} MB from {len(set(ideas))} old card(s)")
    return freed


def c_days(ts) -> float:
    return (datetime.now(timezone.utc) - ts).total_seconds() / 86400


def set_media(idea_id, media: list[dict], state: str, analysis: dict | None = None) -> None:
    with db.conn() as c:
        c.execute("update ideas set media = %s, media_state = %s, analysis = coalesce(%s, analysis) where id = %s",
                  (Jsonb(media), state, Jsonb(analysis) if analysis is not None else None, idea_id))
