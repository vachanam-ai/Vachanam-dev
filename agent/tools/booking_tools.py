import json
from datetime import date, timedelta, datetime, time
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.session_state import SessionState
from backend.config import settings
from backend.models.schema import Doctor, Token, Patient, Branch
from backend.services.audit_service import write_audit_row

logger = structlog.get_logger()


def _redis():
    """Create a fresh Redis client. Use as `async with _redis() as r:`.

    Per-call client (not module-level) avoids event-loop binding bugs:
    a module-level client created at import time becomes invalid after
    its loop closes (visible in tests with one loop per function, and
    possible in production if uvicorn ever resets the loop). Cost is
    ~1-2ms per call on localhost — negligible vs LLM/STT on the call path.
    """
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def route_to_doctor(
    complaint: str,
    branch_id: UUID,
    db: AsyncSession,
    llm_call,  # callable: async (messages: list) -> str
) -> dict:
    """Match a patient complaint to the best-fit active doctor for this branch.

    Call this once the patient has stated their health issue. Pass the complaint
    exactly as spoken — do not translate or paraphrase. Uses an LLM to match
    keywords and specializations. Returns the doctor to use for subsequent tools.

    Args:
        complaint: Patient's health complaint in Telugu, Hindi, or English.

    Returns:
        {"doctor_id": str, "confidence": "high"|"low"|"none"}
    """
    result = await db.execute(
        select(Doctor).where(
            and_(Doctor.branch_id == branch_id, Doctor.status == "active")
        )
    )
    doctors = result.scalars().all()

    def _hit(d, confidence: str) -> dict:
        # name + specialization returned so the agent SPEAKS both:
        # "ఇషితా గారు, డయాబెటిస్ స్పెషలిస్ట్" — not just the name.
        return {
            "doctor_id": str(d.id),
            "doctor_name": d.name,
            "specialization": d.specialization,
            "confidence": confidence,
        }

    if len(doctors) == 1:
        return _hit(doctors[0], "high")

    doctors_json = [
        {
            "id": str(d.id),
            "name": d.name,
            "specialization": d.specialization,
            "routing_keywords": d.routing_keywords or [],
            "is_default": d.is_default_doctor,
        }
        for d in doctors
    ]

    prompt = [
        {
            "role": "user",
            "content": (
                f"Patient complaint: '{complaint}'\n"
                f"Doctors: {json.dumps(doctors_json, ensure_ascii=False)}\n"
                "Return JSON only: {\"doctor_id\": \"<uuid or null>\", \"confidence\": \"high|low|none\"}"
            ),
        }
    ]

    try:
        response = await llm_call(prompt)
        # LLMs love ```json fences — keep only the {...} payload.
        raw = response.strip()
        if "{" in raw:
            raw = raw[raw.index("{") : raw.rindex("}") + 1]
        parsed = json.loads(raw)
        chosen = next(
            (d for d in doctors if str(d.id) == str(parsed.get("doctor_id"))), None
        )
        if chosen is None or parsed.get("confidence") == "none":
            default = next((d for d in doctors if d.is_default_doctor), doctors[0])
            return _hit(default, "none")
        return _hit(chosen, parsed.get("confidence", "low"))
    except Exception as e:
        logger.error("route_to_doctor_failed", error=str(e))
        default = next((d for d in doctors if d.is_default_doctor), doctors[0])
        return _hit(default, "none")


async def check_availability(
    doctor_id: UUID,
    branch_id: UUID,
    booking_date: date,
    db: AsyncSession,
    query_start: time | None = None,
    query_end: time | None = None,
) -> str:
    """Check whether the selected doctor has capacity on the given date.

    Call this after route_to_doctor to confirm availability before taking the
    patient's date preference. For token-type doctors, returns current queue
    size and the patient's expected token number. For appointment-type, returns
    available time ranges. Always call before assign_token.

    Args:
        booking_date: The date the patient wants to book (date object).

    Returns:
        Human-readable availability string in the patient's language.
    """
    result = await db.execute(
        select(Doctor).where(and_(Doctor.id == doctor_id, Doctor.branch_id == branch_id))
    )
    doctor = result.scalar_one_or_none()
    if not doctor:
        return "Doctor not found."

    if doctor.booking_type == "token":
        redis_key = f"token:{doctor_id}:{branch_id}:{booking_date}"
        async with _redis() as r:
            current = int(await r.get(redis_key) or 0)
        limit = doctor.daily_token_limit or 50
        if current >= limit:
            next_day = booking_date + timedelta(days=1)
            return f"Doctor is fully booked on {booking_date.strftime('%d %B')}. Next available date is {next_day.strftime('%d %B')}."
        return (
            f"Doctor has {current} patients booked on {booking_date.strftime('%d %B')}. "
            f"You will be token number {current + 1}."
        )

    # Appointment type — compute available ranges
    if not doctor.working_hours_start or not doctor.working_hours_end or not doctor.slot_duration_minutes:
        return "Doctor's schedule is not configured. Please call the clinic directly."

    slots = _generate_slots(
        doctor.working_hours_start,
        doctor.working_hours_end,
        doctor.slot_duration_minutes,
    )
    if query_start and query_end:
        slots = [s for s in slots if query_start <= s < query_end]

    available = []
    async with _redis() as r:
        for slot in slots:
            key = f"slot:{doctor_id}:{branch_id}:{booking_date}:{slot.strftime('%H%M')}"
            booked = int(await r.get(key) or 0)
            if booked < (doctor.max_concurrent_per_slot or 1):
                available.append(slot)

    if not available:
        return f"Doctor is fully booked on {booking_date.strftime('%d %B')}."

    ranges = _merge_to_ranges(available, doctor.slot_duration_minutes)
    range_strs = [
        f"{start.strftime('%I:%M %p').lstrip('0')} to {end.strftime('%I:%M %p').lstrip('0')}"
        for start, end in ranges
    ]
    return f"Doctor is available {' and '.join(range_strs)} on {booking_date.strftime('%d %B')}."


