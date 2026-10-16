"""Milestone 3/4 pipeline: plan → narrate → request render (→ render → assemble).

Fakes: the voice (a silent WAV of a known length), S3 (moto), and later the GPU.
Everything else is the real code against the real schema.
"""

from __future__ import annotations

import http.server
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import boto3
import numpy as np
import pytest
import soundfile as sf
from moto import mock_aws

from corpus import db, storage
from corpus.crypto import encrypt
from corpus.gpu import ltx25
from corpus.handlers import narrate, plan_shots, write_script
from corpus.runner import Runner
from corpus.script.llm import Review, ScriptOut, Shot, Usage

NARRATION = [
    "Your body is giving off tiny flashes of light right now.",
    "It is an ultraweak glow from ordinary chemistry inside living cells.",
    "Here is the strange part: it changes as your body's chemistry changes.",
]


class Writer:
    def __init__(self, api_key):
        pass

    def write(self, *, model, system, user):
        return ScriptOut(
            title="Your body is glowing right now", hook="Your body glows.", description="d",
            hashtags=["#shorts"], intended_dialogue=" ".join(NARRATION), style_prompt="Stylised 3D.",
            shots=[Shot(seconds=8, visual=f"v{i}", audio="soft hum", narration=n)
                   for i, n in enumerate(NARRATION)],
            review=Review(score=8, risks=[], notes="ok"),
        ), Usage(model=model, input_tokens=1, output_tokens=1)


def fake_speak(text: str, voice: str, speed: float, out: Path) -> float:
    seconds = 0.3 * len(text.split())            # deterministic "speech" length
    sf.write(out, np.zeros(int(24000 * seconds), dtype=np.float32), 24000)
    return seconds


@pytest.fixture
def s3(monkeypatch):
    with mock_aws():
        c = boto3.client("s3", region_name="us-east-1", aws_access_key_id="t", aws_secret_access_key="t")
        c.create_bucket(Bucket="corpus-test-media")
        monkeypatch.setattr(storage, "client", lambda: c)
        monkeypatch.setattr(storage, "bucket", lambda: "corpus-test-media")
        yield c


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(write_script, "WRITER_FACTORY", Writer)
    monkeypatch.setattr(narrate, "SPEAK", fake_speak)


@pytest.fixture
def owner():
    with db.conn() as c:
        c.execute("delete from jobs where state in ('queued','claimed')")
        yield c


@pytest.fixture
def user(owner):
    uid = f"test-{uuid.uuid4().hex[:10]}"
    owner.execute('insert into "user" (id, name, email, "emailVerified") values (%s,%s,%s,true)',
                  (uid, uid, f"{uid}@example.test"))
    owner.execute("""insert into app_settings (user_id, script_model, narrator_voice)
                     values (%s, 'test-model', 'bm_george')""", (uid,))
    owner.execute("insert into user_keys (user_id, name, ciphertext) values (%s, 'openai', %s)",
                  (uid, encrypt("sk-test-key")))
    yield uid
    owner.execute("delete from storage_objects where user_id = %s", (uid,))
    owner.execute('delete from "user" where id = %s', (uid,))


def cpu() -> Runner:
    return Runner("cpu", {"write_script": write_script.HANDLER, "plan_shots": plan_shots.HANDLER,
                          "narrate": narrate.HANDLER})


def as_user(owner, uid, sql, params=()):
    owner.execute("select set_config('app.user_id', %s, false)", (uid,))
    try:
        return owner.execute(sql, params).fetchone()
    finally:
        owner.execute("select set_config('app.user_id', '', false)")


def approved_narrated_post(owner, uid) -> tuple[str, str]:
    slot = date(2033, 1, 1) + timedelta(days=uuid.uuid4().int % 3000)
    pid = owner.execute("insert into posts (user_id, topic, slot_date, audio_source, target_seconds) "
                        "values (%s, 'glow', %s, 'kokoro', 15) returning id", (uid, slot)).fetchone()["id"]
    as_user(owner, uid, "select api.generate_script(%s)", (pid,))
    cpu().tick()                                                       # write_script
    sid = owner.execute("select id from scripts where post_id = %s", (pid,)).fetchone()["id"]
    as_user(owner, uid, "select api.approve_script(%s)", (sid,))
    cpu().tick()                                                       # plan_shots
    return pid, sid


