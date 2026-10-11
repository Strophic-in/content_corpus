"""Media in Cloudflare R2, under the app-enforced 9 GB cap.

Every write goes reserve → upload → commit through the storage ledger
(private.reserve_storage & co.). A reservation that would pass the cap is
refused *before* any bytes move; the refusal is recorded in the database (the
dashboard's "storage full" alert) and surfaces here as StorageFull, a Permanent
job failure with stage 'storage_full'. A failed upload releases its reservation.

Keys are per user and per post: u/<user>/p/<post>/{shots,narration,final}/...
"""

from __future__ import annotations

import functools
import hashlib
import os
from pathlib import Path

import boto3
from botocore.config import Config

from . import db
from .config import settings
from .runner import Permanent


class StorageFull(Permanent):
    def __init__(self, used: int, cap: int, requested: int):
        super().__init__(
            f"Media storage is full: {used / 1e9:.2f} of {cap / 1e9:.0f} GB used, this upload "
            f"needs {requested / 1e6:.0f} MB. Free some space to continue.",
            stage="storage_full", detail={"used_bytes": used, "cap_bytes": cap,
                                          "requested_bytes": requested})


@functools.lru_cache(maxsize=1)
def client():
    s = settings()
    # CORPUS_S3_ENDPOINT points tests at a local S3; production uses the R2 account endpoint.
    endpoint = os.environ.get("CORPUS_S3_ENDPOINT") or s.r2_endpoint
    return boto3.client("s3", endpoint_url=endpoint, region_name="auto",
                        aws_access_key_id=s.r2_access_key_id,
                        aws_secret_access_key=s.r2_secret_access_key,
                        config=Config(signature_version="s3v4", retries={"max_attempts": 5}))


def bucket() -> str:
    return settings().r2_bucket


def post_prefix(user_id: str, post_id) -> str:
    return f"u/{user_id}/p/{post_id}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def put_file(key: str, path: Path, *, kind: str, user_id: str, post_id=None, shot_id=None,
             content_type: str = "application/octet-stream") -> dict:
    size = path.stat().st_size
    row = db.one("select ok, used_bytes, cap_bytes from private.reserve_storage(%s, %s, %s, %s, %s, %s)",
                 (key, size, kind, user_id, post_id, shot_id))
    if not row["ok"]:
        raise StorageFull(row["used_bytes"], row["cap_bytes"], size)
    try:
        sha = _sha256(path)
        client().upload_file(str(path), bucket(), key, ExtraArgs={"ContentType": content_type})
    except Exception:
        with db.conn() as c:
            c.execute("select private.release_storage(%s)", (key,))
        raise
    with db.conn() as c:
        c.execute("select private.commit_storage(%s, %s, %s)", (key, size, sha))
    return {"key": key, "bytes": size, "sha256": sha}


def get_file(key: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    client().download_file(bucket(), key, str(dest))
    return dest


def delete(key: str) -> None:
    client().delete_object(Bucket=bucket(), Key=key)
    with db.conn() as c:
        c.execute("select private.mark_storage_deleted(%s)", (key,))
