"""AES-256-GCM secret vault — must stay byte-compatible with apps/web/lib/crypto.ts.

Adapted from TrendCasterStudio worker/trendcaster/crypto.py with one deliberate
change: that project stores the nonce and the ciphertext in two columns, which
means every read path has to remember to fetch both and every new caller is one
forgotten column away from a confusing decrypt failure. Here a secret is a single
self-describing string:

    v1.<base64(12-byte nonce)>.<base64(ciphertext || 16-byte GCM tag)>

The version prefix is what makes a future key rotation or algorithm change a
migration rather than a guess. Python's AESGCM appends the tag to the ciphertext;
the node:crypto side must concatenate `cipher` output with `getAuthTag()` to
match, exactly as TrendCaster's crypto.ts does.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "v1"
_NONCE_BYTES = 12


class VaultError(RuntimeError):
    """Raised for malformed input or a key that cannot decrypt it.

    Deliberately does not subclass ValueError: a bad secret is an operational
    problem (wrong APP_ENCRYPTION_KEY, secret written by another environment), and
    callers should surface it rather than treat it as bad user input.
    """


def _load_key() -> bytes:
    raw = os.environ.get("APP_ENCRYPTION_KEY")
    if not raw:
        raise VaultError("APP_ENCRYPTION_KEY is not set")
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001 - want one error type out of here
        raise VaultError("APP_ENCRYPTION_KEY is not valid base64") from exc
    if len(key) != 32:
        raise VaultError(
            f"APP_ENCRYPTION_KEY must decode to 32 bytes, got {len(key)}"
        )
    return key


def encrypt(plaintext: str) -> str:
    """Encrypt to the single-string storage format."""
    nonce = os.urandom(_NONCE_BYTES)
    ct = AESGCM(_load_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return ".".join(
        (_PREFIX, base64.b64encode(nonce).decode(), base64.b64encode(ct).decode())
    )


def decrypt(stored: str) -> str:
    """Decrypt a value produced by `encrypt` (or by crypto.ts)."""
    if not stored:
        raise VaultError("empty ciphertext")
    parts = stored.split(".")
    if len(parts) != 3 or parts[0] != _PREFIX:
        raise VaultError(f"unrecognised secret format (prefix {parts[0]!r})")
    try:
        nonce = base64.b64decode(parts[1], validate=True)
        ct = base64.b64decode(parts[2], validate=True)
    except Exception as exc:  # noqa: BLE001
        raise VaultError("secret is not valid base64") from exc
    if len(nonce) != _NONCE_BYTES:
        raise VaultError(f"nonce must be {_NONCE_BYTES} bytes, got {len(nonce)}")
    try:
        return AESGCM(_load_key()).decrypt(nonce, ct, None).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        # Authentication failure means the wrong key or a tampered value. Never
        # echo the ciphertext into a log line here.
        raise VaultError("could not decrypt secret (wrong key or corrupt data)") from exc


def generate_key_b64() -> str:
    """Mint a new APP_ENCRYPTION_KEY. Used by worker/scripts/new_key.py."""
    return base64.b64encode(os.urandom(32)).decode()
