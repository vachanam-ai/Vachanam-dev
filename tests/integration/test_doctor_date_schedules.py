import asyncio
import uuid
from datetime import date, datetime, time, timedelta

import pytest
from fastapi import BackgroundTasks, HTTPException, Request
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent.tools.booking_tools import check_availability
import backend.database as _db_module
from backend.models.schema import (
    Branch,
    Doctor,
    DoctorDateSchedule,
    DoctorUnavailability,
    Organization,
    Patient,
    Token,
    User,
)
from backend.middleware.auth_middleware import CurrentUser
from backend.routers.availability import (
    DateScheduleIn,
    DateScheduleRangeIn,
    delete_date_schedule,
    publish_date_schedule,
    publish_date_schedule_range,
)
from backend.routers.doctors import _reject_if_schedule_edit_breaks_bookings
from backend.services.doctor_schedule import doctors_on_shift_at, resolve_doctor_schedule


async def _clinic(db: AsyncSession):
    org = Organization(
        name="Schedule Truth Clinic", owner_phone="+919999999991",
        owner_email="schedule-truth@test.invalid", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="Schedule Truth Branch", timezone="Asia/Kolkata",
        whatsapp_number="+919999999992", did_number="+919999999993",
        emergency_contact="+919999999994", status="active",
    )
    db.add(branch)
    await db.flush()
    doctor = Doctor(
        branch_id=branch.id, name="Dr. Exact", booking_type="appointment",
        schedule_mode="date_specific", recurring_schedule={},
        slot_duration_minutes=30, max_concurrent_per_slot=1, status="active",
    )
    db.add(doctor)
    await db.commit()
    return branch, doctor


@pytest.mark.asyncio
async def test_date_specific_missing_date_is_unpublished_not_unavailable(db):
    branch, doctor = await _clinic(db)
    target = date.today() + timedelta(days=2)
    resolved = await resolve_doctor_schedule(doctor, branch.id, target, db)
    assert resolved.status == "unpublished"
    answer = await check_availability(doctor.id, branch.id, target, db)
    assert "SCHEDULE NOT PUBLISHED" in answer
    assert "on leave" not in answer


@pytest.mark.asyncio
async def test_exact_date_override_supports_two_sessions_and_gap_is_closed(db):
    branch, doctor = await _clinic(db)
    target = date.today() + timedelta(days=2)
    db.add(DoctorDateSchedule(
        branch_id=branch.id, doctor_id=doctor.id, date=target,
        sessions=[
            {"start": "09:00", "end": "12:00"},
            {"start": "17:00", "end": "21:00"},
        ],
    ))
    await db.commit()
    answer = await check_availability(doctor.id, branch.id, target, db)
    assert "9:00 AM to 11:30 AM" in answer
    assert "5:00 PM to 8:30 PM" in answer
    assert "12:00 PM to 5:00 PM" not in answer


@pytest.mark.asyncio
async def test_leave_overrides_even_a_published_date_schedule(db):
    branch, doctor = await _clinic(db)
    target = date.today() + timedelta(days=2)
    db.add_all([
        DoctorDateSchedule(
            branch_id=branch.id, doctor_id=doctor.id, date=target,
            sessions=[{"start": "09:00", "end": "12:00"}],
        ),
        DoctorUnavailability(
            branch_id=branch.id, doctor_id=doctor.id, date=target,
            reason="conference",
        ),
    ])
    await db.commit()
    resolved = await resolve_doctor_schedule(doctor, branch.id, target, db)
    assert resolved.status == "unavailable"
    assert resolved.source == "leave"


@pytest.mark.asyncio
async def test_current_shift_uses_exact_date_sessions_and_excludes_leave(db):
    branch, doctor = await _clinic(db)
    target = date.today() + timedelta(days=2)
    db.add(DoctorDateSchedule(
        branch_id=branch.id,
        doctor_id=doctor.id,
        date=target,
        sessions=[
            {"start": "09:00", "end": "12:00"},
            {"start": "17:00", "end": "21:00"},
        ],
    ))
    recurring = Doctor(
        branch_id=branch.id,
        name="Dr. Recurring",
        booking_type="token",
        schedule_mode="recurring",
        recurring_schedule={
            str(target.weekday()): [{"start": "17:00", "end": "21:00"}]
        },
        status="active",
    )
    on_leave = Doctor(
        branch_id=branch.id,
        name="Dr. Leave",
        booking_type="token",
        schedule_mode="recurring",
        recurring_schedule={
            str(target.weekday()): [{"start": "17:00", "end": "21:00"}]
        },
        status="active",
    )
    db.add_all([recurring, on_leave])
    await db.flush()
    db.add(DoctorUnavailability(
        branch_id=branch.id,
        doctor_id=on_leave.id,
        date=target,
        reason="leave",
    ))
    await db.commit()

    evening = await doctors_on_shift_at(
        branch.id, datetime.combine(target, time(19, 0)), db
    )
    names = {item.name for item in evening}
    assert names == {"Dr. Exact", "Dr. Recurring"}

    afternoon = await doctors_on_shift_at(
        branch.id, datetime.combine(target, time(15, 0)), db
    )
    assert afternoon == []


