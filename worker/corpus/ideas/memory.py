"""The agent's long memory, in Qdrant: has this subject (or one very like it) been
suggested or made before?

One collection, content_corpus_memory, scoped per channel by payload. Suggestions
(kind "idea") are forgotten after IDEA_MEMORY_DAYS to keep the store small; topics
that became posts (kind "post") stay. Talks to Qdrant's REST API with httpx. When
Qdrant is not configured or not reachable, NullMemory stands in: ideas are still
made, only the cross-batch repeat check is skipped (and logged).
"""

from __future__ import annotations

import time
from typing import Protocol

import httpx

COLLECTION = "content_corpus_memory"
SIMILAR = 0.80            # bge-small: same subject reworded ≈ 0.85, different subjects ≈ 0.4-0.5
IDEA_MEMORY_DAYS = 30


class Memory(Protocol):
    def nearest(self, channel_id: str, vector: list[float]) -> tuple[float, str]: ...
    def remember(self, points: list[dict]) -> None: ...
    def forget(self, ids: list[str]) -> None: ...


class NullMemory:
    def nearest(self, channel_id, vector):
        return 0.0, ""

    def remember(self, points):
        pass

    def forget(self, ids):
        pass


class QdrantMemory:
    def __init__(self, url: str, api_key: str, dim: int = 384):
        self.http = httpx.Client(base_url=url.rstrip("/"), headers={"api-key": api_key}, timeout=20)
        self.dim = dim
        self._ready = False

    def _ensure(self) -> None:
        if self._ready:
            return
        r = self.http.get(f"/collections/{COLLECTION}")
        if r.status_code == 404:
            self.http.put(f"/collections/{COLLECTION}",
                          json={"vectors": {"size": self.dim, "distance": "Cosine"}}).raise_for_status()
            for field, kind in (("channel_id", "keyword"), ("kind", "keyword"), ("created_at", "integer")):
                self.http.put(f"/collections/{COLLECTION}/index",
                              json={"field_name": field, "field_schema": kind}).raise_for_status()
        else:
            r.raise_for_status()
        self._ready = True

    def nearest(self, channel_id: str, vector: list[float]) -> tuple[float, str]:
        self._ensure()
        r = self.http.post(f"/collections/{COLLECTION}/points/search", json={
            "vector": vector, "limit": 1, "with_payload": True,
            "filter": {"must": [{"key": "channel_id", "match": {"value": channel_id}}]}})
        r.raise_for_status()
        hits = r.json().get("result") or []
        return (hits[0]["score"], hits[0]["payload"].get("title", "")) if hits else (0.0, "")

    def remember(self, points: list[dict]) -> None:
        """points: [{"id": uuid, "vector": [...], "channel_id", "kind": "idea"|"post", "title"}]"""
        if not points:
            return
        self._ensure()
        now = int(time.time())
        self.http.put(f"/collections/{COLLECTION}/points", params={"wait": "true"}, json={"points": [
            {"id": str(p["id"]), "vector": p["vector"],
             "payload": {"channel_id": str(p["channel_id"]), "kind": p["kind"], "title": p["title"],
                         "created_at": now}} for p in points]}).raise_for_status()

    def forget(self, ids: list[str]) -> None:
        if not ids:
            return
        self._ensure()
        self.http.post(f"/collections/{COLLECTION}/points/delete", params={"wait": "true"},
                       json={"points": [str(i) for i in ids]}).raise_for_status()


def connect(url: str, api_key: str, log=print) -> Memory:
    if not url:
        log("memory: QDRANT_URL not set; repeat check limited to this batch")
        return NullMemory()
    m = QdrantMemory(url, api_key)
    try:
        m._ensure()
        return m
    except Exception as e:  # noqa: BLE001 - ideas still come; only the long memory is missing
        log(f"memory: Qdrant unreachable ({type(e).__name__}: {str(e)[:120]}); repeat check limited to this batch")
        return NullMemory()
