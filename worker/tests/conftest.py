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


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_copywriter(monkeypatch):
    """No test reaches OpenAI for a reel's caption: posting goes on without one unless a
    test supplies its own copywriter (test_packaging)."""
    from corpus import packaging

    class Offline:
        def __init__(self, key):
            raise RuntimeError("no copywriter in tests")

    monkeypatch.setattr(packaging, "COPYWRITER", Offline)


@pytest.fixture(autouse=True)
def _no_page_videos(monkeypatch):
    """No test asks real news pages for their videos (yt-dlp); test_looks_finder gives its own."""
    from corpus.ideas import media

    monkeypatch.setattr(media, "page_videos", lambda url, most=4: [])