def _request() -> Request:
    return Request({
        "type": "http", "method": "PUT", "path": "/availability/test",
        "headers": [], "client": ("127.0.0.1", 1), "query_string": b"",
        "server": ("test", 80), "scheme": "http",
    })


def _user(branch_id, *, role="org_admin", user_id=None, org_id=None):
    return CurrentUser(
        user_id=str(user_id or uuid.uuid4()), email="schedule@test.invalid",
        role=role, org_id=str(org_id) if org_id else None, branch_ids=[str(branch_id)],
        is_admin=False, jti=str(uuid.uuid4()),
    )


@pytest.mark.asyncio
async def test_schedule_edit_cannot_orphan_confirmed_appointment(db, redis):
    branch, doctor = await _clinic(db)
    target = date.today() + timedelta(days=2)
    patient = Patient(
        branch_id=branch.id, name="Protected Patient", phone="+919888777666",
        age=30, is_primary=True,
    )
    db.add(patient)
    await db.flush()
    db.add(Token(
        branch_id=branch.id, doctor_id=doctor.id, patient_id=patient.id,
        date=target, appointment_time=time(9, 30), token_number=1,
        source="voice", status="confirmed",
    ))
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await publish_date_schedule.__wrapped__(
            branch_id=str(branch.id), doctor_id=str(doctor.id),
            date_str=target.isoformat(),
            body=DateScheduleIn(sessions=[{"start": "17:00", "end": "21:00"}]),
            request=_request(), current_user=_user(branch.id, org_id=branch.org_id), db=db,
        )
    assert exc.value.status_code == 409
    assert "1 confirmed appointment" in exc.value.detail


@pytest.mark.asyncio
async def test_schedule_range_publishes_every_date_in_one_commit(db, redis):
    branch, doctor = await _clinic(db)
    start = date.today() + timedelta(days=2)
    end = start + timedelta(days=30)
    background_tasks = BackgroundTasks()

    result = await publish_date_schedule_range.__wrapped__(
        branch_id=str(branch.id),
        doctor_id=str(doctor.id),
        body=DateScheduleRangeIn(
            date_from=start,
            date_to=end,
            sessions=[
                {"start": "09:00", "end": "12:00"},
                {"start": "17:00", "end": "21:00"},
            ],
            notes="Doctor confirmed the range",
        ),
        request=_request(),
        background_tasks=background_tasks,
        current_user=_user(branch.id, org_id=branch.org_id),
        db=db,
    )

    expected_dates = [start + timedelta(days=offset) for offset in range(31)]
    assert [item.date for item in result.schedules] == [day.isoformat() for day in expected_dates]
    assert len(background_tasks.tasks) == 1
    rows = (
        await db.execute(
            select(DoctorDateSchedule)
            .where(DoctorDateSchedule.doctor_id == doctor.id)
            .order_by(DoctorDateSchedule.date)
        )
    ).scalars().all()
    assert [row.date for row in rows] == expected_dates
    assert all(row.sessions == result.schedules[0].sessions for row in rows)
    assert all(row.notes == "Doctor confirmed the range" for row in rows)


