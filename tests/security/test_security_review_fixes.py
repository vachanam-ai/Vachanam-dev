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
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


# ── Fix #1: caller_name_matches (the second factor's matching logic) ──────────
from agent.tools.booking_tools import caller_name_matches


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
    assert "caller_name_matches(" in src
    assert "self._state.identity_verified = True" in src


def test_find_my_bookings_gated_on_verification():
    src = _method_src("find_my_bookings")
    assert "if not self._state.identity_verified" in src
    assert "needs_verification" in src
    # the gate is BEFORE the DB lookup — no detail leaks pre-verification
    assert src.index("identity_verified") < src.index("find_bookings_by_phone(")


def test_get_queue_status_gated_on_verification():
    src = _method_src("get_queue_status")
    assert "if not self._state.identity_verified" in src
    assert src.index("identity_verified") < src.index("queue_position_by_phone(")


def test_reschedule_booking_gated_on_verification():
    src = _method_src("reschedule_booking")
    assert "identity_not_verified" in src
    assert src.index("identity_verified") < src.index("_do_reschedule(")


def test_cancel_booking_gated_on_verification():
    src = _method_src("cancel_booking")
    assert "identity_not_verified" in src
    assert src.index("identity_verified") < src.index("_do_cancel(")


def test_cold_open_greeting_does_not_speak_stored_name_by_default():
    src = inspect.getsource(agent_mod)
    # default off → name suppressed; a documented kill-switch restores it
    assert '_GREET_BY_NAME = os.getenv("VOICE_GREET_BY_NAME", "0") == "1"' in src
    assert "if not _GREET_BY_NAME:\n                    caller_greeting_name = None" in src


def test_session_state_has_identity_verified_defaulting_false():
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


# ── Fix #3: Google-only self-delete requires fresh Google re-verification ─────
def test_delete_account_reverifies_google_token():
    from backend.routers import auth as auth_mod

    src = inspect.getsource(auth_mod.delete_account)
    # password branch still enforces step-up
    assert "_verify_password(body.password" in src
    # google-only branch now re-verifies a fresh ID token AND matches the email
    assert "verify_oauth2_token(" in src
    assert 'info.get("email")' in src
    assert "me.email" in src


# ── Fix #4: diag guard routes through get_current_user (revocation + tv) ───────
def test_diag_guard_uses_full_auth_not_bare_decode():
    from backend.main import _diag_guard

    assert inspect.iscoroutinefunction(_diag_guard)  # was sync
    src = inspect.getsource(_diag_guard)
    assert "get_current_user(" in src  # revocation + token_version enforced there
    assert "jwt.decode(" not in src    # the old revocation-skipping path is gone
