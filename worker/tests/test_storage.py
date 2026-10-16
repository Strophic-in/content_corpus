"""R2 storage through the 9 GB ledger, against moto's in-process S3."""

from __future__ import annotations

import os
import uuid

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("R2_ACCOUNT_ID", "test")
os.environ.setdefault("R2_ACCESS_KEY_ID", "test")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "test")
os.environ["R2_BUCKET"] = "corpus-test-media"
# moto intercepts AWS hostnames only, so the S3 client is pointed at one in tests.
os.environ["CORPUS_S3_ENDPOINT"] = "https://s3.us-east-1.amazonaws.com"

from corpus import db, storage  # noqa: E402


@pytest.fixture
def s3(monkeypatch):
    # settings() is cached process-wide, so hand storage its client and bucket
    # explicitly instead of relying on env vars read before this module loaded.
    with mock_aws():
        c = boto3.client("s3", region_name="us-east-1", aws_access_key_id="test",
                         aws_secret_access_key="test")
        c.create_bucket(Bucket="corpus-test-media")
        monkeypatch.setattr(storage, "client", lambda: c)
        monkeypatch.setattr(storage, "bucket", lambda: "corpus-test-media")
        yield c


@pytest.fixture
def owner():
    with db.conn() as c:
        yield c


@pytest.fixture
def user(owner):
    uid = f"test-{uuid.uuid4().hex[:10]}"
    owner.execute('insert into "user" (id, name, email, "emailVerified") values (%s,%s,%s,true)',
                  (uid, uid, f"{uid}@example.test"))
    yield uid
    owner.execute("delete from storage_objects where user_id = %s", (uid,))
    owner.execute('delete from "user" where id = %s', (uid,))


def test_put_get_delete_through_the_ledger(s3, owner, user, tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x" * 12345)
    key = f"u/{user}/p/test/shots/0.mp4"
    out = storage.put_file(key, src, kind="shot", user_id=user, content_type="video/mp4")
    assert out["bytes"] == 12345
    row = owner.execute("select state, bytes, sha256 from storage_objects where key = %s", (key,)).fetchone()
    assert (row["state"], row["bytes"], row["sha256"]) == ("stored", 12345, out["sha256"])
    back = storage.get_file(key, tmp_path / "back.mp4")
    assert back.read_bytes() == src.read_bytes()
    storage.delete(key)
    assert owner.execute("select state from storage_objects where key = %s", (key,)).fetchone()["state"] == "deleted"
    assert s3.list_objects_v2(Bucket="corpus-test-media").get("KeyCount", 0) == 0


def test_full_bucket_refuses_before_uploading(s3, owner, user, tmp_path):
    # Real media gets the cap minus the idea-card budget (0013).
    cfg = owner.execute("select cap_bytes - idea_media_cap_bytes as room from storage_config").fetchone()
    used = owner.execute("""select coalesce(sum(bytes), 0)::bigint as u from storage_objects
                             where state in ('reserved','stored') and kind <> 'idea_media'""").fetchone()["u"]
    filler = f"u/{user}/filler"
    assert owner.execute("select ok from private.reserve_storage(%s, %s, 'other', %s)",
                         (filler, cfg["room"] - used - 100, user)).fetchone()["ok"]
    try:
        src = tmp_path / "big.mp4"
        src.write_bytes(b"y" * 1000)
        with pytest.raises(storage.StorageFull) as e:
            storage.put_file(f"u/{user}/p/test/final/x.mp4", src, kind="final", user_id=user)
        assert e.value.stage == "storage_full"
        assert s3.list_objects_v2(Bucket="corpus-test-media").get("KeyCount", 0) == 0   # nothing sent
        assert owner.execute("select full_since from storage_config").fetchone()["full_since"] is not None
    finally:
        owner.execute("delete from storage_objects where key = %s", (filler,))
        owner.execute("update storage_config set full_since = null")


def test_failed_upload_releases_its_reservation(s3, owner, user, tmp_path, monkeypatch):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"z" * 500)
    key = f"u/{user}/p/test/shots/9.mp4"

    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(s3, "upload_file", boom)
    with pytest.raises(RuntimeError):
        storage.put_file(key, src, kind="shot", user_id=user)
    assert owner.execute("select count(*) as n from storage_objects where key = %s", (key,)).fetchone()["n"] == 0


def test_idea_previews_have_their_own_budget(s3, owner, user, tmp_path):
    """A deck full of previews is refused by its own budget, never by the reel's."""
    budget = owner.execute("select idea_media_cap_bytes as b from storage_config").fetchone()["b"]
    used = owner.execute("""select coalesce(sum(bytes), 0)::bigint as u from storage_objects
                             where state in ('reserved','stored') and kind = 'idea_media'""").fetchone()["u"]
    filler = f"u/{user}/ideas/filler"
    assert owner.execute("select ok from private.reserve_storage(%s, %s, 'idea_media', %s)",
                         (filler, budget - used - 100, user)).fetchone()["ok"]
    try:
        src = tmp_path / "preview.mp4"
        src.write_bytes(b"p" * 1000)
        with pytest.raises(storage.StorageFull):
            storage.put_file(f"u/{user}/ideas/x/0.mp4", src, kind="idea_media", user_id=user)
        assert owner.execute("select full_since from storage_config").fetchone()["full_since"] is None
        final = tmp_path / "final.mp4"
        final.write_bytes(b"f" * 1000)
        storage.put_file(f"u/{user}/p/test/final/y.mp4", final, kind="final", user_id=user)   # still fits
    finally:
        owner.execute("delete from storage_objects where key = %s", (filler,))
        owner.execute("delete from storage_objects where key like %s", (f"u/{user}/p/test/final/%",))