def test_narration_sets_shot_lengths_and_unlocks_render(s3, owner, user):
    pid, sid = approved_narrated_post(owner, user)
    with pytest.raises(Exception, match="being planned or voiced"):
        as_user(owner, user, "select api.request_render(%s)", (pid,))  # not voiced yet

    assert cpu().tick()                                                # narrate
    shots = owner.execute("select idx, narration, narration_key, narration_seconds, num_frames from shots "
                          "where script_id = %s order by idx", (sid,)).fetchall()
    for sh, line in zip(shots, NARRATION):
        assert sh["narration"] == line
        assert float(sh["narration_seconds"]) == pytest.approx(0.3 * len(line.split()))
        assert sh["num_frames"] == ltx25.frames_for(float(sh["narration_seconds"]))
        assert sh["num_frames"] % 8 == 1
        assert s3.head_object(Bucket="corpus-test-media", Key=sh["narration_key"])["ContentLength"] > 0
    kinds = owner.execute("select kind, state from storage_objects where post_id = %s", (pid,)).fetchall()
    assert {(k["kind"], k["state"]) for k in kinds} == {("narration", "stored")}
    ev = owner.execute("select detail from post_events where post_id = %s and reason = 'narration recorded'",
                       (pid,)).fetchone()
    assert ev["detail"]["voice"] == "bm_george"

    job = as_user(owner, user, "select * from api.request_render(%s)", (pid,))
    assert (job["lane"], job["kind"], job["state"]) == ("gpu", "render_post", "queued")
    assert owner.execute("select status from posts where id = %s", (pid,)).fetchone()["status"] == "queued_for_render"
    # Pressing Render again while it is queued is refused — no second GPU job.
    with pytest.raises(Exception, match="only an approved post can be rendered"):
        as_user(owner, user, "select api.request_render(%s)", (pid,))


def test_a_line_too_long_for_one_shot_fails_the_post_clearly(s3, owner, user, monkeypatch):
    pid, sid = approved_narrated_post(owner, user)

    def slow(text, voice, speed, out):
        fake_speak(text, voice, speed, out)
        return 12.0                                    # a 12 s line + pause cannot fit a 12 s shot

    monkeypatch.setattr(narrate, "SPEAK", slow)
    cpu().tick()
    p = owner.execute("select status, error from posts where id = %s", (pid,)).fetchone()
    assert p["status"] == "failed" and p["error"]["stage"] == "narration_too_long"
    assert "takes 12.0s to say" in p["error"]["message"]
    assert owner.execute("select count(*) as n from storage_objects where post_id = %s",
                         (pid,)).fetchone()["n"] == 0  # nothing stored for the line that cannot fit


def test_narrate_is_resumable(s3, owner, user, monkeypatch):
    pid, sid = approved_narrated_post(owner, user)
    calls = []

    def flaky(text, voice, speed, out):
        calls.append(text)
        if len(calls) == 2:
            raise RuntimeError("tts crashed mid-way")
        return fake_speak(text, voice, speed, out)

    monkeypatch.setattr(narrate, "SPEAK", flaky)
    cpu().tick()                                                       # fails on shot 2
    voiced = owner.execute("select count(*) as n from shots where script_id = %s and narration_key is not null",
                           (sid,)).fetchone()["n"]
    assert voiced == 1
    owner.execute("update jobs set not_before = now() where kind = 'narrate' and post_id = %s", (pid,))
    monkeypatch.setattr(narrate, "SPEAK", fake_speak)
    cpu().tick()                                                       # resumes
    voiced = owner.execute("select count(*) as n from shots where script_id = %s and narration_key is not null",
                           (sid,)).fetchone()["n"]
    assert voiced == 3


# ── render (fake GPU) → assemble (real ffmpeg) ────────────────────────────────

import subprocess  # noqa: E402
from contextlib import contextmanager  # noqa: E402

from corpus.gpu import session  # noqa: E402
from corpus.gpu.session import Pod  # noqa: E402
from corpus.handlers import assemble, build_segment, render_post  # noqa: E402
from corpus.media import assemble as media  # noqa: E402


