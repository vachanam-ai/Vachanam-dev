"""Owner analytics â€” daily series, show rate, source split, per-doctor stats.

Aggregates only (counts and rates, no patient PII in responses).
Rule 1: every query filters branch_id; branch access asserted from JWT.
"""
from datetime import date, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Integer, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.middleware.branch_guard import assert_branch_access
from backend.models.schema import (
    Branch,
    CallLog,
    CallQuality,
    Doctor,
    DoctorUnavailability,
    Organization,
    Patient,
    Token,
)
from backend.services.billing_math import included_minutes_for

logger = structlog.get_logger()
router = APIRouter()

ACTIVE = ["confirmed", "attended", "no_show"]  # cancelled tracked separately


class DayPoint(BaseModel):
    date: str
    booked: int
    attended: int
    no_show: int
    cancelled: int
    show_rate: float | None  # attended / (attended + no_show); None until known


class DoctorRow(BaseModel):
    doctor_name: str
    booking_type: str
    booked: int
    attended: int
    no_show: int
    show_rate: float | None


class LeaveRow(BaseModel):
    doctor_name: str
    date: str
    reason: str | None
    is_today: bool


class CallsDay(BaseModel):
    date: str
    calls: int
    bookings_made: int


class MinutesUsage(BaseModel):
    used: int  # minutes this calendar month
    included: int  # plan allowance
    pct: float


class WeekdayLoad(BaseModel):
    weekday: str  # Mon..Sun
    bookings: int


class Overview(BaseModel):
    today: DayPoint
    pending_today: int  # confirmed, not yet marked
    new_patients_today: int
    daily: list[DayPoint]
    by_doctor: list[DoctorRow]  # over the selected period
    by_source: dict  # source -> bookings over the selected period
    on_leave: list[LeaveRow]  # today + next 30 days
    calls_daily: list[CallsDay]  # answered calls per day (period)
    calls_today: int
    minutes: MinutesUsage  # this month vs plan
    attendance_rate: float | None  # period: attended / (attended + no_show)
    weekday_load: list[WeekdayLoad]  # bookings per weekday over the period


def _show_rate(attended: int, no_show: int) -> float | None:
    seen = attended + no_show
    return round(attended / seen, 3) if seen else None


# ── Call quality (monitoring + feedback loop) ─────────────────────────────────
# Aggregates over the call_quality capture table. Aggregates ONLY — never returns
# the transcript text (PII stays internal for the eval/judge job). Rule 1: every
# query filters branch_id; branch access asserted from the JWT.


class FailRow(BaseModel):
    reason: str
    count: int


class CallQualitySummary(BaseModel):
    total_calls: int
    booked: int
    conversion_rate: float | None  # booked / total
    abandoned: int                 # held a slot, never confirmed
    abandon_rate: float | None
    transfers: int                 # human-transfer requests
    avg_turns: float | None        # patient turns per call
    avg_duration_seconds: float | None
    by_language: dict              # language -> calls
    failures: list[FailRow]        # fail_reason breakdown (booked calls excluded)


@router.get("/analytics/call-quality", response_model=CallQualitySummary)
async def analytics_call_quality(
    branch_id: str,
    days: int = Query(default=14, ge=1, le=90),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import uuid as _uuid
    from datetime import datetime, timezone

    try:
        branch_uuid = _uuid.UUID(branch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch_id format")
    await assert_branch_access(user, branch_id, db)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    base = and_(CallQuality.branch_id == branch_uuid, CallQuality.created_at >= cutoff)  # Rule 1

    agg = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(cast(CallQuality.booking_made, Integer)), 0),
                func.coalesce(func.sum(cast(CallQuality.booking_abandoned, Integer)), 0),
                func.coalesce(func.sum(cast(CallQuality.transfer_requested, Integer)), 0),
                func.avg(CallQuality.turns),
                func.avg(CallQuality.duration_seconds),
            ).where(base)
        )
    ).one()
    total, booked, abandoned, transfers, avg_turns, avg_dur = agg
    total = int(total or 0)

    lang_rows = (
        await db.execute(
            select(CallQuality.language, func.count()).where(base).group_by(CallQuality.language)
        )
    ).all()

    fail_rows = (
        await db.execute(
            select(CallQuality.fail_reason, func.count())
            .where(and_(base, CallQuality.fail_reason.is_not(None)))
            .group_by(CallQuality.fail_reason)
            .order_by(func.count().desc())
        )
    ).all()

    return CallQualitySummary(
        total_calls=total,
        booked=int(booked),
        conversion_rate=round(int(booked) / total, 3) if total else None,
        abandoned=int(abandoned),
        abandon_rate=round(int(abandoned) / total, 3) if total else None,
        transfers=int(transfers),
        avg_turns=round(float(avg_turns), 1) if avg_turns is not None else None,
        avg_duration_seconds=round(float(avg_dur), 1) if avg_dur is not None else None,
        by_language={(lang or "unknown"): n for lang, n in lang_rows},
        failures=[FailRow(reason=r, count=n) for r, n in fail_rows],
    )


