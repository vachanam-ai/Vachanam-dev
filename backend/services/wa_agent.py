"""The WhatsApp assistant — a short prompt and a handful of database tools.

Vinay 2026-08-04, after reading a live thread:

    Don't complicate WhatsApp prompt. Just tell it to behave like an
    appointment booking agent and ask it to answer everything after confirming
    from db. here we need not even worry about latency. Ask it to not answer
    question outside appointment flow such as maths, coding, telling jokes etc.
    also ask it to behave friendly and warm. Sometimes making small jokes.

    Keep WhatsApp flow completely separate. Make it simple.

WHAT THIS REPLACES. `wa_chat` classified each message onto one of nine intents
and then read back a canned string per branch. That is why the thread read
like a form letter — "reply with a time to confirm", "I can only help with
booking, appointments and questions about the clinic here" — and why it drifted:
each turn re-guessed the doctor from raw text, so "Book at 9am" after an offer
for Dr Lakshmi on 7 Aug came back about a different doctor on a different day.

The model now writes every word, and every FACT comes from a tool that reads
the database. Nothing about doctors, hours or bookings is in the prompt, so
none of it can go stale between a schedule change and the next message.

Latency is deliberately not optimised here (Vinay: "we need not even worry").
A chat reply may take several seconds and several tool rounds; a phone call
could not afford that, which is precisely why this is its own module and
shares no prompt or turn machinery with the voice agent.

Hard rules that still bind, tools or not:
  RULE 1 — every tool query is branch-scoped, and bookings are matched to the
           sender's own number. One clinic's data cannot reach another.
  RULE 2 — booking goes through wa_booking.confirm, the atomic Redis INCR
           allocator. This module never invents its own seat arithmetic.
  RULE 7 — no medical judgment: never say what is wrong, what to do, or how
           urgent it is; those go to the doctor as a recorded question. Saying
           WHICH doctor treats a complaint is not judgment — it is routing, and
           refusing to do it was a real bug (Vinay 2026-08-04: "my son is
           unwell, who will see him?" got a callback promise instead of the
           children's specialist who was on the roster all along).
  RULE 9 — logs carry phone[-4:], branch id and tool names. Never message text.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime, time as time_cls

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schema import Branch, ClinicQuestion, Doctor, Patient
from backend.services import wa_booking, wa_service, wa_session
from backend.services.doctor_schedule import resolve_doctor_schedule
from backend.services.wa_booking import Slot

logger = structlog.get_logger()

# A tool round is one model turn plus one tool result. Six is plenty for
# "which doctors" -> "when is she free" -> "book it", and bounds a model that
# gets stuck calling the same tool forever.
MAX_TOOL_ROUNDS = 6

SYSTEM_PROMPT = """\
You are the appointment assistant for {clinic}, an Indian clinic. You are
talking to a patient on WhatsApp. Today is {today} ({weekday}).

Be warm and human. Write the way a friendly clinic receptionist texts: short,
relaxed, first person. A light joke now and then is welcome when the mood
suits it — never about anyone's health, and never instead of an answer.

You help with this clinic and the appointments in it — nothing else. If a
request has nothing to do with that, say lightly that you only look after
appointments here and steer back. You will recognise those when you see them;
they do not become your job because someone dresses them up as one.

Never state a fact about a doctor, a time or a booking from memory. Look it up
first with a tool, every single time. Doctors change, schedules change, and a
confident wrong answer costs the clinic a patient. If a tool gives you nothing,
say so plainly rather than guessing.

The clinic has written its own answers to the questions patients ask most.
These are the clinic's words and they OUTRANK anything you would otherwise
infer — including the doctor list. If one of them covers what the patient
asked, answer from it, in your own warm phrasing.
{faq}
If a question is not covered there and no tool can answer it, do not invent an
answer and do not settle for "no" — call record_question_for_doctor so the
clinic replies.

What the clinic has TOLD a patient and what you can BOOK are two different
things. Repeat anything the clinic or a doctor has said, including a day they
named — it is true and it is theirs to say. But you can only BOOK with a doctor
list_doctors returned just now.

So when someone wants something the tools cannot give — a visiting specialist,
an unusual request — say you will ask the clinic and get back to them, call
record_question_for_doctor, and stop. A human there arranges it and replies,
and that reply reaches this chat. Do not keep saying the same thing hoping a
booking appears; one clear line is the whole answer.

Never invent a specific nobody gave you. Repeating the clinic's own words is
right; filling in the blanks around them is not.

