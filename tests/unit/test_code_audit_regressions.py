"""Permanent regression contracts produced by the 2026-07 whole-code audit."""
from __future__ import annotations

import html as html_lib
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from sqlalchemy import UniqueConstraint

from backend.config import settings

ROOT = Path(__file__).resolve().parents[2]


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def known(defect_id: str, reason: str):
    """Attach readable audit context without weakening the regression gate."""
    def decorator(test):
        test.__doc__ = test.__doc__ or f"{defect_id}: {reason}"
        return test
    return decorator


def _column_is_unique(model, name: str) -> bool:
    column = model.__table__.c[name]
    return bool(column.unique) or any(
        isinstance(c, UniqueConstraint) and name in {x.name for x in c.columns}
        for c in model.__table__.constraints
    )


# Security and tenancy

@known("AUDIT-001", "Razorpay redeliveries can race because payment IDs are not DB-unique")
def test_razorpay_payment_id_is_database_unique():
    from backend.models.schema import BillingCycle
    assert _column_is_unique(BillingCycle, "razorpay_payment_id")


@known("AUDIT-002", "branch calendar collision checks are raceable without a DB constraint")
def test_branch_calendar_id_has_database_uniqueness_backstop():
    from backend.models.schema import Branch
    assert _column_is_unique(Branch, "google_calendar_id")


@known("AUDIT-003", "doctor calendars do not check IDs owned by other tenants")
def test_doctor_calendar_mutations_check_global_ownership():
    text = source("backend/routers/doctors.py")
    helper = text[text.index("async def _assert_calendar_available"):text.index("def _doctor_to_out")]
    mutations = text[text.index("async def create_doctor"):]
    assert "calendar_id_collision_blocked" in helper
    assert "Branch.google_calendar_id" in helper and "Doctor.google_calendar_id" in helper
    assert mutations.count("_assert_calendar_available(") >= 2


@known("AUDIT-004", "clinic erasure leaves support-ticket PII orphaned")
def test_hard_delete_org_erases_support_data():
    text = source("backend/routers/admin.py")
    start = text.index("async def _hard_delete_org")
    region = text[start:text.index("@router.delete", start)]
    assert "SupportTicket" in region and "SupportMessage" in region


@known("AUDIT-005", "all public tickets use the same empty ownership key")
def test_anonymous_support_tickets_have_an_unforgeable_session_owner():
    from backend.models.schema import SupportTicket
    assert "anonymous_session_id" in SupportTicket.__table__.c


@known("AUDIT-006", "deleted staff JWTs remain accepted until expiry")
def test_authentication_revalidates_that_the_user_exists():
    text = source("backend/middleware/auth_middleware.py")
    region = text[text.index("async def get_current_user"):text.index("async def optional_current_user")]
    assert "select(User)" in region or "token_version" in region


@known("AUDIT-007", "frontend logout never revokes the server JWT")
def test_frontend_logout_calls_backend_revocation():
    assert 'api.post("/auth/logout")' in source("frontend/src/api/client.js")
    assert "logoutSession" in source("frontend/src/hooks/useAuth.jsx")


@known("AUDIT-008", "password reset leaves previously issued sessions valid")
def test_password_reset_revokes_existing_sessions():
    text = source("backend/routers/auth.py")
    region = text[text.index("async def reset_password"):]
    assert "revoke_all" in region or "token_version" in region


