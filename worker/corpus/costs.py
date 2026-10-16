"""The cost ledger: every model call and every GPU minute, priced when it happens.

OpenAI is priced in US dollars from the owner's own price table (Settings),
falling back to DEFAULT_PRICES — list prices when this was written, matched by
model-name prefix. A model with no price is still recorded (its tokens), with
usd_micros null, and the UI asks for a price. GPU time is priced in rupees from
the rate Race quotes for that GPU. Each row freezes the day's USD→INR rate, so a
month's total doesn't drift when the rate does.

Recording never breaks the work it describes: a failed insert is logged and
swallowed.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
from psycopg.types.json import Jsonb

from . import db

log = logging.getLogger("corpus.costs")

# USD per 1M tokens: (input, cached input, output). List prices at the time of
# writing; the owner overrides any of them in Settings (table `prices`).
DEFAULT_PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4.1-nano": (0.10, 0.025, 0.40),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4.1": (2.00, 0.50, 8.00),
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-5": (1.25, 0.125, 10.00),
    "omni-moderation": (0.0, 0.0, 0.0),
}

FX_URL = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=INR"


def _price(c, user_id: str, model: str | None) -> dict | None:
    if not model:
        return None
    row = c.execute("""select input_per_m, cached_input_per_m, output_per_m, per_image from prices
                        where user_id = %s and model = %s""", (user_id, model)).fetchone()
    if row and row["input_per_m"] is not None:
        return {k: float(v) if v is not None else None for k, v in row.items()}
    # A list price applies to that model and its dated snapshots ("gpt-4o-mini-2024-07-18"),
    # never to another model that merely shares a prefix ("gpt-5.6-luna" is not "gpt-5").
    for name in DEFAULT_PRICES:
        if model == name or re.fullmatch(re.escape(name) + r"-\d{4}-\d{2}-\d{2}", model):
            i, ci, o = DEFAULT_PRICES[name]
            return {"input_per_m": i, "cached_input_per_m": ci, "output_per_m": o,
                    "per_image": row["per_image"] if row else None}
    return None


def fx_usd_inr(c, user_id: str) -> Decimal | None:
    """The owner's override, else the latest rate fetched in the last week."""
    o = c.execute("select usd_inr_override as r from app_settings where user_id = %s", (user_id,)).fetchone()
    if o and o["r"]:
        return Decimal(o["r"])
    r = c.execute("select usd_inr from fx_rates where day > current_date - 7 order by day desc limit 1").fetchone()
    return Decimal(r["usd_inr"]) if r else None


def _insert(c, **row) -> None:
    cols = ", ".join(row)
    vals = [Jsonb(v) if isinstance(v, dict) else v for v in row.values()]
    c.execute(f"insert into costs ({cols}) values ({', '.join(['%s'] * len(row))})", vals)


def record_llm(usage, *, user_id: str, kind: str = "llm", post_id=None, channel_id=None, category_id=None,
               job_id=None, images: int = 0, note: str | None = None) -> None:
    """One model call. `usage` has model, input_tokens, output_tokens and optionally
    cached_input_tokens."""
    try:
        with db.conn() as c:
            cached = int(getattr(usage, "cached_input_tokens", 0) or 0)
            tokens_in, tokens_out = int(usage.input_tokens or 0), int(usage.output_tokens or 0)
            p = _price(c, user_id, usage.model)
            usd = None
            if p is not None:
                cached_rate = p["cached_input_per_m"] if p["cached_input_per_m"] is not None else p["input_per_m"]
                usd = round((tokens_in - cached) * p["input_per_m"] + cached * cached_rate
                            + tokens_out * p["output_per_m"]
                            + images * (p.get("per_image") or 0) * 1_000_000)
            _insert(c, user_id=user_id, channel_id=channel_id, category_id=category_id, post_id=post_id,
                    job_id=job_id, kind=kind, provider="openai", model=usage.model,
                    quantity={"input": tokens_in, "cached_input": cached, "output": tokens_out,
                              **({"images": images} if images else {})},
                    usd_micros=usd, fx_usd_inr=fx_usd_inr(c, user_id), note=note)
    except Exception:  # noqa: BLE001 - the ledger must never fail the work it records
        log.exception("could not record a model call's cost")


def record_gpu(*, user_id: str, post_id, job_id, pod_id: int, gpu: str | None, seconds: float,
               rate_paise_h: int | None, confirmed: bool = True, note: str | None = None) -> None:
    """One pod's billed span: from its resume/deploy until it was paused or terminated."""
    try:
        with db.conn() as c:
            paise = round(seconds / 3600 * rate_paise_h) if rate_paise_h else None
            _insert(c, user_id=user_id, post_id=post_id, job_id=job_id, kind="gpu", provider="race",
                    model=gpu, quantity={"pod": pod_id, "seconds": round(seconds, 1),
                                         "rate_paise_h": rate_paise_h, "confirmed": confirmed},
                    inr_paise=paise, fx_usd_inr=fx_usd_inr(c, user_id),
                    note=note or (None if confirmed else "pause not confirmed — check Race"))
    except Exception:  # noqa: BLE001
        log.exception("could not record a GPU span's cost")


def refresh_fx(client: httpx.Client | None = None) -> Decimal | None:
    """Today's ECB reference rate (keyless), stored once per day."""
    with db.conn() as c:
        have = c.execute("select usd_inr from fx_rates where day = current_date").fetchone()
        if have:
            return Decimal(have["usd_inr"])
    try:
        own = client is None
        client = client or httpx.Client(timeout=15)
        try:
            r = client.get(FX_URL)
            r.raise_for_status()
            rate = Decimal(str(r.json()["rates"]["INR"]))
        finally:
            if own:
                client.close()
    except Exception as e:  # noqa: BLE001 - an old rate (or the override) is used instead
        log.warning("exchange rate not refreshed: %s", e)
        return None
    with db.conn() as c:
        c.execute("""insert into fx_rates (day, usd_inr, source) values (current_date, %s, 'ECB via frankfurter')
                     on conflict (day) do nothing""", (rate,))
    return rate


def record_pod_storage(race_pods: list[dict], *, user_id: str, day: date | None = None) -> int:
    """Once a day: what parked pods cost to keep (Race's monthly_cost / 30, INR)."""
    day = day or datetime.now(timezone.utc).date()
    n = 0
    with db.conn() as c:
        for p in race_pods:
            if p.get("status") != "stopped" or not p.get("monthly_cost"):
                continue
            note = f"pod {p['id']} parked on {day.isoformat()}"
            if c.execute("select 1 from costs where kind = 'pod_storage' and note = %s", (note,)).fetchone():
                continue
            _insert(c, user_id=user_id, kind="pod_storage", provider="race", model=p.get("gpu"),
                    quantity={"pod": p["id"], "monthly_cost": p["monthly_cost"]},
                    inr_paise=round(float(p["monthly_cost"]) * 100 / 30), fx_usd_inr=fx_usd_inr(c, user_id),
                    note=note)
            n += 1
    return n


def since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)
