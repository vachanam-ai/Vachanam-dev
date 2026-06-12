import json
from datetime import date, timedelta, datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.session_state import SessionState
from backend.config import settings
from backend.models.schema import Doctor, DoctorUnavailability, Token, Patient, Branch
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


async def _branch_now(branch_id: UUID, db: AsyncSession) -> datetime:
    """Clock in the BRANCH's timezone — server may run UTC (Fly.io)."""
    result = await db.execute(select(Branch.timezone).where(Branch.id == branch_id))
    tzname = result.scalar_one_or_none() or "Asia/Kolkata"
    try:
        return datetime.now(ZoneInfo(tzname))
    except Exception:
        return datetime.now(ZoneInfo("Asia/Kolkata"))


async def doctor_bookable(
    doctor: Doctor, branch_id: UUID, booking_date: date, db: AsyncSession
) -> str | None:
    """Why this doctor can NOT take this date, or None if bookable.

    Guards that were previously missing entirely: past dates, the doctor's
    working weekdays, receptionist-marked leave (doctor_unavailability), and
    same-day walk-in closure for token doctors.
    """
    now = await _branch_now(branch_id, db)
    today = now.date()
    if booking_date < today:
        return f"{booking_date.strftime('%d %B')} is in the past. Ask for a future date."

    if (
        booking_date == today
        and doctor.working_hours_end
        and now.time() >= doctor.working_hours_end
    ):
        return (
            f"{doctor.name} has finished for today "
            f"({doctor.working_hours_end.strftime('%I:%M %p').lstrip('0')}). "
            "Offer tomorrow or a later day."
        )

    weekdays = doctor.available_weekdays or []
    if weekdays and booking_date.weekday() not in weekdays:
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        sits = ", ".join(names[d] for d in sorted(weekdays))
        return (
            f"{doctor.name} does not sit on {names[booking_date.weekday()]}s. "
            f"Available days: {sits}."
        )

    leave = await db.execute(
        select(DoctorUnavailability.id).where(
            and_(
                DoctorUnavailability.branch_id == branch_id,
                DoctorUnavailability.doctor_id == doctor.id,
                DoctorUnavailability.date == booking_date,
            )
        )
    )
    if leave.scalar_one_or_none() is not None:
        return f"{doctor.name} is on leave on {booking_date.strftime('%d %B')}. Offer another date."

    if (
        doctor.booking_type == "token"
        and booking_date == today
        and doctor.walkins_closed_today_date == today
    ):
        return f"{doctor.name} has closed bookings for today. Offer tomorrow."

    return None


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

    # LATENCY FAST-PATH: direct keyword hit skips the extra LLM round-trip
    # (~1-2s on the call). Only when UNAMBIGUOUS — exactly one doctor's
    # keywords/specialization match; otherwise fall through to the LLM.
    lowered = complaint.lower()
    def _kw_hit(d) -> bool:
        if any(k and k.lower() in lowered for k in (d.routing_keywords or [])):
            return True
        spec = (d.specialization or "").lower()
        return bool(spec) and spec in lowered

    kw_matches = [d for d in doctors if _kw_hit(d)]
    if len(kw_matches) == 1:
        logger.info("route_keyword_fastpath", doctor=kw_matches[0].name)
        return _hit(kw_matches[0], "high")

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
                "List EVERY doctor whose specialization or routing_keywords fit "
                "this complaint (often more than one). Return JSON only: "
                '{"doctor_ids": ["<uuid>", ...], "confidence": "high|low|none"}'
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
        ids = {str(i) for i in parsed.get("doctor_ids") or []}
        if not ids and parsed.get("doctor_id"):  # tolerate old single-id shape
            ids = {str(parsed["doctor_id"])}
        matched = [d for d in doctors if str(d.id) in ids]
        if not matched or parsed.get("confidence") == "none":
            default = next((d for d in doctors if d.is_default_doctor), doctors[0])
            return _hit(default, "none")
        confidence = parsed.get("confidence", "low")
        if len(matched) == 1:
            return _hit(matched[0], confidence)
        # Multiple doctors treat this problem: the AGENT must not pick one.
        # Ask the patient's preferred day/time, check each candidate, offer both.
        return {
            "candidates": [_hit(d, confidence) for d in matched],
            "confidence": confidence,
            "instruction": (
                "MULTIPLE doctors treat this problem. Do NOT choose one yourself. "
                "Ask the patient which day and time suits them, then call "
                "check_availability for EACH candidate doctor_id for that date/time, "
                "and offer the patient the doctors (name + specialization) with "
                "their available windows. Book whichever the patient picks."
            ),
        }
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

    blocked = await doctor_bookable(doctor, branch_id, booking_date, db)
    if blocked:
        return blocked

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

    all_slots = _generate_slots(
        doctor.working_hours_start,
        doctor.working_hours_end,
        doctor.slot_duration_minutes,
    )
    # Same-day booking: never offer a slot that has already passed.
    now = await _branch_now(branch_id, db)
    if booking_date == now.date():
        all_slots = [s for s in all_slots if s > now.time()]

    # Occupancy = max(Redis reservation count, DB confirmed count). Redis is
    # the atomic gate but it is a cache — a Redis restart wiped slot keys and
    # made a confirmed 16:30 booking look free (double-booking risk).
    db_counts: dict[time, int] = {}
    confirmed = await db.execute(
        select(Token.appointment_time).where(
            and_(
                Token.branch_id == branch_id,
                Token.doctor_id == doctor_id,
                Token.date == booking_date,
                Token.status == "confirmed",
                Token.appointment_time.is_not(None),
            )
        )
    )
    for (t,) in confirmed.all():
        db_counts[t] = db_counts.get(t, 0) + 1

    available = []
    async with _redis() as r:
        for slot in all_slots:
            key = f"slot:{doctor_id}:{branch_id}:{booking_date}:{slot.strftime('%H%M')}"
            booked = max(int(await r.get(key) or 0), db_counts.get(slot, 0))
            if booked < (doctor.max_concurrent_per_slot or 1):
                available.append(slot)

    if not available:
        return f"{doctor.name} is fully booked on {booking_date.strftime('%d %B')}."

    def _ranges_str(slot_list: list) -> str:
        ranges = _merge_to_ranges(slot_list, doctor.slot_duration_minutes)
        return " and ".join(
            f"{start.strftime('%I:%M %p').lstrip('0')} to {end.strftime('%I:%M %p').lstrip('0')}"
            for start, end in ranges
        )

    if query_start:
        # LLMs pass "4pm to 4pm" for an exact-time ask — a zero-width window
        # matched nothing and the patient heard "not free" for a FREE slot.
        # Guarantee the window spans at least one slot.
        slot_min = doctor.slot_duration_minutes or 30
        if not query_end or query_end <= query_start:
            qs_dt = datetime.combine(booking_date, query_start)
            query_end = (qs_dt + timedelta(minutes=slot_min)).time()
        in_window = [s for s in available if query_start <= s < query_end]
        if in_window:
            return (
                f"{doctor.name} is available {_ranges_str(in_window)} "
                f"on {booking_date.strftime('%d %B')}."
            )
        # Asked window full — offer the nearest free windows instead of a
        # dead-end "fully booked" (patient picks doctor by time).
        return (
            f"{doctor.name} is NOT free between "
            f"{query_start.strftime('%I:%M %p').lstrip('0')} and "
            f"{query_end.strftime('%I:%M %p').lstrip('0')}, but IS available "
            f"{_ranges_str(available)} on {booking_date.strftime('%d %B')}. "
            "Offer the nearest of these windows to the patient."
        )

    return (
        f"{doctor.name} is available {_ranges_str(available)} "
        f"on {booking_date.strftime('%d %B')}."
    )


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

    blocked = await doctor_bookable(doctor, branch_id, booking_date, db)
    if blocked:
        return {"success": False, "reason": blocked}

    if doctor.booking_type == "token":
        appointment_time = None  # token queue has no clock time — ignore strays
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

        # Requested time must sit on the doctor's slot grid (e.g. hours from
        # 9:00 every 30min -> 16:00 valid, 16:10 not). Snap is the agent's job;
        # here we refuse with the nearest grid times so it can re-offer.
        grid = _generate_slots(
            doctor.working_hours_start,
            doctor.working_hours_end,
            doctor.slot_duration_minutes,
        )
        if grid and appointment_time not in grid:
            nearest = sorted(grid, key=lambda s: abs(
                datetime.combine(booking_date, s) - datetime.combine(booking_date, appointment_time)
            ))[:2]
            return {
                "success": False,
                "reason": "off_grid_time",
                "nearest_slots": [s.strftime("%H:%M") for s in nearest],
            }

        max_per_slot = doctor.max_concurrent_per_slot or 1
        # DB confirmed count closes the Redis-restart hole (cache loss must
        # never allow a double-booking — DB is the source of truth).
        db_confirmed = (
            await db.execute(
                select(func.count()).select_from(Token).where(
                    and_(
                        Token.branch_id == branch_id,
                        Token.doctor_id == doctor_id,
                        Token.date == booking_date,
                        Token.appointment_time == appointment_time,
                        Token.status == "confirmed",
                    )
                )
            )
        ).scalar_one()
        if db_confirmed >= max_per_slot:
            return {"success": False, "reason": "full"}

        slot_key = f"slot:{doctor_id}:{branch_id}:{booking_date}:{appointment_time.strftime('%H%M')}"
        slot_dt = datetime.combine(booking_date, appointment_time)
        ttl_seconds = int((slot_dt - datetime.now()).total_seconds()) + 7200

        async with _redis() as r:
            slot_count = await r.incr(slot_key)
            await r.expire(slot_key, max(ttl_seconds, 7200))

            if max(slot_count, db_confirmed + 1) > max_per_slot:
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