@pytest.mark.parametrize("missing", ["sub", "email", "role"])
@known("AUDIT-009", "signed JWTs missing required claims raise KeyError/500")
@pytest.mark.asyncio
async def test_missing_required_jwt_claim_is_a_401(monkeypatch, missing):
    from backend.middleware import auth_middleware as auth

    class Redis:
        async def exists(self, _key):
            return 0

    monkeypatch.setattr(auth, "_revocation_redis", lambda: Redis())
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()), "email": "owner@example.test", "role": "org_admin",
        "org_id": str(uuid.uuid4()), "branch_ids": [], "is_admin": False,
        "iat": int(now.timestamp()), "exp": int((now + timedelta(hours=1)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    payload.pop(missing)
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc:
        await auth.get_current_user(credentials)
    assert exc.value.status_code == 401


@known("AUDIT-010", "calendar-test writes externally for any branch member")
def test_calendar_probe_is_owner_only():
    text = source("backend/routers/branches.py")
    start = text.index("async def test_calendar_connection")
    region = text[start:text.index("async def _probe_calendar")]
    assert "_require_org_admin(current_user)" in region


@known("AUDIT-011", "formatted equivalents bypass the emergency-number loop guard")
def test_branch_phone_loop_guard_compares_normalized_numbers():
    from backend.routers.branches import BranchDetailsUpdate
    model = BranchDetailsUpdate(
        clinic_phone="80960 07554",
        emergency_contact="+91-80960-07554",
    )
    assert model.clinic_phone == model.emergency_contact == "+918096007554"


# Validation and API correctness

@known("AUDIT-012", "staff creation accepts malformed emails")
def test_staff_create_rejects_invalid_email():
    from backend.routers.branches import StaffCreate
    with pytest.raises(ValidationError):
        StaffCreate(email="not-an-email", name="Reception", password="LongEnough123!")


@known("AUDIT-013", "staff fields can overflow database VARCHAR columns")
def test_staff_create_bounds_string_lengths():
    from backend.routers.branches import StaffCreate
    with pytest.raises(ValidationError):
        StaffCreate(email=f"{'a' * 260}@x.test", name="n" * 300, password="LongEnough123!")


@known("AUDIT-014", "platform-owner creation accepts malformed emails")
def test_owner_create_rejects_invalid_email():
    from backend.routers.admin import OwnerCreate
    with pytest.raises(ValidationError):
        OwnerCreate(email="bad", name="Owner")


@known("AUDIT-015", "branch strings can overflow database VARCHAR columns")
def test_branch_settings_match_database_lengths():
    from backend.routers.branches import BranchDetailsUpdate
    with pytest.raises(ValidationError):
        BranchDetailsUpdate(name="x" * 300, google_calendar_id="c" * 300)


@known("AUDIT-016", "branch settings accept garbage phone values")
def test_branch_settings_reject_invalid_phones():
    from backend.routers.branches import BranchDetailsUpdate
    with pytest.raises(ValidationError):
        BranchDetailsUpdate(clinic_phone="call-me-maybe", emergency_contact="123")


@known("AUDIT-017", "doctor weekdays accept -1, 7, and duplicates")
def test_doctor_weekdays_are_bounded_and_unique():
    from backend.routers.doctors import DoctorIn
    with pytest.raises(ValidationError):
        DoctorIn(name="Dr Test", booking_type="token", available_weekdays=[-1, 1, 1, 7])


@known("AUDIT-018", "appointment doctors can be created without a usable schedule")
def test_appointment_doctor_requires_slot_configuration():
    from backend.routers.doctors import DoctorIn
    with pytest.raises(ValidationError):
        DoctorIn(name="Dr Test", booking_type="appointment")


@known("AUDIT-019", "PATCH doctor wrongly requires create-only fields")
def test_doctor_patch_accepts_one_changed_field():
    from backend.routers.doctors import DoctorUpdate
    assert DoctorUpdate.model_validate({"specialization": "Cardiology"}).specialization == "Cardiology"


@known("AUDIT-020", "invited doctor emails are not normalized")
def test_doctor_invited_email_is_normalized():
    from backend.routers.doctors import DoctorIn
    model = DoctorIn(name="Dr Test", booking_type="token", invited_email="  DOC@CLINIC.IN ")
    assert model.invited_email == "doc@clinic.in"


@known("AUDIT-021", "OTP provider failure is still reported as sent")
def test_request_otp_checks_delivery_result():
    text = source("backend/routers/auth.py")
    region = text[text.index("async def request_otp"):text.index("class ForgotPasswordRequest")]
    assert "delivery_failed" in region or "status_code=503" in region


# WhatsApp, billing, and determinism

@known("AUDIT-022", "send helpers bypass the credential and plan gate")
@pytest.mark.asyncio
async def test_whatsapp_send_is_noop_without_credentials(monkeypatch):
    from backend.services import wa_service
    calls = []

    async def fake_post(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(settings, "meta_access_token", "", raising=False)
    monkeypatch.setattr(wa_service, "_post", fake_post)
    branch = SimpleNamespace(id=uuid.uuid4(), wa_phone_number_id="123456")
    assert await wa_service.send_text(branch, "+919000000000", "hello") is False
    assert calls == []


@known("AUDIT-023", "inbound WhatsApp handlers ignore the plan gate")
def test_whatsapp_inbound_handlers_enforce_plan_gate():
    webhook = source("backend/routers/whatsapp_webhook.py")
    chat = source("backend/services/wa_chat.py")
    actions = source("backend/services/wa_actions.py")
    assert "handle_text(" in webhook and "db, branch, plan," in webhook
    assert "wa_enabled(branch, plan)" in chat and "wa_enabled(branch, plan)" in actions


@known("AUDIT-024", "same-day bookings are selected in undefined order")
def test_whatsapp_upcoming_booking_order_is_deterministic():
    text = source("backend/services/wa_chat.py")
    start = text.index("async def _upcoming_token_id")
    region = text[start:text.index("async def handle_text")]
    assert all(key in region for key in ("Token.appointment_time", "Token.token_number", "Token.id"))


@known("AUDIT-025", "invoice HTML interpolates tenant text without escaping")
def test_invoice_html_escapes_tenant_values():
    from backend.services.invoice_email import build_invoice_html
    marker = '<img src=x onerror="alert(1)">'
    output = build_invoice_html(
        org_name=marker, plan="clinic", cycle_start=date(2026, 7, 1), cycle_end=date(2026, 7, 31),
        bd={"base": 100, "overage_minutes": 0, "overage_amount": 0, "gst": 0, "total": 100},
        payment_id=marker,
    )
    assert marker not in output and html_lib.escape(marker) in output


@known("AUDIT-026", "invoice label map omits Lite")
def test_lite_invoice_uses_display_label():
    from backend.services.invoice_email import _rows
    assert _rows("lite", {"base": 100, "overage_minutes": 0, "overage_amount": 0})[0][0] == "Lite plan"


@known("AUDIT-027", "GST-waived receipts still claim an 18% tax line")
def test_gst_waived_receipt_omits_tax_claim():
    from backend.services.billing_math import GST_WAIVED
    from backend.services.invoice_email import build_invoice_html
    assert GST_WAIVED is True
    output = build_invoice_html(
        org_name="Clinic", plan="clinic", cycle_start=date(2026, 7, 1), cycle_end=date(2026, 7, 31),
        bd={"base": 100, "overage_minutes": 0, "overage_amount": 0, "gst": 0, "total": 100},
        payment_id="pay_safe",
    )
    assert "18%" not in output


@known("AUDIT-028", "founding trials use raceable count-then-insert allocation")
def test_founding_trial_allocation_is_serialized():
    text = source("backend/routers/auth.py")
    start = text.index("async def register_clinic")
    region = text[start:text.index("@router.post", start + 1)]
    assert "pg_advisory_xact_lock" in region or "with_for_update" in region


# Frontend/runtime/deployment contracts

@pytest.mark.parametrize("relative", ["frontend/src/pages/Availability.jsx", "frontend/src/pages/Treatments.jsx"])
@known("AUDIT-029", "UTC ISO dates show the previous Indian local day near midnight")
def test_frontend_today_uses_local_calendar_date(relative):
    assert "toISOString().slice(0, 10)" not in source(relative)


@known("AUDIT-030", "doctor advice schedules with server date, not branch-local date")
def test_treatment_followup_uses_branch_local_today():
    text = source("backend/routers/treatment.py")
    region = text[text.index("async def doctor_reply"):]
    assert "date.today()" not in region and "ZoneInfo" in region


@known("AUDIT-031", "multiple Turnstile widgets overwrite one global token/reset slot")
def test_turnstile_state_is_scoped_per_widget():
    text = source("frontend/src/api/client.js")
    assert 'let turnstileToken = ""' not in text and "let turnstileReset = null" not in text


@known("AUDIT-032", "Vite proxy omits active API prefixes")
def test_vite_proxy_covers_active_api_prefixes():
    text = source("frontend/vite.config.js")
    for prefix in ("/patients", "/treatment", "/support", "/webhooks"):
        assert f'"{prefix}": toBackend' in text


@known("AUDIT-033", "backend image omits agent/, imported by backend.main")
def test_backend_container_copies_agent_package():
    assert "COPY agent/ agent/" in source("infra/Dockerfile.backend")


@known("AUDIT-034", "Dependabot targets main while this repository uses master")
def test_dependabot_targets_active_branch():
    text = source(".github/dependabot.yml")
    assert 'target-branch: "main"' not in text
    assert text.count('target-branch: "master"') == 4


@known("AUDIT-035", "ZAP misses pull requests targeting master")
def test_zap_scans_master_pull_requests():
    text = source(".github/workflows/zap-baseline.yml")
    assert "master" in text[:text.index("jobs:")]


@known("AUDIT-036", "WhatsApp UI is hidden by a hard-coded source boolean")
def test_whatsapp_ui_uses_runtime_feature_config():
    assert "const WHATSAPP_LIVE = false" not in source("frontend/src/pages/Settings.jsx")


@known("AUDIT-037", "multi-branch users are silently pinned to branch_ids[0]")
def test_frontend_has_branch_selection_state():
    text = source("frontend/src/hooks/useAuth.jsx")
    assert "branch_ids?.[0]" not in text and "selectedBranch" in text


# Product truth/documentation

@known("AUDIT-038", "landing calls 300 minutes '~100 call minutes'")
def test_trial_marketing_uses_actual_minute_bucket():
    text = source("frontend/src/pages/Landing.jsx")
    assert "≈100 call minutes included" not in text and "300 minutes" in text


@known("AUDIT-039", "login advertises trial after founding slots are exhausted")
def test_login_trial_cta_uses_live_slots():
    assert "founding-slots" in source("frontend/src/pages/Login.jsx")


@known("AUDIT-040", "Multi advertises CSV exports with no export implementation")
def test_marketed_csv_export_has_implementation():
    landing = source("frontend/src/pages/Landing.jsx")
    client = source("frontend/src/api/client.js")
    analytics = source("backend/routers/analytics.py")
    assert "CSV exports" not in landing or ("export" in client.lower() and "csv" in analytics.lower())


@known("AUDIT-041", "support KB says Lite has one doctor; code allows three")
def test_support_kb_matches_lite_doctor_limit():
    text = source("docs/support/KNOWLEDGE.md")
    assert "| Lite | ₹1,999/month | 150 minutes (≈55 calls) | 1 |" not in text
    assert "| Lite | ₹1,999/month | 150 minutes (≈55 calls) | up to 3 |" in text


@known("AUDIT-042", "support KB says 4-minute cap after runtime moved to 10")
def test_support_kb_matches_runtime_call_cap():
    text = source("docs/support/KNOWLEDGE.md")
    assert "AI calls capped at 4 minutes" not in text and "10 minutes" in text


@known("AUDIT-043", "support promises GST credit while GST is waived")
def test_support_kb_matches_current_gst_policy():
    assert "reclaim the 18% GST" not in source("docs/support/KNOWLEDGE.md")


# Healthy invariants

def test_plan_source_of_truth_has_current_doctor_caps():
    from backend.services.billing_math import PLANS
    assert [PLANS[p].max_doctors for p in ("lite", "solo", "clinic", "multi")] == [3, 3, 5, None]


def test_whatsapp_entitlement_is_clinic_and_multi_only():
    from backend.services.billing_math import WHATSAPP_PLANS
    assert WHATSAPP_PLANS == frozenset({"clinic", "multi"})


def test_backend_container_drops_root_privileges():
    assert "USER appuser" in source("infra/Dockerfile.backend")


def test_primary_ci_covers_main_and_master():
    assert "branches: [main, master]" in source(".github/workflows/ci.yml")


def test_billing_cycle_org_fk_restricts_deletion():
    from backend.models.schema import BillingCycle
    assert next(iter(BillingCycle.__table__.c.org_id.foreign_keys)).ondelete == "RESTRICT"
