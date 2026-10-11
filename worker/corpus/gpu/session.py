"""Get a usable Race GPU pod as cheaply as possible, ready to render, then let go.

Race's catalogue is unreliable in two ways seen in practice: a slice listed as
available answers 409/503, and a pod lands on a host whose shared disk is full.
So acquisition is a cheapest-first search that fails fast:

  1. resume paused pods that already hold the verified models (no download);
  2. deploy fresh pods on the preferred slices, and within seconds of SSH coming
     up check the host's real free disk — terminate at once if it is short.

Every probe that cannot be used costs roughly a minute of GPU time instead of a
failed download. After the work, a pod on a healthy host is *paused*, not
terminated: a stopped pod has not been billed so far, and its /workspace keeps
the models, so the next session on that host skips the download.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from ..race import RaceClient, RaceError
from . import models

COMFYUI_TEMPLATE = "3"
POD_DISK_GB = 70
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ServerAliveInterval=30"]

Log = Callable[[str], None]


@dataclass
class Pod:
    id: int
    host: str
    port: int
    web_url: str
    fresh: bool          # deployed now (True) or resumed with its cache (False)


def _parse_ssh(cmd: str) -> tuple[str, int]:
    m = re.search(r"root@([\w.\-]+)\s+-p\s+(\d+)", cmd or "")
    if not m:
        raise RuntimeError(f"cannot parse ssh command {cmd!r}")
    return m.group(1), int(m.group(2))


def ssh(pod: Pod, command: str, *, stdin: str | None = None, timeout: int = 60,
        check: bool = False) -> subprocess.CompletedProcess:
    # Bytes, not text mode: on Windows, text-mode pipes turn every LF into CRLF,
    # and bash on the pod then chokes on the carriage returns of a piped script.
    r = subprocess.run(["ssh", *SSH_OPTS, "-p", str(pod.port), f"root@{pod.host}", command],
                       input=stdin.encode() if stdin is not None else None,
                       capture_output=True, timeout=timeout, check=check)
    r.stdout = r.stdout.decode("utf-8", "replace")
    r.stderr = r.stderr.decode("utf-8", "replace")
    return r


def _wait_ssh(pod: Pod, timeout: int = 120) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            if ssh(pod, "true", timeout=20).returncode == 0:
                return
        except subprocess.TimeoutExpired:
            pass
        time.sleep(4)
    raise RuntimeError(f"ssh to pod {pod.id} never came up")


def host_free_bytes(pod: Pod) -> int:
    out = ssh(pod, "df -B1 --output=avail / | tail -1", timeout=30).stdout.strip()
    return int(out)


def _pod_by_name(race: RaceClient, name: str) -> dict:
    running = [p for p in race.pods() if p.get("name") == name and p.get("status") == "running"]
    if not running:
        raise RuntimeError(f"deployed pod {name!r} not found in pod-list")
    return max(running, key=lambda p: int(p["id"]))


def acquire(race: RaceClient, *, resume_ids: list[int], slices: list[int], name: str,
            log: Log = print) -> Pod | None:
    """Cheapest usable pod, or None when every option is busy or short of disk."""
    for pid in resume_ids:
        try:
            r = race.resume(str(pid))
        except RaceError as e:
            log(f"resume {pid}: {e.message}")
            continue
        host, port = _parse_ssh(r.get("ssh_command"))
        pod = Pod(pid, host, port, r.get("web_url", ""), fresh=False)
        _wait_ssh(pod)
        log(f"resumed pod {pid} on {host} (models cached there)")
        return pod

    need = models.TOTAL_BYTES + models.MARGIN_BYTES
    for slice_id in slices:
        t0 = time.monotonic()
        try:
            race.deploy(str(slice_id), COMFYUI_TEMPLATE, disk_gb=POD_DISK_GB, name=name)
        except RaceError as e:
            log(f"slice {slice_id}: {e.message}")
            continue
        p = _pod_by_name(race, name)
        host, port = _parse_ssh(p.get("ssh_command"))
        pod = Pod(int(p["id"]), host, port, p.get("web_url", ""), fresh=True)
        try:
            _wait_ssh(pod)
            free = host_free_bytes(pod)
        except Exception as e:  # noqa: BLE001 - an unusable pod is released below
            free, why = -1, str(e)
        else:
            why = f"host has {free / 1e9:.0f} GB free, needs {need / 1e9:.0f} GB"
        if free >= need:
            log(f"slice {slice_id}: pod {pod.id} on {host} — {why} — using it "
                f"({time.monotonic() - t0:.0f}s to check)")
            return pod
        race.terminate(str(pod.id))
        log(f"slice {slice_id}: pod {pod.id} on {host} unusable ({why}); terminated after "
            f"{time.monotonic() - t0:.0f}s")
    return None


class NeedsDownload(RuntimeError):
    """The pod lacks model files and was asked not to fetch them."""


def ensure_models(pod: Pod, hf_token: str, log: Log = print, *, fetch: bool = True) -> None:
    """Make the LTX-2.5 files present, verified and linked. Raises if impossible;
    with fetch=False, raises NeedsDownload instead of downloading anything."""
    ssh(pod, "umask 077; cat > /root/.hf_token", stdin=hf_token, timeout=30, check=True)
    t0 = time.monotonic()
    r = ssh(pod, "bash -s" if fetch else "NO_FETCH=1 bash -s", stdin=models.ensure_script(), timeout=3600)
    for line in r.stdout.splitlines():
        if line.startswith("STATUS"):
            log("  " + line[7:])
    if r.returncode == 5:
        raise NeedsDownload(f"pod {pod.id} would need a model download")
    if r.returncode != 0:
        raise RuntimeError(f"model setup failed (exit {r.returncode}): {r.stderr[-500:]}")
    log(f"models ready in {time.monotonic() - t0:.0f}s")


def wait_comfy(pod: Pod, timeout: int = 600, log: Log = print) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        r = ssh(pod, "curl -sf -m 5 http://127.0.0.1:28188/system_stats", timeout=30)
        if r.returncode == 0 and '"devices"' in r.stdout:
            dev = json.loads(r.stdout)["devices"][0]
            log(f"ComfyUI ready: {dev['name'][:40]}, {dev['vram_total'] / 2**30:.0f} GB VRAM")
            return
        time.sleep(5)
    raise RuntimeError("ComfyUI did not become ready")


def release(race: RaceClient, pod: Pod, *, keep_cache: bool, log: Log = print) -> None:
    if keep_cache:
        race.pause(str(pod.id))
        log(f"paused pod {pod.id} (models stay cached on {pod.host})")
    else:
        race.terminate(str(pod.id))
        log(f"terminated pod {pod.id}")
