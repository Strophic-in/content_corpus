"""Integration tests run the real worker code against a real Postgres.

Point TEST_DATABASE_URL_OWNER at a database with db/migrations applied (default:
the local docker Postgres from the dev setup). It is exported as DATABASE_URL
before `corpus` is imported, so the worker under test talks to it.
"""

import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL_OWNER", "postgres://app_owner:localdev@127.0.0.1:55442/corpus_test")
os.environ.setdefault("CORPUS_WORKER_ID", "cpu-test")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
