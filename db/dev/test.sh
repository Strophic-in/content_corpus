#!/usr/bin/env bash
# Run every test suite against the local test database, never production.
#
#   bash db/dev/test.sh                 # migrate the test DB, then worker + db tests
#   bash db/dev/test.sh -k publish      # extra pytest arguments pass through
#
# The repo-root .env holds the production URLs; every URL a test or migration
# could read is pinned here to the throwaway Postgres from db/dev/test_db.sh.
set -euo pipefail
cd "$(dirname "$0")/../.."
PORT=${PORT:-55442}
export DATABASE_URL_UNPOOLED="postgres://app_owner:localdev@127.0.0.1:$PORT/corpus_test"
export DATABASE_URL="$DATABASE_URL_UNPOOLED"
export TEST_DATABASE_URL_OWNER="$DATABASE_URL_UNPOOLED"
export TEST_DATABASE_URL_WEB="postgres://corpus_web:local-web-pass@127.0.0.1:$PORT/corpus_test"
PY=worker/.venv/bin/python; [ -x "$PY" ] || PY=worker/.venv/Scripts/python
"$PY" db/migrate.py --target test
[ $# -gt 0 ] || set -- worker/tests db/tests
"$PY" -m pytest -q "$@"