class FakeGPU:
    """Stands in for Race + ComfyUI: pods that make real little clips of the right length.

    `cached` lists the paused pods Race reports (id, vram); `busy` ids refuse to
    resume; `no_models` ids lack the model files; `breaks` ids die on their first
    shot; `fails` maps a pod id to the shots ComfyUI errors on there (out of memory,
    say); `slow` seconds is how long each shot takes on a pod.
    """

    def __init__(self, available=True):
        self.available = available
        self.cached: list[tuple[int, int]] = []
        self.busy: set[int] = set()
        self.no_models: set[int] = set()
        self.breaks: set[int] = set()
        self.fails: dict[int, set[int]] = {}
        self.slow: dict[int, float] = {}
        self.resumed: list[int] = []
        self.released: list[tuple[int, bool]] = []
        self.rendered: list[int] = []
        self.by_pod: dict[int, list[int]] = {}
        self._lock = threading.Lock()

    def race(self):
        pods = [{"id": i, "name": "corpus-render", "status": "stopped", "vram": v} for i, v in self.cached]
        return type("R", (), {"pods": lambda _self: pods})()

    def acquire(self, race, *, resume_ids, slices, name, log, on_billed=None):
        for pid in resume_ids:
            if pid not in self.busy:
                with self._lock:
                    self.resumed.append(pid)
                return Pod(pid, "gpu.test", 22, "", fresh=False)
        return Pod(1, "gpu.test", 22, "", fresh=True) if self.available and slices is not None and (
            slices or not resume_ids) else None

    def prepare(self, pod, log, fetch):
        if pod.id in self.no_models and not fetch:
            raise session.NeedsDownload(f"pod {pod.id} would need a model download")

    @contextmanager
    def tunnel(self, pod):
        yield f"http://comfy.test/{pod.id}"

    def render(self, base, queue, out_dir, on_done, should_continue, log, *, who):
        pod_id = int(base.rsplit("/", 1)[1])
        out_dir.mkdir(parents=True, exist_ok=True)
        while should_continue() and (shot := queue.take(who)) is not None:
            if pod_id in self.breaks:
                queue.give_back(shot)
                raise RuntimeError("ssh connection lost")
            time.sleep(self.slow.get(pod_id, 0.0))
            if shot["idx"] in self.fails.get(pod_id, ()):
                queue.shot_failed(shot, who)
                continue
            path = out_dir / f"shot{shot['idx']}.mp4"
            secs = (int(shot["num_frames"]) - 1) / 24
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            f"testsrc2=size={shot['width']}x{shot['height']}:rate=24",
                            "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000",
                            "-t", f"{secs:.3f}", "-pix_fmt", "yuv420p", "-c:v", "libx264",
                            "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)], check=True)
            with self._lock:
                self.rendered.append(shot["idx"])
                self.by_pod.setdefault(pod_id, []).append(shot["idx"])
            on_done(shot, path, 1.0)
            queue.done_by.setdefault(who, []).append(shot["idx"])

    def release(self, race, pod, *, keep_cache, log):
        with self._lock:
            self.released.append((pod.id, keep_cache))


@pytest.fixture
def gpu(monkeypatch):
    g = FakeGPU()
    monkeypatch.setattr(render_post, "ACQUIRE", g.acquire)
    monkeypatch.setattr(render_post, "PREPARE", g.prepare)
    monkeypatch.setattr(render_post, "TUNNEL", g.tunnel)
    monkeypatch.setattr(render_post, "RENDER", g.render)
    monkeypatch.setattr(render_post, "RELEASE", g.release)
    monkeypatch.setattr(render_post, "RACE", g.race)
    return g


@pytest.fixture(autouse=True)
def pod_notes(monkeypatch, tmp_path):
    notes = tmp_path / "race_pods.json"
    monkeypatch.setattr(render_post, "_pod_notes", lambda: notes)
    return notes


@pytest.fixture(autouse=True)
def segment_cache(monkeypatch, tmp_path):
    root = tmp_path / "segment-cache"
    monkeypatch.setattr(build_segment, "cache_dir", lambda post_id: root / str(post_id))
    return root


def even_timings(audio, hint):
    """Instead of Whisper: the hint's words spread evenly over the audio."""
    words = hint.split()
    total = media.probe_duration(audio)
    step = total / max(1, len(words))
    return [(i * step, (i + 1) * step, w) for i, w in enumerate(words)]


@pytest.fixture(autouse=True)
def fake_whisper(monkeypatch):
    monkeypatch.setattr(narrate, "WORD_TIMINGS", even_timings)
    monkeypatch.setattr(build_segment, "WORD_TIMINGS", even_timings)


def gpu_lane() -> Runner:
    return Runner("gpu", {"render_post": render_post.HANDLER})


