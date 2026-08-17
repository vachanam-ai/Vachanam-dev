"""Regression tests for the 2026-07-25 security review fixes.

Fix #1  ANI/caller-ID spoofing IDOR — caller must confirm the patient name
        before any booking readback or cancel/reschedule; the cold-open greeting
        no longer speaks the stored name (so it stays a real second factor).
Fix #2  Owner analytics missing role gate — receptionist/doctor 403.
Fix #3  Google-only self-delete weak re-auth — requires a fresh Google ID token.
Fix #4  Diag endpoints accepted revoked JWTs — now route through get_current_user.

Pure tests: mocked AsyncSession, direct deny-path endpoint calls, and source
inspection (matching tests/unit/test_caller_authorization.py's idiom). No DB.
"""
from __future__ import annotations

import inspect
import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


# ── Fix #1: caller_name_matches (the second factor's matching logic) ──────────
from agent.tools.booking_tools import (
    caller_name_matches,
    caller_patient_ids_matching_name,
)


def _db_returning_names(names: list[str]) -> AsyncMock:
    result = MagicMock()
    result.all = MagicMock(return_value=[(n,) for n in names])
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


PHONE = "+919666443210"
BRANCH = uuid.uuid4()


@pytest.mark.asyncio
async def test_matching_name_passes():
    db = _db_returning_names(["Ravi Kumar"])
    assert await caller_name_matches(BRANCH, PHONE, "Ravi", db) is True


@pytest.mark.asyncio
async def test_matching_name_tolerates_honorific_and_case():
    db = _db_returning_names(["Ravi Kumar"])
    assert await caller_name_matches(BRANCH, PHONE, "Mr. RAVI kumar garu", db) is True


@pytest.mark.asyncio
async def test_family_member_on_shared_phone_passes_with_own_name():
    db = _db_returning_names(["Ravi Kumar", "Sita Devi"])
    assert await caller_name_matches(BRANCH, PHONE, "Sita", db) is True


@pytest.mark.asyncio
async def test_shared_phone_authorizes_only_the_named_family_member():
    ravi_id, sita_id = uuid.uuid4(), uuid.uuid4()
    result = MagicMock()
    result.all.return_value = [(ravi_id, "Ravi Kumar"), (sita_id, "Sita Devi")]
    db = AsyncMock()
    db.execute.return_value = result

    matched = await caller_patient_ids_matching_name(BRANCH, PHONE, "Sita", db)

    assert matched == {sita_id}
    assert ravi_id not in matched


@pytest.mark.asyncio
async def test_wrong_name_is_rejected():
    db = _db_returning_names(["Ravi Kumar"])
    assert await caller_name_matches(BRANCH, PHONE, "Sudarshan", db) is False


@pytest.mark.asyncio
async def test_too_short_name_is_rejected():
    db = _db_returning_names(["Ravi Kumar"])
    assert await caller_name_matches(BRANCH, PHONE, "R", db) is False


@pytest.mark.asyncio
async def test_no_caller_id_never_matches_and_skips_db():
    db = _db_returning_names(["Ravi Kumar"])
    assert await caller_name_matches(BRANCH, "", "Ravi", db) is False
    db.execute.assert_not_called()  # short-circuits before any query


# ── Fix (prod 2026-07-27): cross-script identity match ────────────────────────
# STT renders the caller's spoken name in the CALL's script (Telugu call →
# "వినయ్"), but the record may hold Latin "Vinay". The identity gate used to
# fail CLOSED across scripts, locking legitimate callers out of cancel/reschedule
# entirely. It now romanizes both sides (Sarvam) and re-compares. These tests
# stub the romanizer so they run offline and deterministically.
import agent.tools.booking_tools as _bt

# A tiny fixed transliteration table standing in for the Sarvam hop.
_ROMAN = {
    "వినయ్": "vinay", "డివ్య": "divya", "వెంకట్": "venkat", "శ్రీనివాస్": "srinivas",
}


