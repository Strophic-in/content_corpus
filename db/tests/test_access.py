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
    cap = owner.execute("select cap_bytes from storage_config").fetchone()[0]
    used = owner.execute("select private.storage_used()").fetchone()[0]
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
