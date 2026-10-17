"""The workers' own checks of what they depend on, for the Health page (ported in
spirit from TrendCaster's doctor.py: one cheap call per dependency, never a
secret in the result).

Run hourly by the ideas lane's upkeep. Each check writes one row to
health_checks (name, ok, detail); the web app adds what it can see itself
(queues, workers' heartbeats, storage, connected accounts).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from typing import Callable

from . import db, storage
from .config import settings

FREE_DISK_MIN = 2_000_000_000


def _record(name: str, ok: bool, detail: str) -> None:
    with db.conn() as c:
        c.execute("""insert into health_checks (name, ok, detail, checked_at) values (%s, %s, %s, now())
                     on conflict (name) do update set ok = excluded.ok, detail = excluded.detail,
                                                      checked_at = excluded.checked_at""",
                  (name, ok, detail[:500]))


def _r2() -> tuple[bool, str]:
    key = f"health/{uuid.uuid4().hex}.txt"
    storage.client().put_object(Bucket=storage.bucket(), Key=key, Body=b"ok")
    storage.client().delete_object(Bucket=storage.bucket(), Key=key)
    return True, "write and delete work"


def _race() -> tuple[bool, str]:
    key = os.environ.get("RACE_API_KEY", "").strip()
    if not key:
        return False, "RACE_API_KEY is not set on the workers"
    from .race import RaceClient
    race = RaceClient(key)
    offers = race.gpus()
    pods = [p for p in race.pods() if str(p.get("name", "")).startswith("corpus-")]
    parked = sum(1 for p in pods if p.get("status") == "stopped")
    running = sum(1 for p in pods if p.get("status") == "running")
    return True, f"{len(offers)} GPU offers; our pods: {parked} parked, {running} running"


def _disk() -> tuple[bool, str]:
    free = shutil.disk_usage(settings().cache_dir).free
    return free >= FREE_DISK_MIN, f"{free / 1e9:.1f} GB free on the workers' cache disk"


def _ffmpeg() -> tuple[bool, str]:
    out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=20).stdout
    return bool(out), (out.splitlines() or ["ffmpeg missing"])[0][:120]


CHECKS: dict[str, Callable[[], tuple[bool, str]]] = {
    "storage (R2)": _r2, "GPUs (Race)": _race, "worker disk": _disk, "ffmpeg": _ffmpeg,
}


def run_all(log: Callable[[str], None] = print) -> dict[str, bool]:
    results = {}
    for name, check in CHECKS.items():
        try:
            ok, detail = check()
        except Exception as e:  # noqa: BLE001 - the failure is the result
            ok, detail = False, f"{type(e).__name__}: {str(e)[:300]}"
        _record(name, ok, detail)
        results[name] = ok
        if not ok:
            log(f"health: {name} — {detail}")
    return results
