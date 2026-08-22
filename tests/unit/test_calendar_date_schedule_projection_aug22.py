"""Exact-date clinic-hour projection is an idempotent replacement."""

from copy import deepcopy
from datetime import date, time

import pytest

from backend.services.calendar_service import GoogleCalendarService


class _Request:
    def __init__(self, action):
        self._action = action

    def execute(self):
        return self._action()


class _Events:
    def __init__(self):
        self.store = {}
        self.inserts = 0
        self.patches = 0
        self.deletes = 0
        self.last_list_kwargs = None

    def list(self, **kwargs):
        self.last_list_kwargs = kwargs
        return _Request(lambda: {"items": [deepcopy(row) for row in self.store.values()]})

    def insert(self, *, calendarId, body):
        assert calendarId == "clinic-calendar"

        def action():
            self.inserts += 1
            self.store[body["id"]] = deepcopy(body)
            return {"id": body["id"]}

        return _Request(action)

    def patch(self, *, calendarId, eventId, body):
        assert calendarId == "clinic-calendar"

        def action():
            self.patches += 1
            self.store[eventId] = {"id": eventId, **deepcopy(body)}
            return {"id": eventId}

        return _Request(action)

    def delete(self, *, calendarId, eventId):
        assert calendarId == "clinic-calendar"

        def action():
            self.deletes += 1
            self.store.pop(eventId, None)
            return None

        return _Request(action)


class _Calendar:
    def __init__(self):
        self.events_api = _Events()

    def events(self):
        return self.events_api


def _service():
    service = object.__new__(GoogleCalendarService)
    service._service = _Calendar()
    return service


async def _replace(service, windows, *, cleanup_legacy=False):
    return await service.replace_date_schedule_events(
        calendar_id="clinic-calendar",
        branch_id="branch-a",
        doctor_id="doctor-a",
        target_date=date(2026, 8, 24),
        doctor_name="Exact",
        windows=windows,
        timezone_name="Asia/Kolkata",
        cleanup_legacy=cleanup_legacy,
    )


@pytest.mark.asyncio
async def test_republish_patches_stable_events_without_duplicates():
    service = _service()
    windows = [(time(9), time(12)), (time(17), time(21))]

    assert await _replace(service, windows) == 2
    first_ids = set(service._service.events_api.store)
    assert len(first_ids) == 2
    assert service._service.events_api.inserts == 2

    assert await _replace(service, windows) == 2
    assert set(service._service.events_api.store) == first_ids
    assert service._service.events_api.inserts == 2
    assert service._service.events_api.patches == 2
    assert service._service.events_api.last_list_kwargs["showDeleted"] is True


@pytest.mark.asyncio
async def test_republishing_removed_hours_restores_the_stable_event():
    service = _service()
    events = service._service.events_api
    windows = [(time(9), time(12))]

    await _replace(service, windows)
    event_id, tombstone = next(iter(events.store.items()))
    await _replace(service, [])
    tombstone["status"] = "cancelled"
    events.store[event_id] = tombstone

    assert await _replace(service, windows) == 1
    assert events.store[event_id]["status"] == "confirmed"
    assert events.patches == 1


@pytest.mark.asyncio
async def test_unavailable_clears_managed_and_legacy_blocks_only():
    service = _service()
    events = service._service.events_api
    await _replace(service, [(time(9), time(12)), (time(17), time(21))])
    events.store["legacy"] = {
        "id": "legacy",
        "summary": "Dr Exact — clinic hours",
        "description": "",
        "start": {"dateTime": "2026-08-24T08:00:00"},
        "end": {"dateTime": "2026-08-24T10:00:00"},
    }
    events.store["other-doctor"] = {
        "id": "other-doctor",
        "summary": "Dr Other — clinic hours",
        "start": {"dateTime": "2026-08-24T09:00:00"},
        "end": {"dateTime": "2026-08-24T12:00:00"},
    }
    events.store["recurring"] = {
        "id": "recurring",
        "summary": "Dr Exact — clinic hours",
        "recurringEventId": "weekly-exact",
        "start": {"dateTime": "2026-08-24T09:00:00"},
        "end": {"dateTime": "2026-08-24T12:00:00"},
    }
    events.store["manual"] = {
        "id": "manual",
        "summary": "Dr Exact — clinic hours",
        "description": "Manually maintained special hours",
        "start": {"dateTime": "2026-08-24T13:00:00"},
        "end": {"dateTime": "2026-08-24T14:00:00"},
    }

    assert await _replace(service, [], cleanup_legacy=True) == 0
    assert set(events.store) == {"other-doctor", "recurring", "manual"}


@pytest.mark.asyncio
async def test_ambiguous_same_name_legacy_block_is_never_claimed():
    service = _service()
    events = service._service.events_api
    events.store["same-name-other-doctor"] = {
        "id": "same-name-other-doctor",
        "summary": "Dr Exact — clinic hours",
        "description": "",
        "start": {"dateTime": "2026-08-24T09:00:00"},
        "end": {"dateTime": "2026-08-24T12:00:00"},
    }

    assert await _replace(service, [], cleanup_legacy=False) == 0
    assert set(events.store) == {"same-name-other-doctor"}
