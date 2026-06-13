"""Vachanam LiveKit voice agent — production booking brain, inbound + outbound.

Stack: Sarvam Saaras v3 STT (te-IN) + Gemini 2.5 Flash (GPT-4o-mini fallback,
RULE 9) + Sarvam Bulbul v3 TTS (kavitha, Telugu script, pace 1.3).

Booking brain (ported from agent/bot.py Pipecat implementation):
  - DID -> branch resolution from SIP participant attributes (RULE 5)
  - 4 booking tools backed by agent/tools/booking_tools.py
    (Redis INCR tokens RULE 2, calendar-first confirm RULE 4)
  - Token rollback on disconnect when held but unconfirmed (RULE 3)
  - DPDP s.5 disclosure spoken first, every TTS line sanitized (RULE 6)
  - request_human_transfer via LiveKit SIP REFER

Run from this directory: `python agent.py start` (repo root is added to
sys.path below; root .env supplies DB/Redis/keys, local .env supplies
LiveKit + trunk IDs).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import date as date_cls, datetime as datetime_cls, time as time_cls
from datetime import timezone as _tz

timezone_utc = _tz.utc
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
sys.path.insert(0, str(_REPO_ROOT))

# Root .env first (DATABASE_URL, REDIS_URL, SARVAM/GEMINI/OPENAI keys), then
# the local one (LIVEKIT_*, trunk IDs) overriding where both define a var.
load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_HERE / ".env", override=True)

from livekit import agents, api  # noqa: E402
from livekit.agents import (  # noqa: E402
    Agent,
    AgentSession,
    MetricsCollectedEvent,
    RoomInputOptions,
    RunContext,
    ToolError,
    function_tool,
    metrics,
)
from livekit.agents import llm as lk_llm  # noqa: E402
from livekit.plugins import google, noise_cancellation, openai, sarvam, silero  # noqa: E402

import redis.asyncio as aioredis  # noqa: E402
from sqlalchemy import and_, select  # noqa: E402

from agent.prompts.system_prompt import (  # noqa: E402
    DoctorContext,
    build_system_prompt,
)
# CalendarService (legacy-signature shim), NOT GoogleCalendarService —
# booking_tools.confirm_booking calls the legacy create_booking_event kwargs.
from agent.services.calendar_proxy import CalendarService  # noqa: E402
from agent.services.meta_stub import MetaService  # noqa: E402
from agent.services.telugu_dates import telugu_date, telugu_time  # noqa: E402
from agent.services.tts_sanitizer import sanitize_for_tts  # noqa: E402
from agent.session_state import SessionState  # noqa: E402
from agent.tools.booking_tools import (  # noqa: E402
    assign_token,
    check_availability,
    confirm_booking,
    find_bookings_by_phone,
    route_to_doctor,
)
from backend.config import settings  # noqa: E402
from backend.database import AsyncSessionLocal  # noqa: E402
from backend.models.schema import Branch, Doctor  # noqa: E402
from backend.models.schema import Patient as _PatientModel  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vachanam-agent")

AGENT_NAME = "vachanam-agent"

# Service-blocked utterances (org paused by super-admin, or hard-block after
# minutes exhausted). RULE 8: the call is ANSWERED and gets one coherent
# sentence — never dead air, never endless ringing.
SERVICE_BLOCKED_UTTERANCE = (
    "నమస్కారం! క్షమించండి, ఈ సేవ ప్రస్తుతం తాత్కాలికంగా అందుబాటులో లేదు. "
    "దయచేసి క్లినిక్‌ని నేరుగా సంప్రదించండి. ధన్యవాదాలు."
)

# Professional welcome + DPDP s.5 AI disclosure in ONE short Telugu utterance.
# "AI అసిస్టెంట్" must stay (DPDP — caller must know it's not a human). The
# name/phone collection notice moved to the point of collection (booking flow
# asks it when taking details) — better DPDP practice AND a warmer opening.
# Wording per Vinay 2026-06-11.
DISCLOSURE_GREETING = (
    "నమస్కారం! {clinic} కి స్వాగతం. నేను క్లినిక్ AI అసిస్టెంట్‌ని. "
    "మీకు ఏ విధంగా సహాయపడగలను?"
)

# 15-minute pre-appointment reminder call (outbound, appointment-type only).
REMINDER_GREETING = (
    "నమస్కారం {patient} గారు! ఇది {clinic} క్లినిక్ నుండి రిమైండర్ కాల్. "
    "ఈరోజు {time}కి {doctor} గారితో మీ అపాయింట్‌మెంట్ ఉంది. మీరు వస్తున్నారా?"
)

# Doctor-leave cascade rebook call (outbound). Apologise, rebook, retain.
REBOOK_GREETING = (
    "నమస్కారం {patient} గారు! {clinic} క్లినిక్ నుండి కాల్ చేస్తున్నాము. "
    "{date}న {doctor} గారు సెలవులో ఉండటం వల్ల మీ అపాయింట్‌మెంట్ క్యాన్సిల్ "
    "అయింది. క్షమించండి. వేరే రోజు బుక్ చేయమంటారా?"
)

REBOOK_PROMPT_EXTRA = (
    "\n\nTHIS IS A CASCADE-REBOOK CALL (doctor went on leave; the patient's "
    "booking on {cancelled_date} with {doctor} was cancelled by the clinic). "
    "The greeting already apologised and offered to rebook.\n"
    "YOU ALREADY KNOW THIS PATIENT: name={patient}, phone=the number you "
    "dialed, doctor={doctor}. NEVER ask who they are, NEVER ask their health "
    "problem, NEVER restart the new-patient flow — this overrides the booking "
    "flow steps above. If their reply is unclear or mumbled, simply repeat "
    "your question once: 'సరిగా వినిపించలేదండి — వేరే రోజు బుక్ చేయమంటారా?'\n"
    "If they ask about their PREVIOUS booking ('when was my appointment?'): "
    "answer from THIS context — it was on {cancelled_date} with {doctor} and "
    "the clinic cancelled it for the leave. NEVER say they have no booking; "
    "find_my_bookings will show it with status=cancelled_by_clinic.\n"
    "- If they want to rebook: ask which day suits them, then check_availability "
    "for the same doctor (skip leave days), assign_token, confirm_booking with "
    "the same patient name and phone. Keep it to two short sentences per turn.\n"
    "- If they ask WHEN the doctor will be back/available: do NOT guess and do "
    "NOT hang up — call check_availability for the next few days until one is "
    "free, then offer that day: 'డాక్టర్ గారు ___ నుండి ఉంటారు. ఆ రోజు బుక్ "
    "చేయమంటారా?'\n"
    "- If the doctor's next days are also on leave, offer the nearest available "
    "day, or another suitable doctor if they prefer.\n"
    "- If they DO NOT want to rebook (say no, 'cancel it', or they'll call "
    "later themselves): their booking is ALREADY cancelled — there is nothing "
    "more to cancel, NEVER say they have no booking. Say 'మీ అపాయింట్‌మెంట్ "
    "ఇప్పటికే క్యాన్సిల్ అయింది అండి', call decline_rebook (stops further "
    "calls from the clinic), thank them, then end_call.\n"
    "- Only when the patient has clearly FINISHED (declined politely or said "
    "bye, with NO open question): apologise once more, thank them, then end_call."
)

REMINDER_PROMPT_EXTRA = (
    "\n\nTHIS IS A REMINDER CALL (not a new booking call). The patient has an "
    "appointment today: token_id={token_id}, doctor={doctor}, time={time}. "
    "The greeting already asked if they are coming.\n"
    "YOU ALREADY KNOW THIS PATIENT — never ask who they are or their health "
    "problem, never restart the new-patient flow (overrides the booking flow "
    "steps above). Unclear/mumbled reply -> repeat the same question once.\n"
    "- If they confirm: say 'సరే, ఎదురుచూస్తుంటాము. ధన్యవాదాలు!' and nothing more.\n"
    "- If they CANNOT come: this patient matters — rebook them, do not lose them. "
    "Ask which day and time suits them, then call reschedule_booking("
    "old_token_id=token_id above, new_date, new_time) — one atomic call. If it "
    "returns success=true, confirm the new time in one breath and close warmly; "
    "if false, offer another slot.\n"
    "- If they want a different doctor or time, follow the normal availability "
    "negotiation rules. Keep every reply to two short sentences."
)

# Appended AFTER the shared production prompt — phone replies must be terse.
# Long replies were costing 10-16s of TTS audio per turn on top of LLM time.
BREVITY_OVERRIDE = (
    "\n\nVOICE BREVITY — OVERRIDES EVERYTHING ABOVE: ప్రతి రిప్లై గరిష్టంగా "
    "రెండు చిన్న వాక్యాలు (మొత్తం ~15 పదాలు). లిస్ట్‌లు, వివరణలు, రిపీట్‌లు వద్దు. "
    "డిస్క్లోజర్ మళ్ళీ చెప్పవద్దు. ఒక ప్రశ్న మాత్రమే ఒకసారి అడగండి."
)


def _build_fallback_llm() -> lk_llm.FallbackAdapter:
    """RULE 9: Gemini primary, GPT-4o-mini automatic fallback.

    attempt_timeout is forwarded to the provider as the HTTP deadline; the
    Google GenAI API rejects anything under 10s with a 400, which silently
    pushed every single turn onto GPT-4o-mini (and its much weaker Telugu).
    """
    from google.genai import types as genai_types

    return lk_llm.FallbackAdapter(
        llm=[
            google.LLM(
                api_key=settings.gemini_api_key,
                model="gemini-2.5-flash",
                # Thinking is ON by default for 2.5 Flash and adds 1-3s+ of
                # silence per turn before the first token. A booking
                # receptionist needs none of it.
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            ),
            openai.LLM(api_key=settings.openai_api_key, model="gpt-4o-mini"),
        ],
        attempt_timeout=10.0,
    )


async def _routing_llm_call(messages: list) -> str:
    """Plain-text LLM call used by route_to_doctor (Gemini -> OpenAI fallback)."""
    combined = "\n".join(m["content"] for m in messages)
    try:
        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=settings.gemini_api_key)
        resp = await client.aio.models.generate_content(
            # flash-lite: matching a complaint to a doctor list needs no depth;
            # noticeably faster first token than full flash on the call path.
            model="gemini-2.5-flash-lite",
            contents=combined,
            config=genai_types.GenerateContentConfig(
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
                response_mime_type="application/json",
            ),
        )
        return resp.text or ""
    except Exception as exc:
        logger.error("routing_llm_gemini_failed: %s", exc)
        from openai import AsyncOpenAI

        oai = AsyncOpenAI(api_key=settings.openai_api_key)
        resp = await oai.chat.completions.create(
            model="gpt-4o-mini", messages=messages, temperature=0
        )
        return resp.choices[0].message.content or ""


class VachanamAgent(Agent):
    """Booking receptionist with real tools. One instance per call."""

    def __init__(
        self,
        *,
        instructions: str,
        state: SessionState,
        db,
        room,
        calendar_service: CalendarService | None,
        meta_service: MetaService,
        transfer_to: str,
    ) -> None:
        super().__init__(instructions=instructions)
        self._state = state
        self._db = db
        self._room = room
        self._calendar = calendar_service
        self._meta = meta_service
        self._transfer_to = transfer_to

    async def _resolve_doctor_id(self, doctor_id: str | None) -> UUID:
        """Never trust the LLM to echo a UUID. Accept a real UUID, else match a
        doctor name within this branch, else fall back to the doctor selected by
        route_to_doctor. Raises ToolError (LLM-visible) instead of crashing."""
        if doctor_id:
            try:
                return UUID(doctor_id)
            except ValueError:
                pass  # probably a name — try matching below
            needle = doctor_id.strip().lower().removeprefix("dr.").removeprefix("dr").strip()
            if needle:
                result = await self._db.execute(
                    select(Doctor).where(
                        and_(
                            Doctor.branch_id == self._state.branch_id,
                            Doctor.status == "active",
                        )
                    )
                )
                matches = [doc for doc in result.scalars() if needle in doc.name.lower()]
                if len(matches) == 1:
                    return matches[0].id
                if len(matches) > 1:
                    # "kumar" matches both "Test Kumar" and "Ravi Kumar" — never
                    # guess; a silent first-match books the WRONG doctor.
                    names = ", ".join(d.name for d in matches)
                    raise ToolError(
                        f"'{doctor_id}' matches multiple doctors: {names}. Use the "
                        "exact doctor_id returned by route_to_doctor or "
                        "find_my_bookings instead of a name."
                    )
        if self._state.doctor_id:
            return self._state.doctor_id
        raise ToolError(
            "Unknown doctor. Call route_to_doctor with the patient's complaint "
            "first, then use the doctor_id it returns."
        )

    @staticmethod
    def _parse_date(booking_date: str) -> date_cls:
        try:
            return date_cls.fromisoformat(booking_date)
        except ValueError:
            raise ToolError(
                f"Invalid booking_date '{booking_date}'. Use YYYY-MM-DD."
            ) from None

    @staticmethod
    def _parse_time(value: str | None) -> time_cls | None:
        if not value:
            return None
        try:
            return time_cls.fromisoformat(value)
        except ValueError:
            raise ToolError(f"Invalid time '{value}'. Use HH:MM (24h).") from None

    @function_tool()
    async def route_to_doctor(self, context: RunContext, complaint: str) -> dict:
        """Match the patient's stated health complaint to the right doctor.
        Call once the patient has described their problem. Pass the complaint
        exactly as spoken."""
        self._state.complaint = complaint
        result = await route_to_doctor(
            complaint=complaint,
            branch_id=self._state.branch_id,
            db=self._db,
            llm_call=_routing_llm_call,
        )
        if result.get("doctor_id"):
            # Single match — safe to pre-select for later tools.
            self._state.doctor_id = UUID(result["doctor_id"])
        # Multiple candidates: leave state unset; the patient picks after
        # hearing each doctor's availability (result carries instruction).
        return result

    @function_tool()
    async def check_availability(
        self,
        context: RunContext,
        doctor_id: str,
        booking_date: str,
        query_start: str | None = None,
        query_end: str | None = None,
    ) -> dict:
        """Check whether the doctor has capacity on a date (YYYY-MM-DD).
        Optional query_start/query_end are HH:MM strings for slot doctors."""
        resolved = await self._resolve_doctor_id(doctor_id)
        availability = await check_availability(
            doctor_id=resolved,
            branch_id=self._state.branch_id,
            booking_date=self._parse_date(booking_date),
            db=self._db,
            query_start=self._parse_time(query_start),
            query_end=self._parse_time(query_end),
        )
        return {"availability": availability}

    @function_tool()
    async def assign_token(
        self,
        context: RunContext,
        doctor_id: str,
        booking_date: str,
        appointment_time: str | None = None,
    ) -> dict:
        """Atomically reserve the next token for doctor+date. Call only after
        check_availability confirms capacity AND the patient agrees to the date.
        appointment_time (HH:MM) only for slot-type doctors."""
        result = await assign_token(
            doctor_id=await self._resolve_doctor_id(doctor_id),
            branch_id=self._state.branch_id,
            booking_date=self._parse_date(booking_date),
            db=self._db,
            appointment_time=self._parse_time(appointment_time),
        )
        if result.get("success"):
            self._state.token_held = True
            self._state.token_number = result["token_number"]
            self._state.token_redis_key = result["redis_key"]
        return result

    @function_tool()
    async def confirm_booking(
        self,
        context: RunContext,
        doctor_id: str,
        patient_name: str,
        complaint: str,
        booking_date: str,
        token_number: int,
        followup_consent: bool,
        patient_phone: str | None = None,
        appointment_time: str | None = None,
        patient_age: int | None = None,
        patient_gender: str | None = None,
        different_person: bool = False,
    ) -> dict:
        """Finalize the booking AFTER the patient explicitly confirms. Writes the
        token to the database and creates the calendar event. patient_name is the
        PATIENT being seen (may differ from the caller — family bookings);
        patient_phone defaults to the caller's number when omitted.
        patient_gender: 'male' | 'female' | 'other' if known.
        different_person: True ONLY when the caller explicitly books for a
        DIFFERENT family member who already has a booking that day."""
        if self._calendar is None:
            logger.error("confirm_booking_no_calendar_service")
            return {"success": False, "error": "booking_system_unavailable"}
        phone = patient_phone or self._state.patient_phone
        resolved = await self._resolve_doctor_id(doctor_id)
        parsed_date = self._parse_date(booking_date)
        parsed_time = self._parse_time(appointment_time)
        # RULE 2 (race-proof): if the LLM skipped assign_token there is no
        # server-side hold, and confirm_booking's DB re-count is TOCTOU under
        # concurrency (bug-bounty T1). Acquire the atomic Redis hold NOW — same
        # gate assign_token uses — so two simultaneous skip-assign confirms for
        # the last slot can't both pass. assign_token also respects
        # max_concurrent_per_slot, which a DB unique index could not.
        if not self._state.token_held:
            held = await assign_token(
                doctor_id=resolved,
                branch_id=self._state.branch_id,
                booking_date=parsed_date,
                db=self._db,
                appointment_time=parsed_time,
            )
            if not held.get("success"):
                return held  # full / past_slot / outside_hours — surfaced to LLM
            self._state.token_held = True
            self._state.token_number = held["token_number"]
            self._state.token_redis_key = held.get("redis_key")
        # The number reserved by assign_token (held server-side) is the truth —
        # never trust the LLM's echo of token_number.
        if self._state.token_held and self._state.token_number is not None:
            token_number = self._state.token_number
        try:
            result = await confirm_booking(
                doctor_id=resolved,
                branch_id=self._state.branch_id,
                patient_name=patient_name,
                patient_phone=phone,
                complaint=complaint,
                booking_date=parsed_date,
                token_number=token_number,
                followup_consent=followup_consent,
                appointment_time=self._parse_time(appointment_time),
                source="voice",
                db=self._db,
                calendar_service=self._calendar,
                meta_service=self._meta,
                patient_age=patient_age,
                patient_gender=patient_gender,
                different_person=different_person,
            )
        except Exception as e:
            logger.error("confirm_booking_failed: %s", e)
            # Recover the session so a same-call retry works (e.g. the rare
            # unique-index race backstop poisons the transaction).
            try:
                await self._db.rollback()
            except Exception:
                pass
            return {"success": False, "error": "booking_failed"}
        if result.get("success"):
            self._state.token_confirmed = True
            self._state.patient_name = patient_name
            if self._state.followup_task_id:
                # Cascade-rebook call achieved its goal — stop the retry loop.
                await self._complete_followup_task("rebooked_on_call")
        return result

    async def _complete_followup_task(self, summary: str) -> bool:
        """Mark this call's FollowupTask completed (stops the outbound retry
        loop). Used when the patient rebooks AND when they decline — either
        way the clinic must stop calling them every 30 minutes."""
        if not self._state.followup_task_id:
            return False
        try:
            from backend.models.schema import FollowupTask

            task = (
                await self._db.execute(
                    select(FollowupTask).where(
                        and_(
                            FollowupTask.id == self._state.followup_task_id,
                            FollowupTask.branch_id == self._state.branch_id,
                        )
                    )
                )
            ).scalar_one_or_none()
            if task is None:
                return False
            task.status = "completed"
            task.response_summary = summary[:200]
            await self._db.commit()
            return True
        except Exception as e:
            logger.warning("followup_complete_mark_failed: %s", e)
            return False

    @function_tool()
    async def decline_rebook(self, context: RunContext, reason: str = "declined") -> dict:
        """ONLY on clinic-initiated rebook/reminder calls: the patient does
        NOT want to rebook (says no, asks to cancel, or will call back
        themselves). Marks the follow-up done so the clinic STOPS calling
        them. Their old booking is ALREADY cancelled — never tell them they
        have no booking, and never call cancel_booking for it."""
        done = await self._complete_followup_task(f"patient_declined: {reason}")
        if not done:
            return {"success": False, "error": "not_a_followup_call"}
        return {
            "success": True,
            "instruction": (
                "Acknowledge warmly that their appointment stays cancelled and "
                "they can call anytime to book again. Thank them, then end_call."
            ),
        }

    @function_tool()
    async def find_my_bookings(
        self, context: RunContext, phone_number: str | None = None
    ) -> dict:
        """Look up the caller's bookings: upcoming confirmed ones AND recently
        clinic-cancelled ones (doctor leave). Matches by the number they are
        calling from automatically — do NOT ask for their number first. Only
        pass phone_number if the search came back empty AND the patient says
        the booking was made with a different number. Use when the patient
        wants to reschedule, cancel, or asks about an existing/previous
        appointment. status='cancelled_by_clinic' bookings are what rebook
        calls are about — never tell such a patient they have no booking;
        offer to rebook it instead."""
        phone = phone_number or self._state.patient_phone
        if not phone:
            return {"bookings": [], "note": "caller number unknown — ask for the booking phone number"}
        rows = await find_bookings_by_phone(self._state.branch_id, phone, self._db)
        confirmed_rows = [r for r in rows if r[0].status == "confirmed"]
        if len(confirmed_rows) == 1:
            rows_single = confirmed_rows
        else:
            rows_single = rows if len(rows) == 1 else []
        if rows_single:
            # One relevant booking: pre-select its doctor so later tools never
            # hit "Unknown doctor" (reschedules skip route_to_doctor entirely).
            self._state.doctor_id = rows_single[0][1].id
        return {
            "bookings": [
                {
                    "token_id": str(t.id),
                    "patient_name": p.name,
                    "doctor": d.name,
                    "doctor_id": str(d.id),
                    "date": t.date.isoformat(),
                    "time": t.appointment_time.strftime("%H:%M") if t.appointment_time else None,
                    "token_number": t.token_number,
                    "booking_type": d.booking_type,
                    "status": t.status,
                }
                for t, d, p in rows
            ]
        }

    @function_tool()
    async def reschedule_booking(
        self,
        context: RunContext,
        old_token_id: str,
        new_date: str,
        new_time: str | None = None,
    ) -> dict:
        """Reschedule an existing confirmed booking to a new date/time in ONE
        atomic step: books the new slot for the SAME patient and same doctor,
        and only after the new booking is confirmed cancels the old one. Use
        this instead of manual assign/confirm/cancel for every reschedule.
        new_time (HH:MM) required only for schedule (appointment) doctors."""
        return await self._do_reschedule(old_token_id, new_date, new_time)

    async def _do_reschedule(
        self, old_token_id: str, new_date: str, new_time: str | None = None
    ) -> dict:
        from backend.models.schema import Token

        try:
            old_uuid = UUID(old_token_id)
        except ValueError:
            raise ToolError(
                "old_token_id must be the token_id returned by find_my_bookings."
            ) from None
        row = (
            await self._db.execute(
                select(Token, _PatientModel)
                .join(_PatientModel, Token.patient_id == _PatientModel.id)
                .where(
                    and_(
                        Token.id == old_uuid,
                        Token.branch_id == self._state.branch_id,  # RULE 1
                    )
                )
            )
        ).first()
        if row is None:
            return {"success": False, "error": "booking_not_found"}
        old_token, patient = row
        if old_token.status != "confirmed":
            return {"success": False, "error": f"not_reschedulable_{old_token.status}"}

        booking_date = self._parse_date(new_date)
        appt_time = self._parse_time(new_time)
        assigned = await assign_token(
            doctor_id=old_token.doctor_id,
            branch_id=self._state.branch_id,
            booking_date=booking_date,
            db=self._db,
            appointment_time=appt_time,
        )
        if not assigned.get("success"):
            return {"success": False, "step": "assign", **assigned}
        # Record the hold so a hard call-drop between assign and confirm is
        # released by _cleanup_on_shutdown (bug-bounty T4) — not just the
        # in-band failure paths that call _release_hold below.
        self._state.token_held = True
        self._state.token_number = assigned["token_number"]
        self._state.token_redis_key = assigned.get("redis_key")

        try:
            confirmed = await confirm_booking(
                doctor_id=old_token.doctor_id,
                branch_id=self._state.branch_id,
                patient_name=patient.name,
                patient_phone=patient.phone,
                complaint=self._state.complaint or "reschedule",
                booking_date=booking_date,
                token_number=assigned["token_number"],
                followup_consent=patient.followup_consent,
                appointment_time=self._parse_time(
                    assigned.get("appointment_time") or new_time
                ),
                source="voice",
                db=self._db,
                calendar_service=self._calendar,
                meta_service=self._meta,
                exclude_token_id=old_token.id,  # ignore the booking being replaced
            )
        except Exception as e:
            logger.error("reschedule_confirm_failed: %s", e)
            await self._release_hold(assigned)  # RULE 3: don't leak the new hold
            self._clear_hold()  # so shutdown cleanup doesn't DECR it a 2nd time
            return {"success": False, "step": "confirm", "error": "booking_failed"}
        if not confirmed.get("success"):
            await self._release_hold(assigned)  # RULE 3: dup guard / capacity etc.
            self._clear_hold()
            return {"success": False, "step": "confirm", **confirmed}
        self._state.token_confirmed = True
        self._state.token_number = confirmed.get("token_number") or assigned["token_number"]

        # New booking exists — NOW it is safe to drop the old one.
        cancelled = await self._do_cancel(str(old_token.id))
        return {
            "success": True,
            "new_token_number": assigned["token_number"],
            "new_date": booking_date.isoformat(),
            "new_time": assigned.get("appointment_time"),
            "old_cancelled": bool(cancelled.get("success")),
        }

    @function_tool()
    async def cancel_booking(
        self, context: RunContext, token_id: str, reason: str = "cancel"
    ) -> dict:
        """Cancel an existing confirmed booking (frees the slot and removes the
        calendar event). reason: 'cancel' when the patient just cancels;
        for reschedules PREFER the reschedule_booking tool (atomic). If you do
        cancel manually for a reschedule, the NEW booking must already be
        confirmed."""
        # HARD GUARD: a reschedule may only cancel after the replacement is
        # CONFIRMED. The LLM once treated assign_token as "booked", cancelled
        # the old appointment, and left the patient with nothing.
        unconfirmed_hold = self._state.token_held and not self._state.token_confirmed
        if (reason == "reschedule" or unconfirmed_hold) and not self._state.token_confirmed:
            raise ToolError(
                "Replacement booking is NOT confirmed yet. assign_token is only "
                "a hold — call confirm_booking for the new slot first, verify "
                "success=true, and only then cancel the old booking. For "
                "reschedules prefer the reschedule_booking tool."
            )
        return await self._do_cancel(token_id)

    def _clear_hold(self) -> None:
        """Forget the server-side hold so _cleanup_on_shutdown won't DECR a key
        that an in-band failure path already released (avoids double-release)."""
        self._state.token_held = False
        self._state.token_redis_key = None
        self._state.token_number = None

    @staticmethod
    async def _release_hold(assigned: dict) -> None:
        """RULE 3: DECR a slot hold that won't become a booking.

        _do_reschedule calls the module-level assign_token directly (not the
        wrapper), so state.token_redis_key is never set and the shutdown
        cleanup can't release it. A failed confirm after a successful assign
        would leave the slot 'full' until TTL — including for the patient's own
        retry seconds later. Token-doctor holds are NOT decremented (the
        counter is the queue sequence — same rule as _do_cancel)."""
        key = assigned.get("redis_key") or ""
        # only slot holds carry an appointment_time; token holds must not DECR
        if not key.startswith("slot:"):
            return
        try:
            r = aioredis.from_url(settings.redis_url, decode_responses=True)
            try:
                if int(await r.get(key) or 0) > 0:
                    await r.decr(key)
            finally:
                await r.aclose()
        except Exception as e:
            logger.warning("reschedule_hold_release_failed: %s", e)

    async def _do_cancel(self, token_id: str) -> dict:
        """Shared cancel core (no guards) — used by cancel_booking and
        reschedule_booking after their preconditions hold."""
        from sqlalchemy import and_ as _and

        from backend.models.schema import Token

        try:
            token_uuid = UUID(token_id)
        except ValueError:
            raise ToolError(
                "token_id must be the booking id from find_my_bookings or the "
                "reminder metadata."
            ) from None
        result = await self._db.execute(
            select(Token).where(
                _and(Token.id == token_uuid, Token.branch_id == self._state.branch_id)
            )
        )
        token = result.scalar_one_or_none()
        if token is None:
            return {"success": False, "error": "booking_not_found"}
        if token.status != "confirmed":
            if token.status == "cancelled_by_clinic":
                return {
                    "success": False,
                    "error": "already_cancelled",
                    "instruction": (
                        "This booking was ALREADY cancelled by the clinic "
                        "(doctor leave). Tell the patient it is already "
                        "cancelled and nothing more is needed — NEVER say "
                        "they have no booking. On a rebook call, also call "
                        "decline_rebook so the clinic stops calling them."
                    ),
                }
            return {"success": False, "error": f"not_cancellable_{token.status}"}

        token.status = "cancelled_by_clinic"
        token.cancellation_reason = "patient_cancelled_or_rescheduled_on_call"
        await self._db.commit()

        # Release capacity — SLOT doctors only. Token counters must NEVER be
        # decremented: the counter IS the queue-number sequence, so a DECR
        # makes the next patient receive the SAME token number as the
        # cancelled one (and DECR on an expired key goes to -1 -> token 0).
        # Cancelled token capacity is simply not reclaimed — token numbers
        # stay unique, which matters more than one lost queue slot.
        if token.appointment_time is not None:
            try:
                r = aioredis.from_url(settings.redis_url, decode_responses=True)
                try:
                    key = (
                        f"slot:{token.doctor_id}:{token.branch_id}:{token.date}:"
                        f"{token.appointment_time.strftime('%H%M')}"
                    )
                    # guard: never push an absent/zero key negative
                    if int(await r.get(key) or 0) > 0:
                        await r.decr(key)
                finally:
                    await r.aclose()
            except Exception as e:
                logger.warning("cancel_redis_release_failed: %s", e)

        if token.google_calendar_event_id and self._calendar is not None:
            try:
                # Delete from the SAME calendar create used: doctor's personal
                # calendar first, branch calendar as fallback. Deleting only
                # from the branch calendar left ghost events on every doctor
                # who had a personal calendar (404 silently treated as success).
                doc_cal = (
                    await self._db.execute(
                        select(Doctor.google_calendar_id).where(Doctor.id == token.doctor_id)
                    )
                ).scalar_one_or_none()
                branch_cal = (
                    await self._db.execute(
                        select(Branch.google_calendar_id).where(
                            Branch.id == self._state.branch_id
                        )
                    )
                ).scalar_one_or_none()
                cal_id = doc_cal or branch_cal
                if cal_id:
                    await self._calendar.delete_event(cal_id, token.google_calendar_event_id)
            except Exception as e:
                logger.warning("cancel_calendar_delete_failed: %s", e)

        logger.info(
            "booking_cancelled_for_reschedule token=%s branch_id=%s",
            token_id[-8:],
            str(self._state.branch_id),
        )
        return {"success": True}

    @staticmethod
    def _check_end_allowed(state: SessionState, abandon_pending_booking: bool) -> None:
        """Refuse to hang up mid-booking. The LLM once said a random
        ధన్యవాదాలు and ended the call while a token was held but never
        confirmed — the patient thought they were booked. Raises ToolError
        (LLM-visible) unless the booking is complete or explicitly abandoned."""
        if state.token_held and not state.token_confirmed and not abandon_pending_booking:
            raise ToolError(
                "A booking is IN PROGRESS (token held, not confirmed). Do not "
                "end the call. Either finish confirm_booking, or — ONLY if the "
                "patient clearly said they no longer want the booking — say "
                "goodbye and call end_call with abandon_pending_booking=true."
            )

    @function_tool()
    async def end_call(
        self, context: RunContext, abandon_pending_booking: bool = False
    ) -> dict:
        """Hang up the call. STRICT rule: only when the conversation is truly
        over — goodbye spoken AND the patient has no unanswered question and
        asked for nothing further. NEVER call this because a phrase merely
        sounded final; if the patient just asked something, answer it first.
        abandon_pending_booking=true ONLY when a started booking is being
        dropped because the patient clearly declined to finish it."""
        self._check_end_allowed(self._state, abandon_pending_booking)
        try:
            # Let the goodbye finish playing before tearing the room down.
            await context.wait_for_playout()
        except Exception:
            pass
        try:
            lkapi = api.LiveKitAPI()
            await lkapi.room.delete_room(api.DeleteRoomRequest(room=self._room.name))
            await lkapi.aclose()
            logger.info("call_ended_by_agent room=%s", self._room.name)
            return {"success": True}
        except Exception as e:
            logger.error("end_call_failed: %s", e)
            return {"success": False}

    @function_tool()
    async def request_human_transfer(self, context: RunContext, reason: str) -> dict:
        """Transfer the call to a human. Use ONLY if the patient explicitly asks
        for a person/doctor/receptionist, or keeps insisting across turns."""
        room = self._room
        if room is None or not self._transfer_to:
            return {"success": False, "error": "transfer_unavailable"}
        participant_identity = next(iter(room.remote_participants), None)
        if participant_identity is None:
            return {"success": False, "error": "no_participant"}
        logger.info(
            "human_transfer_requested reason=%s to=...%s",
            reason[:60],
            self._transfer_to[-4:],
        )
        try:
            lkapi = api.LiveKitAPI()
            await lkapi.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=room.name,
                    participant_identity=participant_identity,
                    transfer_to=f"tel:{self._transfer_to}",
                    play_dialtone=True,
                )
            )
            await lkapi.aclose()
            return {"success": True}
        except Exception as e:
            logger.error("transfer_failed: %s", e)
            return {"success": False, "error": "transfer_failed"}


async def entrypoint(ctx: agents.JobContext) -> None:
    await ctx.connect()
    logger.info("Joined room: %s", ctx.room.name)

    # Outbound dispatches carry the callee number (+ reminder context) in metadata
    outbound_number = None
    meta: dict = {}
    if ctx.job.metadata:
        try:
            meta = json.loads(ctx.job.metadata)
            outbound_number = meta.get("phone_number")
        except json.JSONDecodeError:
            pass
    is_reminder = meta.get("call_type") == "reminder"
    is_rebook_call = meta.get("call_type") == "cascade_rebook"

    if outbound_number:
        logger.info("Outbound: dialing ...%s", outbound_number[-4:])
        try:
            await ctx.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    room_name=ctx.room.name,
                    sip_trunk_id=os.getenv("OUTBOUND_TRUNK_ID", ""),
                    sip_call_to=outbound_number,
                    participant_identity=f"sip_{outbound_number}",
                    wait_until_answered=True,
                )
            )
        except api.TwirpError as e:
            logger.error("Outbound dial failed: %s %s", e.code, e.message)
            ctx.shutdown()
            return

    # Resolve the dialed DID + caller from the SIP participant. For inbound the
    # SIP leg is bridged into the room by LiveKit; we wait briefly for it but
    # must NEVER hard-block here — if we don't reach session.start(), the agent
    # never answers and the caller just hears endless ringback. So on any miss
    # we fall back to the configured DID and let the session answer the call.
    def _read_sip(p) -> tuple[str, str]:
        a = (p.attributes or {}) if p else {}
        return a.get("sip.trunkPhoneNumber", ""), a.get("sip.phoneNumber", "")

    did = ""
    caller = outbound_number or ""

    # 1) The SIP leg is usually already in the room when the agent is dispatched.
    for p in ctx.room.remote_participants.values():
        d, c = _read_sip(p)
        if d or c:
            did, caller = d or did, c or caller
            break

    # 2) Otherwise wait briefly — but never hard-block: if we don't reach
    #    session.start() the agent never answers and the caller hears endless
    #    ringback. 4s is enough for the SIP leg; then we proceed with a fallback.
    if not did and not caller:
        try:
            participant = await asyncio.wait_for(ctx.wait_for_participant(), timeout=4.0)
            did, caller = _read_sip(participant)
            caller = caller or outbound_number or ""
        except Exception as e:  # noqa: BLE001 — proceed regardless of why
            logger.warning("participant_wait_fallback: %s", e)

    # 3) Single-DID test/fallback so the call always proceeds and is answered.
    # TENANT NOTE (RULE 5): branch context must come from the dialed DID. This
    # fallback is only safe while one clinic exists; with multiple clinics a
    # missing SIP attribute must never route a call to the wrong tenant, so we
    # log loudly for monitoring.
    did_from_fallback = False
    if not did:
        did = os.getenv("VOBIZ_OUTBOUND_NUMBER", "") or settings.vobiz_did_number
        did_from_fallback = True
        logger.warning(
            "did_fallback_used room=%s — SIP trunkPhoneNumber missing; "
            "verify dispatch rule passes attributes (multi-tenant risk)",
            ctx.room.name,
        )
    logger.info("call_started did=...%s caller=...%s", did[-4:], caller[-4:] if caller else "????")

    state = SessionState(session_id=ctx.room.name)
    state.patient_phone = caller or None
    state.call_type = "outbound" if outbound_number else "inbound_booking"
    state.call_start = datetime_cls.now(timezone_utc)

    db = AsyncSessionLocal()

    # Branch resolution. INBOUND: by dialed DID (RULE 5). OUTBOUND: there is
    # no dialed DID — the dispatch metadata carries the branch_id; relying on
    # the DID fallback would resolve the WRONG tenant the moment a second
    # clinic exists (caller's number must never pick the branch).
    branches = []
    if outbound_number and meta.get("branch_id"):
        try:
            meta_branch_uuid = UUID(meta["branch_id"])
            result = await db.execute(select(Branch).where(Branch.id == meta_branch_uuid))
            branches = result.scalars().all()
        except ValueError:
            logger.error("outbound_branch_id_invalid: %s", meta.get("branch_id"))
    if not branches:
        # RULE 5 guard (bounce F4): the DID came from a fallback, not the actual
        # dialed number. Resolving a branch from it is only safe when exactly one
        # clinic exists — with two clinics the fallback DID would serve caller A
        # the tenant context of clinic B (whose attribute was dropped). If more
        # than one branch exists, refuse rather than risk a cross-tenant leak.
        if did_from_fallback:
            from sqlalchemy import func as _func

            total_branches = (
                await db.execute(select(_func.count()).select_from(Branch))
            ).scalar_one()
            if total_branches != 1:
                logger.error(
                    "did_fallback_refused matches=%d branches — multi-tenant, "
                    "cannot resolve tenant without dialed DID; aborting call",
                    total_branches,
                )
                await db.close()
                ctx.shutdown()
                return

        # Normalize the dialed DID to the same canonical form Settings stores
        # (bug-bounty M11) — a format difference (spaces, missing +91) otherwise
        # fails the match and aborts every inbound call to that clinic.
        from backend.services.validators import normalize_did

        did_norm = normalize_did(did)
        # .first() not .one_or_none(): a DB-level partial-unique index guarantees at
        # most one branch per DID, but if that invariant were ever violated we must
        # NOT crash the call — and must NOT silently serve an ambiguous tenant.
        result = await db.execute(
            select(Branch)
            .where(Branch.did_number.in_([did, did_norm]))
            .limit(2)
        )
        branches = result.scalars().all()
    if len(branches) != 1:
        logger.error(
            "did_resolution_failed did=...%s matches=%d — aborting call",
            did[-4:],
            len(branches),
        )
        await db.close()
        ctx.shutdown()
        return
    branch = branches[0]

    # Super-admin service gate: paused/cancelled org, expired trial, or
    # hard-block with the month's minutes exhausted -> answer, speak ONE line,
    # hang up (RULE 8). Also captures the org plan for the call-duration cap.
    blocked_reason = None
    org_plan = "clinic"
    try:
        from zoneinfo import ZoneInfo as _ZoneInfo

        from backend.models.schema import CallLog, Organization
        from backend.services.billing_math import call_blocked

        org = (
            await db.execute(select(Organization).where(Organization.id == branch.org_id))
        ).scalar_one_or_none()
        if org is not None:
            org_plan = org.plan or "clinic"
            used_min = 0.0
            if getattr(org, "hard_block_on_exhaust", False):
                # Month boundary in the BRANCH timezone, not server UTC —
                # otherwise IST calls 00:00-05:30 on the 1st meter into the
                # previous month and the hard-block trigger shifts 5.5h.
                try:
                    now_branch = datetime_cls.now(_ZoneInfo(branch.timezone or "Asia/Kolkata"))
                except Exception:
                    now_branch = datetime_cls.now(_ZoneInfo("Asia/Kolkata"))
                month_start = now_branch.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                )
                from sqlalchemy import func as _func

                branch_ids = (
                    await db.execute(select(Branch.id).where(Branch.org_id == org.id))
                ).scalars().all()
                secs = (
                    await db.execute(
                        select(_func.coalesce(_func.sum(CallLog.duration_seconds), 0)).where(
                            and_(
                                CallLog.branch_id.in_(branch_ids),
                                CallLog.started_at >= month_start,
                            )
                        )
                    )
                ).scalar_one()
                used_min = secs / 60.0
            blocked_reason = call_blocked(
                org.status,
                org.plan,
                bool(getattr(org, "hard_block_on_exhaust", False)),
                used_min,
                trial_ends_at=getattr(org, "trial_ends_at", None),
            )
    except Exception as e:  # gate must never kill a call — fail open
        logger.warning("service_gate_check_failed: %s", e)

    if blocked_reason:
        logger.warning(
            "call_blocked reason=%s branch_id=%s did=...%s",
            blocked_reason,
            str(branch.id),
            did[-4:],
        )
        gate_session = AgentSession(
            stt=sarvam.STT(api_key=settings.sarvam_api_key, model="saaras:v3", language="te-IN"),
            llm=_build_fallback_llm(),
            tts=sarvam.TTS(
                api_key=settings.sarvam_api_key,
                model="bulbul:v3",
                speaker=getattr(branch, "tts_voice", None) or "rupali",
                target_language_code="te-IN",
                pace=1.3,
            ),
            vad=silero.VAD.load(),
        )
        await gate_session.start(
            room=ctx.room,
            agent=Agent(instructions="Say nothing. The call is being ended."),
        )
        await gate_session.say(sanitize_for_tts(SERVICE_BLOCKED_UTTERANCE))
        await asyncio.sleep(1.0)  # let the tail of the audio flush
        try:
            lkapi = api.LiveKitAPI()
            await lkapi.room.delete_room(api.DeleteRoomRequest(room=ctx.room.name))
            await lkapi.aclose()
        except Exception as e:
            logger.error("blocked_call_hangup_failed: %s", e)
        await db.close()
        return

    if True:  # noqa: SIM108 — preserves indentation of the call-setup block
        branch_id, branch_name = branch.id, branch.name
        emergency_contact = branch.emergency_contact or ""
        tts_voice = getattr(branch, "tts_voice", None) or "rupali"
        state.branch_id = branch_id
        state.emergency_contact = emergency_contact
        state.plan = org_plan  # was always "clinic" — solo cap could never fire

        result = await db.execute(
            select(Doctor).where(
                and_(Doctor.branch_id == branch_id, Doctor.status == "active")
            )
        )
        doctors = result.scalars().all()
        doctor_contexts = [
            DoctorContext(
                id=str(d.id),
                name=d.name,
                specialization=d.specialization or "",
                routing_keywords=list(d.routing_keywords or []),
                booking_type=d.booking_type or "token",
                is_default=bool(d.is_default_doctor),
            )
            for d in doctors
        ]

        # The LLM has NO clock: without this it guesses today's date (wrong
        # year even), books "tomorrow" in the past, and the past-date guard
        # then refuses everything. Branch-local time, not server time.
        try:
            from zoneinfo import ZoneInfo

            now_b = datetime_cls.now(ZoneInfo(branch.timezone or "Asia/Kolkata"))
        except Exception:
            now_b = datetime_cls.now()
        date_context = (
            f"\n\nTODAY IS {now_b.strftime('%A, %d %B %Y')} "
            f"({now_b.strftime('%Y-%m-%d')}), current time {now_b.strftime('%H:%M')}. "
            "Resolve EVERY relative date from this — today/ఈరోజు, "
            "tomorrow/రేపు, ఎల్లుండి (day after tomorrow), next Monday, etc. "
            "Always pass booking_date as YYYY-MM-DD with the correct year. "
            "Never announce a date the patient didn't ask about."
        )

        instructions = (
            build_system_prompt(
                clinic_name=branch_name,
                doctors=doctor_contexts,
                emergency_contact=emergency_contact,
                plan=state.plan or "clinic",
            )
            + date_context
            + BREVITY_OVERRIDE
        )
        # Outbound calls carry the doctor in metadata — pre-select so tools
        # never fail with "Unknown doctor" no matter how the LLM names them.
        if meta.get("doctor_id"):
            try:
                state.doctor_id = UUID(meta["doctor_id"])
            except ValueError:
                pass
        if is_reminder:
            instructions += REMINDER_PROMPT_EXTRA.format(
                token_id=meta.get("token_id", ""),
                doctor=meta.get("doctor_name", ""),
                time=meta.get("appointment_time", ""),
            )
            state.call_type = "reminder"
        elif is_rebook_call:
            instructions += REBOOK_PROMPT_EXTRA.format(
                cancelled_date=meta.get("cancelled_date", ""),
                doctor=meta.get("doctor_name", ""),
                patient=meta.get("patient_name", ""),
            )
            state.call_type = "cascade_rebook"
            if meta.get("followup_task_id"):
                try:
                    state.followup_task_id = UUID(meta["followup_task_id"])
                except ValueError:
                    pass

        try:
            # SA path resolved against repo root — settings default is the
            # relative './google-service-account.json', which breaks when the
            # worker's cwd is livekit_minimal/.
            sa_path = _REPO_ROOT / "google-service-account.json"
            calendar_service: CalendarService | None = CalendarService(
                sa_json_path=str(sa_path) if sa_path.exists() else None
            )
        except Exception as e:
            logger.critical("calendar_service_init_failed: %s", e)
            calendar_service = None

        vachanam_agent = VachanamAgent(
            instructions=instructions,
            state=state,
            db=db,
            room=ctx.room,
            calendar_service=calendar_service,
            meta_service=MetaService(),
            transfer_to=emergency_contact,
        )

        session = AgentSession(
            stt=sarvam.STT(
                api_key=settings.sarvam_api_key,
                model="saaras:v3",
                language="te-IN",
                flush_signal=True,  # final transcript on client VAD end (-1-2s/turn)
            ),
            llm=_build_fallback_llm(),
            tts=sarvam.TTS(
                api_key=settings.sarvam_api_key,
                model="bulbul:v3",
                speaker=tts_voice,  # clinic-selected (branches.tts_voice, default rupali)
                target_language_code="te-IN",
                pace=1.3,
            ),
            vad=silero.VAD.load(),
            preemptive_generation=True,
            min_endpointing_delay=0.4,
            max_endpointing_delay=3.0,
        )

        @session.on("metrics_collected")
        def _on_metrics(ev: MetricsCollectedEvent) -> None:
            metrics.log_metrics(ev.metrics)

        # RULE 3: release a held-but-unconfirmed token when the call ends.
        # Also closes the long-lived DB session (entrypoint returns while the
        # call is still live — LiveKit keeps the session running; cleanup
        # happens here at job shutdown).
        async def _cleanup_on_shutdown() -> None:
            try:
                if (
                    state.token_held
                    and not state.token_confirmed
                    and state.token_redis_key
                ):
                    r = aioredis.from_url(settings.redis_url, decode_responses=True)
                    try:
                        # Only roll back if OUR number is still the latest —
                        # a blind DECR after someone else INCRed would make the
                        # counter reissue their number (same bug as cancel's).
                        current = int(await r.get(state.token_redis_key) or 0)
                        if state.token_number is not None and current == state.token_number:
                            await r.decr(state.token_redis_key)
                            logger.warning(
                                "token_released_on_disconnect token=%s branch_id=%s",
                                state.token_number,
                                str(state.branch_id),
                            )
                    finally:
                        await r.aclose()
                # Call log — analytics + minute metering (Rule 9: last-4 only).
                try:
                    from backend.models.schema import CallLog

                    started = state.call_start or datetime_cls.now(timezone_utc)
                    await db.rollback()  # clear any failed tx before logging
                    db.add(
                        CallLog(
                            branch_id=state.branch_id,
                            call_type=state.call_type or "inbound",
                            caller_last4=(state.patient_phone or "")[-4:] or None,
                            answered=True,
                            started_at=started,
                            duration_seconds=max(
                                0,
                                int(
                                    (datetime_cls.now(timezone_utc) - started).total_seconds()
                                ),
                            ),
                            booking_made=state.token_confirmed,
                        )
                    )
                    await db.commit()
                except Exception as e:
                    logger.warning("call_log_write_failed: %s", e)
            finally:
                await db.close()

        ctx.add_shutdown_callback(_cleanup_on_shutdown)

        await session.start(
            room=ctx.room,
            agent=vachanam_agent,
            room_input_options=RoomInputOptions(
                noise_cancellation=noise_cancellation.BVCTelephony(),
            ),
        )

        # RULE 6: single short opening utterance, sanitized.
        if is_reminder:
            # L6: speak the time in Telugu words, not raw "16:30".
            _appt_raw = meta.get("appointment_time", "")
            try:
                _spoken_time = telugu_time(time_cls.fromisoformat(_appt_raw))
            except (ValueError, TypeError):
                _spoken_time = _appt_raw
            await session.say(
                sanitize_for_tts(
                    REMINDER_GREETING.format(
                        patient=meta.get("patient_name", ""),
                        clinic=branch_name,
                        doctor=meta.get("doctor_name", ""),
                        time=_spoken_time,
                    )
                )
            )
        elif is_rebook_call:
            # ISO date would be read digit-by-digit by TTS — speak it in Telugu.
            try:
                spoken_date = telugu_date(date_cls.fromisoformat(meta.get("cancelled_date", "")))
            except ValueError:
                spoken_date = meta.get("cancelled_date", "")
            await session.say(
                sanitize_for_tts(
                    REBOOK_GREETING.format(
                        patient=meta.get("patient_name", ""),
                        clinic=branch_name,
                        doctor=meta.get("doctor_name", ""),
                        date=spoken_date,
                    )
                )
            )
        else:
            await session.say(
                sanitize_for_tts(DISCLOSURE_GREETING.format(clinic=branch_name))
            )

        # SOLO-PLAN CALL CAP (pricing table: "4-min AI call cap"). The Pipecat
        # watchdog (TD-009) was lost in the LiveKit port — solo calls ran
        # unbounded. Warn 10s before the cap, then close politely AT the cap.
        # Default 240s for solo even when the env var is 0/unset (bug-bounty T2 —
        # the cap shipped disabled-by-default). A non-zero env value overrides.
        #
        # ABSOLUTE SAFETY CEILING (bounce F16): clinic/multi have no per-call
        # plan cap, but a stuck call still burns Vobiz+LiveKit+Sarvam minutes
        # (~₹1.49/min) forever. Worse, if plan resolution failed above, a SOLO
        # clinic mis-defaults to "clinic" and dodges its 240s cap. So every call
        # gets a ceiling: solo → 240s, everyone else → ABSOLUTE_CAP. A real call
        # finishes in ~4 min; the ceiling only ever fires on a hung session.
        SOLO_CAP_DEFAULT = 240
        ABSOLUTE_CAP_DEFAULT = 900  # 15 min — never hits a legitimate call
        if state.plan == "solo":
            cap = settings.max_call_duration_seconds or SOLO_CAP_DEFAULT
        else:
            cap = ABSOLUTE_CAP_DEFAULT
        if cap and cap > 15:

            async def _solo_cap_watchdog() -> None:
                try:
                    await asyncio.sleep(cap - 10)
                    if not state.solo_warning_sent:
                        state.solo_warning_sent = True
                        await session.say(
                            sanitize_for_tts(
                                "క్షమించండి, మన సమయం అయిపోతోంది. మీ బుకింగ్ "
                                "ఖరారు చేద్దాం."
                            )
                        )
                    await asyncio.sleep(10)
                    await session.say(
                        sanitize_for_tts("ధన్యవాదాలు అండి, ఉంటాను!")
                    )
                    try:
                        await session.current_speech.wait_for_playout()
                    except Exception:
                        pass
                    lkapi = api.LiveKitAPI()
                    await lkapi.room.delete_room(api.DeleteRoomRequest(room=ctx.room.name))
                    await lkapi.aclose()
                    logger.info("solo_cap_reached room=%s cap=%ds", ctx.room.name, cap)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("solo_cap_watchdog_failed: %s", e)

            _cap_task = asyncio.create_task(_solo_cap_watchdog())
            ctx.add_shutdown_callback(lambda: _cap_task.cancel())


if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=AGENT_NAME,
        )
    )