def cpu_all() -> Runner:
    return Runner("cpu", {"write_script": write_script.HANDLER, "plan_shots": plan_shots.HANDLER,
                          "narrate": narrate.HANDLER, "build_segment": build_segment.HANDLER,
                          "assemble": assemble.HANDLER})


def drain(runner: Runner) -> list[str]:
    """Run the lane's jobs until none is ready; the kinds, in the order they ran."""
    kinds = []
    while True:
        job = db.claim(runner.lane, runner.s.version, list(runner.handlers))
        if not job:
            return kinds
        runner.run_job(job)
        kinds.append(job["kind"])


def test_render_then_assemble_to_a_ready_reel(s3, owner, user, gpu, tmp_path, segment_cache):
    pid, sid = approved_narrated_post(owner, user)
    cpu_all().tick()                                                   # narrate (+ word timings)
    words = owner.execute("select narration_words from shots where script_id = %s order by idx",
                          (sid,)).fetchall()
    assert [" ".join(w[2] for w in r["narration_words"]) for r in words] == NARRATION
    as_user(owner, user, "select api.request_render(%s)", (pid,))
    assert gpu_lane().tick()                                           # render_post
    assert sorted(gpu.rendered) == [0, 1, 2] and gpu.released == [(1, True)]   # paused, not killed
    shots = owner.execute("select state, artifact_key from shots where script_id = %s order by idx",
                          (sid,)).fetchall()
    assert all(s["state"] == "uploaded" and s["artifact_key"] for s in shots)
    assert owner.execute("select status from posts where id = %s", (pid,)).fetchone()["status"] == "rendered"

    # Each shot was handed to the cpu lane as it finished; those run first, then the join.
    assert drain(cpu_all()) == ["build_segment"] * 3 + ["assemble"]
    p = owner.execute("select status, final_key, final_duration_s, final_bytes from posts where id = %s",
                      (pid,)).fetchone()
    assert p["status"] == "ready" and p["final_bytes"] > 0
    expected = sum((ltx25.frames_for(0.3 * len(l.split())) - 1) / 24 for l in NARRATION)
    assert float(p["final_duration_s"]) == pytest.approx(expected, abs=0.1)
    assembled = owner.execute("select result from jobs where kind = 'assemble' and post_id = %s",
                              (pid,)).fetchone()["result"]
    assert assembled["segments_ready"] == 3                            # nothing re-encoded at the end
    assert not (segment_cache / str(pid)).exists()                     # cache cleared after the upload
    final = storage.get_file(p["final_key"], tmp_path / "final.mp4")
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
                              "-of", "csv=p=0", str(final)], capture_output=True, text=True).stdout
    assert "video,1080,1920" in streams and "audio" in streams
    # Sound and picture line up: the decoded sound is the pictures' length, give or
    # take the padding of AAC's last 1024-sample frame — no drift across the joins.
    frames = media._frames(final)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(final), "-vn", "-c:a", "pcm_s16le",
                    str(tmp_path / "sound.wav")], check=True)
    assert 0 <= sf.info(str(tmp_path / "sound.wav")).frames - frames * 2000 < 1024
    kinds = {k["kind"] for k in owner.execute("select kind from storage_objects where post_id = %s and state = 'stored'",
                                               (pid,)).fetchall()}
    assert kinds == {"narration", "shot", "final"}
    events = [e["reason"] for e in owner.execute("select reason from post_events where post_id = %s order by id",
                                                 (pid,)).fetchall()]
    assert events[-5:] == ["render requested", "rendering started", "all shots rendered", "assembling",
                           "reel assembled"]


