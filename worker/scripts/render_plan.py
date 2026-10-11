"""Render a plan's shots on Race in one unattended session — no pauses between steps.

    worker/.venv/Scripts/python worker/scripts/render_plan.py PLAN.json TIMING.json OUT_DIR \
        [--resume 4813] [--slices 5,16,11]

PLAN.json: {"shots": [{"idx", "prompt", "negative", "seed", "width", "height", ...}]}
TIMING.json: {"shots": [{"idx", "seconds"}]} — narration length per shot; each shot
is rendered that long plus a short pause (narrated mode). Pass "-" to use each
shot's own num_frames instead.

Order of attempts: resume the given paused pods (models cached, no download), then
fresh pods on --slices in order, each checked for real host disk within seconds and
terminated at once if short. ComfyUI is driven through an SSH tunnel and the pod's
public relay is shut, so the GPU is never reachable from the internet. Whatever
happens, the pod is paused at the end (its /workspace keeps the models for next time).
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from corpus.gpu import ltx25, session  # noqa: E402
from corpus.race import RaceClient  # noqa: E402


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("timing")
    ap.add_argument("out")
    ap.add_argument("--resume", type=int, nargs="*", default=[])
    ap.add_argument("--slices", default="5,16,11")
    a = ap.parse_args()

    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    timing = {} if a.timing == "-" else {
        t["idx"]: t["seconds"] for t in json.loads(Path(a.timing).read_text())["shots"]}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    race = RaceClient(os.environ["RACE_API_KEY"])
    rates = {g["gpu_name"]: g["hourly_rate"] for g in race.gpus()}

    t_start = time.monotonic()
    pod = session.acquire(race, resume_ids=a.resume, slices=[int(x) for x in a.slices.split(",") if x],
                          name="corpus-render", log=log)
    if pod is None:
        log("NO GPU: every option was busy or out of disk. Nothing rendered.")
        return 2
    gpu_name = next((p["gpu"] for p in race.pods() if int(p["id"]) == pod.id), "")
    rate = next((r for n, r in rates.items() if n in gpu_name), None)

    tunnel = None
    try:
        session.ensure_models(pod, os.environ["HF_TOKEN"].strip(), log=log)
        session.wait_comfy(pod, log=log)
        # Close Race's public ComfyUI relay: from here the GPU is reachable only
        # through our SSH tunnel. (pkill -x matches the process name, never this command.)
        session.ssh(pod, "pkill -x socat || true", timeout=30)
        port = free_port()
        tunnel = subprocess.Popen(["ssh", *session.SSH_OPTS, "-N", "-L", f"{port}:127.0.0.1:28188",
                                   "-p", str(pod.port), f"root@{pod.host}"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{port}"
        for _ in range(30):
            try:
                if httpx.get(base + "/system_stats", timeout=5).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(1)
        with httpx.Client(base_url=base, timeout=120) as http:
            info = http.get("/object_info").json()
            jobs = []
            for shot in plan["shots"]:
                frames = (ltx25.frames_for(timing[shot["idx"]]) if timing
                          else int(shot["num_frames"]))
                graph, problems = ltx25.build(info, ltx25.nodes(shot, frames, f"render/shot{shot['idx']}"))
                if problems:
                    raise RuntimeError(f"shot {shot['idx']} graph invalid: {problems}")
                jobs.append((shot["idx"], frames, graph))
            cid, queued = uuid.uuid4().hex, []
            for idx, frames, graph in jobs:
                r = http.post("/prompt", json={"prompt": graph, "client_id": cid})
                r.raise_for_status()
                queued.append((idx, r.json()["prompt_id"]))
                log(f"queued shot {idx}: {frames} frames ({(frames - 1) / ltx25.FPS:.2f}s)")
            t0 = time.monotonic()
            for idx, pid in queued:
                while True:
                    h = http.get(f"/history/{pid}").json().get(pid)
                    if h and h.get("status", {}).get("completed") is not None:
                        break
                    time.sleep(8)
                status = h["status"].get("status_str")
                if status != "success":
                    errs = [m for m in h["status"].get("messages", []) if m[0] == "execution_error"]
                    log(f"shot {idx} FAILED: {json.dumps(errs)[:600]}")
                    continue
                for o in h["outputs"].values():
                    for items in o.values():
                        for it in items if isinstance(items, list) else []:
                            if isinstance(it, dict) and it.get("filename"):
                                v = http.get("/view", params={"filename": it["filename"],
                                                              "subfolder": it.get("subfolder", ""),
                                                              "type": it.get("type", "output")})
                                (out / f"shot{idx}.mp4").write_bytes(v.content)
                log(f"shot {idx} done at +{time.monotonic() - t0:.0f}s render time")
    finally:
        if tunnel:
            tunnel.terminate()
        session.release(race, pod, keep_cache=True, log=log)
        mins = (time.monotonic() - t_start) / 60
        cost = f" ≈ ₹{mins / 60 * rate * 1.18:.0f} incl. GST" if rate else ""
        log(f"session over: {mins:.1f} min on {gpu_name or 'the GPU'}{cost}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
