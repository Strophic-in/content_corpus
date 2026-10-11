"""Database access for workers: a small pool and the queue RPCs.

The pool keeps no idle connections (min_size=0, short max_idle): an idle worker
should hold nothing open on the shared VibeDB cluster, where every project's
connections come out of one PostgreSQL's limit.
"""

from __future__ import annotations

import functools
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .config import settings


@functools.lru_cache(maxsize=1)
def pool() -> ConnectionPool:
    return ConnectionPool(
        settings().database_url,
        min_size=0,
        max_size=4,
        max_idle=60,
        kwargs={"row_factory": dict_row, "autocommit": True},
        open=True,
    )


@contextmanager
def conn() -> Iterator[Connection]:
    with pool().connection() as c:
        yield c


@contextmanager
def tx() -> Iterator[Connection]:
    """A connection inside one transaction (committed on clean exit)."""
    with pool().connection() as c:
        with c.transaction():
            yield c


def one(sql: str, params: Any = None) -> dict | None:
    with conn() as c:
        return c.execute(sql, params).fetchone()


# ── queue RPCs (private schema; owner only) ───────────────────────────────────

def ping(lane: str, version: str, boot_id: str, stats: dict) -> None:
    s = settings()
    with conn() as c:
        c.execute("select private.worker_ping(%s, %s, %s, %s, %s)",
                  (s.worker_id, lane, version, boot_id, Jsonb(stats)))


def claim(lane: str, version: str, kinds: list[str] | None) -> dict | None:
    row = one("select * from private.claim_job(%s, %s, %s, %s)",
              (settings().worker_id, lane, version, kinds))
    # claim_job returns a NULL composite when nothing is ready.
    return row if row and row.get("id") else None


def heartbeat(job_id, stats: dict) -> bool:
    row = one("select private.heartbeat_job(%s, %s, %s) as ok",
              (job_id, settings().worker_id, Jsonb(stats)))
    return bool(row and row["ok"])


def finish(job_id, state: str, *, error: dict | None = None, result: dict | None = None,
           retry_in: int | None = None) -> dict:
    return one("select * from private.finish_job(%s, %s, %s, %s, %s, %s)",
               (job_id, settings().worker_id, state,
                Jsonb(error) if error is not None else None,
                Jsonb(result) if result is not None else None, retry_in))


def reap() -> list[dict]:
    with conn() as c:
        return c.execute("select * from private.reap_expired_leases()").fetchall()


def next_due(lanes: list[str]) -> datetime | None:
    row = one("select private.next_due(%s) as due", (lanes,))
    return row["due"] if row else None


# Lanes this process queued work for since the last take_enqueued_lanes(). The runner
# reads it after each job to wake the other workers (handlers run on the main thread).
_enqueued_lanes: set[str] = set()


def take_enqueued_lanes() -> set[str]:
    lanes = set(_enqueued_lanes)
    _enqueued_lanes.clear()
    return lanes


def enqueue(c: Connection, *, user_id: str, lane: str, kind: str, dedupe_key: str,
            payload: dict | None = None, post_id=None, shot_id=None, batch_id=None,
            priority: int = 100, max_attempts: int = 1, lease_seconds: int = 120,
            state: str = "queued", not_before: datetime | None = None) -> dict:
    if state == "queued":
        _enqueued_lanes.add(lane)
    return c.execute(
        """select * from private.enqueue_job(
             p_user_id => %s, p_lane => %s, p_kind => %s, p_dedupe_key => %s,
             p_payload => %s, p_post_id => %s, p_shot_id => %s, p_batch_id => %s,
             p_priority => %s, p_max_attempts => %s, p_lease_seconds => %s,
             p_state => %s, p_not_before => %s)""",
        (user_id, lane, kind, dedupe_key, Jsonb(payload or {}), post_id, shot_id, batch_id,
         priority, max_attempts, lease_seconds, state, not_before)).fetchone()


def schedule_daily_ideas() -> int:
    """Queue each channel's daily idea batch for today if it is not queued yet."""
    with conn() as c:
        return c.execute("select private.schedule_daily_ideas() as n").fetchone()["n"]


def log_event(c: Connection, post_id, from_state: str | None, to_state: str, actor: str,
              reason: str | None = None, detail: dict | None = None) -> None:
    c.execute("select private.log_post_event(%s, %s, %s, %s, %s, %s)",
              (post_id, from_state, to_state, actor, reason,
               Jsonb(detail) if detail is not None else None))
