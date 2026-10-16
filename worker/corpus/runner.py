"""The lane loop: claim a job, run its handler under a heartbeat lease, finish it.

Idle behaviour: with nothing ready, the worker asks the database once when the
next job is due, then sleeps until that moment, at most idle_max_seconds, or
until the web app POSTs /wake. A click is picked up within a moment, and an
idle worker sends no queries at all. A job that queues work for another lane
wakes the other workers the same way when it ends (gpu/render_post → cpu/assemble).

Handlers raise one of three exceptions to say how a failure should be treated:

    Retryable   — try again (backoff and max_attempts are decided by finish_job)
    Permanent   — retrying cannot help (missing key, bad input); stop now
    NeedsReview — the outcome is unknown (publish lane); a human must decide
    Defer       — not yet (something it waits for isn't ready); run again later
                  without counting an attempt

Anything else is treated as Retryable, with the traceback tail recorded.
"""

from __future__ import annotations

import http.server
import logging
import threading
import time
import traceback
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from . import db
from .config import BOOT_ID, settings

log = logging.getLogger("corpus.runner")

HEARTBEAT_SECONDS = 15


class Retryable(Exception):
    def __init__(self, message: str, *, stage: str = "handler", retry_in: int | None = None,
                 detail: dict | None = None):
        super().__init__(message)
        self.stage, self.retry_in, self.detail = stage, retry_in, detail or {}


class Permanent(Retryable):
    """Not worth retrying. Finishes the job as dead regardless of attempts left."""


class Defer(Exception):
    """Come back in `retry_in` seconds. Not a failure: the attempt is given back."""

    def __init__(self, message: str, *, retry_in: int = 60):
        super().__init__(message)
        self.retry_in = retry_in


