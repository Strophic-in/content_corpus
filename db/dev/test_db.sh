#!/usr/bin/env bash
# A throwaway Postgres for the test suites, shaped like a VibeDB project:
# an owner role without CREATEROLE, the restricted web role, and VibeDB's
# `<db>_app` role with default privileges on everything (which db/access.sql
# must strip). Then all migrations are applied.
#
#   bash db/dev/test_db.sh          # container corpus-pg on 127.0.0.1:55442
#   PORT=55443 NAME=corpus-pg2 bash db/dev/test_db.sh
set -euo pipefail
NAME=${NAME:-corpus-pg}
PORT=${PORT:-55442}
cd "$(dirname "$0")/../.."

docker run -d --name "$NAME" -p "127.0.0.1:$PORT:5432" \
  -e POSTGRES_USER=pgsuper -e POSTGRES_PASSWORD=localdev postgres:18 >/dev/null
until docker exec "$NAME" pg_isready -U pgsuper -q; do sleep 1; done
sleep 2   # the entrypoint restarts the server once after initdb

docker exec -i "$NAME" psql -q -v ON_ERROR_STOP=1 -U pgsuper -d postgres <<'SQL'
create role app_owner login password 'localdev';
create role corpus_web login password 'local-web-pass';
create role corpus_test_app login password 'localdev';
create database corpus_test owner app_owner;
\c corpus_test
alter default privileges for role app_owner grant all on tables to corpus_test_app;
alter default privileges for role app_owner grant all on sequences to corpus_test_app;
alter default privileges for role app_owner grant all on functions to corpus_test_app;
SQL

PY=worker/.venv/bin/python; [ -x "$PY" ] || PY=worker/.venv/Scripts/python
DATABASE_URL_UNPOOLED="postgres://app_owner:localdev@127.0.0.1:$PORT/corpus_test" "$PY" db/migrate.py --target test
echo "test database ready on 127.0.0.1:$PORT"
