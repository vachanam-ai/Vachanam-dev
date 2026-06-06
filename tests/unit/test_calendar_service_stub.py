"""Tests for CalendarService stub (Phase 1 — Gap 6).

All tests are pure unit tests (no DB, no Redis, no network).
"""
import re
from datetime import date, time
from unittest.mock import patch

import pytest

from backend.services.calendar_service import CalendarService


@pytest.fixture()
def svc() -> CalendarService:
    return CalendarService()


@pytest.fixture()
def booking_date() -> date:
    return date(2026, 6, 10)


# ── Test 1 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_calendar_stub_returns_stub_prefixed_uuid(svc: CalendarService, booking_date: date) -> None:
    """Stub must return an event_id that starts with 'stub-' followed by a UUID4."""
    event_id = await svc.create_booking_event(
        calendar_id="cal-abc123",
        patient_name="Ravi Kumar",
        patient_phone="+919876543210",
        token_number=7,
        booking_date=booking_date,
        appointment_time=None,
        doctor_name="Dr. Lakshmi",
    )

    assert event_id.startswith("stub-"), f"Expected 'stub-' prefix, got: {event_id!r}"
    # The remainder should be a valid UUID4 (8-4-4-4-12 hex chars)
    remainder = event_id[len("stub-"):]
    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        re.IGNORECASE,
    )
    assert uuid_pattern.match(remainder), f"Remainder is not a valid UUID4: {remainder!r}"


# ── Test 2 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_calendar_stub_returns_unique_ids_per_call(svc: CalendarService, booking_date: date) -> None:
    """Each stub call must return a different event_id (UUID4 guarantees uniqueness)."""
    id_1 = await svc.create_booking_event(
        calendar_id="cal-1",
        patient_name="Patient A",
        patient_phone="+919000000001",
        token_number=1,
        booking_date=booking_date,
        appointment_time=None,
        doctor_name="Dr. X",
    )
    id_2 = await svc.create_booking_event(
        calendar_id="cal-1",
        patient_name="Patient B",
        patient_phone="+919000000002",
        token_number=2,
        booking_date=booking_date,
        appointment_time=None,
        doctor_name="Dr. X",
    )
    assert id_1 != id_2


# ── Test 3 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_calendar_stub_logs_warning_with_masked_phone(
    svc: CalendarService, booking_date: date
) -> None:
    """Stub must log a 'calendar_stub_used' structlog warning.

    The logged patient_phone field MUST be the last-4 digits only
    (CLAUDE.md Rule 10 — phone[-4:] only in logs).
    """
    captured_events: list[dict] = []

    def fake_warning(event: str, **kwargs) -> None:
        captured_events.append({"event": event, **kwargs})

    from backend.services import calendar_service as cs_module

    with patch.object(cs_module.logger, "warning", fake_warning):
        await svc.create_booking_event(
            calendar_id="cal-abc",
            patient_name="Sita Devi",
            patient_phone="+919876543210",
            token_number=3,
            booking_date=booking_date,
            appointment_time=time(10, 30),
            doctor_name="Dr. Reddy",
        )

    assert len(captured_events) == 1, "Expected exactly 1 log call"
    ev = captured_events[0]
    assert ev["event"] == "calendar_stub_used"
    # Must NOT log the full phone number
    assert ev.get("patient_phone") == "3210", (
        f"Expected masked phone '3210', got {ev.get('patient_phone')!r}"
    )
    # Full number must NOT appear anywhere in logged values
    full_phone = "+919876543210"
    for val in ev.values():
        assert full_phone not in str(val), (
            f"Full phone number leaked into logs under key: {ev}"
        )


# ── Test 4 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_calendar_stub_handles_none_phone(svc: CalendarService, booking_date: date) -> None:
    """Stub must handle None patient_phone gracefully (no AttributeError)."""
    event_id = await svc.create_booking_event(
        calendar_id=None,
        patient_name="Unknown",
        patient_phone=None,
        token_number=1,
        booking_date=booking_date,
        appointment_time=None,
        doctor_name="Dr. Y",
    )
    assert event_id.startswith("stub-")


# ── Test 5 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_calendar_stub_logs_token_and_date(svc: CalendarService, booking_date: date) -> None:
    """Logged event must contain the token number and booking date ISO string."""
    captured_events: list[dict] = []

    def fake_warning(event: str, **kwargs) -> None:
        captured_events.append({"event": event, **kwargs})

    from backend.services import calendar_service as cs_module

    with patch.object(cs_module.logger, "warning", fake_warning):
        await svc.create_booking_event(
            calendar_id="cal-xyz",
            patient_name="Mr. Test",
            patient_phone="+911234567890",
            token_number=42,
            booking_date=booking_date,
            appointment_time=None,
            doctor_name="Dr. Z",
        )

    ev = captured_events[0]
    assert ev["token"] == 42
    assert ev["booking_date"] == "2026-06-10"
