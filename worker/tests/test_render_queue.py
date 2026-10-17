"""render.render_shots against fake ComfyUI servers: the real HTTP loop, no GPU.

Covers what the FakeGPU in test_render_pipeline stands in for: several pods
draining one ShotQueue, the next shot queued before the last clip is fetched, a
failed prompt, and a pod dying with a shot in flight.
"""

from __future__ import annotations

import http.server
import json
import threading
import uuid
from pathlib import Path

import pytest

from corpus.gpu import ltx25, render


class FakeComfy:
    """Just enough of ComfyUI's API. A prompt completes on its `polls`-th /history
    check; `fail_idx` shots end in an execution error; after `die_after` completed
    prompts every request fails, like a pod whose SSH tunnel dropped."""

    def __init__(self, polls=2, fail_idx=(), die_after=None):
        self.polls, self.fail_idx, self.die_after = polls, set(fail_idx), die_after
        self.events: list[str] = []
        self.prompts: dict[str, dict] = {}
        self.uploads: dict[str, bytes] = {}
        self.completed = 0
        self._lock = threading.Lock()
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def _send(self, code, body=b"", ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                with fake._lock:
                    if fake.die_after is not None and fake.completed >= fake.die_after:
                        return self._send(502, b"tunnel down", "text/plain")
                    if self.path == "/object_info":
                        return self._send(200, b"{}")
                    if self.path == "/object_info/LoadImage":
                        fake.events.append("refresh LoadImage")
                        return self._send(200, json.dumps({"LoadImage": {"input": {"required": {
                            "image": [sorted(fake.uploads)]}}}}).encode())
                    if self.path.startswith("/history/"):
                        pid = self.path.rsplit("/", 1)[1]
                        p = fake.prompts[pid]
                        p["polls"] += 1
                        if p["polls"] < fake.polls:
                            return self._send(200, b"{}")
                        if not p["done"]:
                            p["done"] = True
                            fake.completed += 1
                        ok = p["idx"] not in fake.fail_idx
                        h = {"status": {"completed": True, "status_str": "success" if ok else "error",
                                        "messages": [] if ok else [["execution_error", {"node": "9"}]]},
                             "outputs": {"9": {"videos": [{"filename": f"shot{p['idx']}.mp4", "subfolder": "",
                                                           "type": "output"}]}} if ok else {}}
                        return self._send(200, json.dumps({pid: h}).encode())
                    if self.path.startswith("/view"):
                        idx = self.path.split("shot", 1)[1].split(".mp4", 1)[0]
                        fake.events.append(f"fetch {idx}")
                        return self._send(200, f"clip {idx}".encode(), "video/mp4")
                return self._send(404)

            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                with fake._lock:
                    if fake.die_after is not None and fake.completed >= fake.die_after:
                        return self._send(502, b"tunnel down", "text/plain")
                    if self.path == "/upload/image":
                        name = body.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
                        fake.uploads[name] = body
                        fake.events.append(f"upload {name}")
                        return self._send(200, json.dumps({"name": name, "subfolder": "", "type": "input"}).encode())
                    if self.path == "/prompt":
                        idx = json.loads(body)["prompt"]["idx"]
                        fake.guides = getattr(fake, "guides", []) + [json.loads(body)["prompt"].get("guide")]
                        pid = uuid.uuid4().hex
                        fake.prompts[pid] = {"idx": idx, "polls": 0, "done": False}
                        fake.events.append(f"start {idx}")
                        return self._send(200, json.dumps({"prompt_id": pid}).encode())
                return self._send(200, b"{}")

            def log_message(self, *args):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"

    def close(self):
        self.srv.shutdown()


@pytest.fixture(autouse=True)
def tiny_graphs(monkeypatch):
    monkeypatch.setattr(ltx25, "nodes", lambda shot, frames, prefix, guide=None: (shot["idx"], guide))
    monkeypatch.setattr(ltx25, "build", lambda info, nodes: ({"idx": nodes[0], "guide": nodes[1]}, []))


def shots(*frames):
    return [{"idx": i, "num_frames": f} for i, f in enumerate(frames)]


def run_pods(queue, comfies, tmp_path):
    done, errors = [], []

    def on_done(shot, path, seconds):
        assert path.read_bytes() == f"clip {shot['idx']}".encode()
        done.append(shot["idx"])

    def drive(k, c):
        try:
            render.render_shots(c.base, queue, tmp_path / f"pod{k}", on_done, log=lambda m: None,
                                who=f"pod {k}", poll=0.01)
        except Exception as e:  # noqa: BLE001
            errors.append((k, e))

    def drive_and_leave(k, c):
        try:
            drive(k, c)
        finally:
            queue.leave(f"pod {k}")

    for k in range(len(comfies)):
        queue.join(f"pod {k}")
    threads = [threading.Thread(target=drive_and_leave, args=(k, c)) for k, c in enumerate(comfies)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return done, errors


def test_one_pod_queues_the_next_shot_before_fetching_the_last(tmp_path):
    c = FakeComfy()
    try:
        q = render.ShotQueue(shots(97, 241, 137))
        done, errors = run_pods(q, [c], tmp_path)
    finally:
        c.close()
    assert errors == [] and q.remaining() == 0
    assert done == [1, 2, 0]                                    # longest first
    assert c.events == ["start 1", "start 2", "fetch 1", "start 0", "fetch 2", "fetch 0"]
    assert q.done_by == {"pod 0": [1, 2, 0]}


def test_two_pods_drain_one_queue(tmp_path):
    a, b = FakeComfy(polls=2), FakeComfy(polls=6)              # b is the slower GPU
    try:
        q = render.ShotQueue(shots(137, 185, 201, 193, 241))
        done, errors = run_pods(q, [a, b], tmp_path)
    finally:
        a.close(), b.close()
    assert errors == [] and sorted(done) == [0, 1, 2, 3, 4]
    assert q.done_by["pod 0"] and q.done_by["pod 1"]            # both took shots
    assert len(q.done_by["pod 0"]) >= len(q.done_by["pod 1"])   # the faster one took more


def test_a_shot_one_pod_fails_is_rendered_by_the_other(tmp_path):
    small, big = FakeComfy(fail_idx={1}), FakeComfy(polls=3)       # shot 1 is too much for `small`
    try:
        q = render.ShotQueue(shots(97, 241, 137))
        done, errors = run_pods(q, [small, big], tmp_path)
    finally:
        small.close(), big.close()
    assert errors == [] and sorted(done) == [0, 1, 2] and q.failed == []
    assert 1 in q.done_by["pod 1"]


def test_a_failed_prompt_is_reported_not_retried(tmp_path):
    c = FakeComfy(fail_idx={1})
    try:
        q = render.ShotQueue(shots(97, 241, 137))
        done, errors = run_pods(q, [c], tmp_path)
    finally:
        c.close()
    assert errors == [] and sorted(done) == [0, 2] and q.failed == [1]


@pytest.mark.parametrize("die_after, delivered, given_back", [
    (1, [], [1, 2]),    # dies after the GPU finished shot 1, before its clip came down
    (2, [1], [2, 0]),   # shot 1 delivered; dies fetching shot 2 / submitting shot 0
])
def test_a_dying_pod_gives_its_shots_back(tmp_path, die_after, delivered, given_back):
    q = render.ShotQueue(shots(97, 241, 137))
    dying = FakeComfy(die_after=die_after)
    try:
        done, errors = run_pods(q, [dying], tmp_path)
    finally:
        dying.close()
    assert done == delivered and [k for k, _ in errors] == [0]
    assert [s["idx"] for s in q.left()][:len(given_back)] == given_back   # at the front, in order
    assert sorted(s["idx"] for s in q.left()) == sorted({0, 1, 2} - set(delivered))
    healthy = FakeComfy()
    try:
        done, errors = run_pods(q, [healthy], Path(tmp_path) / "again")
    finally:
        healthy.close()
    assert errors == [] and sorted(done + delivered) == [0, 1, 2]       # nothing lost


def test_a_guided_shot_uploads_its_picture_before_its_prompt(tmp_path):
    comfy = FakeComfy(polls=1)
    picture = tmp_path / "guide.png"
    picture.write_bytes(b"\x89PNG fake picture")
    queue = render.ShotQueue([{"idx": 0, "num_frames": 97, "id": "s0", "guide_path": str(picture)},
                              {"idx": 1, "num_frames": 49, "id": "s1"}])
    queue.join("pod")
    try:
        render.render_shots(comfy.base, queue, tmp_path / "out", lambda *a: None, log=lambda m: None, poll=0.01)
    finally:
        comfy.close()
    assert comfy.events[:3] == ["upload corpus_s0.png", "refresh LoadImage", "start 0"]
    assert comfy.guides == ["corpus_s0.png", None]                   # the plain shot has no guide
    assert b"fake picture" in comfy.uploads["corpus_s0.png"]

