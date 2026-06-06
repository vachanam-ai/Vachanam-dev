"""Tests for MetaService stub (Phase 1 — Gap 7 / WhatsApp deferred to MVP2).

All tests are pure unit tests (no DB, no Redis, no network).
"""
from datetime import date, time
from unittest.mock import patch

import pytest

from backend.services.meta_service import MetaService


@pytest.fixture()
def svc() -> MetaService:
    return MetaService()


# ── Test 1 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_meta_stub_send_booking_confirmation_no_ops(svc: MetaService) -> None:
    """send_booking_confirmation must return None (no-op) without raising."""
    result = await svc.send_booking_confirmation(
        to="+919876543210",
        patient_name="Ravi Kumar",
        doctor_name="Dr. Lakshmi",
        clinic_name="City Clinic",
        booking_date=date(2026, 6, 10),
        token_number=5,
        appointment_time=None,
    )
    assert result is None


# ── Test 2 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_meta_stub_send_doctor_notification_no_ops(svc: MetaService) -> None:
    """send_doctor_notification must return None (no-op) without raising."""
    result = await svc.send_doctor_notification(
        doctor_phone="+919000000001",
        patient_name="Sita Devi",
        token_number=3,
        appointment_time="14:30",
    )
    assert result is None


# ── Test 3 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_meta_stub_logs_warning_with_masked_phone(svc: MetaService) -> None:
    """send_booking_confirmation must log a structlog warning with last-4 of phone only."""
    captured_events: list[dict] = []

    def fake_warning(event: str, **kwargs) -> None:
        captured_events.append({"event": event, **kwargs})

    from backend.services import meta_service as ms_module

    with patch.object(ms_module.logger, "warning", fake_warning):
        await svc.send_booking_confirmation(
            to="+919876543210",
            patient_name="Sita Devi",
            doctor_name="Dr. Reddy",
            clinic_name="Apollo",
            booking_date=date(2026, 6, 10),
            token_number=7,
        )

    assert len(captured_events) == 1
    ev = captured_events[0]
    assert ev["event"] == "whatsapp_stub_skipped"

    # Masked to last-4 only
    assert ev.get("to_last4") == "3210", (
        f"Expected masked to_last4='3210', got {ev.get('to_last4')!r}"
    )

    # Full phone must NOT appear in any log value
    full_phone = "+919876543210"
    for val in ev.values():
        assert full_phone not in str(val), f"Full phone leaked in log: {ev}"


# ── Test 4 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_meta_stub_doctor_notification_logs_masked_phone(svc: MetaService) -> None:
    """send_doctor_notification must log with doctor_phone_last4 only."""
    captured_events: list[dict] = []

    def fake_warning(event: str, **kwargs) -> None:
        captured_events.append({"event": event, **kwargs})

    from backend.services import meta_service as ms_module

    with patch.object(ms_module.logger, "warning", fake_warning):
        await svc.send_doctor_notification(
            doctor_phone="+918888881234",
            patient_name="Mr. Test",
            token_number=9,
        )

    assert len(captured_events) == 1
    ev = captured_events[0]
    assert ev["event"] == "whatsapp_doctor_notification_stub_skipped"
    assert ev.get("doctor_phone_last4") == "1234"

    full_phone = "+918888881234"
    for val in ev.values():
        assert full_phone not in str(val)


# ── Test 5 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_meta_stub_handles_none_phones(svc: MetaService) -> None:
    """Stub must not crash when phone values are empty strings or trigger graceful None handling."""
    # Empty string — last-4 of "" is "" (no crash)
    await svc.send_booking_confirmation(
        to="",
        patient_name="Unknown",
        doctor_name="Dr. X",
        clinic_name="Test",
        booking_date=date(2026, 1, 1),
        token_number=1,
    )
    await svc.send_doctor_notification(
        doctor_phone="",
        patient_name="Unknown",
        token_number=1,
    )
