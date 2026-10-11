"""Drive ComfyUI on an acquired pod: private tunnel, queue shots, collect clips.

Shared by the gpu/render_post job and worker/scripts/render_plan.py. The pod's
public ComfyUI relay is shut first, so the GPU is reachable only through our SSH
tunnel; clips are handed back one at a time as they finish, so the caller can
upload each immediately and a crash loses at most the shot in flight. Several pods
can work through one ShotQueue at the same time.
"""

from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

import httpx

from . import ltx25, session


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def tunnel(pod: session.Pod) -> Iterator[str]:
    """Base URL of the pod's ComfyUI through an SSH tunnel; public relay shut."""
    # pkill -x matches the process name exactly, so it can never match this command.
    session.ssh(pod, "pkill -x socat || true", timeout=30)
    port = _free_port()
    proc = subprocess.Popen(["ssh", *session.SSH_OPTS, "-N", "-L", f"{port}:127.0.0.1:28188",
                             "-p", str(pod.port), f"root@{pod.host}"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(40):
            try:
                if httpx.get(base + "/system_stats", timeout=5).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(1)
        else:
            raise RuntimeError("SSH tunnel to ComfyUI never came up")
        yield base
    finally:
        proc.terminate()


class ShotQueue:
    """The shots of one render, shared by every pod working on it.

    Longest first: with GPUs of different speeds the short shots left at the end
    fill the gaps, so the pods finish close together. A pod that dies mid-shot gives
    its shot back for another pod to render. A shot ComfyUI fails on one pod (say,
    out of memory on the smaller GPU) goes to the others before it counts as failed.
    """

    def __init__(self, shots: list[dict]):
        self._todo = sorted(shots, key=lambda s: int(s["num_frames"]), reverse=True)
        self._lock = threading.Lock()
        self._pods: set[str] = set()                 # pods working on (or joining) this render
        self._failed_on: dict[int, set[str]] = {}
        self.failed: list[int] = []
        self.done_by: dict[str, list[int]] = {}

    def join(self, who: str) -> None:
        with self._lock:
            self._pods.add(who)

    def leave(self, who: str) -> None:
        with self._lock:
            self._pods.discard(who)
            for shot in list(self._todo):           # shots no pod left can render
                tried = self._failed_on.get(shot["idx"])
                if tried and not self._pods - tried:
                    self._todo.remove(shot)
                    self.failed.append(shot["idx"])

    def take(self, who: str = "pod") -> dict | None:
        """The next shot this pod has not already failed."""
        with self._lock:
            for i, shot in enumerate(self._todo):
                if who not in self._failed_on.get(shot["idx"], ()):
                    return self._todo.pop(i)
            return None

    def give_back(self, shot: dict) -> None:
        with self._lock:
            self._todo.insert(0, shot)

    def shot_failed(self, shot: dict, who: str) -> bool:
        """ComfyUI failed `shot` on `who`. True if it went back for another pod to
        try; False once every pod has failed it (it is then in `failed`)."""
        with self._lock:
            tried = self._failed_on.setdefault(shot["idx"], set())
            tried.add(who)
            if self._pods - tried:
                self._todo.insert(0, shot)
                return True
            self.failed.append(shot["idx"])
            return False

    def remaining(self) -> int:
        with self._lock:
            return len(self._todo)

    def left(self) -> list[dict]:
        with self._lock:
            return list(self._todo)


def render_shots(base: str, queue: ShotQueue, out_dir: Path,
                 on_done: Callable[[dict, Path, float], None],
                 should_continue: Callable[[], bool] = lambda: True,
                 log: Callable[[str], None] = print, *, who: str = "pod", poll: float = 2.0) -> None:
    """Render shots from `queue` on one pod until it is empty, handing each finished
    clip to on_done(shot, path, seconds).

    One shot at a time per pod, so a faster pod naturally takes more of them; the
    next shot is queued in ComfyUI before the finished clip is downloaded, so the
    GPU does not wait for the transfer. A shot ComfyUI fails on is reported to the
    queue (queue.shot_failed); if this raises, every shot it took and did not
    finish is given back to the queue. Callers join() the pod to the queue first.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=base, timeout=120) as http:
        info = http.get("/object_info").json()
        cid = uuid.uuid4().hex

        def submit(shot: dict) -> tuple[dict, str, float]:
            graph, problems = ltx25.build(info, ltx25.nodes(shot, int(shot["num_frames"]),
                                                           f"render/shot{shot['idx']}"))
            if problems:
                raise RuntimeError(f"shot {shot['idx']} graph invalid: {problems}")
            r = http.post("/prompt", json={"prompt": graph, "client_id": cid})
            r.raise_for_status()
            log(f"{who}: shot {shot['idx']} started ({shot['num_frames']} frames)")
            return shot, r.json()["prompt_id"], time.monotonic()

        def take_and_submit() -> tuple[dict, str, float] | None:
            shot = queue.take(who)
            if shot is None:
                return None
            in_hand.append(shot)
            return submit(shot)

        in_hand: list[dict] = []    # taken from the queue, not finished: given back if this pod dies
        try:
            current = take_and_submit()
            while current:
                shot, pid, t0 = current
                while True:
                    r = http.get(f"/history/{pid}")
                    r.raise_for_status()
                    h = r.json().get(pid)
                    if h and h.get("status", {}).get("completed") is not None:
                        break
                    if not should_continue():
                        http.post("/interrupt")
                        http.post("/queue", json={"clear": True})
                        raise RuntimeError("render cancelled or lease lost")
                    time.sleep(poll)
                seconds = time.monotonic() - t0
                current = take_and_submit()                 # keep the GPU busy...
                if h["status"].get("status_str") != "success":
                    errs = [m for m in h["status"].get("messages", []) if m[0] == "execution_error"]
                    in_hand.remove(shot)
                    again = queue.shot_failed(shot, who)
                    log(f"{who}: shot {shot['idx']} FAILED{' (another pod will try it)' if again else ''}: "
                        f"{json.dumps(errs)[:400]}")
                    continue
                path = out_dir / f"shot{shot['idx']}.mp4"  # ...while this clip comes down
                for o in h["outputs"].values():
                    for items in o.values():
                        for it in items if isinstance(items, list) else []:
                            if isinstance(it, dict) and it.get("filename"):
                                v = http.get("/view", params={"filename": it["filename"],
                                                              "subfolder": it.get("subfolder", ""),
                                                              "type": it.get("type", "output")})
                                v.raise_for_status()
                                path.write_bytes(v.content)
                on_done(shot, path, seconds)
                in_hand.remove(shot)
                queue.done_by.setdefault(who, []).append(shot["idx"])
        except BaseException:
            for shot in reversed(in_hand):                  # back at the front, in order
                queue.give_back(shot)
            raise
