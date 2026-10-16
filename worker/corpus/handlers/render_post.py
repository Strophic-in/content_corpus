"""gpu/render_post — render an approved script's shots on Race and store them in R2.

Runs on the always-on worker box, not on the pod: it rents the GPU, drives
ComfyUI through an SSH tunnel, and the pod never holds database or R2
credentials. Cheapest GPU first (paused pods that already cache the models,
then fresh pods checked for disk), and the pod is always paused afterwards.

Two GPUs when they are free: after the main pod, other paused pods that already
hold the models are resumed too, and every pod takes shots from one shared queue
until it is empty — the same GPU-minutes in about half the time. A helper is never
deployed fresh or made to download models; if it is busy, it is simply skipped.

Resumable shot by shot: each clip is uploaded the moment it finishes (and handed
to the cpu lane to be captioned while the GPU renders on), so a retry renders
only what is missing. No free GPU is not a failure — the post says it is waiting
and the job retries every 10 minutes.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

from psycopg.types.json import Jsonb

from .. import costs, db, storage
from ..config import settings
from ..gpu import render, session
from ..race import RaceClient
from ..runner import Handler, JobContext, Permanent, Retryable

# Swapped by tests: the GPU side (acquire a pod, set it up, tunnel, render).
ACQUIRE = session.acquire
PREPARE = lambda pod, log, fetch: (  # noqa: E731
    session.ensure_models(pod, os.environ["HF_TOKEN"].strip(), log=log, fetch=fetch),
    session.wait_comfy(pod, log=log))
TUNNEL = render.tunnel
RENDER = render.render_shots
RELEASE = session.release
RACE = lambda: RaceClient(os.environ["RACE_API_KEY"])  # noqa: E731

NO_GPU_RETRY_SECONDS = 600
# Pods per render: the main one plus up to (MAX_PODS - 1) cached helpers.
MAX_PODS = max(1, int(os.environ.get("CORPUS_RENDER_PODS", "2")))
SEGMENT_PRIORITY = 40     # ahead of default cpu work: someone is waiting for this reel


def _cache_pods(race) -> list[int]:
    """Paused pods we rented before: they hold verified models (no download).
    Biggest GPU first, so it is the main pod whenever it is free."""
    try:
        pods = [p for p in race.pods()
                if p.get("status") == "stopped" and str(p.get("name", "")).startswith("corpus-")]
        return [int(p["id"]) for p in sorted(pods, key=lambda p: -int(p.get("vram") or 0))]
    except Exception:  # noqa: BLE001 - discovery is an optimisation, never a blocker
        return []


# Paused pods found without the models: resuming one as a helper costs a minute of
# GPU time just to learn that, so they are left out until a session as the main pod
# (which does download) has filled them. Local to this worker; losing it is harmless.
def _pod_notes() -> Path:
    return settings().cache_dir / "race_pods.json"


def _pods_without_models() -> set[int]:
    try:
        return set(json.loads(_pod_notes().read_text())["no_models"])
    except (OSError, ValueError, KeyError):
        return set()


def _remember_models(pod_id: int | None, has_models: bool) -> None:
    if pod_id is None:
        return
    with _notes_lock:
        ids = _pods_without_models()
        ids = ids - {pod_id} if has_models else ids | {pod_id}
        _pod_notes().parent.mkdir(parents=True, exist_ok=True)
        _pod_notes().write_text(json.dumps({"no_models": sorted(ids)}))


_notes_lock = threading.Lock()


class _Rates:
    """What a pod costs an hour, in paise: the rate Race quotes for its slice or GPU
    (remembered, since a busy GPU drops off the offers list), else the owner's
    configured rate."""

    def __init__(self, race, fallback_paise: int | None):
        self.fallback = fallback_paise
        self.by_slice: dict[int, int] = {}
        self.by_gpu: dict[str, int] = {}
        self.gpu_of: dict[int, str] = {}
        notes = _rate_notes()
        self.by_gpu.update(notes)
        try:
            for o in race.gpus():
                if o.get("hourly_rate") is not None and (o.get("currency") or "INR") == "INR":
                    paise = round(float(o["hourly_rate"]) * 100)
                    self.by_slice[int(o["slice_id"])] = paise
                    self.by_gpu[str(o.get("gpu_name", ""))] = paise
            for p in race.pods():
                self.gpu_of[int(p["id"])] = str(p.get("gpu") or "")
        except Exception:  # noqa: BLE001 - the fallback rate applies
            pass
        _save_rate_notes(self.by_gpu)

    def gpu(self, pod_id: int) -> str:
        return self.gpu_of.get(pod_id, "")

    def paise_h(self, pod_id: int, slice_id: int | None = None) -> int | None:
        if slice_id is not None and slice_id in self.by_slice:
            return self.by_slice[slice_id]
        name = self.gpu(pod_id)
        # A pod's GPU reads "NVIDIA RTX 5090-SLICE-2"; offers read "NVIDIA RTX 5090".
        for gpu, paise in sorted(self.by_gpu.items(), key=lambda kv: -len(kv[0])):
            if gpu and name.startswith(gpu):
                return paise
        return self.fallback


def _rate_notes() -> dict[str, int]:
    try:
        return json.loads((settings().cache_dir / "race_rates.json").read_text())
    except (OSError, ValueError):
        return {}


def _save_rate_notes(rates: dict[str, int]) -> None:
    try:
        (settings().cache_dir / "race_rates.json").parent.mkdir(parents=True, exist_ok=True)
        (settings().cache_dir / "race_rates.json").write_text(json.dumps(rates))
    except OSError:
        pass


def _set_post(post_id, status: str, reason: str, error: dict | None = None) -> None:
    with db.tx() as c:
        old = c.execute("select status from posts where id = %s for update", (post_id,)).fetchone()["status"]
        c.execute("update posts set status = %s, error = %s where id = %s",
                  (status, Jsonb(error) if error else None, post_id))
        if old != status or error:
            db.log_event(c, post_id, old, status, f"worker:{settings().worker_id}", reason, error)


def run(ctx: JobContext) -> dict:
    script_id = ctx.payload["script_id"]
    log = lambda m: print(f"[render_post {script_id}] {m}", flush=True)  # noqa: E731
    with db.conn() as c:
        post = c.execute("select * from posts where approved_script_id = %s", (script_id,)).fetchone()
        if post is None:
            raise Permanent("post or approved script no longer exists", stage="input")
        shots = c.execute("""select id, idx, prompt, negative_prompt as negative, seed, width, height,
                                    num_frames, state, artifact_key
                               from shots where script_id = %s order by idx""", (script_id,)).fetchall()
    if not shots:
        raise Permanent("approved script has no shots", stage="input")
    pending = [s for s in shots if s["state"] != "uploaded"]
    result: dict = {"shots": len(shots), "rendered_now": len(pending)}

    if pending:
        race = RACE()
        slices = [int(x) for x in os.environ.get("CORPUS_RACE_SLICES", "5,16,11").split(",") if x]
        cached = _cache_pods(race)
        with db.conn() as c:
            fallback = (c.execute("select gpu_rate_paise_per_hour as r from app_settings where user_id = %s",
                                  (post["user_id"],)).fetchone() or {}).get("r")
        rates = _Rates(race, fallback)

        def bill(pod_id: int, seconds: float, slice_id: int | None, note: str | None = None,
                 confirmed: bool = True) -> None:
            costs.record_gpu(user_id=post["user_id"], post_id=post["id"], job_id=ctx.job.get("id"),
                             pod_id=pod_id, gpu=rates.gpu(pod_id) or None, seconds=seconds,
                             rate_paise_h=rates.paise_h(pod_id, slice_id), confirmed=confirmed, note=note)

        pod = ACQUIRE(race, resume_ids=cached, slices=slices, name="corpus-render", log=log,
                      on_billed=lambda pid, s, sl, note: bill(pid, s, sl, note))
        if pod is None:
            _set_post(post["id"], "queued_for_render", "waiting for a GPU",
                      {"stage": "no_gpu", "message": "Waiting for a free GPU — retrying every 10 minutes."})
            raise Retryable("no free GPU on Race", stage="no_gpu", retry_in=NO_GPU_RETRY_SECONDS)

        _set_post(post["id"], "rendering", "rendering started")
        prefix = storage.post_prefix(post["user_id"], post["id"])

        def on_done(shot: dict, path: Path, seconds: float) -> None:
            key = f"{prefix}/shots/{script_id}/{shot['idx']}-{shot['seed']}.mp4"
            info = storage.put_file(key, path, kind="shot", user_id=post["user_id"], post_id=post["id"],
                                    shot_id=shot["id"], content_type="video/mp4")
            with db.tx() as c:
                c.execute("""update shots set state = 'uploaded', artifact_key = %s, artifact_sha256 = %s,
                                              artifact_bytes = %s, gpu_seconds = %s, attempts = attempts + 1,
                                              error = null
                              where id = %s""", (key, info["sha256"], info["bytes"], round(seconds, 1), shot["id"]))
                # Caption and encode it on the cpu lane while the GPU renders on.
                db.enqueue(c, user_id=post["user_id"], lane="cpu", kind="build_segment",
                           dedupe_key=f"build_segment:{shot['id']}:{info['sha256'][:16]}",
                           payload={"shot_id": str(shot["id"])}, post_id=post["id"], shot_id=shot["id"],
                           priority=SEGMENT_PRIORITY, max_attempts=2, lease_seconds=600)
            ctx.wake()
            log(f"shot {shot['idx']} stored ({info['bytes'] / 1e6:.1f} MB)")

        with db.conn() as c:
            c.execute("update shots set state = 'rendering' where id = any(%s)", ([s["id"] for s in pending],))
        queue = render.ShotQueue(pending)
        # Cached pods after the main one in the list were not tried yet (those before
        # it were busy a moment ago); a fresh pod means no cached one was free at all.
        skip = _pods_without_models()
        helpers = (([pid for pid in cached[cached.index(pod.id) + 1:] if pid not in skip])[:MAX_PODS - 1]
                   if pod.id in cached and len(pending) > 1 else [])
        stop = threading.Event()               # a Permanent error stops every pod
        fatal: list[BaseException] = []
        errors: list[str] = []

        def keep_going() -> bool:
            return ctx.should_continue() and not stop.is_set()

        def drive(main: bool, pid: int | None, who: str) -> None:
            plog = lambda m: log(f"[{who}] {m}")  # noqa: E731
            r, p = (race, pod) if main else (RACE(), None)
            try:
                if not main:
                    p = ACQUIRE(r, resume_ids=[pid], slices=[], name="corpus-render", log=plog,
                                on_billed=lambda i, s, sl, note: bill(i, s, sl, note))
                    if p is None:
                        return
                if queue.remaining() == 0:
                    return
                PREPARE(p, plog, main)         # helpers never download models
                _remember_models(p.id, True)
                if queue.remaining() == 0:
                    plog("nothing left to render; letting go")
                    return
                with TUNNEL(p) as base, tempfile.TemporaryDirectory() as tmp:
                    RENDER(base, queue, Path(tmp), on_done, keep_going, plog, who=who)
            except session.NeedsDownload as e:
                plog(f"skipped, and not asked to help again until it has the models: {e}")
                _remember_models(pid, False)
            except BaseException as e:  # noqa: BLE001 - reported after every pod has stopped
                plog(f"stopped: {type(e).__name__}: {e}")
                errors.append(f"{who}: {e}")
                if isinstance(e, Permanent):
                    fatal.append(e)
                    stop.set()
            finally:
                queue.leave(who)
                if p is not None:
                    confirmed = True
                    try:
                        RELEASE(r, p, keep_cache=True, log=plog)
                    except Exception as e:  # noqa: BLE001 - recorded; the pod may still be billing
                        confirmed = False
                        plog(f"pause failed: {e}")
                    bill(p.id, time.time() - getattr(p, "started", time.time()),
                         getattr(p, "slice_id", None), None, confirmed)

        crew = [(True, pod.id)] + [(False, pid) for pid in helpers]
        for _, pid in crew:                    # joined up front: a shot the main pod fails waits
            queue.join(f"pod {pid}")           # for a helper that is still starting
        threads = [threading.Thread(target=drive, args=(main, pid, f"pod {pid}"), name=f"pod-{pid}")
                   for main, pid in crew]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if fatal:
            raise fatal[0]
        if queue.failed:
            with db.conn() as c:
                again = c.execute("""update shots set state = 'failed', attempts = attempts + 1
                                      where script_id = %s and idx = any(%s)
                                  returning idx, attempts""", (script_id, queue.failed)).fetchall()
            # A shot that failed on every GPU twice will fail again: stop paying for it.
            hopeless = sorted(r["idx"] for r in again if r["attempts"] >= 2)
            if hopeless:
                raise Permanent(f"shot(s) {[i + 1 for i in hopeless]} failed to render twice on every GPU "
                                f"we tried ({'; '.join(errors)[:300] or 'ComfyUI execution error'})",
                                stage="render")
        with db.conn() as c:
            missing = [r["idx"] for r in c.execute(
                "select idx from shots where script_id = %s and state <> 'uploaded' order by idx",
                (script_id,)).fetchall()]
        if missing:
            raise Retryable(f"{len(missing)} shot(s) not rendered: {missing}"
                            + (f" ({'; '.join(errors)[:500]})" if errors else ""), stage="render")
        result["pods"] = {who: sorted(idx) for who, idx in queue.done_by.items()}

    with db.tx() as c:
        db.enqueue(c, user_id=post["user_id"], lane="cpu", kind="assemble",
                   dedupe_key=f"assemble:{script_id}", payload={"script_id": str(script_id)},
                   post_id=post["id"], max_attempts=3, lease_seconds=900)
    _set_post(post["id"], "rendered", "all shots rendered")
    return result


def on_give_up(ctx: JobContext, err: dict) -> None:
    with db.conn() as c:
        post = c.execute("select id from posts where approved_script_id = %s",
                         (ctx.payload["script_id"],)).fetchone()
    if post:
        _set_post(post["id"], "failed", "rendering gave up",
                  {"stage": err.get("stage"), "message": err.get("message")})


HANDLER = Handler(run=run, on_give_up=on_give_up)