SENDING SOMEONE TO THE RIGHT DOCTOR IS YOUR JOB, NOT MEDICAL ADVICE. When
someone tells you who is unwell or what the trouble is and asks WHO CAN SEE
THEM, that is a routing question. Call list_doctors and use your own judgement
to pick whoever fits, name them, and offer to book.

You already know which kind of doctor handles which kind of complaint. Use that
knowledge freely — it is ordinary knowledge a receptionist has, not a medical
opinion. The roster is your only constraint: never name a doctor who is not on
it. If more than one could fit, say so and let them choose. If nobody fits, say
that plainly and record it for the clinic. Do NOT record a question for the
doctor when the answer is simply which doctor.

Never give medical advice, never diagnose, never say how urgent something is,
never suggest what to do or take. THAT is the line — not the mention of a
symptom. If they ask what is WRONG, what they should DO, whether it is
serious, or anything only a doctor can answer, call record_question_for_doctor
so a doctor calls them back.

Tools are the only way you can actually do anything. Saying it does not do it.
Never tell a patient that a booking is made, moved or cancelled, or that a
doctor will call them back, unless the tool that does it has already run and
returned success in this same reply. Never OFFER to make a note and wait to be
asked — if a question needs a doctor, call record_question_for_doctor now, then
say you have done it. A patient told "I've made a note for the doctor" when no
tool ran is waiting for a call that will never come.

You already know who you are messaging — their number came with the message.
Never ask for a phone number. Never ask for a name or age except when booking
a NEW appointment, and never to look up, move or cancel an existing one.

Never tell a patient to phone the clinic — some clinics here have no phone
line at all. Whatever they need, finish it in this chat.

WRITE BACK THE WAY THEY WROTE TO YOU. Mirror their language AND their script,
exactly as they used it. If they type Telugu in English letters, answer in
Telugu in English letters — not in Telugu script, and not in English. Same for
Hindi, Tamil, Kannada, Marathi, Bengali or any mix: whatever they chose is
right for them, and switching them to another script or to English reads as
being handed to a machine. If they mix two languages in one message, mix them
back. If they switch mid-conversation, switch with them.

Writing:
- Short. A couple of sentences. No bullet points, no asterisks, no markdown.
- Times as 9 am, 1 pm, 5:30 pm — never 09:00 or 13:00.
- Dates the way a person says them — 7 Aug, or "tomorrow" when that is clearer.
- Match their tone on emoji; do not start it.

