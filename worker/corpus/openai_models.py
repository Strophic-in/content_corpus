"""Which OpenAI models the owner's key can use (Settings → models), kept current.

Stored unfiltered in app_settings.openai_models; each Settings dropdown picks the
ones that suit it (text models for scripts and vision; image models later).
"""

from __future__ import annotations

from . import db, vault


def refresh(user_id: str) -> list[str] | None:
    key = vault.secret(user_id, "openai")
    if not key:
        return None
    from openai import OpenAI

    ids = sorted(m.id for m in OpenAI(api_key=key, timeout=30, max_retries=2).models.list())
    with db.conn() as c:
        c.execute("update app_settings set openai_models = %s where user_id = %s", (ids, user_id))
    return ids
