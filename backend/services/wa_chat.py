"""WhatsApp free-text handler — intent router (WA MVP1 Task 6, rewritten).

A patient typed free text to the clinic's WhatsApp. One Gemini call classifies
the intent onto `agent.prompts.whatsapp_prompt.INTENTS` (book, reschedule,
cancel, location, faq, ask_doctor, off_topic) and extracts a handful of
booking fields; deterministic code below decides what happens next and what
is actually said back to the patient — the model never gets to freelance a
reply for anything except `faq` (and even there it is grounded strictly on
the clinic's own FAQ rows, same discipline as before).

    book                 → backend.services.wa_booking (RULE 2's atomic
                            Redis INCR, the SAME allocator the voice path
                            uses — see the ordering-hazard note on
                            `handle_text` before touching this function)
    reschedule | cancel   → the existing wa_actions.handle_change_request
                            clinic-callback flow on the caller's upcoming
                            CONFIRMED booking at this branch
    location              → clinic address + maps link
    faq                   → answered STRICTLY from the clinic's own FAQ rows
    ask_doctor            → a real clinic question the FAQ can't answer
                            (RULE 7: this is ALSO where every symptom/medical
                            question goes — never triaged, never answered by
                            the bot) — logged as a ClinicQuestion so it
                            reaches the doctor and the patient gets a
                            callback (same shape as the voice agent's
                            `log_clinic_question`, agent/livekit_minimal/agent.py)
    off_topic             → prompt injection / general-assistant requests —
                            deflected politely, WITHOUT complying, and never
                            logged as a clinic question (it isn't one)

BANNED (Vinay 2026-08-02): "please call us" / "call the clinic", anywhere,
for any reason. A `wa`-plan clinic has no phone line Vachanam provides —
sending a patient to call is sending them to a number that may not exist.
Every branch below, including Gemini failure and unparseable output
(RULE 8), resolves inside the chat.

RULE 9: the patient's text goes to Gemini for classification but is never
logged; logs carry phone[-4:], branch id and the classified intent only.
"""
from __future__ import annotations

import json
import re
from datetime import date as date_cls, datetime, time, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.prompts.whatsapp_prompt import build_chat_prompt
from backend.models.schema import Branch, ClinicQuestion, Doctor, Patient, PatientMessage, Token
from backend.services import wa_actions, wa_booking, wa_service, wa_session, wa_templates
from backend.services.doctor_schedule import resolve_doctor_schedule, sessions_as_text
from backend.services.resilience import guard
from backend.services.support_bot import _call_gemini
from backend.services.wa_booking import Slot

logger = structlog.get_logger()

# WhatsApp replies stay short (Task 4 style rules) — never dump a whole day's
# grid on the patient.
_MAX_OFFER_LINES = 3

# Appended to whatsapp_prompt.build_chat_prompt()'s output. That module owns
# the classification rules and reply STYLE (Task 4); this is the machine
# contract this router needs on top of it. Deliberately does NOT ask the
# model for a "reply" on book/reschedule/cancel/location/ask_doctor/off_topic
# — those replies are computed deterministically below (RULE 7: no medical
# judgment ever reaches the patient via free model text; RULE 8: no
# hallucinated availability).
_JSON_CONTRACT = (
    # Single braces on purpose: this string is CONCATENATED onto the output of
    # build_chat_prompt(), never passed through str.format(). Doubling them
    # (as an f-string/format template would need) literally instructed the
    # model to emit `{{...}}`, which is not JSON.
    "\n\nReply as compact JSON only, with EXACTLY these keys and no others:\n"
    '{"intent": "<one of greeting, book, reschedule, cancel, doctor_info, '
    'location, faq, ask_doctor, off_topic>", '
    '"answer": "<ONLY when intent=faq — the reply text, answering strictly '
    "from the clinic FAQ above, plain text, max 3 sentences, same language "
    'as the patient; empty otherwise>", '
    '"chosen_time": "<HH:MM if the patient is now confirming one of the '
    "appointment times already offered to them earlier in this conversation, "
    'or a time they just stated themselves; else empty>", '
    '"patient_name": "<the patient\'s full name if stated in THIS message, '
    'else empty>", '
    '"patient_age": <the patient\'s age as a whole number if stated in THIS '
    "message, else null>, "
    '"patient_gender": "<male, female or other if stated or unambiguous, '
    'else empty>", '
    '"doctor_name": "<ONLY when intent=doctor_info — the doctor name the '
    "patient named, copied verbatim from their message, with no title; empty "
    'if they asked about the clinic generally>", '
    '"target_date": "<the calendar date the patient is asking about as '
    'YYYY-MM-DD, resolved against today\'s date above; empty if none>"}'
)


