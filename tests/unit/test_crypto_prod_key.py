"""SEC #5 (2026-07-11 audit): FIELD_ENCRYPTION_KEY must be enforced in prod.

Deriving the at-rest Fernet key from the JWT secret is a dev convenience; in
production it must hard-fail so SIP secrets aren't encrypted with a key that
lives in the same env and dies on JWT rotation.
"""
import base64
import hashlib

import pytest
from cryptography.fernet import Fernet

import backend.services.crypto as crypto


@pytest.fixture(autouse=True)
def _reset_fernet():
    crypto._fernet = None
    yield
    crypto._fernet = None


def test_prod_without_key_hard_fails(monkeypatch):
    monkeypatch.setattr(crypto.settings, "app_env", "production")
    monkeypatch.setattr(crypto.settings, "field_encryption_key", "")
    with pytest.raises(RuntimeError, match="FIELD_ENCRYPTION_KEY is required"):
        crypto._get_fernet()


def test_prod_with_key_works(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(crypto.settings, "app_env", "production")
    monkeypatch.setattr(crypto.settings, "field_encryption_key", key)
    tok = crypto.encrypt_secret("sip-password")
    assert crypto.decrypt_secret(tok) == "sip-password"


def test_dev_without_key_derives_from_jwt(monkeypatch):
    monkeypatch.setattr(crypto.settings, "app_env", "development")
    monkeypatch.setattr(crypto.settings, "field_encryption_key", "")
    monkeypatch.setattr(crypto.settings, "jwt_secret", "dev-jwt-secret")
    tok = crypto.encrypt_secret("x")
    assert crypto.decrypt_secret(tok) == "x"
    # confirms it used the JWT-derived key path (no exception, round-trips)
    expected = Fernet(base64.urlsafe_b64encode(
        hashlib.sha256(b"dev-jwt-secret").digest()))
    assert expected.decrypt(tok.encode()).decode() == "x"
