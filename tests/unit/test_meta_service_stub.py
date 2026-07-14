"""MetaService no-op contracts (real service as of WA T4 — the old stub tests
asserted stub-era log events; the CONTRACT that survives is: without wiring it
never raises, never sends, and never logs a full phone number)."""
from datetime import date
from unittest.mock import patch

import pytest

from backend.services.meta_service import MetaService


@pytest.fixture()
def svc() -> MetaService:
    return MetaService()


@pytest.mark.asyncio
async def test_confirmation_without_branch_id_no_ops(svc: MetaService) -> None:
    """Call-site compatibility: legacy calls without branch_id must be a safe
    no-op (RULE 4) — returns None, no exception, nothing sent."""
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


@pytest.mark.asyncio
async def test_doctor_notification_no_ops(svc: MetaService) -> None:
    """Doctor pings are out of WhatsApp scope (spec 2026-07-13) — no-op."""
    result = await svc.send_doctor_notification(
        doctor_phone="+919000000001",
        patient_name="Sita Devi",
        token_number=3,
        appointment_time="14:30",
    )
    assert result is None


@pytest.mark.asyncio
async def test_doctor_notification_log_masks_phone(svc: MetaService) -> None:
    """RULE 9: any log line carries last-4 only, never the full number."""
    captured: list[dict] = []

    def fake_debug(event: str, **kwargs) -> None:
        captured.append({"event": event, **kwargs})

    from backend.services import meta_service as ms_module

    with patch.object(ms_module.logger, "debug", fake_debug):
        await svc.send_doctor_notification(
            doctor_phone="+919000000001",
            patient_name="Sita Devi",
            token_number=3,
        )

    assert len(captured) == 1
    ev = captured[0]
    assert ev["event"] == "wa_doctor_notification_skipped"
    assert ev.get("doctor_last4") == "0001"
    for val in ev.values():
        assert "+919000000001" not in str(val), f"Full phone leaked: {ev}"


@pytest.mark.asyncio
async def test_handles_empty_phones(svc: MetaService) -> None:
    """Empty phone values must not crash either path."""
    await svc.send_doctor_notification(
        doctor_phone="", patient_name="X", token_number=1
    )
    result = await svc.send_booking_confirmation(
        to="", patient_name="X", doctor_name="D", clinic_name="C",
        booking_date=date(2026, 1, 1), token_number=1,
    )
    assert result is None