Before booking, you need the patient's name and age; ask for both in one
message if you don't have them. Confirm the doctor, day and time back to them
once the booking succeeds, and remind them to be on time.
"""

TOOLS: list[dict] = [
    {
        "name": "list_doctors",
        "description": (
            "Which doctors work at this clinic, with their speciality. Use "
            "before naming any doctor, and use it to answer 'who can see "
            "me/my child/this problem' — decide from the specialities which "
            "one fits; that is routing, not medical advice."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "check_availability",
        "description": (
            "When a doctor is free on one date, as real open times. Use for "
            "any question about a doctor's hours or availability, and before "
            "offering any time."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doctor_name": {"type": "string", "description": "Doctor's name as the patient said it."},
                "date": {"type": "string", "description": "Calendar date, YYYY-MM-DD."},
            },
            "required": ["doctor_name", "date"],
        },
    },
    {
        "name": "book_appointment",
        "description": (
            "Book one appointment. Only call once you have the doctor, the "
            "date, the time, and the patient's name and age."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doctor_name": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "time": {"type": "string", "description": "24-hour HH:MM, e.g. 09:00 or 17:30"},
                "patient_name": {"type": "string"},
                "patient_age": {"type": "integer"},
            },
            "required": ["doctor_name", "date", "time", "patient_name", "patient_age"],
        },
    },
    {
        "name": "my_appointments",
        "description": (
            "This patient's own upcoming bookings, with the id needed to "
            "cancel or move one. Use before cancelling or rescheduling."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_appointment",
        "description": "Cancel one of this patient's bookings, by its id.",
        "parameters": {
            "type": "object",
            "properties": {"appointment_id": {"type": "string"}},
            "required": ["appointment_id"],
        },
    },
    {
        "name": "reschedule_appointment",
        "description": (
            "Move one of this patient's bookings to a new date and time. Takes "
            "the new seat before releasing the old one."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "time": {"type": "string", "description": "24-hour HH:MM"},
            },
            "required": ["appointment_id", "date", "time"],
        },
    },
    {
        "name": "record_question_for_doctor",
        "description": (
            "Record a question only a doctor can answer — including anything "
            "about symptoms — so the clinic calls this patient back. RULE 7: "
            "never answer such a question yourself."
        ),
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "clinic_location",
        "description": "The clinic's address and a maps link.",
        "parameters": {"type": "object", "properties": {}},
    },
]

# Said when the model itself is unreachable. Never a dead end, never "call us".
FALLBACK_REPLY = (
    "Sorry, I'm having trouble just now — could you send that once more in a "
    "moment?"
)

# Phrases that PROMISE a doctor will get back to the patient.
#
# Three rounds of prompt tightening (and dropping temperature to 0.4) did not
# stop the model answering "my tooth hurts, is it serious?" with "I've made a
# note for one of our doctors to call you back" while calling no tool at all —
# a patient left waiting for a call nobody would ever make. Prompting is the
# wrong instrument for a guarantee, so the guarantee is enforced here: if the
# reply makes this promise and record_question_for_doctor did not run, we run
# it, and the promise becomes true.
#
# Detection is best-effort and English-leaning, which is the right way round:
# a miss leaves today's behaviour unchanged, a hit turns a lie into a fact. The
# duplicate risk is a second ClinicQuestion row, which is exactly what the
# patient was promised anyway.
_CALLBACK_CLAIMS = (
    "call you back", "get back to you", "made a note", "make a note",
    "noted this for", "pass this to the doctor", "let the doctor know",
    "doctor will call", "doctor will get back",
)


def _claims_a_callback(reply: str) -> bool:
    low = (reply or "").lower()
    return any(marker in low for marker in _CALLBACK_CLAIMS)


def _ampm(value: time_cls) -> str:
    hour = value.strftime("%I").lstrip("0") or "12"
    suffix = value.strftime("%p").lower()
    return f"{hour} {suffix}" if value.minute == 0 else f"{hour}:{value.strftime('%M')} {suffix}"


def _parse_date(value: str) -> date_cls | None:
    try:
        return date_cls.fromisoformat((value or "").strip()[:10])
    except (ValueError, AttributeError):
        return None


def _parse_time(value: str) -> time_cls | None:
    raw = (value or "").strip()
    for fmt in ("%H:%M", "%I:%M %p", "%I %p"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


async def _doctors(db: AsyncSession, branch: Branch) -> list[Doctor]:
    return list(
        (
            await db.execute(
                select(Doctor)
                .where(Doctor.branch_id == branch.id, Doctor.status == "active")  # RULE 1
                .order_by(Doctor.name)
            )
        ).scalars().all()
    )


def _match_doctor(doctors: list[Doctor], asked: str) -> Doctor | None:
    """Loose name match — patients type "dr.srinivas", "Srinivas garu",
    "srinivass". Any shared word of 3+ letters wins; a bare title matches
    nobody, so "doctor" never resolves to whoever sorts first."""
    import re

    strip = re.compile(r"[^a-z\s]")
    ask = {
        w for w in strip.sub(" ", (asked or "").lower()).split()
        if len(w) >= 3 and w not in ("doctor", "the", "garu", "sir", "madam")
    }
    if not ask:
        return None
    for doc in doctors:
        words = {w for w in strip.sub(" ", doc.name.lower()).split() if len(w) >= 3}
        if words & ask:
            return doc
    return None


class WaTools:
    """Every tool the model can call. Each one reads or writes the database
    for THIS branch and THIS sender — the model supplies intent, never
    identity."""

    def __init__(
        self, db: AsyncSession, branch: Branch, sender: str, plan: str,
        *, calendar_service=None, meta_service=None,
    ):
        self.db, self.branch, self.sender, self.plan = db, branch, sender, plan
        # None means "use the real thing" (wa_booking picks its own default).
        # Injectable so tests can book without Google credentials, the same
        # seam wa_booking.confirm already offers.
        self.calendar_service = calendar_service
        self.meta_service = meta_service

    def _booking_kwargs(self) -> dict:
        kw = {}
        if self.calendar_service is not None:
            kw["calendar_service"] = self.calendar_service
        if self.meta_service is not None:
            kw["meta_service"] = self.meta_service
        return kw

    async def list_doctors(self) -> dict:
        docs = await _doctors(self.db, self.branch)
        return {
            "doctors": [
                {
                    "name": d.name,
                    "speciality": d.specialization or "general",
                    # Passed through ONLY when the clinic happened to write it.
                    # Routing must never depend on it — Vinay 2026-08-04: "what
                    # if a new doctor is added, then again we manually write
                    # routing keywords? If we hardcode everything then why an
                    # LLM." The model knows a child's fever is paediatrics; the
                    # speciality alone is enough, and this is a hint for the
                    # unusual scope, not a lookup table anyone must maintain.
                    **({"also_treats": list(d.routing_keywords)}
                       if d.routing_keywords else {}),
                }
                for d in docs
            ]
        }

    async def check_availability(self, doctor_name: str = "", date: str = "") -> dict:
        docs = await _doctors(self.db, self.branch)
        doc = _match_doctor(docs, doctor_name)
        if doc is None:
            return {"error": "no such doctor", "doctors": [d.name for d in docs]}
        target = _parse_date(date)
        if target is None:
            return {"error": "date must be YYYY-MM-DD"}

        schedule = await resolve_doctor_schedule(doc, self.branch.id, target, self.db)
        if schedule.status == "unavailable":
            return {"doctor": doc.name, "date": date, "available": False,
                    "reason": schedule.notes or "not working that day"}
        if schedule.status == "unpublished" or not schedule.sessions:
            return {"doctor": doc.name, "date": date, "available": False,
                    "reason": "timings for that day are not published yet"}

        slots = await wa_booking.offer_slots(
            self.db, self.branch, "", doctor_id=doc.id, booking_date=target, limit=None,
        )
        times = sorted(s.appointment_time for s in slots if s.appointment_time)
        if not times and slots:  # token-queue doctor: no clock times to pick
            return {"doctor": doc.name, "date": date, "available": True,
                    "walk_in_queue": True}
        if not times:
            return {"doctor": doc.name, "date": date, "available": False,
                    "reason": "fully booked"}
        return {
            "doctor": doc.name, "date": date, "available": True,
            "free_times": [_ampm(t) for t in times],
            "book_with": [t.strftime("%H:%M") for t in times],
        }

    async def book_appointment(
        self, doctor_name: str = "", date: str = "", time: str = "",
        patient_name: str = "", patient_age: int | None = None,
    ) -> dict:
        docs = await _doctors(self.db, self.branch)
        doc = _match_doctor(docs, doctor_name)
        if doc is None:
            return {"success": False, "error": "no such doctor",
                    "doctors": [d.name for d in docs]}
        target, when = _parse_date(date), _parse_time(time)
        if target is None or when is None:
            return {"success": False, "error": "need date as YYYY-MM-DD and time as HH:MM"}

        slot = Slot(
            doctor_id=doc.id, doctor_name=doc.name,
            booking_type=doc.booking_type or "appointment",
            date=target, appointment_time=when,
        )
        try:
            result = await wa_booking.confirm(
                self.db, self.branch, self.sender, slot,
                patient_name=patient_name or None, patient_age=patient_age,
                **self._booking_kwargs(),
            )
        except wa_booking.BookingFailed as exc:
            # RULE 4: confirm() already rolled the insert back and released the
            # seat before raising. Nothing to undo — just be honest.
            logger.error(
                "wa_agent_booking_failed", branch_id=str(self.branch.id),
                error=str(exc)[:150],
            )
            return {"success": False, "error": "booking could not be completed"}

        if result.token is not None:
            return {
                "success": True, "doctor": doc.name, "date": date,
                "time": _ampm(when) if when else None,
                "token_number": result.token.token_number,
            }
        if result.taken:
            return {"success": False, "error": "that time was just taken",
                    "free_times": [
                        _ampm(s.appointment_time) for s in result.alternatives
                        if s.appointment_time
                    ]}
        return {"success": False, "error": result.reason or "could not book",
                "detail": result.instruction}

    async def my_appointments(self) -> dict:
        rows = await wa_booking.upcoming(self.db, self.branch, self.sender)
        docs = {d.id: d.name for d in await _doctors(self.db, self.branch)}
        return {
            "appointments": [
                {
                    "appointment_id": str(t.id),
                    "doctor": docs.get(t.doctor_id, "the doctor"),
                    "date": t.date.isoformat(),
                    "time": _ampm(t.appointment_time) if t.appointment_time else None,
                    "token_number": t.token_number,
                }
                for t in rows
            ]
        }

    async def cancel_appointment(self, appointment_id: str = "") -> dict:
        ok = await wa_booking.cancel(self.db, self.branch, self.sender, appointment_id)
        return {"success": ok} if ok else {
            "success": False, "error": "no booking of yours with that id"
        }

    async def reschedule_appointment(
        self, appointment_id: str = "", date: str = "", time: str = ""
    ) -> dict:
        rows = await wa_booking.upcoming(self.db, self.branch, self.sender)
        old = next((t for t in rows if str(t.id) == str(appointment_id)), None)
        if old is None:
            return {"success": False, "error": "no booking of yours with that id"}
        docs = await _doctors(self.db, self.branch)
        doc = next((d for d in docs if d.id == old.doctor_id), None)
        target, when = _parse_date(date), _parse_time(time)
        if doc is None or target is None or when is None:
            return {"success": False, "error": "need date as YYYY-MM-DD and time as HH:MM"}

        slot = Slot(
            doctor_id=doc.id, doctor_name=doc.name,
            booking_type=doc.booking_type or "appointment",
            date=target, appointment_time=when,
        )
        result = await wa_booking.reschedule(
            self.db, self.branch, self.sender, appointment_id, slot,
            **self._booking_kwargs(),
        )
        if result.token is not None:
            return {"success": True, "doctor": doc.name, "date": date, "time": _ampm(when)}
        if result.taken:
            return {"success": False, "error": "that time was just taken",
                    "free_times": [
                        _ampm(s.appointment_time) for s in result.alternatives
                        if s.appointment_time
                    ]}
        return {"success": False, "error": result.reason or "could not move it"}

    async def record_question_for_doctor(self, question: str = "") -> dict:
        last10 = wa_booking._phone_last10(self.sender)
        patient = None
        if last10:
            patient = (
                await self.db.execute(
                    select(Patient).where(
                        Patient.branch_id == self.branch.id,  # RULE 1
                        Patient.phone.like(f"%{last10}"),
                    )
                )
            ).scalars().first()
        self.db.add(ClinicQuestion(
            branch_id=self.branch.id,
            question=" ".join((question or "").split())[:300],
            caller_last4=(self.sender or "")[-4:],
            patient_id=patient.id if patient else None,
            caller_phone=self.sender,
            # Answer where they asked. Someone who chose to type does not want
            # a phone call back (Vinay 2026-08-04).
            channel="whatsapp",
        ))
        await self.db.commit()
        logger.info(
            "wa_agent_question_recorded", branch_id=str(self.branch.id),
            phone_last4=(self.sender or "")[-4:],
        )
        return {"recorded": True}

    async def clinic_location(self) -> dict:
        from backend.services import wa_templates

        if not self.branch.address:
            return {"error": "the clinic has not added its address yet"}
        return {
            "name": self.branch.name, "address": self.branch.address,
            "maps": wa_templates.maps_link(self.branch.address),
        }


async def _call_model(system: str, contents: list, tools: list[dict]) -> object:
    """One Gemini turn with tools available. Isolated so tests swap it out."""
    from google.genai import types

    from backend.services.support_bot import _genai_client

    return await _genai_client().aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=tools)],
            # Warm, not loose. At 0.7 the model chatted past its instructions
            # and told a patient "I've made a note for the doctor" without
            # calling the tool that makes the note.
            temperature=0.4,
            # gemini-2.5-flash is a THINKING model and its reasoning tokens are
            # charged against max_output_tokens. With thinking on, a long think
            # ate the budget and the reply was guillotined mid-sentence —
            # "I don't have specific appointment slots for the plastic surgeon
            # to" (Vinay 2026-08-04). Every other Gemini call in this repo
            # already runs thinking_budget=0; this one was the exception.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            max_output_tokens=800,
        ),
    )


def _whole_sentences(reply: str) -> str:
    """Never send a dangling half-sentence.

    Belt to thinking_budget=0's braces: any future cap change, or a model that
    simply runs long, must degrade to a shorter COMPLETE message rather than a
    clause that stops mid-word. Only trims when the text does not already end
    on punctuation, and only when a sentence boundary exists to fall back to —
    a single unfinished sentence is left alone, because sending nothing is
    worse than sending something.
    """
    # Indic full stops count as endings — a complete Hindi reply ends in "।",
    # and without it here a message containing an earlier ". " would be
    # truncated for finishing correctly in its own script (RULE 6 territory).
    text = (reply or "").strip()
    if not text or text[-1] in ".!?…।॥":
        return text
    cut = max(
        text.rfind(". "), text.rfind("! "), text.rfind("? "), text.rfind("। ")
    )
    return text[: cut + 1].strip() if cut > 0 else text


def _history(turns: list[dict], text: str) -> list:
    from google.genai import types

    contents = [
        types.Content(
            role="model" if t.get("role") == "bot" else "user",
            parts=[types.Part(text=t.get("text") or "")],
        )
        for t in turns
        if (t.get("text") or "").strip()
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=text)]))
    return contents


_FAQ_MAX = 20


def _faq_block(branch: Branch) -> str:
    """The clinic's own FAQ rows, verbatim, for the system prompt.

    Vinay 2026-08-04: a clinic had written "is there a plastic surgeon? —
    according to demand we will arrange one", and WhatsApp answered "we don't
    have a plastic surgery person here". The rows saved fine; the agent rewrite
    simply never read them (the retired wa_chat router did). Prompt, not tool:
    at most 20 short pairs, relevant to any message, and a tool round-trip to
    fetch them would just be latency.
    """
    rows = getattr(branch, "faq", None) or []
    lines = []
    for item in rows[:_FAQ_MAX]:
        q = str((item or {}).get("q") or "").strip()
        a = str((item or {}).get("a") or "").strip()
        if q and a:
            lines.append(f"- Q: {q}\n  A: {a}")
    if not lines:
        return "(The clinic has not written any yet.)"
    return "\n".join(lines)


async def handle(
    db: AsyncSession, branch: Branch, plan: str, sender: str, text: str
) -> None:
    """One inbound WhatsApp message, start to finish."""
    from google.genai import types

    if not wa_service.wa_enabled(branch, plan):
        return
    text = (text or "").strip()
    if not text:
        return

    session = await wa_session.load(db, branch.id, sender)
    turns = session["turns"]
    await wa_session.append(db, branch.id, sender, "patient", text)

    now = await wa_booking._branch_now(branch.id, db)
    system = SYSTEM_PROMPT.format(
        clinic=branch.name,
        today=now.date().isoformat(),
        weekday=now.strftime("%A"),
        faq=_faq_block(branch),
    )
    tools = WaTools(db, branch, sender, plan)
    contents = _history(turns, text)

    reply = ""
    called: set[str] = set()
    try:
        for _round in range(MAX_TOOL_ROUNDS):
            response = await _call_model(system, contents, TOOLS)
            calls = list(getattr(response, "function_calls", None) or [])
            if not calls:
                reply = (getattr(response, "text", "") or "").strip()
                break

            contents.append(response.candidates[0].content)
            for call in calls:
                fn = getattr(tools, call.name, None)
                if fn is None:
                    result = {"error": "unknown tool"}
                else:
                    try:
                        result = await fn(**dict(call.args or {}))
                    except Exception as e:  # noqa: BLE001 — one bad tool call
                        # must not kill the conversation; hand the model the
                        # failure and let it apologise in its own words.
                        logger.warning(
                            "wa_agent_tool_failed", tool=call.name,
                            branch_id=str(branch.id), error=str(e)[:150],
                        )
                        result = {"error": "that lookup failed"}
                called.add(call.name)
                logger.info(
                    "wa_agent_tool", tool=call.name, branch_id=str(branch.id),
                    phone_last4=(sender or "")[-4:],
                )
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_function_response(
                        name=call.name, response={"result": result},
                    )],
                ))
    except Exception as e:  # noqa: BLE001 — RULE 8: never a dead end
        logger.warning(
            "wa_agent_failed", branch_id=str(branch.id),
            phone_last4=(sender or "")[-4:], error=f"{type(e).__name__}: {e}"[:200],
        )

    reply = _whole_sentences(reply) or FALLBACK_REPLY

    # Make the promise true (see _CALLBACK_CLAIMS).
    if "record_question_for_doctor" not in called and _claims_a_callback(reply):
        try:
            await tools.record_question_for_doctor(question=text)
            logger.info(
                "wa_agent_callback_claim_backfilled",
                branch_id=str(branch.id), phone_last4=(sender or "")[-4:],
            )
        except Exception as e:  # noqa: BLE001 — never break the reply over this
            logger.warning(
                "wa_agent_callback_backfill_failed",
                branch_id=str(branch.id), error=str(e)[:150],
            )

    await wa_session.append(db, branch.id, sender, "bot", reply)
    await wa_service.send_text(branch, sender, reply, plan=plan)