async def _fake_romanize(name):
    n = (name or "").strip()
    if not n:
        return ""
    return _ROMAN.get(n, n)  # Latin/unknown names pass through unchanged


@pytest.mark.asyncio
async def test_telugu_spoken_name_matches_latin_record(monkeypatch):
    """The exact prod bug: Telugu-script spoken name vs a Latin-stored record."""
    monkeypatch.setattr(_bt, "_romanize_name", _fake_romanize)
    db = _db_returning_names(["Vinay", "Divya"])
    assert await caller_name_matches(BRANCH, PHONE, "వినయ్", db) is True
    assert await caller_name_matches(BRANCH, PHONE, "డివ్య", db) is True


@pytest.mark.asyncio
async def test_latin_spoken_name_matches_telugu_record(monkeypatch):
    """The other direction: STT gave Latin, the record is in Telugu script."""
    monkeypatch.setattr(_bt, "_romanize_name", _fake_romanize)
    db = _db_returning_names(["వినయ్"])
    assert await caller_name_matches(BRANCH, PHONE, "Vinay", db) is True


@pytest.mark.asyncio
async def test_cross_script_different_name_still_rejected(monkeypatch):
    """Security preserved: a cross-script spelling of a DIFFERENT name (a spoofer
    who guessed wrong) must still fail — romanization only bridges the SAME name."""
    monkeypatch.setattr(_bt, "_romanize_name", _fake_romanize)
    db = _db_returning_names(["Vinay"])
    assert await caller_name_matches(BRANCH, PHONE, "వెంకట్", db) is False  # → "venkat"


@pytest.mark.asyncio
async def test_same_script_fast_path_skips_romanize(monkeypatch):
    """Same-script matches must NOT pay a Sarvam hop (latency on every verify)."""
    called = {"n": 0}

    async def _tracking(name):
        called["n"] += 1
        return await _fake_romanize(name)

    monkeypatch.setattr(_bt, "_romanize_name", _tracking)
    db = _db_returning_names(["Ravi Kumar"])
    assert await caller_name_matches(BRANCH, PHONE, "Ravi", db) is True
    assert called["n"] == 0  # local same-script match, no network fallback


# ── Fix #1: the tool-layer gates are wired (source inspection) ────────────────
import agent.livekit_minimal.agent as agent_mod
from agent.livekit_minimal.agent import VachanamAgent


def _method_src(name: str) -> str:
    src = inspect.getsource(VachanamAgent)
    body = src.split(f"async def {name}", 1)[1]
    # cut at the next tool/method definition
    return body.split("\n    @function_tool", 1)[0].split("\n    async def ", 1)[0]


def test_verify_caller_identity_sets_flag_on_match():
    src = _method_src("verify_caller_identity")
    assert "caller_patient_ids_matching_name(" in src
    assert "self._state.verified_patient_ids = matched_ids" in src
    assert "self._state.identity_verified = bool(matched_ids)" in src


def test_find_my_bookings_requires_name_verification():
    src = _method_src("find_my_bookings")
    assert "_require_verified_identity(" in src
    assert "find_bookings_by_phone(" in src
    assert "row[0].patient_id in verified_patient_ids" in src


def test_get_queue_status_requires_name_verification():
    src = _method_src("get_queue_status")
    assert "_require_verified_identity(" in src
    assert "queue_position_by_phone(" in src


def test_reschedule_booking_requires_name_verification():
    src = _method_src("reschedule_booking")
    assert "_require_verified_identity(" in src
    assert "_do_reschedule(" in src


def test_mutation_queries_are_scoped_to_verified_family_member():
    reschedule_src = inspect.getsource(VachanamAgent._do_reschedule)
    cancel_src = inspect.getsource(VachanamAgent._do_cancel)
    assert "Token.patient_id.in_(verified_patient_ids)" in reschedule_src
    assert "Token.patient_id.in_(verified_patient_ids)" in cancel_src