def test_a_failed_join_is_retried_without_the_gpu(s3, owner, user, gpu, monkeypatch):
    """Live incident: 8 shots rendered, then the final join failed on the server's
    ffmpeg. The shots must stay usable: retrying re-joins them, never re-renders."""
    pid, sid = approved_narrated_post(owner, user)
    cpu_all().tick()
    as_user(owner, user, "select api.request_render(%s)", (pid,))
    assert gpu_lane().tick()
    real_join = media.join_segments

    def broken(*a, **k):
        raise media.FfmpegError("ffmpeg failed: Cannot select channel layout")

    monkeypatch.setattr(media, "join_segments", broken)
    for _ in range(3):                                                 # assemble gives up
        drain(cpu_all())
        owner.execute("update jobs set not_before = now() where kind = 'assemble' and post_id = %s", (pid,))
    p = owner.execute("select status, error from posts where id = %s", (pid,)).fetchone()
    assert p["status"] == "failed" and p["error"]["stage"] == "assemble"
    assert "rendered shots are safe" in p["error"]["message"] and "channel layout" in p["error"]["message"]

    monkeypatch.setattr(media, "join_segments", real_join)
    rendered = list(gpu.rendered)
    job = as_user(owner, user, "select * from api.request_render(%s)", (pid,))   # Retry assembly
    assert (job["lane"], job["kind"], job["state"]) == ("cpu", "assemble", "queued")
    assert not gpu_lane().tick()                                       # nothing for the GPU to do
    assert drain(cpu_all()) == ["assemble"]
    assert gpu.rendered == rendered                                    # no shot rendered twice
    assert owner.execute("select status from posts where id = %s", (pid,)).fetchone()["status"] == "ready"


def test_the_image_selftest_passes():
    from corpus import selftest
    assert selftest.main() == 0


def test_assemble_builds_segments_the_cache_lost(s3, owner, user, gpu, segment_cache):
    pid, sid = approved_narrated_post(owner, user)
    cpu_all().tick()                                                   # narrate
    as_user(owner, user, "select api.request_render(%s)", (pid,))
    gpu_lane().tick()
    owner.execute("update jobs set state = 'cancelled' where kind = 'build_segment' and post_id = %s", (pid,))
    owner.execute("update shots set narration_words = null where script_id = %s", (sid,))   # voiced long ago
    assert drain(cpu_all()) == ["assemble"]
    p = owner.execute("select status, final_duration_s from posts where id = %s", (pid,)).fetchone()
    assert p["status"] == "ready"
    expected = sum((ltx25.frames_for(0.3 * len(l.split())) - 1) / 24 for l in NARRATION)
    assert float(p["final_duration_s"]) == pytest.approx(expected, abs=0.1)
    res = owner.execute("select result from jobs where kind = 'assemble' and post_id = %s", (pid,)).fetchone()
    assert res["result"]["segments_ready"] == 0
    assert owner.execute("select count(*) as n from shots where script_id = %s and narration_words is not null",
                         (sid,)).fetchone()["n"] == 3                  # timings measured and kept


def test_two_gpus_share_the_shots(s3, owner, user, gpu):
    gpu.cached = [(32, 32), (96, 96)]                                  # a 5090 and a PRO 6000, both paused
    gpu.slow = {96: 0.4, 32: 0.4}
    pid, sid = approved_narrated_post(owner, user)
    cpu_all().tick()
    as_user(owner, user, "select api.request_render(%s)", (pid,))
    assert gpu_lane().tick()
    assert sorted(gpu.rendered) == [0, 1, 2]
    assert set(gpu.by_pod) == {96, 32}                                 # both GPUs rendered shots
    assert sorted(gpu.released) == [(32, True), (96, True)]            # both paused afterwards
    res = owner.execute("select result from jobs where kind = 'render_post' and post_id = %s", (pid,)).fetchone()
    assert set(res["result"]["pods"]) == {"pod 96", "pod 32"}
    # Each pod's billed time is on the post's bill, at the fallback rate (no Race offers here).
    bills = owner.execute("""select (quantity->>'pod')::int as pod, inr_paise, quantity->>'confirmed' as ok
                               from costs where post_id = %s and kind = 'gpu' order by 1""", (pid,)).fetchall()
    assert [b["pod"] for b in bills] == [32, 96] and all(b["ok"] == "true" for b in bills)
    assert all(b["inr_paise"] is not None for b in bills)


def test_a_busy_or_unready_helper_is_skipped(s3, owner, user, gpu):
    gpu.cached = [(96, 96), (32, 32), (33, 32)]
    gpu.busy = {32}                                                    # Race: no GPU of this type
    gpu.no_models = {33}                                               # would need a 40 GB download
    gpu.slow = {96: 0.2}
    pid, sid = approved_narrated_post(owner, user)
    cpu_all().tick()
    as_user(owner, user, "select api.request_render(%s)", (pid,))
    render_post.MAX_PODS, old = 3, render_post.MAX_PODS
    try:
        assert gpu_lane().tick()
    finally:
        render_post.MAX_PODS = old
    assert set(gpu.by_pod) == {96} and sorted(gpu.rendered) == [0, 1, 2]
    assert sorted(gpu.released) == [(33, True), (96, True)]            # the unready one let go at once
    assert owner.execute("select status from posts where id = %s", (pid,)).fetchone()["status"] == "rendered"