def _faq_text(branch: Branch) -> str:
    rows = branch.faq or []
    if not rows:
        return "(clinic has not provided any FAQ)"
    return "\n".join(
        f"Q: {r.get('q', '')}\nA: {r.get('a', '')}" for r in rows[:20]
    )


def _last4(phone: str | None) -> str:
    return (phone or "")[-4:] or "----"


async def _upcoming_token_id(db: AsyncSession, branch: Branch, sender: str) -> str | None:
    """Sender's next confirmed booking at THIS branch (RULE 1 scoped).
    Meta sends numbers without '+' (919000000042); patients are stored E.164 —
    match on the last 10 digits."""
    last10 = wa_actions._last10(sender)
    if len(last10) < 10:
        return None
    from datetime import datetime
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo(branch.timezone or "Asia/Kolkata")).date()
    token = (
        await db.execute(
            select(Token)
            .join(Patient, Patient.id == Token.patient_id)
            .where(
                Token.branch_id == branch.id,  # RULE 1
                Token.status == "confirmed",
                Token.date >= today,  # audit #7: never a stale past booking
                Patient.phone.like(f"%{last10}"),
            )
            .order_by(
                Token.date,
                Token.appointment_time.asc().nullslast(),
                Token.token_number.asc().nullslast(),
                Token.id,
            )
        )
    ).scalars().first()
    return str(token.id) if token else None


async def _find_patient(db: AsyncSession, branch_id, phone: str) -> Patient | None:
    """Best-effort identity lookup for a ClinicQuestion caller (RULE 1
    scoped) — mirrors the voice agent's own lookup in `log_clinic_question`.
    A miss just means the dashboard shows an unknown caller; never blocks."""
    last10 = wa_actions._last10(phone)
    if len(last10) < 10:
        return None
    return (
        await db.execute(
            select(Patient).where(
                Patient.branch_id == branch_id,  # RULE 1
                Patient.phone.like(f"%{last10}"),
            )
        )
    ).scalars().first()


async def _log_clinic_question(db: AsyncSession, branch: Branch, sender: str, question: str) -> None:
    """Same shape as the voice agent's `log_clinic_question`
    (agent/livekit_minimal/agent.py) — the dashboard's doctor-callback loop
    does not care whether the question arrived by voice or WhatsApp."""
    patient = await _find_patient(db, branch.id, sender)
    q = " ".join((question or "").split())[:300]
    db.add(ClinicQuestion(
        branch_id=branch.id,
        question=q,
        caller_last4=_last4(sender),
        patient_id=patient.id if patient else None,
        caller_phone=sender,
    ))
    await db.commit()
    logger.info(
        "wa_clinic_question_logged", branch_id=str(branch.id), phone_last4=_last4(sender)
    )


async def _no_existing_booking(
    db: AsyncSession, branch: Branch, plan: str, sender: str, what: str
) -> None:
    """Patient asked to reschedule/cancel but has no upcoming CONFIRMED
    booking under this number at this branch. RULE 8/ban: no dead end, no
    "call us" — tell the clinic (same Dashboard Messages card the token-found
    path already uses) and give the patient an honest, helpful reply."""
    db.add(PatientMessage(
        branch_id=branch.id,
        patient_id=None,
        caller_phone=sender,
        message=f"[WhatsApp] Wants to {what} a booking but none was found for this number.",
        urgent=False,
    ))
    await db.commit()
    await wa_service.send_text(
        branch, sender,
        f"I couldn't find an upcoming booking under this number. I've let "
        f"the clinic know so they can help you {what} it.",
        plan=plan,
    )


_GEMINI_DOWN_REPLY = (
    "Sorry, I had trouble understanding that just now — could you try "
    "sending it again in a moment?"
)
_OFF_TOPIC_REPLY = (
    "I can only help with booking, appointments and questions about the "
    "clinic here. Is there something about your visit I can help with?"
)
_ASK_DOCTOR_REPLY = "Let me check that with the doctor and get back to you shortly."
_NO_OPENING_REPLY = (
    "I couldn't find an opening for that — could you tell me a different "
    "day, time or doctor?"
)
_BOOKING_TROUBLE_REPLY = (
    "Something went wrong completing that booking — please try again in a "
    "moment."
)

