"""Authoritative doctor schedule validation and exact-date resolution."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schema import Doctor, DoctorDateSchedule, DoctorUnavailability

ScheduleStatus = Literal["available", "unavailable", "unpublished"]
ScheduleSource = Literal["leave", "date_override", "recurring", "legacy", "unpublished"]


@dataclass(frozen=True)
class SessionWindow:
    start: time
    end: time

    def as_dict(self) -> dict[str, str]:
        return {"start": self.start.strftime("%H:%M"), "end": self.end.strftime("%H:%M")}


@dataclass(frozen=True)
class ResolvedDoctorSchedule:
    status: ScheduleStatus
    source: ScheduleSource
    sessions: tuple[SessionWindow, ...]
    token_limit: int | None
    notes: str | None = None

    @property
    def is_bookable(self) -> bool:
        return self.status == "available" and bool(self.sessions)

    def contains(self, value: time) -> bool:
        return any(window.start <= value < window.end for window in self.sessions)

    def slots(self, duration_minutes: int | None) -> list[time]:
        if not duration_minutes or duration_minutes <= 0:
            return []
        result: list[time] = []
        step = timedelta(minutes=duration_minutes)
        for window in self.sessions:
            current = datetime.combine(date.min, window.start)
            end = datetime.combine(date.min, window.end)
            while current + step <= end:
                result.append(current.time())
                current += step
        return result


def _parse_clock(raw: Any, field: str) -> time:
    if not isinstance(raw, str):
        raise ValueError(f"{field} must be HH:MM")
    try:
        parsed = time.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{field} must be HH:MM") from exc
    if parsed.second or parsed.microsecond:
        raise ValueError(f"{field} must be minute-precision HH:MM")
    return parsed


def validate_sessions(raw_sessions: Any, *, allow_empty: bool = True) -> list[dict[str, str]]:
    """Validate and canonicalize disjoint sessions for one date."""
    if raw_sessions is None:
        raw_sessions = []
    if not isinstance(raw_sessions, list):
        raise ValueError("sessions must be a list")
    if not raw_sessions and not allow_empty:
        raise ValueError("at least one session is required")
    if len(raw_sessions) > 12:
        raise ValueError("a doctor can have at most 12 sessions per day")

    windows: list[SessionWindow] = []
    for index, item in enumerate(raw_sessions):
        if not isinstance(item, dict):
            raise ValueError(f"sessions[{index}] must contain start and end")
        start = _parse_clock(item.get("start"), f"sessions[{index}].start")
        end = _parse_clock(item.get("end"), f"sessions[{index}].end")
        if start >= end:
            raise ValueError(f"sessions[{index}].end must be later than start")
        windows.append(SessionWindow(start=start, end=end))

    windows.sort(key=lambda item: item.start)
    for previous, current in zip(windows, windows[1:]):
        if current.start < previous.end:
            raise ValueError("doctor sessions cannot overlap")
    return [window.as_dict() for window in windows]


def validate_recurring_schedule(raw: Any) -> dict[str, list[dict[str, str]]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("recurring_schedule must be an object keyed by weekday 0 through 6")
    invalid = set(raw) - {str(day) for day in range(7)}
    if invalid:
        raise ValueError("recurring_schedule keys must be weekday numbers 0 through 6")
    return {
        str(day): validate_sessions(raw.get(str(day), []))
        for day in range(7)
        if str(day) in raw
    }


def legacy_recurring_schedule(doctor: Doctor) -> dict[str, list[dict[str, str]]]:
    start = getattr(doctor, "working_hours_start", None)
    end = getattr(doctor, "working_hours_end", None)
    weekdays = getattr(doctor, "available_weekdays", None) or []
    if not start or not end or start >= end:
        return {}
    session = {"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")}
    return {
        str(day): [session]
        for day in weekdays
        if isinstance(day, int) and 0 <= day <= 6
    }


def effective_recurring_schedule(doctor: Doctor) -> dict[str, list[dict[str, str]]]:
    configured = getattr(doctor, "recurring_schedule", None) or {}
    return validate_recurring_schedule(configured) if configured else legacy_recurring_schedule(doctor)


def sessions_as_text(sessions: tuple[SessionWindow, ...] | list[SessionWindow]) -> str:
    return " and ".join(
        f"{item.start.strftime('%I:%M %p').lstrip('0')} to "
        f"{item.end.strftime('%I:%M %p').lstrip('0')}"
        for item in sessions
    )


async def resolve_doctor_schedule(
    doctor: Doctor,
    branch_id: UUID,
    target_date: date,
    db: AsyncSession,
) -> ResolvedDoctorSchedule:
    """Resolve one date, always scoped to the supplied branch."""
    # Leave and exact-date override are independent but share the same unique
    # doctor/date key. Resolve both in one DB round trip; doing them serially
    # added a visible network RTT to every spoken availability answer.
    leave, row = (
        await db.execute(
            select(DoctorUnavailability, DoctorDateSchedule)
            .select_from(Doctor)
            .outerjoin(
                DoctorUnavailability,
                and_(
                    DoctorUnavailability.branch_id == branch_id,
                    DoctorUnavailability.doctor_id == doctor.id,
                    DoctorUnavailability.date == target_date,
                ),
            )
            .outerjoin(
                DoctorDateSchedule,
                and_(
                    DoctorDateSchedule.branch_id == branch_id,
                    DoctorDateSchedule.doctor_id == doctor.id,
                    DoctorDateSchedule.date == target_date,
                ),
            )
            .where(and_(Doctor.id == doctor.id, Doctor.branch_id == branch_id))
        )
    ).one()
    if leave is not None:
        return ResolvedDoctorSchedule(
            status="unavailable", source="leave", sessions=(), token_limit=None,
            notes=leave.reason,
        )

    if row is not None:
        raw = validate_sessions(row.sessions)
        sessions = tuple(
            SessionWindow(_parse_clock(item["start"], "start"), _parse_clock(item["end"], "end"))
            for item in raw
        )
        return ResolvedDoctorSchedule(
            status="available" if sessions else "unavailable",
            source="date_override",
            sessions=sessions,
            token_limit=row.token_limit if row.token_limit is not None else doctor.daily_token_limit,
            notes=row.notes,
        )

    if getattr(doctor, "schedule_mode", "recurring") == "date_specific":
        return ResolvedDoctorSchedule(
            status="unpublished", source="unpublished", sessions=(), token_limit=None,
        )

    recurring = effective_recurring_schedule(doctor)
    if not recurring:
        return ResolvedDoctorSchedule(
            status="unpublished", source="unpublished", sessions=(), token_limit=None,
        )
    raw = recurring.get(str(target_date.weekday()), [])
    sessions = tuple(
        SessionWindow(_parse_clock(item["start"], "start"), _parse_clock(item["end"], "end"))
        for item in raw
    )
    source: ScheduleSource = "recurring" if getattr(doctor, "recurring_schedule", None) else "legacy"
    return ResolvedDoctorSchedule(
        status="available" if sessions else "unavailable",
        source=source,
        sessions=sessions,
        token_limit=doctor.daily_token_limit,
    )