def test_a_helper_without_models_is_not_woken_again(s3, owner, user, gpu):
    gpu.cached = [(96, 96), (33, 32)]
    gpu.no_models = {33}
    for _ in range(2):
        pid, sid = approved_narrated_post(owner, user)
        cpu_all().tick()
        as_user(owner, user, "select api.request_render(%s)", (pid,))
        assert gpu_lane().tick()
        drain(cpu_all())                                               # segments + assembly
    assert gpu.resumed == [96, 33, 96]                                 # second render left 33 alone


def test_a_shot_the_smaller_gpu_cannot_render_goes_to_the_bigger_one(s3, owner, user, gpu):
    gpu.cached = [(96, 96), (32, 32)]
    gpu.slow = {96: 0.3}
    gpu.fails = {32: {0, 1, 2}}                                        # out of memory on the 5090
    pid, sid = approved_narrated_post(owner, user)
    cpu_all().tick()
    as_user(owner, user, "select api.request_render(%s)", (pid,))
    assert gpu_lane().tick()
    assert sorted(gpu.by_pod[96]) == [0, 1, 2] and 32 not in gpu.by_pod
    assert owner.execute("select status from posts where id = %s", (pid,)).fetchone()["status"] == "rendered"


def test_a_shot_failing_everywhere_twice_stops_the_job(s3, owner, user, gpu):
    gpu.fails = {1: {1}}                                               # the graph breaks on shot 1
    pid, sid = approved_narrated_post(owner, user)
    cpu_all().tick()
    job = as_user(owner, user, "select * from api.request_render(%s)", (pid,))
    gpu_lane().tick()                                                  # attempt 1: retried later
    j = owner.execute("select state, error from jobs where id = %s", (job["id"],)).fetchone()
    assert j["state"] == "queued" and j["error"]["stage"] == "render"
    owner.execute("update jobs set not_before = now() where id = %s", (job["id"],))
    gpu_lane().tick()                                                  # attempt 2: give up
    j = owner.execute("select state, error from jobs where id = %s", (job["id"],)).fetchone()
    assert j["state"] == "dead" and "failed to render twice" in j["error"]["message"]
    p = owner.execute("select status from posts where id = %s", (pid,)).fetchone()
    assert p["status"] == "failed"
    assert sorted(gpu.rendered) == [0, 2]                              # the good shots were kept


def test_a_helper_dying_mid_shot_hands_it_back(s3, owner, user, gpu):
    gpu.cached = [(96, 96), (32, 32)]
    gpu.breaks = {32}
    gpu.slow = {96: 0.3}
    pid, sid = approved_narrated_post(owner, user)
    cpu_all().tick()
    as_user(owner, user, "select api.request_render(%s)", (pid,))
    assert gpu_lane().tick()
    assert gpu.by_pod == {96: gpu.by_pod[96]} and sorted(gpu.rendered) == [0, 1, 2]
    assert sorted(gpu.released) == [(32, True), (96, True)]
    assert owner.execute("select status from posts where id = %s", (pid,)).fetchone()["status"] == "rendered"


def test_render_wakes_the_cpu_worker_for_each_shot(s3, owner, user, gpu):
    """gpu/render_post queues cpu work (each shot, then assembly); the cpu worker must not sleep through it."""
    hits = []

    class Peer(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            hits.append((self.path, self.headers.get("Authorization")))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Peer)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        pid, sid = approved_narrated_post(owner, user)
        cpu = cpu_all()
        cpu.s = replace(cpu.s, wake_urls=(f"http://127.0.0.1:{srv.server_port}/wake",), wake_token="tok")
        cpu.tick()                                                     # narrate: same lane, no nudge
        assert hits == []
        as_user(owner, user, "select api.request_render(%s)", (pid,))
        gpu_runner = gpu_lane()
        gpu_runner.s = cpu.s
        assert gpu_runner.tick()
        assert hits == [("/wake", "Bearer tok")] * 4                  # 3 shots as they finish + assembly
    finally:
        srv.shutdown()