_REFUSAL_REPLIES: dict[str, str] = {
    "missing_patient_details": (
        "This looks like your first visit here — could you share your "
        "name and age so I can complete the booking?"
    ),
    "not_bookable": "That doctor isn't available on that day — could you try a different day?",
    "off_grid_time": (
        "That exact time isn't available — could you pick one of the times "
        "I offered, or ask for a nearby time?"
    ),
    "past_slot": "That time has already passed — could you pick a later time or a different day?",
    "invalid_phone": "I couldn't confirm a number for that booking — could you share your 10-digit mobile number?",
    "doctor_not_found": "I couldn't find that doctor — could you tell me which doctor or specialty you'd like?",
    "appointment_time_required": "Could you share a preferred time for that appointment?",
}
_DEFAULT_REFUSAL_REPLY = "I couldn't complete that booking — could you try a different day or time?"

_CHOSEN_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def _coerce_age(value) -> int | None:
    try:
        age = int(value)
    except (TypeError, ValueError):
        return None
    return age if 0 < age < 130 else None


def _context_text(turns: list[dict], text: str) -> str:
    """Everything the PATIENT has said this conversation, oldest first, plus
    the current message — fed to `wa_booking.offer_slots`' own text-based
    doctor/date parsing so a doctor or date mentioned two turns ago ("skin
    doctor") still resolves when the patient later just says a time ("10:30").
    Bot turns are excluded: they are the clinic's own words, not a source of
    booking intent, and mixing them in only adds noise to the date/doctor
    heuristics."""
    bits = [t.get("text", "") for t in turns if t.get("role") == "patient"]
    bits.append(text)
    return " ".join(b for b in bits if b)[-1500:]