class NeedsReview(Exception):
    def __init__(self, message: str, *, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail or {}


@dataclass
class JobContext:
    job: dict
    stats: Callable[[], dict] = field(default=lambda: {})
    # Nudge the other lanes' workers about work this job has just committed to the
    # queue, without waiting for the job to end (render_post hands each finished
    # shot to the cpu lane while it renders the next).
    wake: Callable[[], None] = field(default=lambda: None)
    _cancelled: threading.Event = field(default_factory=threading.Event)
    _lost: threading.Event = field(default_factory=threading.Event)

    @property
    def payload(self) -> dict:
        return self.job.get("payload") or {}

    def should_continue(self) -> bool:
        """False once cancellation was requested or the lease was lost. Long
        handlers check this between expensive steps (e.g. between shots)."""
        return not (self._cancelled.is_set() or self._lost.is_set())


@dataclass
class Handler:
    run: Callable[[JobContext], dict | None]
    # Called once, when the job will not be retried again (dead / permanent), so
    # the handler can mark the post failed with a reason a human can read.
    on_give_up: Callable[[JobContext, dict], None] | None = None


def _error_json(exc: BaseException, stage: str, detail: dict | None = None) -> dict:
    return {
        "stage": stage,
        "message": str(exc)[:2000],
        "type": type(exc).__name__,
        "detail": detail or {},
        "trace": traceback.format_exc()[-4000:],
        "at": datetime.now(timezone.utc).isoformat(),
    }


class Runner:
    def __init__(self, lane: str, handlers: dict[str, Handler],
                 upkeep: Callable[[], None] | None = None):
        self.lane = lane
        self.handlers = handlers
        self.upkeep = upkeep
        self.s = settings()
        self.wake = threading.Event()

    # ── wake endpoint ────────────────────────────────────────────────────────

    def start_wake_server(self) -> None:
        token = self.s.wake_token
        if not token:
            log.info("wake endpoint disabled (CORPUS_WAKE_TOKEN unset)")
            return
        wake = self.wake

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - http.server API
                if self.path != "/wake" or self.headers.get("Authorization") != f"Bearer {token}":
                    self.send_response(404)
                    self.end_headers()
                    return
                wake.set()
                self.send_response(204)
                self.end_headers()

            def log_message(self, *args):  # silence per-request logs
                pass

        srv = http.server.ThreadingHTTPServer(("0.0.0.0", self.s.wake_port), H)
        threading.Thread(target=srv.serve_forever, daemon=True, name="wake").start()
        log.info("wake endpoint listening on :%s", self.s.wake_port)

    # ── main loop ────────────────────────────────────────────────────────────

    def run_forever(self) -> None:
        self.start_wake_server()
        while True:
            try:
                did_work = self.tick()
            except Exception:  # noqa: BLE001 - the loop must survive a bad tick
                log.exception("tick failed")
                did_work = False
                time.sleep(self.s.poll_seconds)
            if not did_work:
                self.sleep_until_due()

    def tick(self) -> bool:
        """Claim and run at most one job. True if a job ran."""
        db.ping(self.lane, self.s.version, BOOT_ID, {})
        if self.lane == "cpu":
            for r in db.reap():
                log.warning("reaped lease: %s %s -> %s", r["kind"], r["job_id"], r["new_state"])
            if db.schedule_daily_ideas():
                log.info("queued today's idea batches")
        if self.upkeep:
            try:
                self.upkeep()
            except Exception:  # noqa: BLE001 - housekeeping must not stop the lane
                log.exception("upkeep failed")
        job = db.claim(self.lane, self.s.version, list(self.handlers))
        if not job:
            return False
        self.run_job(job)
        return True

    def sleep_until_due(self) -> None:
        due = db.next_due([self.lane])
        timeout = float(self.s.idle_max_seconds)
        if due is not None:
            timeout = max(1.0, min(timeout, (due - datetime.now(timezone.utc)).total_seconds()))
        log.info("idle: sleeping %.0fs (or until woken)", timeout)
        self.wake.wait(timeout)
        self.wake.clear()

    def run_job(self, job: dict) -> None:
        handler = self.handlers[job["kind"]]
        ctx = JobContext(job=job, wake=self.wake_others)
        stop = threading.Event()

        def beat():
            while not stop.wait(HEARTBEAT_SECONDS):
                try:
                    if not db.heartbeat(job["id"], ctx.stats()):
                        ctx._lost.set()
                        ctx._cancelled.set()
                        return
                except Exception:  # noqa: BLE001 - a missed beat is not fatal
                    log.exception("heartbeat failed")

        t = threading.Thread(target=beat, daemon=True, name=f"hb-{job['id']}")
        t.start()
        log.info("job %s %s attempt %s", job["kind"], job["id"], job["attempts"])
        try:
            result = handler.run(ctx)
            db.finish(job["id"], "succeeded", result=result or {})
        except Defer as e:
            # Give the attempt back, then re-queue through the normal retry path.
            with db.conn() as c:
                c.execute("update jobs set attempts = greatest(attempts - 1, 0) where id = %s", (job["id"],))
            db.finish(job["id"], "failed", error={"stage": "deferred", "message": str(e)[:500],
                                                  "at": datetime.now(timezone.utc).isoformat()},
                      retry_in=e.retry_in)
        except NeedsReview as e:
            db.finish(job["id"], "needs_review", error=_error_json(e, "needs_review", e.detail))
        except Permanent as e:
            err = _error_json(e, e.stage, e.detail)
            # Exhaust attempts so finish_job records 'dead' instead of requeueing.
            with db.conn() as c:
                c.execute("update jobs set max_attempts = attempts where id = %s", (job["id"],))
            db.finish(job["id"], "failed", error=err)
            self._give_up(handler, ctx, err)
        except Exception as e:  # noqa: BLE001 - Retryable and everything unexpected
            stage = getattr(e, "stage", "handler")
            err = _error_json(e, stage, getattr(e, "detail", None))
            out = db.finish(job["id"], "failed", error=err, retry_in=getattr(e, "retry_in", None))
            if out and out.get("state") == "dead":
                self._give_up(handler, ctx, err)
        finally:
            stop.set()
            self.wake_others()

    def wake_others(self) -> None:
        """Wake the other workers if this process queued work for another lane since
        the last call. Its own lane needs no nudge: this loop ticks again at once."""
        if db.take_enqueued_lanes() - {self.lane}:
            self.wake_peers()

    def wake_peers(self) -> None:
        """POST every wake URL so a worker on another lane claims what this job queued
        without waiting out its idle sleep. Best effort: an unreachable worker still
        finds the job on its next scheduled check."""
        if not self.s.wake_token:
            return
        for url in self.s.wake_urls:
            req = urllib.request.Request(url, method="POST",
                                         headers={"Authorization": f"Bearer {self.s.wake_token}"})
            try:
                urllib.request.urlopen(req, timeout=2).close()
            except Exception as e:  # noqa: BLE001
                log.info("wake %s failed: %s", url, e)

    @staticmethod
    def _give_up(handler: Handler, ctx: JobContext, err: dict) -> None:
        if handler.on_give_up:
            try:
                handler.on_give_up(ctx, err)
            except Exception:  # noqa: BLE001
                log.exception("on_give_up failed for job %s", ctx.job["id"])