@router.get("/analytics/overview", response_model=Overview)
async def analytics_overview(
    branch_id: str,
    days: int = Query(default=14, ge=1, le=90),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Validate format BEFORE the access check (the other routers 400 on
    # garbage; this one relied on asyncpg coercion), then compute "today" in
    # the BRANCH timezone - UTC server time shifts every day-bucket between
    # 00:00 and 05:30 IST.
    import uuid as _uuid

    try:
        branch_uuid = _uuid.UUID(branch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch_id format")
    await assert_branch_access(user, branch_id, db)
    from backend.routers.queue import _branch_today

    today = await _branch_today(branch_uuid, db)
    start = today - timedelta(days=days - 1)

    # One grouped query for the whole period: date x status counts.
    rows = (
        await db.execute(
            select(Token.date, Token.status, func.count())
            .where(
                and_(
                    Token.branch_id == branch_uuid,  # Rule 1
                    Token.date >= start,
                    Token.date <= today,
                )
            )
            .group_by(Token.date, Token.status)
        )
    ).all()

    by_day: dict[date, dict[str, int]] = {}
    for d, status, n in rows:
        by_day.setdefault(d, {})[status] = n

    daily: list[DayPoint] = []
    for i in range(days):
        d = start + timedelta(days=i)
        c = by_day.get(d, {})
        attended, no_show = c.get("attended", 0), c.get("no_show", 0)
        daily.append(
            DayPoint(
                date=d.isoformat(),
                booked=sum(c.get(s, 0) for s in ACTIVE),
                attended=attended,
                no_show=no_show,
                cancelled=c.get("cancelled_by_clinic", 0) + c.get("cancelled_by_patient", 0),
                show_rate=_show_rate(attended, no_show),
            )
        )
    today_point = daily[-1]

    pending_today = (
        await db.execute(
            select(func.count()).select_from(Token).where(
                and_(
                    Token.branch_id == branch_uuid,
                    Token.date == today,
                    Token.status == "confirmed",
                )
            )
        )
    ).scalar_one()

    # B8: bucket "new patients today" in the BRANCH tz, not UTC. func.date() on
    # the created_at timestamptz truncates in the session (UTC) zone while
    # `today` is branch-local (_branch_today), so 00:00-05:30 IST the count was
    # wrong and inconsistent with every other "today" on this page (same class
    # as the M13 CallLog fix below). timezone(tz, ts) converts to local first.
    _patient_tz = (
        await db.execute(select(Branch.timezone).where(Branch.id == branch_uuid))
    ).scalar_one_or_none() or "Asia/Kolkata"
    new_patients_today = (
        await db.execute(
            select(func.count()).select_from(Patient).where(
                and_(
                    Patient.branch_id == branch_uuid,
                    func.date(func.timezone(_patient_tz, Patient.created_at)) == today,
                )
            )
        )
    ).scalar_one()

    doctor_rows = (
        await db.execute(
            select(Doctor.name, Doctor.booking_type, Token.status, func.count())
            .join(Token, Token.doctor_id == Doctor.id)
            .where(
                and_(
                    Token.branch_id == branch_uuid,
                    Token.date >= start,
                    Token.date <= today,
                )
            )
            .group_by(Doctor.name, Doctor.booking_type, Token.status)
        )
    ).all()
    per_doc: dict[str, dict] = {}
    for name, btype, status, n in doctor_rows:
        slot = per_doc.setdefault(name, {"booking_type": btype, "counts": {}})
        slot["counts"][status] = n
    by_doctor = []
    for name, info in sorted(per_doc.items()):
        c = info["counts"]
        attended, no_show = c.get("attended", 0), c.get("no_show", 0)
        by_doctor.append(
            DoctorRow(
                doctor_name=name,
                booking_type=info["booking_type"],
                booked=sum(c.get(s, 0) for s in ACTIVE),
                attended=attended,
                no_show=no_show,
                show_rate=_show_rate(attended, no_show),
            )
        )

    source_rows = (
        await db.execute(
            select(Token.source, func.count())
            .where(
                and_(
                    Token.branch_id == branch_uuid,
                    Token.date >= start,
                    Token.date <= today,
                    Token.status.in_(ACTIVE),
                )
            )
            .group_by(Token.source)
        )
    ).all()

    leave_rows = (
        await db.execute(
            select(Doctor.name, DoctorUnavailability.date, DoctorUnavailability.reason)
            .join(Doctor, DoctorUnavailability.doctor_id == Doctor.id)
            .where(
                and_(
                    DoctorUnavailability.branch_id == branch_uuid,  # Rule 1
                    DoctorUnavailability.date >= today,
                    DoctorUnavailability.date <= today + timedelta(days=30),
                )
            )
            .order_by(DoctorUnavailability.date)
        )
    ).all()

    # â”€â”€ Calls (answered) per day + bookings made on calls â”€â”€
    # M13: bucket calls by BRANCH-LOCAL day, not UTC. func.date() on a
    # timestamptz truncates in the session (UTC) tz, so IST calls 00:00-05:30
    # landed on the previous day's point and disagreed with the booking series
    # (which uses _branch_today). timezone(tz, ts) converts to local first.
    _tzname = (
        await db.execute(select(Branch.timezone).where(Branch.id == branch_uuid))
    ).scalar_one_or_none() or "Asia/Kolkata"
    _call_day = func.date(func.timezone(_tzname, CallLog.started_at))
    call_rows = (
        await db.execute(
            select(
                _call_day,
                func.count(),
                func.sum(cast(CallLog.booking_made, Integer)),
            )
            .where(
                and_(
                    CallLog.branch_id == branch_uuid,  # Rule 1
                    CallLog.answered.is_(True),
                    _call_day >= start,
                )
            )
            .group_by(_call_day)
        )
    ).all()
    calls_by_day = {d: (n, int(b or 0)) for d, n, b in call_rows}
    calls_daily = [
        CallsDay(
            date=(start + timedelta(days=i)).isoformat(),
            calls=calls_by_day.get(start + timedelta(days=i), (0, 0))[0],
            bookings_made=calls_by_day.get(start + timedelta(days=i), (0, 0))[1],
        )
        for i in range(days)
    ]

    # â”€â”€ Minutes used this calendar month vs plan allowance â”€â”€
    month_start = today.replace(day=1)
    used_seconds = (
        await db.execute(
            select(func.coalesce(func.sum(CallLog.duration_seconds), 0)).where(
                and_(
                    CallLog.branch_id == branch_uuid,
                    _call_day >= month_start,  # branch-local day (M13)
                )
            )
        )
    ).scalar_one()
    org_row = (
        await db.execute(
            select(Organization.plan, Organization.status, Organization.minutes_adjustment)
            .join(Branch, Branch.org_id == Organization.id)
            .where(Branch.id == branch_uuid)
        )
    ).first()
    plan, org_status, adj = (
        (org_row[0], org_row[1], org_row[2]) if org_row else ("clinic", "active", 0)
    )
    # Trial clinics get the flat 500-min trial bucket, not the plan allowance;
    # plus the super-admin per-clinic minute adjustment.
    included = included_minutes_for(plan or "clinic", org_status or "active", adj or 0)
    used_min = int(used_seconds // 60)

    # â”€â”€ Attendance rate + weekday load over the period â”€â”€
    total_attended = sum(d.attended for d in daily)
    total_no_show = sum(d.no_show for d in daily)
    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday_counts = [0] * 7
    for d in daily:
        weekday_counts[date.fromisoformat(d.date).weekday()] += d.booked

    return Overview(
        today=today_point,
        pending_today=pending_today,
        new_patients_today=new_patients_today,
        daily=daily,
        by_doctor=by_doctor,
        by_source={s: n for s, n in source_rows},
        calls_daily=calls_daily,
        calls_today=calls_daily[-1].calls if calls_daily else 0,
        minutes=MinutesUsage(
            used=used_min,
            included=included,
            pct=round(min(used_min / included, 1.0) * 100, 1) if included else 0.0,
        ),
        attendance_rate=_show_rate(total_attended, total_no_show),
        weekday_load=[
            WeekdayLoad(weekday=weekday_names[i], bookings=weekday_counts[i])
            for i in range(7)
        ],
        on_leave=[
            LeaveRow(
                doctor_name=name,
                date=d.isoformat(),
                reason=reason,
                is_today=d == today,
            )
            for name, d, reason in leave_rows
        ],
    )
