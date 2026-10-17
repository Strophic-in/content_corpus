"""Housekeeping the ideas lane does between jobs, at most once an hour.

  * sweep card media, published reels' footage, and shots and narration nobody
    can use any more (ideas/sweep.py);
  * the health checks the Health page shows (health.py);
  * today's USD→INR rate, for pricing OpenAI calls in rupees;
  * once a day, what the parked Race pods cost to keep (their monthly_cost / 30),
    charged to the owner so the month's total is the whole bill;
  * once a day, the OpenAI models each key can use (new ones appear by themselves).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date

from . import costs, db, health, openai_models
from .ideas import sweep

log = logging.getLogger("corpus.upkeep")
EVERY_S = 3600
_last = 0.0
_models_day: date | None = None


def _owner_id() -> str | None:
    """Whose bill the shared GPU account is: the first allowed sign-in email's user."""
    email = (os.environ.get("AUTH_ALLOWED_EMAILS", "").split(",")[0] or "").strip().lower()
    row = db.one('select id from "user" where lower(email) = %s', (email,)) if email else None
    row = row or db.one('select id from "user" order by "createdAt" limit 1')
    return row["id"] if row else None


def _promote_owners() -> None:
    """The sign-in emails in AUTH_ALLOWED_EMAILS are the owners (memberships, 0019)."""
    emails = [e.strip().lower() for e in os.environ.get("AUTH_ALLOWED_EMAILS", "").split(",") if e.strip()]
    if not emails:
        return
    with db.conn() as c:
        n = c.execute("""update memberships m set role = 'owner', status = 'active', decided_at = now()
                           from "user" u
                          where u.id = m.user_id and lower(u.email) = any(%s)
                            and (m.role <> 'owner' or m.status <> 'active')""", (emails,)).rowcount
    if n:
        log.info("made %s account(s) owners (AUTH_ALLOWED_EMAILS)", n)


def _key_owners() -> list[str]:
    with db.conn() as c:
        return [r["user_id"] for r in c.execute("select user_id from user_keys where name = 'openai'").fetchall()]


def ideas_lane() -> None:
    global _last, _models_day
    if time.monotonic() - _last < EVERY_S:
        return
    _last = time.monotonic()
    try:
        sweep.sweep(lambda m: log.info(m))
        sweep.sweep_assets(lambda m: log.info(m))
        sweep.sweep_intermediates(lambda m: log.info(m))
        sweep.sweep_uploads(lambda m: log.info(m))
    except Exception:  # noqa: BLE001 - each chore on its own
        log.exception("card media sweep failed")
    try:
        _promote_owners()
    except Exception:  # noqa: BLE001
        log.exception("owner check failed")
    try:
        health.run_all(lambda m: log.warning(m))
    except Exception:  # noqa: BLE001
        log.exception("health checks failed")
    try:
        costs.refresh_fx()
    except Exception:  # noqa: BLE001
        log.exception("exchange rate refresh failed")
    if _models_day != date.today():
        _models_day = date.today()
        for user_id in _key_owners():
            try:
                openai_models.refresh(user_id)
            except Exception:  # noqa: BLE001 - tomorrow, or the Settings button
                log.exception("model list not refreshed")
    key = os.environ.get("RACE_API_KEY", "").strip()
    owner = _owner_id()
    if key and owner:
        try:
            from .race import RaceClient
            pods = [p for p in RaceClient(key).pods() if str(p.get("name", "")).startswith("corpus-")]
            n = costs.record_pod_storage(pods, user_id=owner)
            if n:
                log.info("recorded %s parked pod(s)' storage for today", n)
        except Exception:  # noqa: BLE001
            log.exception("pod storage cost not recorded")