def test_no_free_gpu_waits_and_retries(s3, owner, user, gpu):
    gpu.available = False
    pid, sid = approved_narrated_post(owner, user)
    cpu_all().tick()                                                   # narrate
    job = as_user(owner, user, "select * from api.request_render(%s)", (pid,))
    gpu_lane().tick()
    j = owner.execute("select state, not_before - now() as wait, error from jobs where id = %s", (job["id"],)).fetchone()
    assert j["state"] == "queued" and j["wait"].total_seconds() > 500 and j["error"]["stage"] == "no_gpu"
    p = owner.execute("select status, error from posts where id = %s", (pid,)).fetchone()
    assert p["status"] == "queued_for_render" and "Waiting for a free GPU" in p["error"]["message"]
    assert gpu.released == []                                          # nothing was rented


def test_captions_use_script_words_not_misheard_ones():
    heard = [(0.0, 0.3, "As"), (0.3, 0.6, "sells"), (0.6, 0.9, "bokas"), (0.9, 1.2, "oxygen")]
    script = ["As", "cells", "use", "oxygen"]
    times = media.align(script, heard, total=2.0)
    assert [round(t[0], 2) for t in times] == [0.0, 0.3, 0.6, 0.9]
    ass = media.captions_ass([(t[0], t[1], w.upper()) for t, w in zip(times, script)], set(), media.CaptionStyle())
    backslash, form_feed = chr(92), chr(12)
    assert "BOKAS" not in ass and "CELLS" in ass
    assert backslash + "fscx118" in ass and form_feed not in ass   # real ASS tags, not escapes


def _caption_texts(ass: str) -> list[str]:
    """Each caption event's text without override tags; a wrapped line keeps its \\N."""
    out = []
    for ln in ass.splitlines():
        if ln.startswith("Dialogue:"):
            t = re.sub(r"\{[^}]*\}", "", ln.split(",,", 2)[-1])
            if not out or out[-1] != t:
                out.append(t)
    return out


def test_captions_wrap_onto_a_second_line_instead_of_leaving_the_frame():
    """Live reel 1: "glowing—you are glowing" was one 23-character line and ran off both edges."""
    style, nl = media.CaptionStyle(), chr(92) + "N"
    words = media._spoken_words("Darkness and sensitive scientific cameras are needed, you are glowing—you are.")
    assert words[9:11] == ["glowing—", "you"]                           # a dash splits the words
    timed = [(i * 0.3, i * 0.3 + 0.3, w.upper().strip(",.—")) for i, w in enumerate(words)]
    texts = _caption_texts(media.captions_ass(timed, {9}, style))
    assert texts == ["DARKNESS" + nl + "AND SENSITIVE",                 # too wide: wrapped, evenly
                     "SCIENTIFIC" + nl + "CAMERAS ARE",
                     "NEEDED YOU ARE", "GLOWING", "YOU ARE"]           # fits: one line
    for t in texts:
        assert all(media._line_px([(0, 0, w) for w in line.split()], style) <= media.SAFE_WIDTH
                   for line in t.split(nl)), t

    long_word = media.captions_ass([(0.0, 1.0, "PNEUMONOULTRAMICROSCOPIC")], set(), style)
    assert chr(92) + "fs" in long_word.split("Dialogue:")[1]               # shrunk to fit, not clipped


@pytest.mark.parametrize("caption", ["AND SENSITIVE SCIENTIFIC", "TO ORDINARY CHEMISTRY",
                                     "PNEUMONOULTRAMICROSCOPIC", "YOUR BODY IS"])
def test_burned_in_captions_never_leave_the_frame(tmp_path, caption):
    """Draw each caption state with the real font through ffmpeg's libass and look at the pixels."""
    style = media.CaptionStyle()
    words = [(i * 1.0, i * 1.0 + 1.0, w) for i, w in enumerate(caption.split())]
    (tmp_path / "c.ass").write_text(media.captions_ass(words, set(), style), encoding="utf-8")
    shutil.copytree(media.FONTS_DIR, tmp_path / "fonts")
    for i in range(len(words)):                        # every word takes its turn at 118 %
        raw = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=1080x1920:d=8",
                              "-vf", "ass=c.ass:fontsdir=fonts", "-ss", f"{i + 0.5}", "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             capture_output=True, check=True, cwd=tmp_path).stdout
        ink = np.where(np.frombuffer(raw, np.uint8).reshape(1920, 1080).max(axis=0) > 100)[0]
        assert ink.size, "caption not drawn"
        assert ink[0] >= 60 - style.outline_px and ink[-1] <= 1020 + style.outline_px, (caption, i, ink[0], ink[-1])