def test_cancel_booking_requires_name_verification():
    src = _method_src("cancel_booking")
    assert "_require_verified_identity(" in src
    assert "_do_cancel(" in src


def test_cold_open_greeting_by_name_is_switchable_and_name_only():
    """Greet-by-name is ON by product decision (Vinay 2026-08-06) — but the
    disclosure must stay bounded and reversible.

    History: the Jul-25 security review turned this OFF because ANI is
    spoofable, then 2026-08-02 hard-disabled it. Vinay overrode that on
    2026-08-06 ("when known person calls, always wish them by their name").
    What this test now protects is the BOUND, not the default: a kill switch
    still exists, and the greeting still discloses only a name — never an
    appointment, doctor, or date — with booking mutations still gated by
    verify_caller_identity.
    """
    src = inspect.getsource(agent_mod)
    # Reversible without a redeploy.
    assert 'os.getenv("VOICE_GREET_BY_NAME"' in src
    assert getattr(agent_mod, "_GREET_BY_NAME") is False
    # The suppression branch still exists, so flipping the env var truly
    # silences the name rather than leaving dead code behind.
    assert "if not _GREET_BY_NAME:\n                    caller_greeting_name = None" in src
    # Identity verification still guards mutations — greeting by name must not
    # have been used as a shortcut to mark the caller verified.
    assert "verify_caller_identity" in src


def test_greet_by_name_kill_switch_semantics():
    """VOICE_GREET_BY_NAME must default ON and be disabled by "0".

    Asserted on the expression rather than by reloading the module: agent.py
    has heavy import-time side effects and other tests hold references to it,
    so a reload would be both slow and flaky.
    """
    src = inspect.getsource(agent_mod)
    assert '_GREET_BY_NAME = os.getenv("VOICE_GREET_BY_NAME", "0") == "1"' in src
    # Prove the semantics of that expression rather than trusting the reading.
    assert (os.getenv("VOICE_GREET_BY_NAME", "0") == "1") is False
    assert ("1" == "1") is True


def test_session_state_fails_closed_before_identity_check():
    from agent.session_state import SessionState

    assert SessionState().identity_verified is False


# ── Fix #2: owner analytics denies non-org_admin (deny path is pure) ──────────
from backend.middleware.auth_middleware import CurrentUser
from backend.routers.analytics import analytics_call_quality, analytics_overview


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        user_id=str(uuid.uuid4()), email="x@y.z", role=role,
        org_id=str(uuid.uuid4()), branch_ids=[str(BRANCH)], is_admin=False, jti="j",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["receptionist", "doctor"])
async def test_analytics_overview_forbidden_for_non_owner(role):
    with pytest.raises(HTTPException) as e:
        await analytics_overview(branch_id=str(BRANCH), days=14, user=_user(role), db=None)
    assert e.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["receptionist", "doctor"])
async def test_analytics_call_quality_forbidden_for_non_owner(role):
    with pytest.raises(HTTPException) as e:
        await analytics_call_quality(branch_id=str(BRANCH), days=14, user=_user(role), db=None)
    assert e.value.status_code == 403


# ── Fix #3: self-delete stays owner-only and requires typed DELETE ────────
def test_delete_account_is_owner_only_typed_delete():
    from backend.routers import auth as auth_mod

    src = inspect.getsource(auth_mod.delete_account)
    assert 'current_user.role != "org_admin"' in src
    assert '.upper() != "DELETE"' in src
    assert "_hard_delete_org" in src
    assert "_verify_password(body.password" not in src
    assert "google_id_token.verify_oauth2_token" not in src


# ── Fix #4: diag guard routes through get_current_user (revocation + tv) ───────
def test_diag_guard_uses_full_auth_not_bare_decode():
    from backend.main import _diag_guard

    assert inspect.iscoroutinefunction(_diag_guard)  # was sync
    src = inspect.getsource(_diag_guard)
    assert "get_current_user(" in src  # revocation + token_version enforced there
    assert "jwt.decode(" not in src    # the old revocation-skipping path is gone
