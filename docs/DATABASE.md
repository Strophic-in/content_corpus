# Database — VibeDB

content_corpus runs on a **VibeDB** project (our self-hosted PostgreSQL 18 behind
PgBouncer; see `../vibeDB`). Two roles touch it:

| Role | Used by | Connects to | Rights |
|---|---|---|---|
| project owner (`content_corpus_owner`) | migrations, workers | 5432 direct (migrations), 6432 pooled (workers) | owns everything; exempt from RLS |
| `corpus_web` | the web app | 6432 pooled | only what `db/access.sql` grants; rows scoped by RLS |

VibeDB's own app role (`content_corpus_app`) is **not used** — `db/access.sql`
revokes everything VibeDB's default privileges give it.

## One-time setup (on the VibeDB server)

```bash
sudo vibedb project create content-corpus
sudo vibedb role create content-corpus corpus_web --exact
sudo vibedb project credentials content-corpus --role owner
sudo vibedb project credentials content-corpus --role corpus_web
```

Put the URLs in the repo-root `.env` (and the web ones in Vercel):

| `.env` key | Value |
|---|---|
| `DATABASE_URL` | owner, **pooled** (6432) — workers |
| `DATABASE_URL_UNPOOLED` | owner, **direct** (5432) — `db/migrate.py` |
| `WEB_DATABASE_URL` | `corpus_web`, **pooled** (6432) — web app |

Then: `worker/.venv/Scripts/python db/migrate.py`

The web app uses node-postgres, which treats `sslmode=require` as full
certificate verification — the server needs the installer's `--letsencrypt`
certificate for `--public-host`.

## Backups

Dashboard → **Backups**: add a Neon API key once, then enable backups for
`content-corpus` and pick an interval (6 h – 1 week). Check from the server:

```bash
sudo vibedb backup list
sudo vibedb backup run content-corpus     # first copy now, instead of waiting
```

Why the schema is shaped for this: a backup is `pg_dump` → `pg_restore
--no-owner --no-acl` into Neon. RLS policies therefore name no role
(`0004_rls.sql`), and every grant lives in the repeatable `db/access.sql`.
Verified on PostgreSQL 18: backup, restore into a new project, re-migrate, and
the full security test suite passes against the restored database.

## Restoring a backup

1. Dashboard → Backups → restore into a **new** project (e.g. `content-corpus-r1`).
2. Give it a web role. Role names are cluster-wide, so if `corpus_web` still
   exists (the original project, or its soft-deleted remains):
   `sudo vibedb role create content-corpus-r1 corpus_web_r1 --exact`
3. **Immediately** run migrate against it (`DATABASE_URL_UNPOOLED` = the new
   owner's direct URL, and `CORPUS_WEB_ROLE=corpus_web_r1` if you used a new
   name). A restore carries no grants: until this runs the web role can reach
   nothing (fails closed), but VibeDB's app role has its default privileges
   back — migrate takes them away again.
4. Point `DATABASE_URL`, `DATABASE_URL_UNPOOLED` and `WEB_DATABASE_URL` at the new project.