@pytest.mark.asyncio
async def test_schedule_range_conflict_names_date_and_writes_nothing(db, redis):
    branch, doctor = await _clinic(db)
    doctor_id = doctor.id
    start = date.today() + timedelta(days=2)
    conflict_date = start + timedelta(days=1)
    end = start + timedelta(days=2)
    original_sessions = [{"start": "08:00", "end": "10:00"}]
    patient = Patient(
        branch_id=branch.id,
        name="Range Protected Patient",
        phone="+919888777664",
        age=32,
        is_primary=True,
    )
    db.add(patient)
    await db.flush()
    db.add_all([
        DoctorDateSchedule(
            branch_id=branch.id,
            doctor_id=doctor.id,
            date=start,
            sessions=original_sessions,
            notes="Keep this",
        ),
        Token(
            branch_id=branch.id,
            doctor_id=doctor.id,
            patient_id=patient.id,
            date=conflict_date,
            appointment_time=time(9, 30),
            token_number=1,
            source="voice",
            status="confirmed",
        ),
    ])
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await publish_date_schedule_range.__wrapped__(
            branch_id=str(branch.id),
            doctor_id=str(doctor.id),
            body=DateScheduleRangeIn(
                date_from=start,
                date_to=end,
                sessions=[{"start": "17:00", "end": "21:00"}],
            ),
            request=_request(),
            background_tasks=BackgroundTasks(),
            current_user=_user(branch.id, org_id=branch.org_id),
            db=db,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "message": "Schedule range has conflicts. No dates were changed.",
        "conflicts": [{
            "date": conflict_date.isoformat(),
            "reasons": ["Schedule would invalidate 1 confirmed appointment(s)."],
        }],
    }
    rows = (
        await db.execute(
                select(DoctorDateSchedule)
                .where(DoctorDateSchedule.doctor_id == doctor_id)
            .order_by(DoctorDateSchedule.date)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].date == start
    assert rows[0].sessions == original_sessions
    assert rows[0].notes == "Keep this"


@pytest.mark.asyncio
async def test_schedule_range_rejects_32_dates_before_locking_or_writing(db, redis):
    branch, doctor = await _clinic(db)
    start = date.today() + timedelta(days=2)

    with pytest.raises(HTTPException) as exc:
        await publish_date_schedule_range.__wrapped__(
            branch_id=str(branch.id),
            doctor_id=str(doctor.id),
            body=DateScheduleRangeIn(
                date_from=start,
                date_to=start + timedelta(days=31),
                sessions=[{"start": "09:00", "end": "12:00"}],
            ),
            request=_request(),
            background_tasks=BackgroundTasks(),
            current_user=_user(branch.id, org_id=branch.org_id),
            db=db,
        )

    assert exc.value.status_code == 422
    assert "1 to 31 dates" in exc.value.detail
    assert (
        await db.execute(
            select(DoctorDateSchedule).where(DoctorDateSchedule.doctor_id == doctor.id)
        )
    ).scalars().all() == []


@pytest.mark.asyncio
async def test_schedule_range_waits_for_doctor_config_and_validates_fresh_shape(
    db, redis
):
    branch, doctor = await _clinic(db)
    target = date.today() + timedelta(days=2)
    patient = Patient(
        branch_id=branch.id,
        name="Config Race Patient",
        phone="+919888777663",
        age=33,
        is_primary=True,
    )
    db.add(patient)
    await db.flush()
    db.add(Token(
        branch_id=branch.id,
        doctor_id=doctor.id,
        patient_id=patient.id,
        date=target,
        appointment_time=time(9, 30),
        token_number=1,
        source="voice",
        status="confirmed",
    ))
    await db.commit()

    async with _db_module.AsyncSessionLocal() as writer, _db_module.AsyncSessionLocal() as publisher:
        await writer.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"schedule-config:{branch.id}:{doctor.id}"},
        )
        await writer.execute(
            update(Doctor)
            .where(Doctor.id == doctor.id)
            .values(slot_duration_minutes=60)
        )
        publish = asyncio.create_task(
            publish_date_schedule_range.__wrapped__(
                branch_id=str(branch.id),
                doctor_id=str(doctor.id),
                body=DateScheduleRangeIn(
                    date_from=target,
                    date_to=target,
                    sessions=[{"start": "09:00", "end": "10:00"}],
                ),
                request=_request(),
                background_tasks=BackgroundTasks(),
                current_user=_user(branch.id, org_id=branch.org_id),
                db=publisher,
            )
        )
        try:
            await asyncio.sleep(0.1)
            assert not publish.done(), "range publish read stale doctor config"
        finally:
            await writer.commit()

        with pytest.raises(HTTPException) as exc:
            await asyncio.wait_for(publish, timeout=2)
        assert exc.value.status_code == 409
        assert "1 confirmed appointment" in str(exc.value.detail)

    rows = (
        await db.execute(
            select(DoctorDateSchedule).where(DoctorDateSchedule.doctor_id == doctor.id)
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_unavailable_and_unpublished_dates_project_an_empty_calendar_set(
    db, redis, monkeypatch
):
    from backend.services.doctor_calendar import sync_date_schedule_events

    branch, doctor = await _clinic(db)
    branch.google_calendar_id = "clinic-calendar"
    target = date.today() + timedelta(days=2)
    row = DoctorDateSchedule(
        branch_id=branch.id,
        doctor_id=doctor.id,
        date=target,
        sessions=[],
    )
    db.add(row)
    await db.commit()
    calls = []

    class _Calendar:
        async def replace_date_schedule_events(self, **kwargs):
            calls.append(kwargs)
            return len(kwargs["windows"])

    monkeypatch.setattr(
        "backend.services.calendar_service.GoogleCalendarService", _Calendar
    )

    assert await sync_date_schedule_events(db, branch.id, doctor.id, target) == 0
    assert calls[-1]["windows"] == []
    assert calls[-1]["cleanup_legacy"] is True

    await db.delete(row)
    await db.commit()
    assert await sync_date_schedule_events(db, branch.id, doctor.id, target) == 0
    assert calls[-1]["windows"] == []


@pytest.mark.asyncio
async def test_same_name_doctors_sharing_calendar_disable_legacy_cleanup(
    db, redis, monkeypatch
):
    from backend.services.doctor_calendar import sync_date_schedule_events

    branch, doctor = await _clinic(db)
    branch.google_calendar_id = "shared-clinic-calendar"
    db.add(
        Doctor(
            branch_id=branch.id,
            name=doctor.name,
            booking_type="appointment",
            schedule_mode="date_specific",
            recurring_schedule={},
            slot_duration_minutes=30,
            max_concurrent_per_slot=1,
            status="active",
        )
    )
    await db.commit()
    calls = []

    class _Calendar:
        async def replace_date_schedule_events(self, **kwargs):
            calls.append(kwargs)
            return 0

    monkeypatch.setattr(
        "backend.services.calendar_service.GoogleCalendarService", _Calendar
    )

    target = date.today() + timedelta(days=2)
    assert await sync_date_schedule_events(db, branch.id, doctor.id, target) == 0
    assert calls[-1]["cleanup_legacy"] is False


@pytest.mark.asyncio
async def test_unpublish_commits_then_enqueues_calendar_cleanup(db, redis):
    branch, doctor = await _clinic(db)
    target = date.today() + timedelta(days=2)
    row = DoctorDateSchedule(
        branch_id=branch.id,
        doctor_id=doctor.id,
        date=target,
        sessions=[{"start": "09:00", "end": "12:00"}],
    )
    db.add(row)
    await db.commit()
    row_id = row.id
    background_tasks = BackgroundTasks()

    await delete_date_schedule.__wrapped__(
        branch_id=str(branch.id),
        doctor_id=str(doctor.id),
        date_str=target.isoformat(),
        request=_request(),
        background_tasks=background_tasks,
        current_user=_user(branch.id, org_id=branch.org_id),
        db=db,
    )

    assert await db.get(DoctorDateSchedule, row_id) is None
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].args == (branch.id, doctor.id, [target])


@pytest.mark.asyncio
async def test_linked_doctor_can_publish_self_but_not_another_doctor(db, redis):
    branch, doctor = await _clinic(db)
    linked_id = uuid.uuid4()
    db.add(User(
        id=linked_id, org_id=branch.org_id, email="linked-doctor@test.invalid",
        name="Linked Doctor", role="doctor", branch_ids=[str(branch.id)],
        is_admin=False,
    ))
    await db.flush()
    doctor.user_id = linked_id
    other = Doctor(
        branch_id=branch.id, name="Dr. Other", booking_type="token",
        schedule_mode="date_specific", recurring_schedule={}, status="active",
    )
    db.add(other)
    await db.commit()
    target = date.today() + timedelta(days=2)
    actor = _user(
        branch.id, role="doctor", user_id=linked_id, org_id=branch.org_id
    )

    published = await publish_date_schedule.__wrapped__(
        branch_id=str(branch.id), doctor_id=str(doctor.id),
        date_str=target.isoformat(),
        body=DateScheduleIn(sessions=[{"start": "09:00", "end": "12:00"}]),
        request=_request(), current_user=actor, db=db,
    )
    assert published.status == "available"

    with pytest.raises(HTTPException) as exc:
        await publish_date_schedule.__wrapped__(
            branch_id=str(branch.id), doctor_id=str(other.id),
            date_str=target.isoformat(),
            body=DateScheduleIn(sessions=[{"start": "09:00", "end": "12:00"}]),
            request=_request(), current_user=actor, db=db,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_recurring_edit_cannot_orphan_confirmed_appointment(db):
    branch, doctor = await _clinic(db)
    target = date.today() + timedelta(days=2)
    day_key = str(target.weekday())
    doctor.schedule_mode = "recurring"
    doctor.recurring_schedule = {day_key: [{"start": "09:00", "end": "12:00"}]}
    patient = Patient(
        branch_id=branch.id, name="Recurring Protected", phone="+919888777665",
        age=31, is_primary=True,
    )
    db.add(patient)
    await db.flush()
    db.add(Token(
        branch_id=branch.id, doctor_id=doctor.id, patient_id=patient.id,
        date=target, appointment_time=time(9, 30), token_number=1,
        source="voice", status="confirmed",
    ))
    await db.commit()

    doctor.recurring_schedule = {day_key: [{"start": "17:00", "end": "21:00"}]}
    with pytest.raises(HTTPException) as exc:
        await _reject_if_schedule_edit_breaks_bookings(doctor, branch.id, db)
    assert exc.value.status_code == 409
    assert "confirmed future booking" in exc.value.detail
