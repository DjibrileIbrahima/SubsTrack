"""Encryption for secrets at rest (Plaid access tokens, MFA secrets).

Two schemes are supported, chosen by environment:

* **AWS KMS (production).** Set ENCRYPTION_KMS_KEY_ID. Ciphertext is produced by
  KMS Encrypt, so the master key never exists on the application host — a host
  compromise yields ciphertext only, not the key. KMS values are tagged with a
  "kms:v1:" prefix.
* **Fernet (local dev / fallback).** Set ENCRYPTION_KEY (single key) or
  ENCRYPTION_KEYS (comma-separated, newest first) for key rotation via MultiFernet.

decrypt() dispatches on the stored value's prefix, so rows written under the old
Fernet scheme keep decrypting after KMS is switched on. Keep a Fernet key
configured alongside KMS during migration; use reencrypt() to move rows over.
"""

import base64
import os
from functools import lru_cache

from cryptography.fernet import Fernet, MultiFernet

_KMS_KEY_ID = os.getenv("ENCRYPTION_KMS_KEY_ID")
_KMS_PREFIX = "kms:v1:"


def _load_fernet() -> MultiFernet | None:
    """Build a MultiFernet from ENCRYPTION_KEYS (preferred, comma-separated,
    newest first) or ENCRYPTION_KEY. Encryption uses the first key; decryption
    tries all, so rotation is: prepend a new key, redeploy, re-encrypt lazily."""
    raw = os.getenv("ENCRYPTION_KEYS") or os.getenv("ENCRYPTION_KEY")
    if not raw:
        return None
    keys = [Fernet(part.strip().encode()) for part in raw.split(",") if part.strip()]
    return MultiFernet(keys) if keys else None


_fernet = _load_fernet()

if not _KMS_KEY_ID and _fernet is None:
    raise RuntimeError(
        "No encryption key configured. Set ENCRYPTION_KMS_KEY_ID (production) or "
        "ENCRYPTION_KEY / ENCRYPTION_KEYS (local dev). Generate a Fernet key with: "
        'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
    )


@lru_cache(maxsize=1)
def _kms_client():
    # Imported lazily so boto3 is only required when KMS is actually in use.
    import boto3

    return boto3.client("kms", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))


def encrypt(value: str) -> str:
    """Encrypt a plaintext string. Returns a string safe to store in the DB."""
    if _KMS_KEY_ID:
        blob = _kms_client().encrypt(KeyId=_KMS_KEY_ID, Plaintext=value.encode())["CiphertextBlob"]
        return _KMS_PREFIX + base64.b64encode(blob).decode()
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Decrypt a stored encrypted string back to plaintext.

    Dispatches on the scheme prefix so both KMS and legacy Fernet ciphertexts
    read correctly regardless of the currently-active scheme.
    """
    if value.startswith(_KMS_PREFIX):
        blob = base64.b64decode(value[len(_KMS_PREFIX):])
        # Passing KeyId makes KMS reject a blob encrypted under a different key.
        return _kms_client().decrypt(CiphertextBlob=blob, KeyId=_KMS_KEY_ID)["Plaintext"].decode()
    if _fernet is None:
        raise RuntimeError(
            "Found a Fernet ciphertext but no ENCRYPTION_KEY/ENCRYPTION_KEYS is "
            "configured to decrypt it. Provide the legacy key to read this row."
        )
    return _fernet.decrypt(value.encode()).decode()


def reencrypt(value: str) -> str:
    """Decrypt then re-encrypt under the current primary scheme.

    Use in a migration job to move legacy Fernet rows to KMS, or to rotate a row
    onto the newest Fernet key. Idempotent for values already on the active scheme.
    """
    return encrypt(decrypt(value))
