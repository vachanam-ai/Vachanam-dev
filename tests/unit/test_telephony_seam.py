"""Per-clinic Vobiz sub-account seam (Vinay 2026-06-15): concurrency isolation.

Proves the credential seam is correct and SAFE:
  - SIP secrets round-trip through encryption and a tampered token is rejected
  - a branch WITH a sub-account uses its own (decrypted) creds + outbound trunk
  - a branch WITHOUT one falls back to the global account (backward compatible)
"""
from types import SimpleNamespace as NS

import pytest

from backend.services.crypto import decrypt_secret, encrypt_secret
from backend.services.telephony import branch_outbound_trunk_id, resolve_branch_telephony


def test_secret_round_trips():
    token = encrypt_secret("s3cr3t-sip-pass")
    assert token and token != "s3cr3t-sip-pass"  # ciphertext, not plaintext
    assert decrypt_secret(token) == "s3cr3t-sip-pass"


def test_empty_secret_is_passthrough():
    assert encrypt_secret("") == ""
    assert decrypt_secret("") == ""


def test_tampered_token_raises():
    token = encrypt_secret("abc")
    with pytest.raises(ValueError):
        decrypt_secret(token[:-4] + "zzzz")


def test_branch_with_subaccount_uses_its_own_creds():
    branch = NS(
        id="b1",
        vobiz_subaccount_id="sub_123",
        vobiz_sip_username="clinicuser",
        vobiz_sip_password_enc=encrypt_secret("clinicpass"),
        vobiz_sip_domain="sip.vobiz.ai",
        outbound_trunk_id="ST_clinic",
    )
    t = resolve_branch_telephony(branch)
    assert t.subaccount_id == "sub_123"
    assert t.sip_username == "clinicuser"
    assert t.sip_password == "clinicpass"  # decrypted at point of use
    assert t.outbound_trunk_id == "ST_clinic"
    assert branch_outbound_trunk_id(branch) == "ST_clinic"


def test_branch_without_subaccount_falls_back_to_global(monkeypatch):
    import backend.services.telephony as tp

    monkeypatch.setattr(tp.settings, "vobiz_auth_id", "globaluser")
    monkeypatch.setattr(tp.settings, "vobiz_auth_token", "globaltoken")
    monkeypatch.setattr(tp.settings, "outbound_trunk_id", "ST_global")
    branch = NS(id="b2", vobiz_subaccount_id=None)
    t = resolve_branch_telephony(branch)
    assert t.subaccount_id is None
    assert t.sip_username == "globaluser"
    assert t.outbound_trunk_id == "ST_global"


def test_decrypt_failure_falls_back_not_crash():
    """A bad/old ciphertext must not crash a dispatch job — it falls back to no
    password (the call is still attempted) rather than raising."""
    branch = NS(
        id="b3",
        vobiz_subaccount_id="sub_x",
        vobiz_sip_username="u",
        vobiz_sip_password_enc="not-a-valid-fernet-token",
        vobiz_sip_domain="d",
        outbound_trunk_id="ST_x",
    )
    t = resolve_branch_telephony(branch)  # must NOT raise
    assert t.sip_password == ""
    assert t.outbound_trunk_id == "ST_x"