# NOTE: deliberately NO function-level @retry here. The old
# @retry(stop_after_attempt(3)) re-ran the WHOLE function on a transient
# calendar failure, and because the session still held attempt #1's pending
# Token row, attempt #2 added a second one — duplicate bookings on success.
# The only flaky step (Google Calendar) gets its own retry below.
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
    patient_age: int | None = None,
    patient_gender: str | None = None,
    different_person: bool = False,
    exclude_token_id: UUID | None = None,  # reschedule: ignore the booking being replaced
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
    # 0. Phone sanity. Spoken numbers arrive garbled ("nine triple six double
    # four..." became 9-digit 966444428) and were stored as-is, splitting one
    # patient into several records. Reject anything that is not a valid Indian
    # mobile so the agent re-asks digit by digit.
    if patient_phone:
        from backend.services.validators import normalize_indian_phone

        try:
            patient_phone = normalize_indian_phone(patient_phone)
        except ValueError:
            return {
                "success": False,
                "reason": "invalid_phone",
                "instruction": (
                    f"'{patient_phone}' is not a valid 10-digit Indian mobile. "
                    "Re-ask the patient for the number, then read it back in "
                    "ENGLISH digits one by one for confirmation before retrying."
                ),
            }

    # 1. Find or create patient. Match on phone AND name: a caller books for
    # family members too, so several patients legitimately share one phone —
    # matching on phone alone attached the booking to whoever called first.
    result = await db.execute(
        select(Patient).where(
            and_(Patient.branch_id == branch_id, Patient.phone == patient_phone)
        )
    )
    same_phone = result.scalars().all()
    wanted = patient_name.strip().lower()
    patient = next((p for p in same_phone if p.name.strip().lower() == wanted), None)
    if not patient:
        patient = Patient(
            branch_id=branch_id,
            name=patient_name,
            phone=patient_phone,
            age=patient_age,
            gender=patient_gender,
            followup_consent=followup_consent,
        )
        db.add(patient)
        await db.flush()
    else:
        patient.followup_consent = followup_consent
        if patient_age is not None:
            patient.age = patient_age
        if patient_gender:
            patient.gender = patient_gender

    # 1b. Duplicate guard at PHONE level: same phone + doctor + date already
    # confirmed. Name-level matching alone failed (STT spells the same name
    # differently across calls). different_person=True lets a family member
    # sharing the phone book the same doctor the same day.
    dup_filters = [
        Token.branch_id == branch_id,
        Token.doctor_id == doctor_id,
        Token.date == booking_date,
        Token.status == "confirmed",
    ]
    if exclude_token_id is not None:
        dup_filters.append(Token.id != exclude_token_id)
    if patient_phone and not different_person:
        dup_filters.append(
            Token.patient_id.in_(
                select(Patient.id).where(
                    and_(Patient.branch_id == branch_id, Patient.phone == patient_phone)
                )
            )
        )
    else:
        dup_filters.append(Token.patient_id == patient.id)
    dup = await db.execute(select(Token).where(and_(*dup_filters)))
    existing = dup.scalars().first()
    if existing is not None:
        return {
            "success": False,
            "reason": "already_booked",
            "existing_token_number": existing.token_number,
            "existing_time": existing.appointment_time.strftime("%H:%M")
            if existing.appointment_time
            else None,
            "instruction": "Patient already has a confirmed booking that day — "
            "tell them their existing booking instead of creating another.",
        }

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

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def _calendar_write() -> str:
        return await calendar_service.create_booking_event(
            calendar_id=doctor_calendar_id or branch_calendar_id,
            patient_name=patient_name,
            patient_phone=patient_phone[-4:] if patient_phone else "unknown",
            token_number=token_number,
            booking_date=booking_date,
            appointment_time=appointment_time,
            doctor_name=doctor_name,
        )

    event_id = await _calendar_write()
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
