"""Race Engineering GPU cloud client — the pod lifecycle the `gpu` lane runs on.

Written against the wire format of the official `race-ai` CLI (0.1.1,
race_cli/api_client.py), because the public API docs 404. That package is not a
dependency: it keeps the key in the OS keychain, which a headless Oracle box does
not have, and it is an alpha whose surface will move.

Two quirks this module absorbs so callers never see them:

  * pod-list is wrapped in {"status", "data"}; gpu-list and templates are bare
    arrays.
  * Only built-in templates deploy with an API key, and deploy takes no env vars
    or startup command. The worker is therefore started over the `ssh_command`
    that deploy-status and resume-pod return, never baked in at deploy time.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.raceengineering.ai"


class RaceError(RuntimeError):
    """Any failed call. `status` is 0 when the request never got an answer.

    Only status 0 is safe to retry blindly, and only for deploy, which carries an
    idempotency key. A 4xx/5xx is the server's definitive answer.
    """

    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"[{status}] {message}")


class RaceClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL,
                 timeout: float = 30.0):
        if not api_key.startswith("rk_"):
            raise RaceError(0, "Race API keys start with 'rk_'")
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def _call(self, method: str, path: str, *, json: dict | None = None,
              params: dict | None = None, headers: dict | None = None,
              timeout: float | None = None) -> Any:
        try:
            resp = self._http.request(method, path, json=json, params=params,
                                      headers=headers,
                                      timeout=timeout or self._http.timeout)
        except httpx.HTTPError as exc:
            raise RaceError(0, f"{type(exc).__name__}: {exc}") from exc
        if resp.status_code >= 400:
            try:
                body = resp.json()
                message = body.get("message") or body.get("detail") or str(body)
            except ValueError:
                message = resp.text or f"HTTP {resp.status_code}"
            raise RaceError(resp.status_code, message)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # ── discovery ────────────────────────────────────────────────────────────

    def whoami(self) -> dict:
        return self._call("GET", "/v1/api-keys/whoami/")

    def gpus(self) -> list[dict]:
        return self._call("GET", "/v1/gpu/gpu-list/") or []

    def templates(self) -> list[dict]:
        """Built-in templates only: custom ones are rejected with a 400 at deploy."""
        rows = self._call("GET", "/v1/gpu/templates/") or []
        return [t for t in rows if t.get("template_type") == "builtin"]

    def pods(self) -> list[dict]:
        result = self._call("GET", "/v1/gpu/pod-list/")
        return (result or {}).get("data", [])

    def status(self, pod_id: str) -> dict:
        """`ssh_command` and `web_url` appear only once the pod is ready."""
        return self._call("GET", "/v1/gpu/deploy-status/", params={"pod_id": pod_id})

    # ── lifecycle ────────────────────────────────────────────────────────────
    #
    # These block server-side while the container is created, stopped or started.
    # A pause on a busy host took over 30 s and still succeeded, so a short client
    # timeout reports failure for an action that happened. After any timeout, read
    # pods() to learn the real state before retrying.
    LIFECYCLE_TIMEOUT = 180.0

    def deploy(self, slice_id: str, template_id: str, *, disk_gb: int = 50,
               name: str | None = None, idempotency_key: str | None = None) -> dict:
        """Start a pod. Reuse one idempotency key across retries of one intent.

        A fresh key per retry would defeat it: the server recognises a retry only
        by seeing the same key again, and a duplicate pod bills by the minute.
        """
        payload: dict[str, Any] = {"slice_id": slice_id, "template_id": template_id,
                                   "disk_size": disk_gb}
        if name:
            payload["pod_name"] = name
        return self._call("POST", "/v1/gpu/start-pod/", json=payload, headers={
            "Idempotency-Key": idempotency_key or str(uuid.uuid4())},
            timeout=self.LIFECYCLE_TIMEOUT)

    def pause(self, pod_id: str) -> dict | None:
        return self._call("POST", "/v1/gpu/pause-pod/", json={"pod_id": pod_id},
                          timeout=self.LIFECYCLE_TIMEOUT)

    def resume(self, pod_id: str) -> dict | None:
        """Returns a fresh `ssh_command`: the SSH port changes on every resume."""
        return self._call("POST", "/v1/gpu/resume-pod/", json={"pod_id": pod_id},
                          timeout=self.LIFECYCLE_TIMEOUT)

    def terminate(self, pod_id: str) -> dict | None:
        return self._call("POST", "/v1/gpu/terminate-pod/", json={"pod_id": pod_id},
                          timeout=self.LIFECYCLE_TIMEOUT)