def _match_chosen_slot(slots: list[Slot], chosen_time: str) -> Slot | None:
    m = _CHOSEN_TIME_RE.match((chosen_time or "").strip())
    if not m:
        return None
    try:
        target = time(int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None
    for s in slots:
        if s.appointment_time == target:
            return s
    return None


def _offer_reply(slots: list[Slot]) -> str:
    day = slots[0].date.strftime("%d %b")
    doctor_name = slots[0].doctor_name
    if slots[0].booking_type == "token":
        return f"{doctor_name} can see you on {day} — reply yes to book the next available token."
    times = ", ".join(
        _hhmm(s.appointment_time) for s in slots[:_MAX_OFFER_LINES] if s.appointment_time
    )
    return f"{doctor_name} has {times} open on {day} — reply with a time to confirm."


def _confirmation_reply(slot: Slot, token: Token) -> str:
    day = slot.date.strftime("%d %b")
    if token.appointment_time:
        return (
            f"You're booked with {slot.doctor_name} on {day} at "
            f"{_hhmm(token.appointment_time)}. Please be on time."
        )
    return f"You're booked with {slot.doctor_name} on {day} — token number {token.token_number}."


async def _handle_book(
    db: AsyncSession,
    branch: Branch,
    sender: str,
    text: str,
    turns: list[dict],
    *,
    chosen_time: str,
    patient_name: str,
    patient_age: int | None,
    patient_gender: str | None,
) -> str:
    """Never appends to the session itself — returns the reply text only, so
    the caller controls exactly when the bot's turn is recorded (see the
    ordering-hazard note on `handle_text`)."""
    context_text = _context_text(turns, text)
    slots = await wa_booking.offer_slots(db, branch, context_text)
    if not slots:
        return _NO_OPENING_REPLY

    # Token-queue doctors have nothing to pick between — the next available
    # number IS the offer. Appointment-type doctors always need an explicit,
    # matched time before anything is reserved (RULE 2/3 spirit: a chat
    # booking only ever proceeds on the patient's own stated choice).
    if slots[0].booking_type == "token":
        slot: Slot | None = slots[0]
    else:
        slot = _match_chosen_slot(slots, chosen_time)

    if slot is None:
        return _offer_reply(slots)

    try:
        result = await wa_booking.confirm(
            db, branch, sender, slot,
            patient_name=patient_name or None,
            patient_age=patient_age,
            patient_gender=patient_gender or None,
        )
    except wa_booking.BookingFailed as exc:
        # RULE 4 — confirm() has ALREADY rolled back the DB insert and
        # released the Redis reservation before raising. Nothing to undo
        # here; just tell the patient honestly. The caller appends this
        # reply to the session, never a claim of success.
        logger.error(
            "wa_chat_booking_failed", branch_id=str(branch.id),
            phone_last4=_last4(sender), error=str(exc)[:150],
        )
        return _BOOKING_TROUBLE_REPLY

    if result.token is not None:
        return _confirmation_reply(slot, result.token)
    if result.taken:
        return _offer_reply(result.alternatives) if result.alternatives else (
            "That slot has just been taken and nothing else is open right "
            "now — could you try a different day?"
        )
    return _REFUSAL_REPLIES.get(result.reason or "", _DEFAULT_REFUSAL_REPLY)


_NO_DOCTORS_REPLY = (
    "I don't have the clinic's doctor list on file yet — I've let the clinic "
    "know so they can add it."
)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A doctor_info answer names at most this many doctors. More than 3 stops
# being a WhatsApp reply and becomes a directory dump.
_MAX_DOCTORS_LISTED = 3


def _parse_iso(value: str) -> date_cls | None:
    v = (value or "").strip()
    if not _ISO_DATE_RE.match(v):
        return None
    try:
        return date_cls.fromisoformat(v)
    except ValueError:
        return None


def _name_matches(doctor_name: str, asked: str) -> bool:
    """Loose name match against what the patient typed. Titles and spelling
    drift ("dr.srinivas", "Srinivas garu") must still find Dr Srinivas Rao, so
    match on any shared word of 3+ characters rather than equality."""
    strip = re.compile(r"[^a-z\s]")
    doc_words = {w for w in strip.sub(" ", doctor_name.lower()).split() if len(w) >= 3}
    ask_words = {
        w for w in strip.sub(" ", asked.lower()).split()
        if len(w) >= 3 and w not in ("doctor", "dr", "the", "garu", "sir", "madam")
    }
    return bool(doc_words & ask_words)


def _merge_to_ranges(slots: list[time], duration_minutes: int) -> list[tuple[time, time]]:
    """Contiguous open slots -> real free windows.

    Vinay 2026-08-03: "if there is one slot booked in between at 8:15 then it
    should say he is available from 8 to 8:15 and 8:30 to 9" — listing the
    first five slot times answers a different question than the patient asked.
    """
    if not slots:
        return []
    step = timedelta(minutes=duration_minutes)
    ranges: list[tuple[time, time]] = []
    start = prev = slots[0]
    for slot in slots[1:]:
        base = date_cls.min
        if datetime.combine(base, slot) == datetime.combine(base, prev) + step:
            prev = slot
            continue
        ranges.append((start, (datetime.combine(base, prev) + step).time()))
        start = prev = slot
    ranges.append((start, (datetime.combine(date_cls.min, prev) + step).time()))
    return ranges


def _hhmm(value: time) -> str:
    """12-hour clock, the way a patient reads a time.

    Vinay 2026-08-04: "Available from 9 to 13 doesn't look good." Nobody in a
    clinic says 13:00. Drops the leading zero and the :00 on the hour, so
    09:00 -> "9 am" and 17:30 -> "5:30 pm".
    """
    hour = value.strftime("%I").lstrip("0") or "12"
    suffix = value.strftime("%p").lower()
    return f"{hour} {suffix}" if value.minute == 0 else f"{hour}:{value.strftime('%M')} {suffix}"


async def _doctor_line(
    db: AsyncSession, branch: Branch, doctor: Doctor, target_date: date_cls
) -> str:
    """One doctor's real availability for one date, straight from the DB.

    Uses `resolve_doctor_schedule` — the SAME resolver check_availability and
    the voice agent's get_doctor_schedule are built on — so leave, published
    date overrides, the recurring week and 'not published yet' all behave
    identically on WhatsApp. Nothing about this doctor comes from the prompt.
    """
    schedule = await resolve_doctor_schedule(doctor, branch.id, target_date, db)
    if schedule.status == "unavailable":
        reason = f" ({schedule.notes})" if schedule.source == "leave" and schedule.notes else ""
        return f"{doctor.name} is not available{reason}"
    if schedule.status == "unpublished" or not schedule.sessions:
        return f"{doctor.name}'s timings for that day aren't published yet"

    if doctor.booking_type == "token":
        return f"{doctor.name} sits {sessions_as_text(schedule.sessions)}"

    slots = await wa_booking.offer_slots(
        db, branch, "", doctor_id=doctor.id, booking_date=target_date, limit=None
    )
    times = sorted(s.appointment_time for s in slots if s.appointment_time)
    if not times:
        return (
            f"{doctor.name} sits {sessions_as_text(schedule.sessions)} but has "
            f"nothing open"
        )
    ranges = _merge_to_ranges(times, doctor.slot_duration_minutes or 15)
    free = " and ".join(f"{_hhmm(a)} to {_hhmm(b)}" for a, b in ranges)
    return f"{doctor.name} is free {free}"


async def _handle_doctor_info(
    db: AsyncSession,
    branch: Branch,
    text: str,
    *,
    doctor_name: str,
    target_date: date_cls,
) -> str:
    """Answers "which doctors are there" / "is Dr X available tomorrow" from
    the database only.

    Before this existed these questions had no intent to land on, so they fell
    through to ask_doctor and became a ClinicQuestion + "let me check with the
    doctor" — for a fact the clinic had already entered (Vinay 2026-08-03).
    """
    doctors = (
        await db.execute(
            select(Doctor)
            .where(Doctor.branch_id == branch.id, Doctor.status == "active")  # RULE 1
            .order_by(Doctor.name)
        )
    ).scalars().all()
    if not doctors:
        return _NO_DOCTORS_REPLY

    asked = (doctor_name or "").strip()
    if asked:
        matched = [d for d in doctors if _name_matches(d.name, asked)]
        if not matched:
            names = ", ".join(d.name for d in doctors[:_MAX_DOCTORS_LISTED])
            return f"I couldn't find that doctor here. Our doctors are {names}."
        doctors = matched

    day = target_date.strftime("%d %b")
    lines = [await _doctor_line(db, branch, d, target_date) for d in doctors[:_MAX_DOCTORS_LISTED]]
    return f"On {day}: " + "; ".join(lines) + "."


# gemini-2.5-flash-lite returns 503 "experiencing high demand" often enough
# that a single 12s attempt with no fallback left patients reading "sorry, I
# had trouble understanding that" for a perfectly clear message (Vinay
# 2026-08-03). CLAUDE.md constraint 8 requires an automatic fallback model, so
# a failed lite call retries once on full 2.5-flash before we give up.
_FALLBACK_MODEL = "gemini-2.5-flash"


async def _classify(prompt: str) -> str:
    """Primary model, then the fallback model. Separate breakers on purpose:
    flash-lite being overloaded must not open the circuit on the model that is
    still healthy."""
    try:
        return await guard(
            "gemini_wa_chat", lambda: _call_gemini(prompt), timeout=15
        )
    except Exception as primary:  # noqa: BLE001 — fall through to the backup model
        logger.warning(
            "wa_chat_primary_llm_failed", error=f"{type(primary).__name__}: {primary}"[:150]
        )
        return await guard(
            "gemini_wa_chat_fallback",
            lambda: _call_gemini(prompt, model=_FALLBACK_MODEL),
            timeout=15,
        )


async def handle_text(
    db: AsyncSession, branch: Branch, plan: str, sender: str, text: str
) -> None:
    """Ordering hazard (WA MVP1 Task 3 review): `wa_session.append()` commits
    on its own. If the bot's turn were appended BETWEEN the atomic token
    allocation and the calendar write inside `wa_booking.confirm()`, that
    commit would persist a Token whose booking never completed — a phantom
    booking, exactly what RULE 3 exists to prevent. `_handle_book` above
    returns a plain string and never touches `wa_session` itself, so the
    single `wa_session.append(..., "bot", reply)` call below — always AFTER
    the intent handler has fully returned, i.e. always after any
    `wa_booking.confirm()` call has already succeeded, refused cleanly, or
    raised `BookingFailed` (which itself already rolled back) — is the only
    place a bot turn is ever recorded. Never move it earlier."""
    if not wa_service.wa_enabled(branch, plan):
        return
    text = (text or "").strip()
    if not text:
        return

    session = await wa_session.load(db, branch.id, sender)
    turns = session["turns"]  # history only — does NOT include this message
    await wa_session.append(db, branch.id, sender, "patient", text)

    now = await wa_booking._branch_now(branch.id, db)
    try:
        prompt = (
            build_chat_prompt(
                _faq_text(branch), turns, text[:1000], today=now.date().isoformat()
            )
            + _JSON_CONTRACT
        )
        data = json.loads(await _classify(prompt))
        intent = (data.get("intent") or "").strip()
    except Exception as e:  # noqa: BLE001 — RULE 8: helpful fallback, never a dead end
        logger.warning(
            "wa_chat_gemini_failed", branch_id=str(branch.id),
            phone_last4=_last4(sender), error=f"{type(e).__name__}: {e}"[:150],
        )
        await wa_session.append(db, branch.id, sender, "bot", _GEMINI_DOWN_REPLY)
        await wa_service.send_text(branch, sender, _GEMINI_DOWN_REPLY, plan=plan)
        return

    logger.info(
        "wa_chat_intent", intent=intent, branch_id=str(branch.id), phone_last4=_last4(sender)
    )

    if intent == "book":
        reply = await _handle_book(
            db, branch, sender, text, turns,
            chosen_time=(data.get("chosen_time") or "").strip(),
            patient_name=(data.get("patient_name") or "").strip(),
            patient_age=_coerce_age(data.get("patient_age")),
            patient_gender=(data.get("patient_gender") or "").strip() or None,
        )
        await wa_session.append(db, branch.id, sender, "bot", reply)
        await wa_service.send_text(branch, sender, reply, plan=plan)
        return

    if intent in ("reschedule", "cancel"):
        token_id = await _upcoming_token_id(db, branch, sender)
        if token_id:
            # wa_actions.handle_change_request sends its own reply and owns
            # its own commit (day-1 clinic-callback flow, unchanged) — this
            # router does not duplicate that text into the session.
            await wa_actions.handle_change_request(
                db, branch, plan, sender, token_id, want_cancel=(intent == "cancel")
            )
        else:
            await _no_existing_booking(
                db, branch, plan, sender, "reschedule" if intent == "reschedule" else "cancel"
            )
        return

    if intent == "greeting":
        # "Hey" used to fall to off_topic and get "I can only help with
        # booking, appointments and questions about the clinic here" — reading
        # like a rejection to someone who had merely said hello (Vinay
        # 2026-08-04). Greet back, by clinic name, and leave the door open.
        reply = (
            f"Welcome to {branch.name}! I can help you book an appointment, "
            f"move or cancel one, or tell you when a doctor is in. What do you need?"
        )
        await wa_session.append(db, branch.id, sender, "bot", reply)
        await wa_service.send_text(branch, sender, reply, plan=plan)
        return

    if intent == "doctor_info":
        # A date the model failed to resolve falls back to TODAY, never to a
        # guess: answering about the wrong day is worse than answering about
        # the day the patient is most likely standing in.
        reply = await _handle_doctor_info(
            db, branch, text,
            doctor_name=(data.get("doctor_name") or "").strip(),
            target_date=_parse_iso(data.get("target_date") or "") or now.date(),
        )
        await wa_session.append(db, branch.id, sender, "bot", reply)
        await wa_service.send_text(branch, sender, reply, plan=plan)
        return

    if intent == "location":
        link = wa_templates.maps_link(branch.address)
        reply = (
            f"{branch.name}: {branch.address}\n{link}" if branch.address
            else "I don't have the clinic's address on file yet — I've let the clinic know to add it."
        )
        await wa_session.append(db, branch.id, sender, "bot", reply)
        await wa_service.send_text(branch, sender, reply, plan=plan)
        return

    if intent == "faq":
        answer = (data.get("answer") or "").strip()
        if answer:
            reply = answer[:900]
            await wa_session.append(db, branch.id, sender, "bot", reply)
            await wa_service.send_text(branch, sender, reply, plan=plan)
            return
        # Classified as faq but nothing in the clinic's FAQ actually answers
        # it — treat it as a real clinic question rather than a dead end.
        await _log_clinic_question(db, branch, sender, text)
        await wa_session.append(db, branch.id, sender, "bot", _ASK_DOCTOR_REPLY)
        await wa_service.send_text(branch, sender, _ASK_DOCTOR_REPLY, plan=plan)
        return

    if intent == "ask_doctor":
        await _log_clinic_question(db, branch, sender, text)
        await wa_session.append(db, branch.id, sender, "bot", _ASK_DOCTOR_REPLY)
        await wa_service.send_text(branch, sender, _ASK_DOCTOR_REPLY, plan=plan)
        return

    # off_topic, or any unrecognised/unparseable intent — polite redirect,
    # never a clinic question (it is not a real one), never a dead end.
    await wa_session.append(db, branch.id, sender, "bot", _OFF_TOPIC_REPLY)
    await wa_service.send_text(branch, sender, _OFF_TOPIC_REPLY, plan=plan)
