"""WA MVP1 Task 2: per-branch Meta token resolution.

RULE 1 — a clinic's token must never be substituted for another clinic's,
and a corrupt/undecryptable clinic token must FAIL CLOSED rather than fall
back to the platform token (that fallback would send the clinic's message
from Vachanam's own WhatsApp account).
RULE 4 — a send never raises into a caller; no token → log + return False.
RULE 9 — never log the token itself.
"""
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio

from backend.config import settings
from backend.models.schema import Branch, Organization
from backend.services import wa_service
from backend.services.crypto import encrypt_secret


def FakeBranch(wa_token_enc=None, id=None, wa_phone_number_id="333444555"):
    return SimpleNamespace(
        id=id or uuid.uuid4(), wa_token_enc=wa_token_enc,
        wa_phone_number_id=wa_phone_number_id,
    )


async def make_branch(db, *, wa_phone_number_id, wa_token_enc=None):
    org = Organization(
        name="TokOrg", owner_phone="+919000700099",
        owner_email=f"tok-{uuid.uuid4().hex[:6]}@test.com", plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name="TokBranch", clinic_phone="+914012340000",
        whatsapp_number=f"+9155{str(uuid.uuid4().int)[:8]}", status="active",
        wa_phone_number_id=wa_phone_number_id, wa_token_enc=wa_token_enc,
    )
    db.add(b)
    await db.commit()
    return b


# ── token_for ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clinic_token_used_and_never_crosses_branches(db):
    """RULE 1 — branch A's token must never send on branch B's number."""
    a = await make_branch(db, wa_phone_number_id="111", wa_token_enc=encrypt_secret("TOKEN_A"))
    b = await make_branch(db, wa_phone_number_id="222", wa_token_enc=encrypt_secret("TOKEN_B"))
    assert wa_service.token_for(a) == "TOKEN_A"
    assert wa_service.token_for(b) == "TOKEN_B"


def test_undecryptable_clinic_token_fails_closed(monkeypatch):
    """A corrupt clinic token must NOT fall back to the platform token — that
    would send this clinic's message from Vachanam's own account."""
    monkeypatch.setattr(wa_service.settings, "meta_access_token", "PLATFORM", raising=False)
    assert wa_service.token_for(FakeBranch(wa_token_enc="not-valid-fernet")) is None


def test_platform_token_used_only_when_branch_has_none(monkeypatch):
    monkeypatch.setattr(wa_service.settings, "meta_access_token", "PLATFORM", raising=False)
    assert wa_service.token_for(FakeBranch(wa_token_enc=None)) == "PLATFORM"


def test_no_platform_token_and_no_branch_token_is_none(monkeypatch):
    monkeypatch.setattr(wa_service.settings, "meta_access_token", "", raising=False)
    assert wa_service.token_for(FakeBranch(wa_token_enc=None)) is None


# ── send paths never fall back on a missing token (RULE 4) ─────────────────────

@pytest.mark.asyncio
async def test_send_without_a_token_logs_and_returns_false(monkeypatch):
    """RULE 4 — never raise into a caller. Gate (link+plan) passes here so the
    assertion actually exercises the token-resolution short-circuit, not the
    unrelated wa_enabled gate."""
    monkeypatch.setattr(wa_service.settings, "meta_access_token", "tok", raising=False)
    monkeypatch.setattr(wa_service, "token_for", lambda b: None)
    assert await wa_service.send_text(
        FakeBranch(), "919000000001", "hi", plan="clinic"
    ) is False


@pytest.mark.asyncio
async def test_send_template_without_a_token_logs_and_returns_false(monkeypatch):
    monkeypatch.setattr(wa_service.settings, "meta_access_token", "tok", raising=False)
    monkeypatch.setattr(wa_service, "token_for", lambda b: None)
    ok = await wa_service.send_template(
        FakeBranch(), "919000000001", "booking_confirm", "en", ["1"], plan="clinic"
    )
    assert ok is False


# ── clinic-owned WABA must not depend on the platform token ───────────────────

def test_branch_with_own_token_is_enabled_without_any_platform_token(monkeypatch):
    """The whole point of clinic-owned WABAs: a clinic sends with ITS token.
    Gating wa_enabled on settings.meta_access_token reported every
    clinic-owned branch as disabled once the platform token was unset —
    which is exactly the Tech Provider end state."""
    monkeypatch.setattr(wa_service.settings, "meta_access_token", "", raising=False)
    branch = FakeBranch(wa_token_enc=encrypt_secret("CLINIC_TOKEN"))
    branch.wa_phone_number_id = "111"
    assert wa_service.wa_enabled(branch, "wa") is True


def test_branch_without_any_token_is_not_enabled(monkeypatch):
    """No clinic token and no platform token → nothing to send with."""
    monkeypatch.setattr(wa_service.settings, "meta_access_token", "", raising=False)
    branch = FakeBranch(wa_token_enc=None)
    branch.wa_phone_number_id = "111"
    assert wa_service.wa_enabled(branch, "wa") is False


def test_corrupt_clinic_token_disables_the_branch_rather_than_borrowing(monkeypatch):
    """Fail closed end-to-end: an undecryptable clinic token must disable the
    branch, never silently send from Vachanam's own account (RULE 1)."""
    monkeypatch.setattr(wa_service.settings, "meta_access_token", "PLATFORM", raising=False)
    branch = FakeBranch(wa_token_enc="not-valid-fernet")
    branch.wa_phone_number_id = "111"
    assert wa_service.wa_enabled(branch, "wa") is False
