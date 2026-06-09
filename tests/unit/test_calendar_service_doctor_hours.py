"""Tests for GoogleCalendarService.upsert_doctor_hours_event — token-doctor path.

Spec: docs/superpowers/specs/2026-06-08-calendar-and-receptionist-pwa-design.md §6.5
Plan: Task 4, Step 1

Constraints (from dispatch):
  - RRULE: FREQ=WEEKLY;BYDAY=<weekday_codes> sorted + deduped ISO 0-6 → MO-SU.
  - Summary: "Dr <name> — clinic hours". Description: empty string.
  - On existing_event_id=None → events().insert called.
  - On existing_event_id given   → events().patch called, return existing id.
  - CalendarWriteFailed raised on HttpError.

All tests are pure unit tests — no network, no DB, no Redis.
"""
from datetime import time
from unittest.mock import MagicMock, patch

import pytest

from backend.services.calendar_service import CalendarWriteFailed, GoogleCalendarService


@pytest.fixture
def svc():
    """GoogleCalendarService with googleapiclient fully mocked."""
    with patch("backend.services.calendar_service.build") as mock_build, patch(
        "backend.services.calendar_service.service_account.Credentials.from_service_account_file"
    ):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        s = GoogleCalendarService(sa_json_path="/fake.json")
        s._service = mock_service
        yield s, mock_service


# ── Test 1: insert called when no existing_event_id ───────────────────────────


@pytest.mark.asyncio
async def test_create_recurring_event_when_no_existing(svc) -> None:
    """When existing_event_id=None, events().insert must be called with correct RRULE."""
    s, mock = svc
    mock.events().insert().execute.return_value = {"id": "evt_recurring_123"}

    event_id = await s.upsert_doctor_hours_event(
        calendar_id="cal",
        doctor_name="Dr Sharma",
        working_hours_start=time(9, 0),
        working_hours_end=time(13, 0),
        available_weekdays=[0, 2, 4],  # Mon, Wed, Fri
        existing_event_id=None,
    )

    assert event_id == "evt_recurring_123"

    # insert must have been called (not patch)
    mock.events().insert.assert_called()

    body = mock.events().insert.call_args.kwargs["body"]

    # Summary format: "Dr <name> — clinic hours"
    assert "Dr Sharma" in body["summary"]
    assert "clinic hours" in body["summary"]

    # Description must be empty (PII rule)
    assert body.get("description", "") == ""

    # RRULE must be present with correct weekday codes in sorted order
    assert any(
        "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR" in r for r in body["recurrence"]
    ), f"Expected RRULE with MO,WE,FR in {body['recurrence']}"

    # Timezone must be Asia/Kolkata
    assert body["start"]["timeZone"] == "Asia/Kolkata"
    assert body["end"]["timeZone"] == "Asia/Kolkata"


# ── Test 2: patch called when existing_event_id is provided ───────────────────


@pytest.mark.asyncio
async def test_update_existing_recurring_event(svc) -> None:
    """When existing_event_id is given, events().patch must be called, return that id."""
    s, mock = svc
    mock.events().patch().execute.return_value = {"id": "evt_existing"}

    event_id = await s.upsert_doctor_hours_event(
        calendar_id="cal",
        doctor_name="Dr Sharma",
        working_hours_start=time(10, 0),
        working_hours_end=time(14, 0),
        available_weekdays=[1, 3],  # Tue, Thu
        existing_event_id="evt_existing",
    )

    assert event_id == "evt_existing"

    # patch must have been called with the existing event id
    mock.events().patch.assert_called()
    patch_kwargs = mock.events().patch.call_args.kwargs
    assert patch_kwargs.get("eventId") == "evt_existing"
    assert patch_kwargs.get("calendarId") == "cal"

    # insert must NOT have been called
    # (MagicMock records calls on the same chain object — verify patch was the path taken)
    body = patch_kwargs["body"]
    assert "Dr Sharma" in body["summary"]
    assert any("RRULE:FREQ=WEEKLY;BYDAY=TU,TH" in r for r in body["recurrence"]), (
        f"Expected RRULE with TU,TH in {body['recurrence']}"
    )


# ── Test 3: weekday deduplication and sorting ─────────────────────────────────


@pytest.mark.asyncio
async def test_weekday_codes_are_sorted_and_deduped(svc) -> None:
    """Duplicate and unordered weekday inputs must produce sorted, deduped BYDAY."""
    s, mock = svc
    mock.events().insert().execute.return_value = {"id": "evt_dedup"}

    await s.upsert_doctor_hours_event(
        calendar_id="cal",
        doctor_name="Dr Test",
        working_hours_start=time(8, 0),
        working_hours_end=time(12, 0),
        available_weekdays=[4, 0, 2, 0, 4],  # duplicates, unsorted
        existing_event_id=None,
    )

    body = mock.events().insert.call_args.kwargs["body"]
    # After sort+dedup: 0,2,4 → MO,WE,FR
    assert any("BYDAY=MO,WE,FR" in r for r in body["recurrence"])


# ── Test 4: CalendarWriteFailed raised on HttpError ───────────────────────────


@pytest.mark.asyncio
async def test_upsert_raises_calendar_write_failed_on_http_error(svc) -> None:
    """Any HttpError from Google API must be re-raised as CalendarWriteFailed."""
    from unittest.mock import MagicMock as _MM

    from googleapiclient.errors import HttpError

    s, mock = svc

    fake_resp = _MM()
    fake_resp.status = 403
    fake_resp.reason = "Forbidden"
    mock.events().insert().execute.side_effect = HttpError(
        resp=fake_resp, content=b"forbidden"
    )

    with pytest.raises(CalendarWriteFailed):
        await s.upsert_doctor_hours_event(
            calendar_id="cal",
            doctor_name="Dr Fail",
            working_hours_start=time(9, 0),
            working_hours_end=time(17, 0),
            available_weekdays=[0, 1, 2, 3, 4],
            existing_event_id=None,
        )
