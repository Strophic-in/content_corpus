"""Read a user's API keys from the vault (user_keys), decrypted.

Returns None when the key was never saved, so callers can gate on presence
before spending anything. A key that exists but cannot be decrypted raises,
because silently treating it as absent would be far more confusing.
"""

from __future__ import annotations

from . import db
from .crypto import decrypt


def secret(user_id: str, name: str) -> str | None:
    row = db.one("select ciphertext from user_keys where user_id = %s and name = %s",
                 (user_id, name))
    return decrypt(row["ciphertext"]) if row else None
