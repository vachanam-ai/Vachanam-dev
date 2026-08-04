"""Publish a doctor's real working week to the clinic calendar.

Vinay 2026-08-04: "fix calender. it should update doctors and appointments.
rightnw appointments getting updated in realtime. but, doctors and their slots
appear static from creation of clinic."

WHY THEY WERE STATIC. `GoogleCalendarService.upsert_doctor_hours_event` models
a doctor as ONE repeating block — a single start, a single end, one RRULE. A
doctor who sits 9-12 and again 5-9 cannot be expressed that way, so
`_maybe_upsert_recurring_cal_event` classed them "complex", deleted the block
and returned. Every split-session doctor therefore had no current hours at all,
and whatever the calendar still showed was the simple block written at clinic
setup, before anyone published real sessions.

WHAT THIS DOES INSTEAD. A week is a set of WINDOWS: (start, end, weekdays).
9-12 Mon-Sat plus 5-9 Mon-Fri is two windows, so two weekly recurring events
with their own BYDAY — not thirteen one-off events, and not one lie.

Grouping matters for more than tidiness: Google counts events, and a clinic
with six doctors publishing a month of split sessions would otherwise write
hundreds of single events, which is both slow and hostile to read.
"""
from __future__ import annotations

from datetime import time

import structlog

logger = structlog.get_logger()


def _parse(value: str | None) -> time | None:
    try:
        return time.fromisoformat(value) if value else None
    except (ValueError, TypeError):
        return None


def windows_from_recurring(
    recurring_schedule: dict | None,
) -> list[tuple[time, time, list[int]]]:
    """Weekly schedule -> the fewest (start, end, weekdays) windows that say it.

    Days sharing an identical window are merged onto one recurring event, so
    "9-12 every weekday" is one event with BYDAY=MO,TU,WE,TH,FR rather than
    five.
    """
    by_window: dict[tuple[time, time], list[int]] = {}
    for day, sessions in (recurring_schedule or {}).items():
        try:
            weekday = int(day)
        except (TypeError, ValueError):
            continue
        if not 0 <= weekday <= 6:
            continue
        for session in sessions or []:
            start = _parse((session or {}).get("start"))
            end = _parse((session or {}).get("end"))
            if start is None or end is None or start >= end:
                continue
            by_window.setdefault((start, end), []).append(weekday)

    return [
        (start, end, sorted(set(days)))
        for (start, end), days in sorted(by_window.items())
    ]


def windows_from_legacy(
    working_hours_start: time | None,
    working_hours_end: time | None,
    available_weekdays: list[int] | None,
) -> list[tuple[time, time, list[int]]]:
    """The pre-`recurring_schedule` shape: one window, some weekdays.

    Still the truth for doctors nobody has re-published since the schedule
    editor arrived, so it must keep working rather than silently vanish.
    """
    if not working_hours_start or not working_hours_end:
        return []
    if working_hours_start >= working_hours_end:
        return []
    days = sorted(set(available_weekdays or [0, 1, 2, 3, 4, 5, 6]))
    return [(working_hours_start, working_hours_end, days)] if days else []


def doctor_windows(doctor) -> list[tuple[time, time, list[int]]]:
    """The doctor's real week, from whichever field actually holds it."""
    windows = windows_from_recurring(getattr(doctor, "recurring_schedule", None))
    if windows:
        return windows
    return windows_from_legacy(
        getattr(doctor, "working_hours_start", None),
        getattr(doctor, "working_hours_end", None),
        getattr(doctor, "available_weekdays", None),
    )


async def sync_date_schedule_events(db, branch_id, doctor_id, target_date) -> int:
    """Publish ONE published date's sessions as one-off calendar events.

    Date-specific schedules are the case the weekly RRULE cannot cover: a
    doctor publishing "next Tuesday I sit 10-1 and 6-8" is describing that
    Tuesday only, and a weekly rule would wrongly repeat it forever.

    Returns how many events were written. Best-effort by contract — the caller
    has already committed the schedule, and a calendar outage must not undo it.
    """
    from datetime import datetime

    from sqlalchemy import select

    from backend.models.schema import Branch, Doctor, DoctorDateSchedule
    from backend.services.calendar_service import GoogleCalendarService

    branch = (
        await db.execute(select(Branch).where(Branch.id == branch_id))
    ).scalar_one_or_none()
    if branch is None or not branch.google_calendar_id:
        return 0
    doctor = (
        await db.execute(
            select(Doctor).where(Doctor.id == doctor_id, Doctor.branch_id == branch_id)
        )
    ).scalar_one_or_none()
    if doctor is None:
        return 0
    row = (
        await db.execute(
            select(DoctorDateSchedule).where(
                DoctorDateSchedule.branch_id == branch_id,  # RULE 1
                DoctorDateSchedule.doctor_id == doctor_id,
                DoctorDateSchedule.date == target_date,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return 0

    svc = GoogleCalendarService()
    written = 0
    for session in row.sessions or []:
        start = _parse((session or {}).get("start"))
        end = _parse((session or {}).get("end"))
        if start is None or end is None or start >= end:
            continue
        try:
            await svc.create_timed_event(
                calendar_id=branch.google_calendar_id,
                summary=f"Dr {doctor.name} — clinic hours",
                start_dt=datetime.combine(target_date, start),
                end_dt=datetime.combine(target_date, end),
            )
            written += 1
        except Exception as exc:  # noqa: BLE001 — one bad session is not fatal
            logger.warning(
                "date_schedule_event_failed",
                doctor_id=str(doctor_id), error=str(exc)[:150],
            )
    logger.info(
        "date_schedule_events_published",
        doctor_id=str(doctor_id), date=str(target_date), events=written,
    )
    return written
