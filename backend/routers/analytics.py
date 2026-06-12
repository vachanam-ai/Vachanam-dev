"""Owner analytics — daily series, show rate, source split, per-doctor stats.

Aggregates only (counts and rates, no patient PII in responses).
Rule 1: every query filters branch_id; branch access asserted from JWT.
"""
from datetime import date, timedelta

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.middleware.branch_guard import assert_branch_access
from backend.models.schema import Doctor, DoctorUnavailability, Patient, Token

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


class Overview(BaseModel):
    today: DayPoint
    pending_today: int  # confirmed, not yet marked
    new_patients_today: int
    daily: list[DayPoint]
    by_doctor: list[DoctorRow]  # over the selected period
    by_source: dict  # source -> bookings over the selected period
    on_leave: list[LeaveRow]  # today + next 30 days


def _show_rate(attended: int, no_show: int) -> float | None:
    seen = attended + no_show
    return round(attended / seen, 3) if seen else None


@router.get("/analytics/overview", response_model=Overview)
async def analytics_overview(
    branch_id: str,
    days: int = Query(default=14, ge=1, le=90),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await assert_branch_access(user, branch_id, db)
    today = date.today()
    start = today - timedelta(days=days - 1)

    # One grouped query for the whole period: date x status counts.
    rows = (
        await db.execute(
            select(Token.date, Token.status, func.count())
            .where(
                and_(
                    Token.branch_id == branch_id,  # Rule 1
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
                cancelled=c.get("cancelled_by_clinic", 0),
                show_rate=_show_rate(attended, no_show),
            )
        )
    today_point = daily[-1]

    pending_today = (
        await db.execute(
            select(func.count()).select_from(Token).where(
                and_(
                    Token.branch_id == branch_id,
                    Token.date == today,
                    Token.status == "confirmed",
                )
            )
        )
    ).scalar_one()

    new_patients_today = (
        await db.execute(
            select(func.count()).select_from(Patient).where(
                and_(
                    Patient.branch_id == branch_id,
                    func.date(Patient.created_at) == today,
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
                    Token.branch_id == branch_id,
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
                    Token.branch_id == branch_id,
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
                    DoctorUnavailability.branch_id == branch_id,  # Rule 1
                    DoctorUnavailability.date >= today,
                    DoctorUnavailability.date <= today + timedelta(days=30),
                )
            )
            .order_by(DoctorUnavailability.date)
        )
    ).all()

    return Overview(
        today=today_point,
        pending_today=pending_today,
        new_patients_today=new_patients_today,
        daily=daily,
        by_doctor=by_doctor,
        by_source={s: n for s, n in source_rows},
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
