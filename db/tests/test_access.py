"""Adversarial checks of the web role's access, against a real Postgres.

    worker/.venv/Scripts/python -m pytest db/tests -q

Needs a database with db/migrations applied and corpus_web able to log in:
TEST_DATABASE_URL_OWNER / TEST_DATABASE_URL_WEB (defaults: the local docker
Postgres from the dev setup). Each test runs as `corpus_web` with `app.user_id`
set, exactly like apps/web/lib/db.ts, and tries to get around a gate.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import date, timedelta

import psycopg
import pytest
from psycopg.types.json import Jsonb

OWNER = os.environ.get("TEST_DATABASE_URL_OWNER",
                       "postgres://app_owner:localdev@127.0.0.1:55442/corpus_test")
WEB = os.environ.get("TEST_DATABASE_URL_WEB",
                     "postgres://corpus_web:local-web-pass@127.0.0.1:55442/corpus_test")


@pytest.fixture
def owner():
    with psycopg.connect(OWNER, autocommit=True) as c:
        yield c


def _mk_user(owner) -> str:
    uid = f"test-{uuid.uuid4().hex[:12]}"
    owner.execute('insert into "user" (id, name, email, "emailVerified") values (%s, %s, %s, true)',
                  (uid, uid, f"{uid}@example.test"))
    return uid


@pytest.fixture
def alice(owner):
    uid = _mk_user(owner)
    yield uid
    owner.execute('delete from "user" where id = %s', (uid,))


@pytest.fixture
def bob(owner):
    uid = _mk_user(owner)
    yield uid
    owner.execute('delete from "user" where id = %s', (uid,))


@contextmanager
def web(user_id: str | None):
    """A transaction as corpus_web, scoped to user_id — rolled back afterwards."""
    with psycopg.connect(WEB) as c:
        with c.transaction(force_rollback=True):
            if user_id:
                c.execute("select set_config('app.user_id', %s, true)", (user_id,))
            yield c


def _slot() -> date:
    return date(2030, 1, 1) + timedelta(days=uuid.uuid4().int % 3000)


def _new_post(c, uid: str) -> uuid.UUID:
    return c.execute("insert into posts (user_id, topic, slot_date) values (%s, %s, %s) "
                     "returning id", (uid, "test topic", _slot())).fetchone()[0]


# ── row isolation ─────────────────────────────────────────────────────────────

def test_no_user_sees_nothing_and_cannot_call_api(alice, owner):
    with psycopg.connect(OWNER, autocommit=True) as o:
        o.execute("insert into posts (user_id, topic, slot_date) values (%s, 't', %s)",
                  (alice, _slot()))
    with web(None) as c:
        assert c.execute("select count(*) from posts").fetchone()[0] == 0
    with pytest.raises(psycopg.errors.InvalidAuthorizationSpecification):
        with web(None) as c:
            c.execute("select api.ensure_settings()")


def test_cannot_read_or_create_other_users_rows(alice, bob):
    with web(alice) as c:
        pid = _new_post(c, alice)
        assert c.execute("select count(*) from posts where id = %s", (pid,)).fetchone()[0] == 1
    with web(bob) as c:
        assert c.execute("select count(*) from posts where user_id = %s",
                         (alice,)).fetchone()[0] == 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):   # RLS with-check
        with web(bob) as c:
            _new_post(c, alice)


# ── the approval gate ─────────────────────────────────────────────────────────

def test_cannot_write_lifecycle_columns_on_posts(alice):
    with web(alice) as c:
        pid = _new_post(c, alice)
        c.execute("update posts set topic = 'edited' where id = %s", (pid,))  # intent: fine
    for stmt in ("update posts set status = 'queued_for_render' where id = %s",
                 "update posts set auto_approve = true where id = %s",
                 "update posts set approved_script_id = null where id = %s",
                 "update posts set final_key = 'x' where id = %s"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with web(alice) as c:
                c.execute(stmt, (_new_post(c, alice),))


def test_cannot_insert_post_with_status_or_auto_approve(alice):
    for col, val in (("status", "approved"), ("auto_approve", True)):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with web(alice) as c:
                c.execute(f"insert into posts (user_id, topic, slot_date, {col}) "
                          f"values (%s, 't', %s, %s)", (alice, _slot(), val))


def test_auto_approve_is_snapshotted_from_settings(alice, owner):
    owner.execute("insert into app_settings (user_id, auto_approve) values (%s, true)", (alice,))
    with web(alice) as c:
        pid = _new_post(c, alice)
        assert c.execute("select auto_approve from posts where id = %s", (pid,)).fetchone()[0]


def _script_awaiting(owner, post_id) -> uuid.UUID:
    owner.execute("update posts set status = 'awaiting_approval' where id = %s", (post_id,))
    return owner.execute("insert into scripts (post_id, version, state, title) "
                         "values (%s, 1, 'awaiting_approval', 'v1') returning id",
                         (post_id,)).fetchone()[0]


def test_cannot_self_approve_script_only_via_api(alice, owner):
    with psycopg.connect(OWNER, autocommit=True) as o:
        pid = o.execute("insert into posts (user_id, topic, slot_date) values (%s,'t',%s) "
                        "returning id", (alice, _slot())).fetchone()[0]
        sid = _script_awaiting(o, pid)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with web(alice) as c:
            c.execute("update scripts set state = 'approved' where id = %s", (sid,))
    with web(alice) as c:
        c.execute("update scripts set title = 'better title' where id = %s", (sid,))
        status = c.execute("select status from api.approve_script(%s)", (sid,)).fetchone()[0]
        assert status == "approved"
        kinds = [r[0] for r in c.execute("select kind from jobs where post_id = %s", (pid,))]
        assert kinds == ["plan_shots"]
        events = c.execute("select to_state, actor from post_events where post_id = %s",
                           (pid,)).fetchall()
        assert events == [("approved", f"user:{alice}")]


def test_cannot_approve_someone_elses_script(alice, bob, owner):
    pid = owner.execute("insert into posts (user_id, topic, slot_date) values (%s,'t',%s) "
                        "returning id", (alice, _slot())).fetchone()[0]
    sid = _script_awaiting(owner, pid)
    with pytest.raises(psycopg.errors.NoDataFound):
        with web(bob) as c:
            c.execute("select api.approve_script(%s)", (sid,))


def test_approved_script_text_is_frozen(alice, owner):
    pid = owner.execute("insert into posts (user_id, topic, slot_date) values (%s,'t',%s) "
                        "returning id", (alice, _slot())).fetchone()[0]
    sid = _script_awaiting(owner, pid)
    owner.execute("update scripts set state = 'approved' where id = %s", (sid,))
    with web(alice) as c:
        c.execute("update scripts set title = 'sneaky' where id = %s", (sid,))
        assert c.execute("select title from scripts where id = %s", (sid,)).fetchone()[0] == "v1"


# ── worker-only surfaces ──────────────────────────────────────────────────────

@pytest.mark.parametrize("stmt", [
    "select private.enqueue_job('x','cpu','k','d')",
    "select private.finish_job(gen_random_uuid(),'w','succeeded')",
    "select private.reserve_storage('k', 1, 'other')",
    "insert into jobs (user_id, lane, kind, dedupe_key) values ('x','cpu','k','d')",
    "update jobs set state = 'queued'",
    "update storage_config set cap_bytes = 999999999999",
])
def test_worker_surfaces_are_unreachable(alice, stmt):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with web(alice) as c:
            c.execute(stmt)


def test_key_vault_is_write_only(alice):
    with web(alice) as c:
        c.execute("insert into user_keys (user_id, name, ciphertext) values (%s, 'openai', 'v1.x.y')",
                  (alice,))
        assert c.execute("select name from user_keys").fetchall() == [("openai",)]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with web(alice) as c:
            c.execute("insert into user_keys (user_id, name, ciphertext) values (%s, 'k', 'v1.x.y')",
                      (alice,))
            c.execute("select ciphertext from user_keys")


# ── storage cap ───────────────────────────────────────────────────────────────

def test_storage_cap_refuses_and_alerts_then_clears(owner):
    # Real media may use the cap minus the idea-card budget (0013).
    cap = owner.execute("select cap_bytes - idea_media_cap_bytes from storage_config").fetchone()[0]
    used = owner.execute("""select coalesce(sum(bytes), 0)::bigint from storage_objects
                             where state in ('reserved','stored') and kind <> 'idea_media'""").fetchone()[0]
    k1, k2 = f"t/{uuid.uuid4()}", f"t/{uuid.uuid4()}"
    try:
        ok = owner.execute("select ok from private.reserve_storage(%s, %s, 'other')",
                           (k1, cap - used - 10)).fetchone()[0]
        assert ok
        ok = owner.execute("select ok from private.reserve_storage(%s, 11, 'other')",
                           (k2,)).fetchone()[0]
        assert not ok
        # The refusal must survive its own transaction: it is what drives the alert.
        assert owner.execute("select full_since from storage_config").fetchone()[0] is not None
        assert owner.execute("select count(*) from storage_objects where key = %s",
                             (k2,)).fetchone()[0] == 0
        owner.execute("select private.commit_storage(%s, %s)", (k1, cap - used - 10))
        owner.execute("select private.mark_storage_deleted(%s)", (k1,))
        assert owner.execute("select full_since from storage_config").fetchone()[0] is None
        # Re-reserving the same key replaces itself rather than double counting.
        owner.execute("select private.reserve_storage(%s, %s, 'other')", (k2, cap - used))
        owner.execute("select private.reserve_storage(%s, %s, 'other')", (k2, cap - used))
    finally:
        owner.execute("delete from storage_objects where key in (%s, %s)", (k1, k2))
        owner.execute("update storage_config set full_since = null")


# ── queue ─────────────────────────────────────────────────────────────────────

def test_version_gate_is_exact_match(alice, owner):
    w = f"test-worker-{uuid.uuid4().hex[:6]}"
    key = f"test:{uuid.uuid4()}"
    try:
        owner.execute("select private.worker_ping(%s, 'publish', 'abc123')", (w,))
        owner.execute("select private.enqueue_job(%s, 'publish', 'noop', %s)", (alice, key))
        owner.execute("update lane_config set required_version = 'fff999' where lane = 'publish'")
        # 'abc123' < 'fff999' as strings — the draft's `<` check would have
        # refused this for the wrong reason and admitted 'zzz' for the wrong one.
        got = owner.execute("select (private.claim_job(%s,'publish','zzz')).id", (w,)).fetchone()[0]
        assert got is None
        got = owner.execute("select (private.claim_job(%s,'publish','fff999')).id", (w,)).fetchone()[0]
        assert got is not None
    finally:
        owner.execute("update lane_config set required_version = '' where lane = 'publish'")
        owner.execute("delete from jobs where dedupe_key = %s", (key,))
        owner.execute("delete from workers where id = %s", (w,))


# ── VibeDB specifics ──────────────────────────────────────────────────────────

APP = os.environ.get("TEST_DATABASE_URL_APP",
                     "postgres://corpus_test_app:localdev@127.0.0.1:55442/corpus_test")


@pytest.mark.parametrize("stmt", [
    "select count(*) from posts",
    'select count(*) from "session"',
    'select password from "account"',
    "select ciphertext from user_keys",
    "select private.finish_job(gen_random_uuid(), 'w', 'succeeded')",
    "select api.ensure_settings()",
    "insert into jobs (user_id, lane, kind, dedupe_key) values ('x','cpu','k','d')",
])
def test_vibedb_app_role_has_no_access(stmt):
    """VibeDB's per-project app role gets default privileges on everything the
    owner creates; db/access.sql must have taken all of it back."""
    try:
        conn = psycopg.connect(APP)
    except psycopg.OperationalError:
        pytest.skip("no VibeDB-style app role in this test database")
    with conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(stmt)


def test_policies_name_no_role(owner):
    """VibeDB backups restore into Neon with --no-acl, where corpus_web does not
    exist; a policy naming it would fail every backup run."""
    named = owner.execute(
        "select tablename, policyname, roles from pg_policies where roles <> '{public}'").fetchall()
    assert named == []


def test_access_sql_is_repeatable(owner):
    from pathlib import Path
    sql_text = (Path(__file__).resolve().parents[1] / "access.sql").read_text(encoding="utf-8")
    with owner.transaction():
        owner.execute(sql_text)
    with owner.transaction():
        owner.execute(sql_text)


def test_key_vault_upsert_as_web(alice, owner):
    """The exact statement Settings → OpenAI key runs. It must work twice (insert,
    then replace) without the web role ever being able to read the ciphertext."""
    upsert = ("insert into user_keys (user_id, name, ciphertext, updated_at) "
              "values (%(u)s, 'openai', %(ct)s, now()) "
              "on conflict (user_id, name) do update set ciphertext = %(ct)s, updated_at = now()")
    with psycopg.connect(WEB) as c:
        c.execute("select set_config('app.user_id', %s, false)", (alice,))
        c.execute(upsert, {"u": alice, "ct": "v1.first.key"})
        c.execute(upsert, {"u": alice, "ct": "v1.second.key"})
        c.commit()
    got = owner.execute("select ciphertext from user_keys where user_id = %s and name = 'openai'",
                        (alice,)).fetchone()[0]
    assert got == "v1.second.key"


# ── channels, prompt library, ideas, connected accounts (0011) ─────────────────

def _new_channel(c, uid: str, name: str = "Cutaway") -> uuid.UUID:
    return c.execute("insert into channels (user_id, name) values (%s, %s) returning id",
                     (uid, name)).fetchone()[0]


def _new_format(c, uid: str, name: str = "3D explainer", channel=None) -> uuid.UUID:
    channel = channel or _new_channel(c, uid, f"ch-{uuid.uuid4().hex[:6]}")
    return c.execute("""insert into formats (user_id, channel_id, name, idea_prompt, script_prompt, visual_style)
                        values (%s, %s, %s, 'ideas v1', 'script v1', 'look v1') returning id""",
                     (uid, channel, name)).fetchone()[0]


def test_format_edits_keep_history_and_can_be_restored(alice):
    with web(alice) as c:
        fid = _new_format(c, alice)
        c.execute("update formats set script_prompt = 'script v2' where id = %s", (fid,))
        c.execute("update formats set description = 'only a label' where id = %s", (fid,))  # not a new version
        assert c.execute("select version from formats where id = %s", (fid,)).fetchone()[0] == 2
        assert c.execute("select snapshot->>'script_prompt' from format_versions where format_id = %s "
                         "and version = 1", (fid,)).fetchone()[0] == "script v1"
        c.execute("select api.restore_format_version(%s, 1)", (fid,))
        row = c.execute("select script_prompt, version from formats where id = %s", (fid,)).fetchone()
        assert row == ("script v1", 3)                                # v2 itself is kept as a version


@pytest.mark.parametrize("stmt", [
    "update formats set version = 99 where id = %s",
    "update formats set is_default = true where id = %s",
    "insert into format_versions (format_id, version, snapshot) values (%s, 5, '{}')",
    "update ideas set status = 'accepted' where format_id = %s",
    "update channels set is_default = true where id = (select channel_id from formats where id = %s)",
])
def test_bookkeeping_columns_are_not_writable(alice, stmt):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with web(alice) as c:
            c.execute(stmt, (_new_format(c, alice),))


def test_cannot_put_a_format_on_someone_elses_channel(alice, bob, owner):
    with psycopg.connect(OWNER, autocommit=True) as o:
        theirs = o.execute("insert into channels (user_id, name) values (%s, 'theirs') returning id",
                           (bob,)).fetchone()[0]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):    # RLS with-check
        with web(alice) as c:
            _new_format(c, alice, channel=theirs)


def test_defaults_are_switched_only_through_api(alice):
    with web(alice) as c:
        ch = _new_channel(c, alice)
        a, b = _new_format(c, alice, "A", ch), _new_format(c, alice, "B", ch)
        c.execute("select api.set_default_format(%s)", (a,))
        c.execute("select api.set_default_format(%s)", (b,))
        assert c.execute("select array_agg(id) from formats where is_default").fetchone()[0] == [b]
        other = _new_channel(c, alice, "Second")
        c.execute("select api.set_default_channel(%s)", (ch,))
        c.execute("select api.set_default_channel(%s)", (other,))
        assert c.execute("select array_agg(id) from channels where is_default").fetchone()[0] == [other]


def test_account_tokens_are_write_only(alice):
    with web(alice) as c:
        ch = _new_channel(c, alice)
        c.execute("""insert into channel_accounts (user_id, channel_id, platform, external_id, handle,
                                                   token_ciphertext) values (%s, %s, 'youtube', 'UC1', '@me', 'v1.x.y')""",
                  (alice, ch))
        assert c.execute("select handle from channel_accounts where channel_id = %s", (ch,)).fetchone()[0] == "@me"
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with web(alice) as c:
            c.execute("select token_ciphertext from channel_accounts")


def test_swiping_schedules_a_post_or_records_why_not(alice, owner):
    with psycopg.connect(OWNER, autocommit=True) as o:       # ideas are written by the worker
        o.execute("insert into app_settings (user_id) values (%s)", (alice,))
        ch = o.execute("insert into channels (user_id, name, timezone) values (%s, 'c', 'Asia/Kolkata') "
                       "returning id", (alice,)).fetchone()[0]
        fid = o.execute("insert into formats (user_id, channel_id, name, idea_prompt, script_prompt) "
                        "values (%s, %s, 'f', 'i', 's') returning id", (alice, ch)).fetchone()[0]
        ids = [o.execute("insert into ideas (user_id, channel_id, format_id, title, hook, brief) values "
                         "(%s, %s, %s, %s, 'A hook.', 'A brief.') returning id", (alice, ch, fid, t)).fetchone()[0]
               for t in ("Why is the sky blue?", "Gum stays 7 years?")]
    with web(alice) as c:
        two_same_day = ["2031-05-04 18:30+05:30", "2031-05-04 21:00+05:30"]
        c.execute("select api.decide_idea(%s, true, %s)", (ids[0], two_same_day[0]))
        c.execute("select api.decide_idea(%s, false, null, %s)", (ids[1], " done before "))
        post = c.execute("select p.topic, p.slot_date::text, p.format_id, p.channel_id, p.brief from ideas i "
                         "join posts p on p.id = i.post_id where i.id = %s", (ids[0],)).fetchone()
        assert post[:4] == ("Why is the sky blue?", "2031-05-04", fid, ch) and "Hook: A hook." in post[4]
        assert c.execute("select status, reject_reason from ideas where id = %s",
                         (ids[1],)).fetchone() == ("rejected", "done before")
        c.execute("insert into posts (user_id, topic, slot_date, publish_at) values (%s, 'same day', "
                  "'2031-05-04', %s)", (alice, two_same_day[1]))            # many posts per day
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            c.execute("select api.decide_idea(%s, true, now())", (ids[0],))  # no second swipe


def test_daily_ideas_are_scheduled_once_per_category_per_day(alice, owner):
    with psycopg.connect(OWNER, autocommit=True) as o:
        ch = o.execute("insert into channels (user_id, name) values (%s, 'daily') returning id",
                       (alice,)).fetchone()[0]
        o.execute("insert into formats (user_id, channel_id, name, idea_prompt, script_prompt, is_default) "
                  "values (%s, %s, 'daily', 'i', 's', true)", (alice, ch))             # brings "General"
        o.execute("insert into categories (user_id, channel_id, name) values (%s, %s, 'World')", (alice, ch))
        o.execute("insert into categories (user_id, channel_id, name, enabled) values (%s, %s, 'Off', false)",
                  (alice, ch))
        o.execute("select private.schedule_daily_ideas()")
        o.execute("select private.schedule_daily_ideas()")
        jobs = o.execute("""select k.name, j.lane, j.state, j.payload->>'trigger', j.not_before
                              from jobs j join categories k on k.id::text = j.payload->>'category_id'
                             where j.kind = 'suggest_ideas' and k.channel_id = %s order by j.not_before""",
                         (ch,)).fetchall()
        assert [(n, lane, st, t) for n, lane, st, t, _ in jobs] == [
            ("General", "ideas", "queued", "daily"), ("World", "ideas", "queued", "daily")]
        assert (jobs[1][4] - jobs[0][4]).total_seconds() == 180                    # staggered


# ── publishing (0012) ─────────────────────────────────────────────────────────

@contextmanager
def web_session(user_id: str):
    """corpus_web with each statement committed — for steps the worker (another
    connection) has to see."""
    with psycopg.connect(WEB, autocommit=True) as c:
        c.execute("select set_config('app.user_id', %s, false)", (user_id,))
        yield c


def _finished_post(o, uid: str, *, platforms=("youtube",)) -> tuple[uuid.UUID, uuid.UUID]:
    """A post with its reel assembled, on a channel with `platforms` connected."""
    ch = o.execute("insert into channels (user_id, name) values (%s, %s) returning id",
                   (uid, f"ch-{uuid.uuid4().hex[:6]}")).fetchone()[0]
    for pf in platforms:
        o.execute("""insert into channel_accounts (user_id, channel_id, platform, external_id, token_ciphertext)
                     values (%s, %s, %s, 'ext', 'v1.x.y')""", (uid, ch, pf))
    pid = o.execute("""insert into posts (user_id, channel_id, topic, slot_date, publish_at)
                       values (%s, %s, 'reel', %s, now() + interval '3 days') returning id""",
                    (uid, ch, _slot())).fetchone()[0]
    o.execute("update posts set status = 'ready', final_key = 'k/final.mp4' where id = %s", (pid,))
    return pid, ch


def _post_status(o, pid) -> str:
    return o.execute("select status from posts where id = %s", (pid,)).fetchone()[0]


def _publish_job(o, pid, pf="youtube"):
    return o.execute("select state, not_before, payload from jobs where dedupe_key = %s",
                     (f"publish:{pid}:{pf}",)).fetchone()


def test_publishing_follows_its_jobs_and_never_posts_twice(alice, owner):
    pid, _ = _finished_post(owner, alice)
    with web_session(alice) as c:
        c.execute("select api.request_publish(%s, array['youtube'], now() + interval '2 days', 'unlisted')", (pid,))
        state, at, payload = _publish_job(owner, pid)
        assert state == "queued" and payload == {"platform": "youtube", "privacy": "unlisted"}
        assert _post_status(owner, pid) == "scheduled"

        c.execute("select api.request_publish(%s, array['youtube'])", (pid,))       # now, instead
        state, now_at, _ = _publish_job(owner, pid)
        assert state == "queued" and now_at < at                                     # same job, moved
        assert owner.execute("select count(*) from jobs where post_id = %s", (pid,)).fetchone()[0] == 1

        c.execute("select api.cancel_publish(%s, 'youtube')", (pid,))
        assert _publish_job(owner, pid)[0] == "cancelled" and _post_status(owner, pid) == "ready"

        c.execute("select api.request_publish(%s, array['youtube'])", (pid,))       # revived
        assert _post_status(owner, pid) == "scheduled"
        # The worker posts it: a live attempt, then the job succeeds.
        owner.execute("insert into publish_attempts (post_id, platform, state, remote_id) "
                      "values (%s, 'youtube', 'live', 'vid1')", (pid,))
        owner.execute("update jobs set state = 'succeeded' where dedupe_key = %s", (f"publish:{pid}:youtube",))
        assert _post_status(owner, pid) == "published"

        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="already posted on YouTube"):
            c.execute("select api.request_publish(%s, array['youtube'])", (pid,))
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="nothing is waiting"):
            c.execute("select api.cancel_publish(%s, 'youtube')", (pid,))


def test_an_unknown_outcome_waits_for_a_human_then_can_run_again(alice, owner):
    pid, _ = _finished_post(owner, alice)
    with web_session(alice) as c:
        c.execute("select api.request_publish(%s, array['youtube'])", (pid,))
        owner.execute("update jobs set state = 'needs_review' where dedupe_key = %s", (f"publish:{pid}:youtube",))
        assert _post_status(owner, pid) == "needs_review"
        c.execute("select api.request_publish(%s, array['youtube'])", (pid,))
        assert _publish_job(owner, pid)[0] == "queued" and _post_status(owner, pid) == "scheduled"


@pytest.mark.parametrize("platforms, at, privacy, error", [
    (["instagram"], None, None, "connect Instagram to this channel first"),
    ([], None, None, "choose where to post"),
    (["tiktok"], None, None, "unknown platform"),
    (["youtube"], None, "secret", "visibility must be"),
    (["youtube"], "2099-01-01T00:00:00Z", None, "within the next 180 days"),
])
def test_publish_requests_are_checked(alice, owner, platforms, at, privacy, error):
    pid, _ = _finished_post(owner, alice)
    with pytest.raises(psycopg.Error, match=error):
        with web(alice) as c:
            c.execute("select api.request_publish(%s, %s::text[], %s, %s)", (pid, platforms, at, privacy))


def test_only_a_finished_reel_of_your_own_can_be_posted(alice, bob, owner):
    pid, _ = _finished_post(owner, alice)
    with pytest.raises(psycopg.errors.NoDataFound):                    # not bob's post
        with web(bob) as c:
            c.execute("select api.request_publish(%s, array['youtube'])", (pid,))
    owner.execute("update posts set status = 'approved' where id = %s", (pid,))
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="only a finished reel"):
        with web(alice) as c:
            c.execute("select api.request_publish(%s, array['youtube'])", (pid,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):          # jobs only through the api
        with web(alice) as c:
            c.execute("insert into jobs (user_id, lane, kind, dedupe_key) values (%s, 'publish', 'publish_post', 'x')",
                      (alice,))


# ── categories, costs, Manual/Automatic (0013) ────────────────────────────────

def test_a_first_format_brings_a_general_category_with_its_sources(alice, owner):
    sources = [{"name": "TIL", "url": "https://www.reddit.com/r/todayilearned+space/top/.rss?t=day"},
               {"name": "Trends", "url": "https://trends.google.com/trending/rss?geo=IN"},
               {"name": "Wiki", "url": "https://api.wikimedia.org/feed/v1/wikipedia/en/featured/{yesterday}"},
               {"name": "NASA", "url": "https://www.nasa.gov/news-release/feed/"}]
    with psycopg.connect(OWNER, autocommit=True) as o:
        ch = o.execute("insert into channels (user_id, name) values (%s, 'fresh') returning id", (alice,)).fetchone()[0]
        fid = o.execute("insert into formats (user_id, channel_id, name, idea_prompt, script_prompt, sources) "
                        "values (%s, %s, 'f', 'i', 's', %s) returning id",
                        (alice, ch, Jsonb(sources))).fetchone()[0]
        cat = o.execute("select id, name, format_id from categories where channel_id = %s", (ch,)).fetchall()
        assert [(n, f) for _, n, f in cat] == [("General", fid)]
        got = o.execute("select kind, value, options from category_sources where category_id = %s order by kind, value",
                        (cat[0][0],)).fetchall()
        assert got == [("google_trends", "IN", {}),
                       ("reddit", "space", {"sort": "top", "t": "day"}),
                       ("reddit", "todayilearned", {"sort": "top", "t": "day"}),
                       ("rss", "https://www.nasa.gov/news-release/feed/", {"name": "NASA"}),
                       ("wikipedia", "en", {})]


def test_categories_belong_to_their_channel_and_owner(alice, bob, owner):
    with psycopg.connect(OWNER, autocommit=True) as o:
        theirs = o.execute("insert into channels (user_id, name) values (%s, 'theirs') returning id",
                           (bob,)).fetchone()[0]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):            # RLS: not your channel
        with web(alice) as c:
            c.execute("insert into categories (user_id, channel_id, name) values (%s, %s, 'x')", (alice, theirs))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):              # a format of another channel
        with web(alice) as c:
            a, b = _new_channel(c, alice, "A"), _new_channel(c, alice, "B")
            f = _new_format(c, alice, "fa", a)
            c.execute("insert into categories (user_id, channel_id, name, format_id) values (%s, %s, 'x', %s)",
                      (alice, b, f))
    with pytest.raises(psycopg.errors.CheckViolation):                   # reddit only via the limiter
        with web(alice) as c:
            k = c.execute("insert into categories (user_id, channel_id, name) values (%s, %s, 'x') returning id",
                          (alice, _new_channel(c, alice))).fetchone()[0]
            c.execute("insert into category_sources (user_id, category_id, kind, value) "
                      "values (%s, %s, 'rss', 'https://old.reddit.com/r/news/.rss')", (alice, k))


@pytest.mark.parametrize("kind,value,ok", [
    ("bluesky", "whats-hot", True), ("bluesky", "https://bsky.app/profile/someone.test/feed/science", True),
    ("bluesky", "https://evil.test/feed/x", False),
    ("mastodon", "mastodon.social", True), ("mastodon", "#science@fosstodon.org", True), ("mastodon", "#x", False),
    ("lemmy", "technology@lemmy.world", True), ("lemmy", "lemmy.world", True), ("lemmy", "http://lemmy.world/", False),
    ("hackernews", "front_page", True), ("youtube", "IN:28", True), ("youtube", "india", False),
])
def test_open_sources_take_only_their_own_shape_of_value(alice, kind, value, ok):   # 0015
    def add():
        with web(alice) as c:
            k = c.execute("insert into categories (user_id, channel_id, name) values (%s, %s, 'x') returning id",
                          (alice, _new_channel(c, alice))).fetchone()[0]
            c.execute("insert into category_sources (user_id, category_id, kind, value) values (%s, %s, %s, %s)",
                      (alice, k, kind, value))
    if ok:
        add()
    else:
        with pytest.raises(psycopg.errors.CheckViolation):
            add()


@pytest.mark.parametrize("stmt", [
    "update category_sources set status = 'ok', last_items = 9 where user_id = %s",
    "insert into costs (user_id, kind, provider) values (%s, 'llm', 'openai')",
    "update posts set pipeline_mode = 'auto' where user_id = %s",
    "update posts set media_choice = 'original' where user_id = %s",
    "insert into fx_rates (day, usd_inr, source) select current_date + 1000, 1, %s",
])
def test_ledger_and_lifecycle_columns_are_not_writable(alice, stmt):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with web(alice) as c:
            c.execute(stmt, (alice,))


def _channel_with_idea(o, uid, *, connected=("youtube",)):
    ch = o.execute("insert into channels (user_id, name) values (%s, %s) returning id",
                   (uid, f"c-{uuid.uuid4().hex[:6]}")).fetchone()[0]
    fid = o.execute("insert into formats (user_id, channel_id, name, idea_prompt, script_prompt, is_default) "
                    "values (%s, %s, 'f', 'i', 's', true) returning id", (uid, ch)).fetchone()[0]
    cat = o.execute("select id from categories where channel_id = %s", (ch,)).fetchone()[0]
    for pf in connected:
        o.execute("""insert into channel_accounts (user_id, channel_id, platform, external_id, token_ciphertext)
                     values (%s, %s, %s, 'ext', 'v1.x.y')""", (uid, ch, pf))
    idea = o.execute("insert into ideas (user_id, channel_id, format_id, category_id, title, brief) "
                     "values (%s, %s, %s, %s, 'A story', 'Brief.') returning id", (uid, ch, fid, cat)).fetchone()[0]
    return ch, cat, idea


def test_automatic_mode_starts_the_script_when_you_swipe(alice, owner):
    with psycopg.connect(OWNER, autocommit=True) as o:
        o.execute("insert into app_settings (user_id, pipeline_mode) values (%s, 'auto')", (alice,))
        _, cat, idea = _channel_with_idea(o, alice, connected=("youtube", "instagram"))
    with web(alice) as c:
        c.execute("select api.decide_idea_v2(%s, true, now() + interval '1 day')", (idea,))
        post = c.execute("""select p.pipeline_mode, p.auto_approve, p.status, p.category_id, p.platforms
                              from ideas i join posts p on p.id = i.post_id where i.id = %s""", (idea,)).fetchone()
        assert post == ("auto", True, "scripting", cat, ["instagram", "youtube"])
        assert c.execute("""select count(*) from jobs j join ideas i on i.post_id = j.post_id
                             where i.id = %s and j.kind = 'write_script'""", (idea,)).fetchone()[0] == 1


def test_manual_mode_waits_and_the_snapshot_cannot_be_changed_later(alice, owner):
    with psycopg.connect(OWNER, autocommit=True) as o:
        o.execute("insert into app_settings (user_id) values (%s)", (alice,))
        _, _, idea = _channel_with_idea(o, alice)
    with web(alice) as c:
        c.execute("select api.decide_idea_v2(%s, true, now() + interval '1 day', null, array['youtube'])", (idea,))
        pid = c.execute("select post_id from ideas where id = %s", (idea,)).fetchone()[0]
        assert c.execute("select pipeline_mode, auto_approve, status from posts where id = %s",
                         (pid,)).fetchone() == ("manual", False, "draft")
        c.execute("update app_settings set pipeline_mode = 'auto'")              # flipping it later...
        assert c.execute("select pipeline_mode from posts where id = %s", (pid,)).fetchone()[0] == "manual"


def test_the_daily_spend_cap_stops_automatic_renders_only(alice, owner):
    with psycopg.connect(OWNER, autocommit=True) as o:
        o.execute("insert into app_settings (user_id, auto_spend_cap_paise_day) values (%s, 10000)", (alice,))
        pid = o.execute("insert into posts (user_id, topic, slot_date) values (%s, 't', %s) returning id",
                        (alice, _slot())).fetchone()[0]
        sid = o.execute("insert into scripts (post_id, version, state) values (%s, 1, 'approved') returning id",
                        (pid,)).fetchone()[0]
        o.execute("update posts set status = 'approved', approved_script_id = %s, audio_source = 'ltx_native' "
                  "where id = %s", (sid, pid))
        o.execute("""insert into shots (post_id, script_id, idx, prompt, seed, width, height, num_frames)
                     values (%s, %s, 0, 'p', 1, 704, 1280, 121)""", (pid, sid))
        o.execute("insert into costs (user_id, kind, provider, inr_paise) values (%s, 'gpu', 'race', 12000)", (alice,))
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="spending limit"):
            o.execute("select private.request_render(%s, 'system:auto')", (pid,))
    with web(alice) as c:                                                      # by hand it still works
        assert c.execute("select (api.request_render(%s)).kind", (pid,)).fetchone()[0] == "render_post"


def test_category_idea_batches_are_yours_alone(alice, bob, owner):
    with psycopg.connect(OWNER, autocommit=True) as o:
        _, cat, _ = _channel_with_idea(o, alice)
    with web(alice) as c:
        j = c.execute("select lane, kind, payload->>'category_id' from api.request_category_ideas(%s)",
                      (cat,)).fetchone()
        assert j == ("ideas", "suggest_ideas", str(cat))
    with pytest.raises(psycopg.errors.NoDataFound):
        with web(bob) as c:
            c.execute("select api.request_category_ideas(%s)", (cat,))


def test_refreshing_models_is_a_job_for_the_ideas_worker(alice, owner):
    with web(alice) as c:
        c.execute("select api.ensure_settings()")
        assert c.execute("select lane, kind from api.refresh_openai_models()").fetchone() == ("ideas", "refresh_models")


# ── footage (0016) ────────────────────────────────────────────────────────────

def _post_with_asset(o, uid: str) -> tuple[uuid.UUID, uuid.UUID]:
    pid = o.execute("insert into posts (user_id, topic, slot_date) values (%s, 'footage', '2031-02-02') returning id",
                    (uid,)).fetchone()[0]
    aid = o.execute("""insert into assets (user_id, post_id, n, kind, origin, credit, rights, state)
                       values (%s, %s, 1, 'video', 'reddit', 'u/a on r/b', 'approved', 'ready') returning id""",
                    (uid, pid)).fetchone()[0]
    return pid, aid


def test_the_owner_may_withdraw_footage_but_not_forge_it(alice, bob, owner):
    pid, aid = _post_with_asset(owner, alice)
    with web(alice) as c:
        assert c.execute("update assets set rights = 'rejected' where id = %s returning rights",
                         (aid,)).fetchone() == ("rejected",)
    with web(bob) as c:                                                  # not bob's footage
        assert c.execute("update assets set rights = 'rejected' where id = %s returning id", (aid,)).fetchone() is None
    for stmt in ("update assets set state = 'ready', key = 'x' where id = %s",
                 "update assets set credit = '' where id = %s",
                 "insert into assets (user_id, post_id, n, kind, origin) select user_id, post_id, 9, 'video', 'x' "
                 "from assets where id = %s"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with web(alice) as c:
                c.execute(stmt, (aid,))


def test_ltx_frame_rules_bind_generated_shots_only(alice, owner):
    pid, aid = _post_with_asset(owner, alice)
    sid = owner.execute("insert into scripts (post_id, version, state) values (%s, 1, 'approved') returning id",
                        (pid,)).fetchone()[0]
    owner.execute("""insert into shots (post_id, script_id, idx, prompt, seed, width, height, num_frames, source, asset_id)
                     values (%s, %s, 0, 'clip', 0, 1080, 1920, 66, 'clip', %s)""", (pid, sid, aid))
    with pytest.raises(psycopg.errors.CheckViolation):
        owner.execute("""insert into shots (post_id, script_id, idx, prompt, seed, width, height, num_frames)
                         values (%s, %s, 1, 'generated', 1, 1080, 1920, 66)""", (pid, sid))


# ── members (0019) ────────────────────────────────────────────────────────────

def test_a_new_account_waits_for_an_owner_who_sets_its_limit(owner):
    owner.execute("update app_config set signups_need_approval = true")
    try:
        boss, new = _mk_user(owner), _mk_user(owner)
    finally:
        owner.execute("update app_config set signups_need_approval = false")
    member = _mk_user(owner)                                            # approval off: active at once
    owner.execute("update memberships set role = 'owner', status = 'active' where user_id = %s", (boss,))
    try:
        got = owner.execute("select role, status from memberships where user_id = any(%s) order by status",
                            ([new, member],)).fetchall()
        assert got == [("member", "active"), ("member", "pending")]
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="this account is pending"):
            with web(new) as c:
                c.execute("select api.ensure_settings()")
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="only the owner"):
            with web(member) as c:
                c.execute("select * from api.admin_members()")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):       # no writing one's own membership
            with web(member) as c:
                c.execute("update memberships set role = 'owner' where user_id = %s", (member,))
        with web_session(boss) as c:
            listed = {r[0]: r[4] for r in c.execute("select * from api.admin_members()").fetchall()}
            assert listed[new] == "pending" and listed[boss] == "active"
            c.execute("select api.admin_set_member(%s, 'active', 0)", (new,))          # in, with ₹0 a month
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="AUTH_ALLOWED_EMAILS"):
                c.execute("select api.admin_set_member(%s, 'suspended', null)", (boss,))
        pid = owner.execute("insert into posts (user_id, topic, slot_date) values (%s, 't', '2032-03-03') "
                            "returning id", (new,)).fetchone()[0]
        with web(new) as c:
            c.execute("select api.ensure_settings()")                   # active now
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="spending limit"):
            with web(new) as c:
                c.execute("select api.generate_script(%s)", (pid,))
    finally:
        for u in (boss, new, member):
            owner.execute('delete from "user" where id = %s', (u,))


def test_a_channel_goes_with_its_posts_even_the_default_one(alice, owner):
    """What the web app's deleteChannel does, as the web role (refinement, 2026-10-17)."""
    a = owner.execute("insert into channels (user_id, name, is_default) values (%s, 'A', true) returning id",
                      (alice,)).fetchone()[0]
    b = owner.execute("insert into channels (user_id, name) values (%s, 'B') returning id", (alice,)).fetchone()[0]
    owner.execute("insert into posts (user_id, channel_id, topic, slot_date) values (%s, %s, 't', '2032-05-05')",
                  (alice, a))
    with web_session(alice) as c:
        c.execute("select api.set_default_channel(%s)", (b,))            # the default moves first
        c.execute("delete from posts where channel_id = %s", (a,))
        c.execute("delete from channels where id = %s", (a,))
        assert c.execute("select name, is_default from channels").fetchall() == [("B", True)]
        assert c.execute("select count(*) from posts").fetchone()[0] == 0
