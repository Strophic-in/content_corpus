"""Jev (TypeSafe AI): fast, typed decisions about text — yes/no, pick-one, 0-n scores.

Jev never writes: it answers questions about a `state` with probabilities, in
about a tenth of a second, for $0.042 per million input tokens (output free). The
pipeline uses it where a judgement is needed but no prose is:

  ideas      which trending items are worth the idea writer's time (in the
             category? trending today? a credible source?) — the writer sees fewer,
             better items; and which of the category's formats suits each idea;
  research   whether another outlet's report is about the same event.

Everything here is optional: no key, or Jev failing, and each caller falls back to
what it did before (the ranking heuristic, the writer's own pick, word overlap).
Calls are made in parallel; each stage's tokens are recorded as one cost row.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import httpx

from . import costs, vault

log = logging.getLogger("corpus.jev")

API = "https://api.typesafe.ai/v1/systemone"
# The newest Jev by name: TypeSafe's "jev-latest" still answered with 1.13.0 on
# 2026-10-18, four days after 1.14 shipped. If this name is ever retired, the alias.
MODEL = "jev-1.14.0"
FALLBACK = "jev-latest"
TIMEOUT = httpx.Timeout(20, connect=10)
WORKERS = 8


class JevError(RuntimeError):
    pass


class Jev:
    def __init__(self, key: str, client: httpx.Client | None = None):
        self.key = key
        self.client = client or httpx.Client(timeout=TIMEOUT)
        self.input_tokens = 0
        self.model = MODEL          # the version that answered (for the cost ledger)
        self.name = MODEL           # the version asked for
        self._lock = threading.Lock()

    def ask(self, state, questions: dict) -> dict:
        """One request: every question answered against the same state."""
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = self.client.post(API, json={"model": self.name, "state": state, "questions": questions},
                                     headers={"Authorization": f"Bearer {self.key}"})
            except httpx.HTTPError as e:
                last = e
                continue
            if r.status_code == 400 and "Unknown model" in r.text and self.name != FALLBACK:
                self.name = FALLBACK
                continue
            if r.status_code in (429, 529, 500, 502, 503) and attempt < 2:
                last = JevError(f"HTTP {r.status_code}")
                continue
            if r.status_code != 200:
                raise JevError(f"Jev answered {r.status_code}: {r.text[:200]}")
            body = r.json()
            with self._lock:
                self.input_tokens += int((body.get("usage") or {}).get("input_tokens") or 0)
                self.model = body.get("model") or self.model
            return body.get("answers") or {}
        raise JevError(f"Jev unreachable: {last}")

    def many(self, jobs: list[tuple[object, dict]]) -> list[dict | None]:
        """Several independent requests at once; a failed one is None."""
        def one(job):
            try:
                return self.ask(*job)
            except Exception as e:  # noqa: BLE001 - the caller falls back for that item
                log.warning("jev: %s", e)
                return None
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            return list(pool.map(one, jobs))

    def record(self, note: str, **billed) -> None:
        """This stage's tokens as one cost row (output is free)."""
        if self.input_tokens:
            from .script.llm import Usage

            costs.record_llm(Usage(model=self.model, input_tokens=self.input_tokens, output_tokens=0), note=note,
                             kind="llm", **billed)
            self.input_tokens = 0


FACTORY: Callable[[str], Jev] = Jev       # swapped by tests


def for_user(user_id: str) -> Jev | None:
    key = vault.secret(user_id, "jev_api_key")
    return FACTORY(key) if key else None


def score(answer: dict | None, default: float = 0.0) -> float:
    return float(answer.get("score", default)) if answer else default


def yes(answer: dict | None, default: float = 0.5) -> float:
    return float(answer.get("noul", default)) if answer else default