async def assign_token(
    doctor_id: UUID,
    branch_id: UUID,
    booking_date: date,
    db: AsyncSession,
    appointment_time: time | None = None,
) -> dict:
    """Atomically reserve the next available token for this doctor+date using Redis INCR.

    Call this after check_availability confirms capacity AND the patient has agreed
    to the date. Do NOT call if check_availability returned fully booked. Redis INCR
    guarantees no double-booking even with concurrent callers. On full queue, rolls
    back atomically via DECR (DECR is rollback only — never used as primary op).

    Args:
        booking_date: Confirmed booking date (date object).
        appointment_time: Required only for appointment-type doctors.

    Returns:
        {"success": True, "token_number": int, "redis_key": str} or
        {"success": False, "reason": "full"|"doctor_not_found"|"appointment_time_required"}
    """
    result = await db.execute(
        select(Doctor).where(and_(Doctor.id == doctor_id, Doctor.branch_id == branch_id))
    )
    doctor = result.scalar_one_or_none()
    if not doctor:
        return {"success": False, "reason": "doctor_not_found"}

    if doctor.booking_type == "token":
        redis_key = f"token:{doctor_id}:{branch_id}:{booking_date}"
        # Midnight of booking_date + 2h buffer
        midnight = datetime.combine(booking_date + timedelta(days=1), time(0, 0))
        ttl_seconds = int((midnight - datetime.now()).total_seconds()) + 7200

        async with _redis() as r:
            token_number = await r.incr(redis_key)
            await r.expire(redis_key, max(ttl_seconds, 7200))

            limit = doctor.daily_token_limit or 50
            if token_number > limit:
                await r.decr(redis_key)  # rollback — only valid rollback use
                return {"success": False, "reason": "full"}

        logger.info(
            "token_assigned",
            branch_id=str(branch_id),
            doctor_id=str(doctor_id),
            token=token_number,
            date=str(booking_date),
        )
        return {"success": True, "token_number": token_number, "redis_key": redis_key}

    else:  # appointment type
        if not appointment_time:
            return {"success": False, "reason": "appointment_time_required"}

        slot_key = f"slot:{doctor_id}:{branch_id}:{booking_date}:{appointment_time.strftime('%H%M')}"
        slot_dt = datetime.combine(booking_date, appointment_time)
        ttl_seconds = int((slot_dt - datetime.now()).total_seconds()) + 7200

        async with _redis() as r:
            slot_count = await r.incr(slot_key)
            await r.expire(slot_key, max(ttl_seconds, 7200))

            max_per_slot = doctor.max_concurrent_per_slot or 1
            if slot_count > max_per_slot:
                await r.decr(slot_key)  # rollback
                return {"success": False, "reason": "full"}

        logger.info(
            "slot_assigned",
            branch_id=str(branch_id),
            doctor_id=str(doctor_id),
            time=str(appointment_time),
            date=str(booking_date),
        )
        return {
            "success": True,
            "token_number": slot_count,
            "redis_key": slot_key,
            "appointment_time": appointment_time.strftime("%H:%M"),
        }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
