"""Milestone 2 pipeline: generate → (validate, retry) → approve → plan shots.

    worker/.venv/Scripts/python -m pytest worker/tests -q

The LLM is the only fake. Everything else — queue functions, leases, the
approval path, constraints — is the real code against the real schema.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from corpus import db
from corpus.crypto import encrypt
from corpus.handlers import plan_shots, write_script
from corpus.runner import Runner
from corpus.script.llm import Review, ScriptOut, Shot, Usage


def _script(seconds=(8, 8, 8), words=6) -> ScriptOut:
    return ScriptOut(
        title="Startup founders 5 mins before the client call",
        hook="Calm founder, burning office",
        description="It is fine. Everything is fine.",
        hashtags=["#shorts", "#startup"],
        intended_dialogue="Everything is completely on track.",
        style_prompt="Bright sitcom office lighting, photorealistic.",
        shots=[Shot(seconds=s, visual=f"Shot {i} visual", audio='He says: "' + " ".join(["word"] * words) + '"',
                    narration="")
               for i, s in enumerate(seconds)],
        review=Review(score=7, risks=["fire may look CGI"], notes="ok"),
    )


class FakeWriter:
    calls = 0
    outputs: list[ScriptOut] = []
    prompts: list[str] = []

    def __init__(self, api_key: str):
        assert api_key == "sk-test-key"

    def write(self, *, model, system, user):
        FakeWriter.calls += 1
        FakeWriter.prompts.append(user)
        assert "Topic: " in user and "## Channel" in system
        out = FakeWriter.outputs.pop(0) if FakeWriter.outputs else _script()
        return out, Usage(model=model, input_tokens=100, output_tokens=200)


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    FakeWriter.calls, FakeWriter.outputs, FakeWriter.prompts = 0, [], []
    monkeypatch.setattr(write_script, "WRITER_FACTORY", FakeWriter)


@pytest.fixture
def owner():
    with db.conn() as c:
        # Leftover runnable cpu jobs from an aborted run would be claimed first.
        c.execute("delete from jobs where lane = 'cpu' and state in ('queued','claimed')")
        yield c


@pytest.fixture
def user(owner):
    uid = f"test-{uuid.uuid4().hex[:10]}"
    owner.execute('insert into "user" (id, name, email, "emailVerified") values (%s,%s,%s,true)',
                  (uid, uid, f"{uid}@example.test"))
    owner.execute("insert into app_settings (user_id, script_model) values (%s, 'test-model')", (uid,))
    owner.execute("insert into user_keys (user_id, name, ciphertext) values (%s, 'openai', %s)",
                  (uid, encrypt("sk-test-key")))
    yield uid
    owner.execute('delete from "user" where id = %s', (uid,))


def runner() -> Runner:
    return Runner("cpu", {"write_script": write_script.HANDLER, "plan_shots": plan_shots.HANDLER})


def new_post(owner, uid) -> str:
    slot = date(2031, 1, 1) + timedelta(days=uuid.uuid4().int % 3000)
    return owner.execute("insert into posts (user_id, topic, slot_date) values (%s, %s, %s) returning id",
                         (uid, "founders before escalation", slot)).fetchone()["id"]


def as_user(owner, uid, sql, params=()):
    owner.execute("select set_config('app.user_id', %s, false)", (uid,))
    try:
        return owner.execute(sql, params).fetchone()
    finally:
        owner.execute("select set_config('app.user_id', '', false)")


def post(owner, pid):
    return owner.execute("select * from posts where id = %s", (pid,)).fetchone()


def test_generate_approve_plan(owner, user):
    pid = new_post(owner, user)
    as_user(owner, user, "select api.generate_script(%s)", (pid,))
    assert post(owner, pid)["status"] == "scripting"

    assert runner().tick()                                   # write_script
    p = post(owner, pid)
    assert p["status"] == "awaiting_approval"
    s = owner.execute("select * from scripts where post_id = %s", (pid,)).fetchone()
    assert (s["version"], s["state"], s["model"]) == (1, "awaiting_approval", "test-model")
    assert s["review"]["score"] == 7 and len(s["shot_plan"]) == 3

    as_user(owner, user, "select api.approve_script(%s)", (s["id"],))
    assert runner().tick()                                   # plan_shots
    shots = owner.execute("select * from shots where script_id = %s order by idx",
                          (s["id"],)).fetchall()
    assert len(shots) == 3
    for sh in shots:
        assert sh["num_frames"] % 8 == 1 and sh["num_frames"] == 193     # 8 s at 24 fps
        assert (sh["width"], sh["height"]) == (704, 1280)
        assert "Bright sitcom office lighting" in sh["prompt"]
    assert len({sh["seed"] for sh in shots}) == 3
    assert plan_shots.seed_for(str(s["id"]), 0) == shots[0]["seed"]      # stable

    events = [r["to_state"] for r in owner.execute(
        "select to_state from post_events where post_id = %s order by id", (pid,))]
    assert events == ["scripting", "awaiting_approval", "approved", "approved"]
    assert not runner().tick()                                # nothing left
    assert FakeWriter.calls == 1


def test_auto_approve_goes_straight_to_planning(owner, user):
    owner.execute("update app_settings set auto_approve = true where user_id = %s", (user,))
    pid = new_post(owner, user)
    as_user(owner, user, "select api.generate_script(%s)", (pid,))
    runner().tick()
    p = post(owner, pid)
    assert p["status"] == "approved" and p["approved_script_id"] is not None
    s = owner.execute("select approved_by from scripts where id = %s", (p["approved_script_id"],)).fetchone()
    assert s["approved_by"] == "system:auto_approve"
    assert runner().tick()                                   # plan_shots
    assert owner.execute("select count(*) as n from shots where post_id = %s", (pid,)).fetchone()["n"] == 3


def test_invalid_draft_is_repaired_in_the_same_attempt(owner, user):
    FakeWriter.outputs = [_script(seconds=(30,)), _script()]   # 30 s shot is out of range
    pid = new_post(owner, user)
    as_user(owner, user, "select api.generate_script(%s)", (pid,))
    runner().tick()
    assert post(owner, pid)["status"] == "awaiting_approval"
    assert FakeWriter.calls == 2
    fix = FakeWriter.prompts[1]                                 # the draft and what to fix, sent back
    assert "## Your previous draft" in fix and "shot 1 is 30s; make it 3-12s" in fix


def test_draft_still_invalid_after_repairs_is_retried(owner, user):
    bad = _script(seconds=(30,))
    FakeWriter.outputs = [bad] * (1 + write_script.REPAIR_ROUNDS) + [_script()]
    pid = new_post(owner, user)
    job = as_user(owner, user, "select (api.generate_script(%s)).id as id", (pid,))
    runner().tick()
    j = owner.execute("select * from jobs where id = %s", (job["id"],)).fetchone()
    assert j["state"] == "queued" and j["error"]["stage"] == "validate"
    assert post(owner, pid)["status"] == "scripting" and FakeWriter.calls == 3
    owner.execute("update jobs set not_before = now() where id = %s", (job["id"],))  # skip backoff
    runner().tick()
    assert post(owner, pid)["status"] == "awaiting_approval"
    assert FakeWriter.calls == 4


def test_writing_again_after_giving_up_runs_again(owner, user):
    """Live bug: the first try died without writing v1, so "Write script" asked for
    write_script:<post>:v1 again, got the dead job back, and the post sat in
    'scripting' with nothing queued."""
    pid = new_post(owner, user)
    job = as_user(owner, user, "select (api.generate_script(%s)).id as id", (pid,))
    owner.execute("update jobs set state = 'dead', attempts = 3, error = '{\"stage\": \"validate\"}' "
                  "where id = %s", (job["id"],))
    owner.execute("update posts set status = 'failed' where id = %s", (pid,))   # as on_give_up does

    again = as_user(owner, user, "select * from api.generate_script(%s)", (pid,))
    assert again["id"] == job["id"]                                   # same work, same row...
    assert (again["state"], again["attempts"], again["error"]) == ("queued", 0, None)   # ...revived
    assert runner().tick()
    assert post(owner, pid)["status"] == "awaiting_approval"


def test_finished_work_is_not_queued_twice(owner, user):
    args = (user, "cpu", "write_script", f"dedupe-test:{uuid.uuid4()}")
    first = owner.execute("select * from private.enqueue_job(%s, %s, %s, %s)", args).fetchone()
    owner.execute("update jobs set state = 'succeeded' where id = %s", (first["id"],))
    second = owner.execute("select * from private.enqueue_job(%s, %s, %s, %s)", args).fetchone()
    assert second["id"] == first["id"] and second["state"] == "succeeded"
    owner.execute("delete from jobs where id = %s", (first["id"],))


def test_missing_key_fails_fast_with_readable_reason(owner, user):
    owner.execute("delete from user_keys where user_id = %s", (user,))
    pid = new_post(owner, user)
    job = as_user(owner, user, "select (api.generate_script(%s)).id as id", (pid,))
    runner().tick()
    j = owner.execute("select state, attempts from jobs where id = %s", (job["id"],)).fetchone()
    assert (j["state"], j["attempts"]) == ("dead", 1)          # no retries burned
    p = post(owner, pid)
    assert p["status"] == "failed"
    assert p["error"]["message"] == "Add your OpenAI API key in Settings."
    assert FakeWriter.calls == 0


def test_retry_after_crash_reuses_written_version(owner, user):
    pid = new_post(owner, user)
    as_user(owner, user, "select api.generate_script(%s)", (pid,))
    runner().tick()
    # Simulate a crash after the script was written but before the job finished:
    # the same version is requested again; no second LLM call may happen.
    owner.execute("update posts set status = 'scripting' where id = %s", (pid,))
    job = db.enqueue(owner, user_id=user, lane="cpu", kind="write_script",
                     dedupe_key=f"retry-{uuid.uuid4()}", payload={"version": 1}, post_id=pid)
    runner().tick()
    assert owner.execute("select result from jobs where id = %s", (job["id"],)).fetchone()["result"]["reused"]
    assert FakeWriter.calls == 1


def test_rejection_note_reaches_the_next_version(owner, user):
    pid = new_post(owner, user)
    as_user(owner, user, "select api.generate_script(%s)", (pid,))
    runner().tick()
    sid = owner.execute("select id from scripts where post_id = %s", (pid,)).fetchone()["id"]
    as_user(owner, user, "select api.reject_script(%s, %s)", (sid, "make the hook funnier"))
    seen = {}

    class Spy(FakeWriter):
        def write(self, *, model, system, user):
            seen["system"] = system
            return super().write(model=model, system=system, user=user)

    write_script.WRITER_FACTORY = Spy
    as_user(owner, user, "select api.generate_script(%s)", (pid,))
    runner().tick()
    assert "make the hook funnier" in seen["system"]
    versions = owner.execute("select version, state from scripts where post_id = %s order by version",
                             (pid,)).fetchall()
    assert [(v["version"], v["state"]) for v in versions] == [(1, "rejected"), (2, "awaiting_approval")]


def test_frames_rounding_is_always_legal():
    for secs in (3, 4.5, 5, 7.3, 8, 12):
        f = plan_shots.frames_for(secs)
        assert f % 8 == 1 and abs((f - 1) / 24 - secs) <= 8 / 24 / 2 + 1e-9



# ── narrated mode (audio_source = 'kokoro') ───────────────────────────────────

def _narrated(audio='Heartbeat thumps, a low whoosh.') -> ScriptOut:
    out = _script(seconds=(8, 8, 8))
    for i, sh in enumerate(out.shots):
        sh.audio = audio
        sh.narration = (f"This is fact number {i + 1}, told to you clearly, with a short pause, "
                        "so that every single word lands on time.")
    return out


def new_narrated_post(owner, uid) -> str:
    slot = date(2032, 1, 1) + timedelta(days=uuid.uuid4().int % 3000)
    return owner.execute("insert into posts (user_id, topic, slot_date, audio_source) "
                         "values (%s, 'what happens if you swallow gum', %s, 'kokoro') returning id",
                         (uid, slot)).fetchone()["id"]


def test_narrated_pipeline_uses_voiceover_prompts(owner, user):
    seen = {}

    class Spy(FakeWriter):
        def write(self, *, model, system, user):
            seen["system"] = system
            return super().write(model=model, system=system, user=user)

    write_script.WRITER_FACTORY = Spy
    FakeWriter.outputs = [_narrated()]
    pid = new_narrated_post(owner, user)
    as_user(owner, user, "select api.generate_script(%s)", (pid,))
    runner().tick()
    assert "single voice-over" in seen["system"]                 # narrated template chosen
    s = owner.execute("select * from scripts where post_id = %s", (pid,)).fetchone()
    assert s["state"] == "awaiting_approval"
    assert all(sh["narration"] for sh in s["shot_plan"])
    as_user(owner, user, "select api.approve_script(%s)", (s["id"],))
    runner().tick()
    shots = owner.execute("select prompt, negative_prompt from shots where post_id = %s", (pid,)).fetchall()
    assert len(shots) == 3
    for sh in shots:
        assert sh["prompt"].endswith(plan_shots.NO_SPEECH)
        assert "speech" in sh["negative_prompt"] and "fact number" not in sh["prompt"]  # narration stays out


def test_narrated_shot_with_dialogue_is_repaired(owner, user):
    FakeWriter.outputs = [_narrated(audio='A man says: "hello there"'), _narrated()]
    pid = new_narrated_post(owner, user)
    as_user(owner, user, "select api.generate_script(%s)", (pid,))
    runner().tick()
    assert post(owner, pid)["status"] == "awaiting_approval"
    assert "sound effects only" in FakeWriter.prompts[1]


def test_narration_must_fit_one_shot_not_the_guessed_seconds(owner, user):
    """Live failure: 27 words "for 7s" was rejected, though the voice sets the length
    and 27 words fit one shot; 35 words do not fit any shot."""
    fits = _narrated()
    fits.shots[1].seconds = 7
    fits.shots[1].narration = " ".join(["word"] * 27)
    FakeWriter.outputs = [fits]
    pid = new_narrated_post(owner, user)
    as_user(owner, user, "select api.generate_script(%s)", (pid,))
    runner().tick()
    assert post(owner, pid)["status"] == "awaiting_approval" and FakeWriter.calls == 1

    too_long = _narrated()
    too_long.shots[2].narration = " ".join(["word"] * 35)
    FakeWriter.outputs = [too_long, _narrated()]
    pid = new_narrated_post(owner, user)
    as_user(owner, user, "select api.generate_script(%s)", (pid,))
    runner().tick()
    assert post(owner, pid)["status"] == "awaiting_approval" and FakeWriter.calls == 3
    assert "shot 3 narration is 35 words but at most 30 fit one shot" in FakeWriter.prompts[2]


def test_prompt_states_the_word_cap(owner, user):
    from corpus.script.llm import narration_word_cap
    system = write_script._system_prompt({}, 40, "", "kokoro", speed=1.1)
    assert f"At most {narration_word_cap(1.1) - 5} words" in system and "{" not in system


# ── Automatic mode (0013) ─────────────────────────────────────────────────────

class FakeReviewer:
    verdicts: list = []
    sources: list[str] = []

    def __init__(self, api_key: str):
        assert api_key == "sk-test-key"

    def review(self, *, model, script, sources):
        FakeReviewer.sources.append(sources)
        return FakeReviewer.verdicts.pop(0), Usage(model=model, input_tokens=50, output_tokens=10)


def test_automatic_mode_holds_what_the_desk_editor_flags_and_renders_the_rest(owner, user, monkeypatch):
    from corpus.script.review import DeskReview
    owner.execute("update app_settings set pipeline_mode = 'auto' where user_id = %s", (user,))
    monkeypatch.setattr(write_script, "REVIEWER_FACTORY", FakeReviewer)
    FakeReviewer.verdicts = [DeskReview(ok=False, issues=["names a minor"]), DeskReview(ok=True, issues=[])]

    held = new_post(owner, user)
    as_user(owner, user, "select api.generate_script(%s)", (held,))
    runner().tick()
    assert post(owner, held)["status"] == "awaiting_approval"            # waits for the owner
    assert owner.execute("select reason from post_events where post_id = %s and actor = 'system:auto'",
                         (held,)).fetchone()["reason"] == "held for your review: names a minor"
    notes = [r["note"] for r in owner.execute("select note from costs where post_id = %s order by id", (held,))]
    assert notes == ["script", "desk review"]

    clean = new_post(owner, user)
    as_user(owner, user, "select api.generate_script(%s)", (clean,))
    runner().tick()                                                      # write_script: reviewed, approved
    assert post(owner, clean)["status"] == "approved"
    runner().tick()                                                      # plan_shots → render, by itself
    assert post(owner, clean)["status"] == "queued_for_render"
    assert owner.execute("select lane from jobs where post_id = %s and kind = 'render_post'",
                         (clean,)).fetchone()["lane"] == "gpu"
    owner.execute("delete from jobs where post_id = %s and kind = 'render_post'", (clean,))
