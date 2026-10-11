"""Worker configuration.

One codebase runs in three roles (`--lane cpu|gpu|publish`), on two machines. Most
settings are shared; the ones that are not are named for the lane that uses them.
Everything comes from the environment (the repo-root .env in development).
"""

from __future__ import annotations

import functools
import os
import secrets
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False)

# Boot identity. Fresh per process start, which on the GPU pod means fresh per
# resume — that is how the UI can say "resumed 4m ago", and how a cleanup pass
# knows last week's pod-local latents are gone.
BOOT_ID = secrets.token_hex(6)

LANES = ("cpu", "gpu", "publish")


def _git_sha() -> str:
    """Deployed version, reported in `workers.version`.

    Read from an env var first: the GPU pod receives a tarball, not a git
    checkout. lane_config.required_version is an exact match on this string.
    """
    env = os.environ.get("CORPUS_VERSION")
    if env:
        return env.strip()
    try:
        out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=5, check=True)
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 - never let version discovery stop a worker
        return "unknown"


@dataclass(frozen=True)
class Settings:
    # The owner role's *pooled* URL (VibeDB: port 6432). Workers are trusted: the owner is not
    # subject to RLS, and the private.* queue functions are only reachable by it.
    database_url: str
    lane: str
    worker_id: str
    version: str
    # While work is in flight the worker polls at this pace...
    poll_seconds: int
    # ...and while idle it sleeps until the next due job, at most this long, unless
    # woken by the web app. A backstop for a missed wake, not the main signal.
    idle_max_seconds: int
    # Wake endpoint: the web app POSTs here after enqueueing, so idle sleep never
    # delays a click by more than a moment. Empty token disables the listener.
    wake_port: int
    wake_token: str
    # Every worker's wake URL (CORPUS_WAKE_URL, comma-separated — the same list the
    # web app uses). A worker that enqueues work for another lane, e.g. gpu/render_post
    # queueing cpu/assemble, nudges these so the hand-off is not left to idle sleep.
    wake_urls: tuple[str, ...]
    # R2 (S3 API). The bucket is private; the cap lives in storage_config.
    r2_account_id: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket: str
    # Worker-local cache (cpu lane: shot segments waiting for assembly). Losing it
    # only costs time: anything missing is rebuilt from R2.
    cache_dir: Path
    # GPU-lane only.
    comfy_url: str
    scratch_root: Path
    prompts_dir: Path

    @property
    def r2_endpoint(self) -> str:
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"


def _default_worker_id(lane: str) -> str:
    host = os.environ.get("CORPUS_HOST") or socket.gethostname()
    # Stable across restarts on purpose: a restarted worker should re-appear as
    # the same row, not accumulate one row per crash.
    return f"{lane}-{host}".lower().replace("_", "-")


@functools.lru_cache(maxsize=1)
def settings() -> Settings:
    lane = os.environ.get("CORPUS_LANE", "cpu").strip()
    if lane not in LANES:
        raise SystemExit(f"CORPUS_LANE must be one of {LANES}, got {lane!r}")
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("DATABASE_URL (the owner's pooled URL) is required")
    return Settings(
        database_url=url,
        lane=lane,
        worker_id=os.environ.get("CORPUS_WORKER_ID") or _default_worker_id(lane),
        version=_git_sha(),
        poll_seconds=max(2, int(os.environ.get("CORPUS_POLL_SECONDS", "10"))),
        idle_max_seconds=max(30, int(os.environ.get("CORPUS_IDLE_MAX_SECONDS", "300"))),
        wake_port=int(os.environ.get("CORPUS_WAKE_PORT", "8787")),
        wake_token=os.environ.get("CORPUS_WAKE_TOKEN", "").strip(),
        wake_urls=tuple(u.strip() for u in os.environ.get("CORPUS_WAKE_URL", "").split(",") if u.strip()),
        r2_account_id=os.environ.get("R2_ACCOUNT_ID", "").strip(),
        r2_access_key_id=os.environ.get("R2_ACCESS_KEY_ID", "").strip(),
        r2_secret_access_key=os.environ.get("R2_SECRET_ACCESS_KEY", "").strip(),
        r2_bucket=os.environ.get("R2_BUCKET", "content-corpus-media").strip(),
        cache_dir=Path(os.environ.get("CORPUS_CACHE_DIR") or Path.home() / ".cache" / "content_corpus"),
        comfy_url=os.environ.get("COMFY_URL", "http://127.0.0.1:28188").rstrip("/"),
        scratch_root=Path(os.environ.get("CORPUS_SCRATCH_ROOT", "/workspace/scratch")),
        prompts_dir=ROOT / "prompts",
    )