async def confirm_booking(
    doctor_id: UUID,
    branch_id: UUID,
    patient_name: str,
    patient_phone: str | None,
    complaint: str,
    booking_date: date,
    token_number: int,
    followup_consent: bool,
    appointment_time: time | None,
    source: str,
    db: AsyncSession,
    calendar_service,   # CalendarService instance (injected)
    meta_service,       # MetaService instance (injected)
) -> dict:
    """Persist the booking: write DB record, create Calendar event, send WhatsApp.

    Call ONLY after assign_token succeeded and the patient has verbally confirmed
    their name, phone number, and date. Calendar creation MUST succeed — raises on
    failure (no silent skip). WhatsApp send is fire-and-forget — failure logged but
    booking is still confirmed. Rule 4: Calendar before WhatsApp, never reversed.

    Args:
        patient_name: Full name as spoken by the patient.
        patient_phone: E.164 format. None if patient declined to share.
        followup_consent: Whether patient agreed to follow-up calls.

    Returns:
        {"success": True, "token_id": str} or {"success": False, "reason": str}
    """
    # 1. Find or create patient
    result = await db.execute(
        select(Patient).where(
            and_(Patient.branch_id == branch_id, Patient.phone == patient_phone)
        )
    )
    patient = result.scalar_one_or_none()
    if not patient:
        patient = Patient(
            branch_id=branch_id,
            name=patient_name,
            phone=patient_phone,
            followup_consent=followup_consent,
        )
        db.add(patient)
        await db.flush()
    else:
        patient.followup_consent = followup_consent

    # 2. Create token record
    token = Token(
        branch_id=branch_id,
        doctor_id=doctor_id,
        patient_id=patient.id,
        date=booking_date,
        token_number=token_number,
        appointment_time=appointment_time,
        source=source,
        status="confirmed",
        confirmed_at=datetime.utcnow(),
    )
    db.add(token)
    await db.flush()

    # 3. Google Calendar (MUST succeed — raises if fails; booking aborts)
    result = await db.execute(
        select(Doctor).where(and_(Doctor.id == doctor_id, Doctor.branch_id == branch_id))
    )
    doctor = result.scalar_one()
    result = await db.execute(select(Branch).where(Branch.id == branch_id))
    branch = result.scalar_one()

    # Capture SQLAlchemy values NOW before session closes
    doctor_name = doctor.name
    doctor_calendar_id = doctor.google_calendar_id
    branch_calendar_id = branch.google_calendar_id
    branch_name = branch.name

    event_id = await calendar_service.create_booking_event(
        calendar_id=doctor_calendar_id or branch_calendar_id,
        patient_name=patient_name,
        patient_phone=patient_phone[-4:] if patient_phone else "unknown",
        token_number=token_number,
        booking_date=booking_date,
        appointment_time=appointment_time,
        doctor_name=doctor_name,
    )
    token.google_calendar_event_id = event_id

    await db.commit()

    logger.info(
        "booking_confirmed",
        branch_id=str(branch_id),
        doctor_id=str(doctor_id),
        token_number=token_number,
        patient_phone=patient_phone[-4:] if patient_phone else "unknown",
        via=source,
    )

    # Audit log — voice path. Fire-and-forget; failure never blocks booking.
    try:
        await write_audit_row(
            action="booking.confirmed",
            resource_type="token",
            resource_id=str(token.id),
            branch_id=branch_id,
            ip_address=None,
            user_agent="voice-agent/1.0",
            metadata={
                "token_number": token_number,
                "doctor_id": str(doctor_id),
                "via": source,
                "calendar_event_id": event_id,
            },
        )
    except Exception as _audit_err:
        logger.error("audit_write_failed_booking_confirmed", error=str(_audit_err))

    # 4. WhatsApp (fire-and-forget — never fails booking)
    if patient_phone:
        try:
            await meta_service.send_booking_confirmation(
                to=patient_phone,
                patient_name=patient_name,
                doctor_name=doctor_name,
                clinic_name=branch_name,
                booking_date=booking_date,
                token_number=token_number,
                appointment_time=appointment_time,
            )
        except Exception as e:
            logger.error("whatsapp_confirmation_failed", error=str(e), token_id=str(token.id))

    return {"success": True, "token_id": str(token.id)}


def _generate_slots(start: time, end: time, duration_minutes: int) -> list[time]:
    slots = []
    current = datetime.combine(date.today(), start)
    end_dt = datetime.combine(date.today(), end)
    delta = timedelta(minutes=duration_minutes)
    while current < end_dt:
        slots.append(current.time())
        current += delta
    return slots


def _merge_to_ranges(slots: list[time], duration_minutes: int) -> list[tuple[time, time]]:
    if not slots:
        return []
    ranges = []
    start = prev = slots[0]
    delta = timedelta(minutes=duration_minutes)
    for slot in slots[1:]:
        prev_dt = datetime.combine(date.today(), prev)
        slot_dt = datetime.combine(date.today(), slot)
        if slot_dt == prev_dt + delta:
            prev = slot
        else:
            prev_end = (datetime.combine(date.today(), prev) + delta).time()
            ranges.append((start, prev_end))
            start = prev = slot
    prev_end = (datetime.combine(date.today(), prev) + delta).time()
    ranges.append((start, prev_end))
    return ranges
