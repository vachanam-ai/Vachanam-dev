"""Tests for real GoogleCalendarService — slot-doctor per-patient event path.

Spec: docs/superpowers/specs/2026-06-08-calendar-and-receptionist-pwa-design.md §6.1-§6.4
Plan: Task 3, Step 1

All tests are pure unit tests — googleapiclient is fully mocked, no network, no DB.
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.services.calendar_service import (
    CalendarNotConfiguredError,
    CalendarWriteFailed,
    GoogleCalendarService,
)


@pytest.fixture
def svc():
    """Fixture: GoogleCalendarService with mocked google libraries."""
    with patch("backend.services.calendar_service.build") as mock_build, patch(
        "backend.services.calendar_service.service_account.Credentials.from_service_account_file"
    ):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        s = GoogleCalendarService(sa_json_path="/fake/path.json")
        s._service = mock_service
        yield s, mock_service


# ── Test 1: summary format compliance ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_event_summary_format(svc) -> None:
    """Event summary must match 'Apt — {first_name} (xx{last4})' format."""
    s, mock = svc
    mock.events().insert().execute.return_value = {"id": "evt_abc"}

    event_id = await s.create_booking_event(
        calendar_id="cal_id",
        patient_first_name="Suresh",
        patient_phone_last4="5891",
        appointment_dt=datetime(2026, 6, 20, 15, 0),
        duration_minutes=30,
        doctor_name="Dr Reddy",
    )

    assert event_id == "evt_abc"
    call_args = mock.events().insert.call_args
    # body may be positional or keyword arg
    kwargs = call_args.kwargs
    body = kwargs.get("body")
    if body is None and len(call_args.args) > 1:
        body = call_args.args[1]
    assert body is not None, "events().insert was not called with a body"
    assert "Apt — Suresh (xx5891)" in body["summary"]
    # PII rule: description MUST be empty string
    assert body.get("description", "") == ""


# ── Test 2: no full phone number in summary ────────────────────────────────────


@pytest.mark.asyncio
async def test_create_event_no_full_phone_in_summary(svc) -> None:
    """Summary must contain only last-4 digits (xx{last4}), never a full phone number."""
    s, mock = svc
    mock.events().insert().execute.return_value = {"id": "evt_xyz"}

    await s.create_booking_event(
        calendar_id="c",
        patient_first_name="Ravi",
        patient_phone_last4="9999",
        appointment_dt=datetime(2026, 6, 20, 10, 0),
        duration_minutes=15,
        doctor_name="Dr A",
    )

    body_summary = mock.events().insert.call_args.kwargs["body"]["summary"]
    # Full phone patterns must not appear
    assert "+91" not in body_summary
    assert "9XXXX" not in body_summary
    # Last-4 obfuscated form must appear
    assert "xx9999" in body_summary


# ── Test 3: raises CalendarNotConfiguredError on None calendar_id ───────────────


@pytest.mark.asyncio
async def test_create_event_raises_on_no_calendar_id(svc) -> None:
    """Must raise CalendarNotConfiguredError immediately when calendar_id is None."""
    s, _ = svc

    with pytest.raises(CalendarNotConfiguredError):
        await s.create_booking_event(
            calendar_id=None,
            patient_first_name="X",
            patient_phone_last4="1234",
            appointment_dt=datetime(2026, 6, 20, 10, 0),
            duration_minutes=15,
            doctor_name="Dr",
        )


# ── Test 4: raises CalendarWriteFailed on HttpError ───────────────────────────


@pytest.mark.asyncio
async def test_create_event_raises_on_http_error(svc) -> None:
    """Must raise CalendarWriteFailed (wrapping HttpError) when Google API fails."""
    from unittest.mock import MagicMock as _MM
    from googleapiclient.errors import HttpError

    s, mock = svc

    # Build a mock HttpError with required positional args
    fake_resp = _MM()
    fake_resp.status = 403
    fake_resp.reason = "Forbidden"
    http_err = HttpError(resp=fake_resp, content=b"forbidden")
    mock.events().insert().execute.side_effect = http_err

    with pytest.raises(CalendarWriteFailed):
        await s.create_booking_event(
            calendar_id="cal_id",
            patient_first_name="Test",
            patient_phone_last4="0001",
            appointment_dt=datetime(2026, 6, 20, 12, 0),
            duration_minutes=20,
            doctor_name="Dr B",
        )


# ── Test 4b (bounty B6): non-HttpError also wraps into CalendarWriteFailed ─────


@pytest.mark.asyncio
async def test_b6_non_http_error_wraps_into_calendar_write_failed(svc) -> None:
    """A socket timeout / auth refresh / SSL error during events().insert must
    ALSO surface as CalendarWriteFailed, so the retry/enqueue wrappers catch it
    (otherwise the walk-in route 500s post-commit and no retry task is queued)."""
    s, mock = svc
    mock.events().insert().execute.side_effect = TimeoutError("socket timed out")

    with pytest.raises(CalendarWriteFailed):
        await s.create_booking_event(
            calendar_id="cal_id",
            patient_first_name="Test",
            patient_phone_last4="0002",
            appointment_dt=datetime(2026, 6, 20, 12, 0),
            duration_minutes=20,
            doctor_name="Dr B",
        )


# ── Test 5: delete_event treats 404 as success ────────────────────────────────


@pytest.mark.asyncio
async def test_delete_event_404_is_success(svc) -> None:
    """delete_event must silently succeed if Google returns 404 (already deleted)."""
    from unittest.mock import MagicMock as _MM
    from googleapiclient.errors import HttpError

    s, mock = svc

    fake_resp = _MM()
    fake_resp.status = 404
    fake_resp.reason = "Not Found"
    mock.events().delete().execute.side_effect = HttpError(
        resp=fake_resp, content=b"not found"
    )

    # Should not raise
    await s.delete_event(calendar_id="cal_id", event_id="evt_gone")


# ── Test 6: update_event calls patch API ──────────────────────────────────────


@pytest.mark.asyncio
async def test_update_event_calls_patch(svc) -> None:
    """update_event must call events().patch() with correct calendar_id + event_id."""
    s, mock = svc
    mock.events().patch().execute.return_value = {"id": "evt_update"}

    await s.update_event(
        calendar_id="cal_update",
        event_id="evt_update",
        new_dt=datetime(2026, 6, 21, 9, 0),
        duration_minutes=45,
    )

    mock.events().patch.assert_called()
    kwargs = mock.events().patch.call_args.kwargs
    assert kwargs.get("calendarId") == "cal_update"
    assert kwargs.get("eventId") == "evt_update"
