"""Apply db/migrations/*.sql in order, then re-apply db/access.sql. From the repo root:

    worker/.venv/Scripts/python db/migrate.py            # apply pending + access
    worker/.venv/Scripts/python db/migrate.py --status   # list, change nothing

Connects with DATABASE_URL_UNPOOLED — the owner role's *direct* URL (port 5432
on VibeDB), because DDL does not belong behind a transaction pooler. Each
migration runs in its own transaction and is recorded with its sha256; a file
that changed after being applied is reported, never silently re-run. Fix
forward with a new migration instead.

db/access.sql (grants, revokes) is repeatable and runs after every migrate,
including right after restoring a database from a VibeDB/Neon backup, which by
design carries no grants. That is the whole restore procedure for permissions.

Local development only: if CORPUS_WEB_PASSWORD is set, corpus_web is given
LOGIN with it. On VibeDB the control plane owns that role and its password
(`vibedb project credentials <project> --role corpus_web`), so leave it unset.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "db" / "migrations"
ACCESS = ROOT / "db" / "access.sql"


def web_role_name() -> str:
    """The web app's role. Normally corpus_web; configurable because role names
    are cluster-wide on VibeDB, so a project restored from backup next to the
    original (or its soft-deleted remains) needs a role of its own."""
    name = os.environ.get("CORPUS_WEB_ROLE", "corpus_web").strip()
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", name):
        raise SystemExit(f"CORPUS_WEB_ROLE must be a plain lowercase identifier, got {name!r}")
    return name


def access_sql(web_role: str) -> str:
    # Policies name no role (0004_rls.sql), so access.sql is the only place the
    # web role's name appears; substitute it as a whole word.
    return re.sub(r"\bcorpus_web\b", web_role, ACCESS.read_text(encoding="utf-8"))


def main() -> int:
    load_dotenv(ROOT / ".env")
    url = (os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get("DATABASE_URL_OWNER") or "").strip()
    if not url:
        print("DATABASE_URL_UNPOOLED is not set (the owner's direct URL, not the pooler)")
        return 2
    status_only = "--status" in sys.argv

    files = sorted(MIGRATIONS.glob("*.sql"))
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("""
            create table if not exists public.schema_migrations (
              name       text primary key,
              sha256     text not null,
              applied_at timestamptz not null default now()
            )""")
        applied = dict(conn.execute("select name, sha256 from public.schema_migrations").fetchall())

        pending = []
        for f in files:
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            if f.name not in applied:
                pending.append((f, digest))
                print(f"  pending   {f.name}")
            elif applied[f.name] != digest:
                print(f"  CHANGED   {f.name}  (applied version differs; add a new migration)")
            else:
                print(f"  applied   {f.name}")
        if status_only:
            return 0

        for f, digest in pending:
            with conn.transaction():
                conn.execute(f.read_text(encoding="utf-8"))
                conn.execute("insert into public.schema_migrations (name, sha256) values (%s, %s)",
                             (f.name, digest))
            print(f"  -> applied {f.name}")

        web_role = web_role_name()
        with conn.transaction():
            conn.execute(access_sql(web_role))
        print(f"  -> access.sql re-applied (web role: {web_role})")

        pw = os.environ.get("CORPUS_WEB_PASSWORD", "").strip()
        if pw:
            try:
                conn.execute(sql.SQL("alter role {} login password {}").format(
                    sql.Identifier(web_role), sql.Literal(pw)))
                print(f"  {web_role}: login enabled with CORPUS_WEB_PASSWORD (local dev)")
            except psycopg.errors.InsufficientPrivilege:
                print(f"  {web_role}: password not changed — this server manages it "
                      f"(VibeDB: vibedb project credentials <project> --role {web_role})")
    print(f"done: {len(pending)} migration(s) applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
