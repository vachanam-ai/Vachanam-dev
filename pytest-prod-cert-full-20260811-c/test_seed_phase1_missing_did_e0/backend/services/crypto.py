"""Symmetric field encryption for secrets stored at rest (DPDP / RULE 9).

Used for per-branch telephony credentials (Vobiz sub-account SIP password) so a
clinic's SIP secret is NEVER a plaintext DB column. Fernet (AES-128-CBC + HMAC)
from `cryptography`, already a dependency via python-jose[cryptography].

Key resolution:
  - settings.field_encryption_key if set — a urlsafe-base64 32-byte Fernet key
    (generate with `Fernet.generate_key()`). REQUIRED in production.
  - else derived deterministically from settings.jwt_secret so dev/test work
    without extra config. A WARNING is logged — a derived key means rotating the
    JWT secret would orphan stored ciphertext, so set a real key in prod.
"""
import base64
import hashlib

import structlog
from cryptography.fernet import Fernet, InvalidToken

from backend.config import settings

logger = structlog.get_logger()

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = (settings.field_encryption_key or "").strip()
    if key:
        _fernet = Fernet(key.encode())
    else:
        # SEC #5: a JWT-derived key is a dev/test convenience only. In production
        # it must be a hard failure — deriving at-rest encryption from the JWT
        # secret means rotating the JWT orphans every stored SIP ciphertext, and
        # the "secret" is no stronger than a value living in the same env.
        if settings.app_env == "production":
            raise RuntimeError(
                "FIELD_ENCRYPTION_KEY is required in production "
                "(generate: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\")"
            )
        # Derive a stable Fernet key from the JWT secret (dev/test convenience).
        logger.warning(
            "field_encryption_key_unset_deriving_from_jwt_secret — set FIELD_ENCRYPTION_KEY in production"
        )
        digest = hashlib.sha256(settings.jwt_secret.encode()).digest()
        _fernet = Fernet(base64.urlsafe_b64encode(digest))
    return _fernet


def encrypt_secret(plaintext: str) -> str:
    """Return a Fernet token (str) for a secret. Empty input → empty string."""
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Return the plaintext for a Fernet token. Empty input → empty string.
    Raises ValueError on a tampered/old-key token so callers fail loudly rather
    than dialing with garbage credentials."""
    if not token:
        return ""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise ValueError("Could not decrypt stored secret (wrong key or tampered)") from e
