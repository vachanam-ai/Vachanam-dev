"""Chat booking: slots -> atomic token -> calendar -> confirm (WA MVP1 Task 5).

Reuses the SAME booking primitives the voice path uses, so a booking made over
WhatsApp is indistinguishable in the database from one made by phone:

  - ``agent.tools.booking_tools.route_to_doctor``        (doctor selection)
  - ``agent.tools.booking_tools.resolve_doctor_schedule`` + the same slot-grid
    and Redis/DB occupancy math ``check_availability`` is built on (no second
    "what's free" implementation)
  - ``agent.tools.booking_tools.assign_token``            RULE 2 — the ONLY
    atomic Redis INCR token allocator in the codebase. Never write a second one.
  - ``agent.tools.booking_tools.confirm_booking``         DB write + calendar +
    WhatsApp, in the exact order/guarantees the voice path already has
    (RULE 4: calendar write is part of the booking; WhatsApp send never is).

Spec: docs/superpowers/specs/2026-08-02-whatsapp-pricing-design.md Section 7.1
"No token holds in chat". RULE 3 ("a held token dies with its call") has no
analogue in chat — there is no call to end, and a patient may reply four hours
later. So ``offer_slots()`` is READ-ONLY: it never calls ``assign_token``,
never increments Redis, never writes a Token row. The token is allocated only
inside ``confirm()``, at the exact moment the patient says yes, via the same
atomic INCR the voice path uses. If the slot filled while the patient was
deciding, ``confirm()`` never crashes and never double-books — it reports
``taken=True`` with fresh alternatives.

RULE 9: logs carry ``phone[-4:]``, branch/doctor ids and token numbers —
never patient names or free text.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.tools.booking_tools import (
    _branch_now,
    _redis,
    _redis_int_values,
    _schedule_block_reason,
    assign_token,
    confirm_booking,
    route_to_doctor,
)
from backend.config import settings
from backend.models.schema import Branch, Doctor, Patient, Token
from backend.services.doctor_schedule import resolve_doctor_schedule
from backend.services.validators import normalize_indian_phone

logger = structlog.get_logger()

# WhatsApp replies stay short (Task 4: "at most 3 sentences") — never dump a
# whole day's grid on the patient.
_MAX_OFFERED_SLOTS = 5

# assign_token / confirm_booking failure reasons that mean "someone else
# already has this exact seat/slot" — worth recomputing fresh alternatives
# for. Other refusals (missing details, past slot, off-grid time, ...) are
# not an occupancy race and are surfaced as-is so the router can react
# correctly (e.g. ask for the patient's age, or a different date).
_CAPACITY_REASONS = frozenset({"full", "already_booked", "slot_full"})


class BookingFailed(Exception):
    """RULE 4 — the calendar write is part of the booking. Raised when the
    calendar write fails after a token was atomically allocated; the caller
    already rolled back the DB insert and released the Redis reservation, so
    nothing is left half-written before this propagates."""


@dataclass(frozen=True)
class Slot:
    """One bookable offer: a doctor + date (+ clock time for appointment-type
    doctors; None for a token-queue "next available number"). Carries the
    patient details gathered so far in the conversation so ``confirm()`` can
    complete the booking with nothing more than the phone number — Task 6's
    router owns collecting and attaching these across turns."""

    doctor_id: uuid.UUID
    doctor_name: str
    booking_type: str  # "token" | "appointment"
    date: date
    appointment_time: time | None = None
    patient_name: str = ""
    patient_age: int | None = None
    patient_gender: str | None = None
    complaint: str = ""
    followup_consent: bool = False
    different_person: bool = False
    preferred_language: str | None = None


@dataclass
class BookingResult:
    """``r.token`` (the confirmed ORM row) on success; ``r.taken`` +
    ``r.alternatives`` when the offer expired; ``r.reason``/``r.instruction``
    for any other clean refusal (e.g. a first-time patient's age is missing).
    Never all unset — exactly one branch is populated."""

    token: Token | None = None
    taken: bool = False
    alternatives: list[Slot] = field(default_factory=list)
    reason: str | None = None
    instruction: str | None = None


def _last4(phone: str | None) -> str:
    return (phone or "")[-4:] or "----"


def _normalize_or_raw(phone: str) -> str:
    try:
        return normalize_indian_phone(phone)
    except ValueError:
        # Let confirm_booking's own validation produce the clean, spoken-back
        # error instead of masking it with a silently-unnormalized lookup.
        return phone


class _LazyGoogleCalendar:
    """Defers constructing the real ``GoogleCalendarService`` (which eagerly
    loads Google service-account credentials in ``__init__``) until a
    calendar write is actually about to happen. Token-queue doctors never
    touch the calendar at all (see confirm_booking), so their WhatsApp
    bookings must not fail merely because Google credentials are not
    configured on this deployment."""

    def __init__(self) -> None:
        self._svc: Any = None

    def _get(self) -> Any:
        if self._svc is None:
            # CalendarService, NOT GoogleCalendarService. confirm_booking calls
            # create_booking_event with the LEGACY keyword names
            # (patient_name / patient_phone / token_number / booking_date /
            # appointment_time / slot_duration_minutes); only this subclass
            # accepts them and maps them onto the real implementation. Passing
            # them to the base class raised TypeError inside the retry wrapper,
            # so every WhatsApp appointment booking died as
            # "calendar write failed: RetryError[... raised TypeError]" and the
            # patient read "Something went wrong completing that booking"
            # (Vinay 2026-08-04, live thread). The voice path never hit this —
            # it imports the same subclass via agent.services.calendar_proxy.
            from backend.services.calendar_service import CalendarService

            self._svc = CalendarService()
        return self._svc

    async def create_booking_event(self, **kwargs: Any) -> str:
        return await self._get().create_booking_event(**kwargs)

    async def delete_event(self, *args: Any, **kwargs: Any) -> None:
        return await self._get().delete_event(*args, **kwargs)


async def _llm_route(messages: list[dict]) -> str:
    """RULE 6 primary model (Gemini 2.5 Flash) for the rare ambiguous-doctor
    case. ``route_to_doctor`` already fails safe — it catches ANY exception
    from this call and falls back to the branch's default doctor (RULE 8) —
    so no separate GPT-4o-mini fallback is wired at this call site."""
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=settings.gemini_api_key)
    prompt = "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in messages)
    resp = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=genai_types.GenerateContentConfig(temperature=0, max_output_tokens=300),
    )
    return resp.text or "{}"


_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_ISO_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _parse_booking_date(text: str, now: datetime) -> date:
    """Best-effort English date hint from free chat text. Deliberately
    simple: full multi-language date NLU belongs to the Gemini-backed router
    (Task 6 / ``agent.prompts.whatsapp_prompt``), which can pass an already
    resolved ``booking_date`` kwarg to ``offer_slots`` instead of relying on
    this heuristic."""
    t = (text or "").lower()
    m = _ISO_DATE_RE.search(t)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    if "day after tomorrow" in t:
        return (now + timedelta(days=2)).date()
    if "tomorrow" in t:
        return (now + timedelta(days=1)).date()
    if "today" in t or "now" in t:
        return now.date()
    for name, idx in _WEEKDAYS.items():
        if name in t:
            days_ahead = (idx - now.weekday()) % 7
            days_ahead = days_ahead or 7  # saying "monday" ON monday means NEXT monday
            return (now + timedelta(days=days_ahead)).date()
    # No recognizable hint — default to the next day rather than guessing
    # today (which may already be closed) or silently picking a random date.
    return (now + timedelta(days=1)).date()


def _parse_time_window(text: str) -> tuple[time, time] | None:
    t = (text or "").lower()
    if "morning" in t:
        return time(6, 0), time(12, 0)
    if "afternoon" in t:
        return time(12, 0), time(17, 0)
    if "evening" in t or "night" in t:
        return time(17, 0), time(21, 30)
    return None


async def offer_slots(
    db: AsyncSession,
    branch: Branch,
    text: str,
    *,
    doctor_id: uuid.UUID | None = None,
    booking_date: date | None = None,
    llm_call=None,
    limit: int | None = _MAX_OFFERED_SLOTS,
) -> list[Slot]:
    """READ-ONLY availability lookup (spec Section 7.1) — never reserves
    anything. Reuses ``resolve_doctor_schedule`` (the exact resolver
    ``check_availability`` is built on) so chat honours the identical
    leave / exact-date / recurring / unpublished rules the voice path does,
    and the same Redis-reservation + DB-confirmed occupancy math for
    appointment-type doctors.

    ``doctor_id``/``booking_date`` let a caller (Task 6's router, or
    ``confirm()`` recomputing alternatives) pin the search instead of
    re-routing from free text.

    ``limit`` caps how many open times come back — 5 is right for an OFFER
    ("reply with a time"), but ``limit=None`` returns the doctor's whole
    remaining day so an availability ANSWER can merge them into real free
    ranges ("free 8:00 to 8:15 and 8:30 to 21:00") instead of truncating at
    the fifth slot and lying about the rest.
    """
    # Captured once: if this runs right after confirm()'s own db.rollback()
    # (recomputing alternatives), the ORM `branch` object is expired and a
    # bare `branch.id` would trigger a lazy DB reload outside an awaited
    # context (MissingGreenlet). Plain values stay valid across a rollback.
    branch_id = branch.id
    now = await _branch_now(branch_id, db)

    doctor: Doctor | None = None
    if doctor_id is not None:
        doctor = (
            await db.execute(
                select(Doctor).where(
                    and_(
                        Doctor.id == doctor_id,
                        Doctor.branch_id == branch_id,  # RULE 1
                        Doctor.status == "active",
                    )
                )
            )
        ).scalar_one_or_none()
    if doctor is None:
        route = await route_to_doctor(text, branch_id, db, llm_call or _llm_route)
        candidate_id = route.get("doctor_id")
        if not candidate_id:
            # Ambiguous / out_of_scope / needs_clarification — nothing to
            # offer yet; the router asks a follow-up and calls this again.
            return []
        doctor = (
            await db.execute(
                select(Doctor).where(
                    and_(
                        Doctor.id == uuid.UUID(str(candidate_id)),
                        Doctor.branch_id == branch_id,  # RULE 1
                        Doctor.status == "active",
                    )
                )
            )
        ).scalar_one_or_none()
        if doctor is None:
            return []

    target_date = booking_date or _parse_booking_date(text, now)

    schedule = await resolve_doctor_schedule(doctor, branch_id, target_date, db)
    if _schedule_block_reason(doctor, target_date, schedule, now):
        return []

    if doctor.booking_type == "token":
        redis_key = f"token:{doctor.id}:{branch_id}:{target_date}"
        async with _redis() as r:
            redis_current = int(await r.get(redis_key) or 0)
        db_confirmed = (
            await db.execute(
                select(func.count()).select_from(Token).where(
                    and_(
                        Token.branch_id == branch_id,
                        Token.doctor_id == doctor.id,
                        Token.date == target_date,
                        Token.status == "confirmed",
                    )
                )
            )
        ).scalar_one()
        limit = schedule.token_limit or doctor.daily_token_limit or 50
        if db_confirmed >= limit or redis_current >= limit:
            return []
        return [
            Slot(
                doctor_id=doctor.id, doctor_name=doctor.name, booking_type="token",
                date=target_date, appointment_time=None,
            )
        ]

    # Appointment-type — enumerate real open times using the same grid +
    # occupancy math check_availability uses (never a second implementation).
    if not schedule.sessions or not doctor.slot_duration_minutes:
        return []
    all_slots = schedule.slots(doctor.slot_duration_minutes)
    if target_date == now.date():
        all_slots = [s for s in all_slots if s > now.time()]
    if not all_slots:
        return []

    window = _parse_time_window(text)
    if window:
        start, end = window
        narrowed = [s for s in all_slots if start <= s < end]
        all_slots = narrowed or all_slots  # a window with nothing free still
        # falls back to the day's other times rather than returning empty.

    db_counts: dict[time, int] = {}
    confirmed = await db.execute(
        select(Token.appointment_time).where(
            and_(
                Token.branch_id == branch_id,
                Token.doctor_id == doctor.id,
                Token.date == target_date,
                Token.status == "confirmed",
                Token.appointment_time.is_not(None),
            )
        )
    )
    for (t,) in confirmed.all():
        db_counts[t] = db_counts.get(t, 0) + 1

    slot_keys = [
        f"slot:{doctor.id}:{branch_id}:{target_date}:{s.strftime('%H%M')}"
        for s in all_slots
    ]
    async with _redis() as r:
        reserved_counts = await _redis_int_values(r, slot_keys)

    open_times = [
        slot_time
        for slot_time, reserved in zip(all_slots, reserved_counts)
        if max(reserved, db_counts.get(slot_time, 0)) < (doctor.max_concurrent_per_slot or 1)
    ]

    return [
        Slot(
            doctor_id=doctor.id, doctor_name=doctor.name, booking_type="appointment",
            date=target_date, appointment_time=t,
        )
        for t in (open_times if limit is None else open_times[:limit])
    ]


async def _existing_self_patient(db: AsyncSession, branch_id: uuid.UUID, phone: str) -> Patient | None:
    """Best-effort name fill-in for a returning self-booker — mirrors
    confirm_booking's own "primary owns the phone" rule, read-only here."""
    if not phone:
        return None
    rows = (
        await db.execute(
            select(Patient).where(
                and_(Patient.branch_id == branch_id, Patient.phone == phone)  # RULE 1
            )
        )
    ).scalars().all()
    primary = next((p for p in rows if p.is_primary), None)
    if primary is not None:
        return primary
    return rows[0] if len(rows) == 1 else None


async def _release_hold(redis_key: str | None) -> None:
    """RULE 2 — DECR is rollback-only, never primary. Gives back a token that
    was atomically allocated but whose booking did not complete."""
    if not redis_key:
        return
    try:
        async with _redis() as r:
            await r.decr(redis_key)
    except Exception as e:  # noqa: BLE001 — best-effort cleanup only
        logger.error("wa_booking_hold_release_failed", redis_key=redis_key, error=str(e)[:150])


async def confirm(
    db: AsyncSession,
    branch: Branch,
    phone: str,
    slot: Slot,
    *,
    patient_name: str | None = None,
    patient_age: int | None = None,
    patient_gender: str | None = None,
    followup_consent: bool | None = None,
    complaint: str | None = None,
    different_person: bool | None = None,
    preferred_language: str | None = None,
    calendar_service: Any = None,
    meta_service: Any = None,
    exclude_token_id: uuid.UUID | None = None,
) -> BookingResult:
    """Book ``slot`` for ``phone`` — the ONLY place chat ever reserves a seat.

    Order (RULE 4): allocate the token atomically -> write the calendar event
    (on failure, release the token and DB insert, raise ``BookingFailed``) ->
    send the WhatsApp confirmation (failure logged only, inside
    ``confirm_booking`` itself — never raised here).
    """
    # Captured once, before anything can rollback/expire the ORM object —
    # see the identical note in offer_slots().
    branch_id = branch.id

    norm_phone = _normalize_or_raw(phone) if phone else phone
    name = (patient_name or slot.patient_name or "").strip()
    if not name:
        existing = await _existing_self_patient(db, branch_id, norm_phone or phone)
        name = existing.name if existing else ""

    # RULE 2 — the SAME atomic Redis INCR the voice path uses. offer_slots()
    # never called this; this is the first and only reservation for this
    # booking attempt.
    held = await assign_token(
        doctor_id=slot.doctor_id,
        branch_id=branch_id,
        booking_date=slot.date,
        db=db,
        appointment_time=slot.appointment_time,
    )
    if not held.get("success"):
        # The offer expired while the patient was deciding (spec Section 7.1)
        # — never crash, never double-book, offer what is free right now.
        logger.info(
            "wa_booking_offer_expired",
            branch_id=str(branch_id), doctor_id=str(slot.doctor_id),
            phone_last4=_last4(phone), reason=held.get("reason"),
        )
        alternatives = await offer_slots(
            db, branch, slot.date.isoformat(), doctor_id=slot.doctor_id, booking_date=slot.date,
        )
        return BookingResult(taken=True, alternatives=alternatives, reason=held.get("reason"))

    token_number = held["token_number"]
    redis_key = held.get("redis_key")

    try:
        result = await confirm_booking(
            doctor_id=slot.doctor_id,
            branch_id=branch_id,
            patient_name=name or "WhatsApp Patient",
            patient_phone=norm_phone or phone,
            complaint=complaint if complaint is not None else slot.complaint,
            booking_date=slot.date,
            token_number=token_number,
            followup_consent=bool(
                followup_consent if followup_consent is not None else slot.followup_consent
            ),
            appointment_time=slot.appointment_time,
            source="whatsapp",
            db=db,
            calendar_service=calendar_service or _LazyGoogleCalendar(),
            meta_service=meta_service or _default_meta_service(),
            patient_age=patient_age if patient_age is not None else slot.patient_age,
            patient_gender=patient_gender if patient_gender is not None else slot.patient_gender,
            different_person=bool(
                different_person if different_person is not None else slot.different_person
            ),
            preferred_language=preferred_language or slot.preferred_language,
            # A reschedule books the new seat while the old one is still
            # confirmed, so confirm_booking's duplicate guard would refuse it
            # as `already_booked` — the patient's own appointment blocking
            # their own move. This is exactly what that parameter is for.
            exclude_token_id=exclude_token_id,
        )
    except Exception as exc:  # noqa: BLE001 — RULE 4: calendar write is part of the booking
        # Nothing half-written: undo the flushed-but-uncommitted Token insert
        # AND give back the Redis reservation before this propagates.
        try:
            await db.rollback()
            # rollback() expires every ORM instance in the session. Refresh
            # the caller's `branch` handle so it stays usable afterward (the
            # router likely needs branch.whatsapp_number etc. to reply) —
            # everything else in THIS function already reads plain captured
            # values (branch_id), never the ORM object again.
            await db.refresh(branch)
        except Exception:  # noqa: BLE001 — best-effort session recovery
            pass
        await _release_hold(redis_key)
        logger.error(
            "wa_booking_calendar_write_failed",
            branch_id=str(branch_id), doctor_id=str(slot.doctor_id),
            phone_last4=_last4(phone), error=str(exc)[:200],
        )
        raise BookingFailed(f"calendar write failed: {exc}") from exc

    if not result.get("success"):
        # confirm_booking refused cleanly (capacity re-check race, missing
        # first-time patient details, off-grid time, ...) — no Token row was
        # committed. Give back the reservation either way.
        await _release_hold(redis_key)
        reason = result.get("reason")
        if reason in _CAPACITY_REASONS:
            alternatives = await offer_slots(
                db, branch, slot.date.isoformat(), doctor_id=slot.doctor_id, booking_date=slot.date,
            )
            return BookingResult(
                taken=True, alternatives=alternatives, reason=reason,
                instruction=result.get("instruction"),
            )
        logger.info(
            "wa_booking_confirm_refused",
            branch_id=str(branch_id), doctor_id=str(slot.doctor_id),
            phone_last4=_last4(phone), reason=reason,
        )
        return BookingResult(reason=reason, instruction=result.get("instruction"))

    token_row = (
        await db.execute(
            select(Token).where(
                Token.id == uuid.UUID(str(result["token_id"])),
                Token.branch_id == branch_id,  # RULE 1
            )
        )
    ).scalar_one()
    logger.info(
        "wa_booking_confirmed",
        branch_id=str(branch_id), doctor_id=str(slot.doctor_id),
        phone_last4=_last4(phone), token_number=token_row.token_number,
        booking_type=slot.booking_type,
    )
    return BookingResult(token=token_row)


def _default_meta_service() -> Any:
    from backend.services.meta_service import MetaService

    return MetaService()


# ── change an existing booking (WhatsApp's own, deliberately small) ──────────
# Vinay 2026-08-04: "Keep WhatsApp flow completely separate. Make it simple."
# The voice equivalents live inside the LiveKit agent class and are tangled
# with speech concerns — barge-in protection, spoken fillers, StopResponse,
# authorization-by-utterance. None of that exists in a text thread, so these
# are written plainly here instead of extracted from there.


async def upcoming(db: AsyncSession, branch: Branch, phone: str) -> list[Token]:
    """This caller's changeable bookings at THIS branch, soonest first.

    `Token.date >= today` rather than "still in the future": someone who
    missed this morning's 8:45 and messages at 11 to move it must still find
    it (the same rule the voice path learned on 2026-08-03).
    """
    last10 = _phone_last10(phone)
    if not last10:
        return []
    today = (await _branch_now(branch.id, db)).date()
    return list(
        (
            await db.execute(
                select(Token)
                .join(Patient, Patient.id == Token.patient_id)
                .where(
                    Token.branch_id == branch.id,  # RULE 1
                    Token.status == "confirmed",
                    Token.date >= today,
                    Patient.phone.like(f"%{last10}"),
                )
                .order_by(Token.date, Token.appointment_time.asc().nullslast())
            )
        ).scalars().all()
    )


async def _owned_token(
    db: AsyncSession, branch: Branch, phone: str, token_id: str
) -> Token | None:
    """The booking, only if this number owns it. RULE 1 + the ownership check
    that stops an invented id touching somebody else's appointment."""
    last10 = _phone_last10(phone)
    if not last10:
        return None
    try:
        tid = uuid.UUID(str(token_id))
    except (ValueError, AttributeError, TypeError):
        return None
    return (
        await db.execute(
            select(Token)
            .join(Patient, Patient.id == Token.patient_id)
            .where(
                Token.id == tid,
                Token.branch_id == branch.id,  # RULE 1
                Patient.phone.like(f"%{last10}"),
            )
        )
    ).scalars().first()


def _phone_last10(phone: str | None) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else ""


async def cancel(db: AsyncSession, branch: Branch, phone: str, token_id: str) -> bool:
    """Cancel one of this caller's bookings. True only if something changed.

    Frees the seat as well as marking the row: the Redis reservation is given
    back and the calendar event deleted, or the slot stays blocked for a
    patient who is no longer coming. Calendar failure does NOT undo the
    cancel — the patient has been told it is cancelled, and a stale calendar
    entry is a smaller wrong than a booking the clinic still thinks is live.
    """
    token = await _owned_token(db, branch, phone, token_id)
    if token is None or token.status != "confirmed":
        return False

    token.status = "cancelled_by_patient"
    token.cancellation_reason = "patient cancelled on WhatsApp"
    await db.commit()

    if token.appointment_time is not None:
        await _release_hold(
            f"slot:{token.doctor_id}:{branch.id}:{token.date}:"
            f"{token.appointment_time.strftime('%H%M')}"
        )
    else:
        await _release_hold(f"token:{token.doctor_id}:{branch.id}:{token.date}")

    event_id = getattr(token, "google_calendar_event_id", None)
    if event_id:
        try:
            await _LazyGoogleCalendar().delete_event(branch.google_calendar_id, event_id)
        except Exception as e:  # noqa: BLE001 — see docstring
            logger.warning(
                "wa_cancel_calendar_delete_failed",
                branch_id=str(branch.id), error=str(e)[:150],
            )
    logger.info(
        "wa_booking_cancelled", branch_id=str(branch.id), phone_last4=_last4(phone),
    )
    return True


async def reschedule(
    db: AsyncSession, branch: Branch, phone: str, token_id: str, slot: Slot,
    **confirm_kwargs: Any,
) -> BookingResult:
    """Move a booking: take the NEW seat first, and only then release the old.

    Order is the whole point. Cancelling first and then failing to rebook
    leaves the patient with nothing — the exact failure the voice path guards
    against with its "replacement booking is NOT confirmed yet" tripwire.
    """
    old = await _owned_token(db, branch, phone, token_id)
    if old is None or old.status != "confirmed":
        return BookingResult(reason="booking_not_found")

    result = await confirm(
        db, branch, phone, slot, exclude_token_id=old.id, **confirm_kwargs
    )
    if result.token is None:
        return result  # nothing taken, old booking untouched and still valid

    await cancel(db, branch, phone, str(old.id))
    logger.info(
        "wa_booking_rescheduled", branch_id=str(branch.id),
        phone_last4=_last4(phone),
    )
    return result
