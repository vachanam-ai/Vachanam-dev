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
import random
import re
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
from livekit.plugins import google, noise_cancellation, openai, sarvam, silero, smallestai  # noqa: E402
from livekit.plugins.turn_detector.multilingual import MultilingualModel  # noqa: E402

import redis.asyncio as aioredis  # noqa: E402
from sqlalchemy import and_, select  # noqa: E402

from agent.i18n import get_lang, get_lines, get_welcome  # noqa: E402
from agent.i18n.transliterate import spoken_name  # noqa: E402
from agent.prompts.system_prompt import (  # noqa: E402
    DoctorContext,
    build_date_context,
    build_system_prompt,
)
# CalendarService (legacy-signature shim), NOT GoogleCalendarService —
# booking_tools.confirm_booking calls the legacy create_booking_event kwargs.
from agent.services.calendar_proxy import CalendarService  # noqa: E402
from agent.services.meta_stub import MetaService  # noqa: E402
from agent.services.telugu_dates import telugu_date, telugu_time  # noqa: E402
from agent.livekit_minimal.welcome_audio import play_welcome  # noqa: E402
from agent.services.tts_sanitizer import sanitize_for_tts  # noqa: E402
from agent.session_state import SessionState  # noqa: E402
from agent.tools.booking_tools import (  # noqa: E402
    assign_token,
    check_availability,
    confirm_booking,
    find_bookings_by_phone,
    recognize_caller_name,
    route_to_doctor,
)
from backend.config import settings  # noqa: E402
from backend.database import AsyncSessionLocal, get_loop_engine  # noqa: E402
from backend.models.schema import Branch, Doctor  # noqa: E402
from backend.models.schema import Patient as _PatientModel  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vachanam-agent")

AGENT_NAME = "vachanam-agent"

# iter1 #11/#19: bounds at the confirm_booking tool boundary. The LLM-supplied
# free-text fields are untrusted — mirror the walk-in desk Field max_lengths
# (queue.py: name<=120, complaint<=500) and clamp the age range so a prompt-
# injected / hallucinated value can't write garbage or oversized rows. The
# family-booking cap stops a hijacked/looping model mass-booking under one
# caller-ID in a single call.
MAX_PATIENT_NAME_LEN = 120
MAX_COMPLAINT_LEN = 500
MIN_PATIENT_AGE = 0
MAX_PATIENT_AGE = 120
MAX_DIFFERENT_PERSON_BOOKINGS_PER_CALL = 2

# Spoken hardcoded lines (greetings, fillers, service-blocked, reminder/rebook,
# caps) now live per-language in agent/i18n/lines.py and are resolved per call
# from Branch.language. The Telugu set there is Vinay's validated reference.

# LATENCY/UX (Vinay 2026-06-14): route_to_doctor (routing LLM + DB) and
# check_availability (DB) take a beat. With no word the caller hears dead air and
# thinks the line dropped. A real receptionist fills it — "one moment, I'm
# checking". session.say() is non-blocking, so the filler covers the gap WHILE
# the tool runs; add_to_chat_ctx=False keeps it out of the LLM turn history.
# The clinic's language fillers ride on the session's userdata (set at session
# build); this Telugu set is the fallback if userdata is ever missing.
_FALLBACK_FILLERS = get_lines("te").fillers


def _say_lookup_filler(context) -> None:
    """Speak a short 'let me check' filler over the dead air while a lookup tool
    runs. Picks the clinic-language fillers off the session userdata (falls back
    to Telugu). Non-blocking and fully guarded — it must NEVER affect booking."""
    try:
        fillers = None
        sess = getattr(context, "session", None)
        ud = getattr(sess, "userdata", None)
        if ud is None:
            ud = getattr(context, "userdata", None)
        if isinstance(ud, dict):
            fillers = ud.get("fillers")
        context.session.say(
            sanitize_for_tts(random.choice(fillers or _FALLBACK_FILLERS)),
            add_to_chat_ctx=False,
        )
    except Exception as e:
        logger.debug("lookup_filler_skipped: %s", e)


def _build_caller_context(rows, today) -> tuple[str | None, str]:
    """Identify an inbound caller from their existing bookings (RULE 1 already
    applied — rows are branch-scoped via find_bookings_by_phone).

    Returns (greeting_name, prompt_extra):
      - greeting_name: the patient name to greet by, or None when the caller is
        new OR several different patients share the number (don't reveal one).
      - prompt_extra: caller-identity instructions injected into the system
        prompt so the agent knows their FUTURE bookings up front and handles the
        "wants a new booking but already has one" case without a tool round-trip.
    """
    confirmed = [
        (t, d, p) for (t, d, p) in rows if t.status == "confirmed" and t.date >= today
    ]
    if not confirmed:
        return None, ""  # new caller (or only clinic-cancelled) -> normal flow
    names = {p.name.strip() for (_, _, p) in confirmed}
    greeting_name = next(iter(names)) if len(names) == 1 else None
    lines = []
    for t, d, p in confirmed:
        if t.appointment_time:
            ref = f"time {t.appointment_time.strftime('%I:%M %p').lstrip('0')}"
        else:
            ref = f"token {t.token_number}"
        lines.append(
            f"  - token_id={t.id} | patient={p.name} | doctor={d.name} | "
            f"date={t.date.isoformat()} | {ref} | type={d.booking_type}"
        )
    bookings_block = "\n".join(lines)
    who = (
        f" by name ({greeting_name})."
        if greeting_name
        else " (several patients share this number — ask which patient they mean "
        "before acting on a specific booking)."
    )
    extra = (
        "\n\nCALLER IDENTIFICATION (looked up by their phone BEFORE this call — "
        "do NOT call find_my_bookings, you already have it):\n"
        "This is an EXISTING patient. The greeting already welcomed them" + who + "\n"
        "Ask their concern warmly. Speak all dates/times in Telugu words.\n"
        "FUTURE booking(s) already on file for this number:\n"
        f"{bookings_block}\n"
        "HOW TO HANDLE THIS CALLER:\n"
        "- Reschedule/cancel one of the above: use its token_id directly "
        "(never re-ask their number).\n"
        "- They ask for a NEW booking while a future booking above already "
        "exists: do NOT silently create a second one. Tell them they already "
        "have a booking on that date and time with that doctor, then ask ONE "
        "question — reschedule that one, or a separate new booking? Follow their "
        "choice: reschedule_booking(old token_id) to move it, or the normal "
        "BOOKING FLOW for a genuinely separate booking (e.g. a family member — "
        "pass different_person=true if same patient_phone+doctor+day).\n"
        "- A clearly UNRELATED request (different doctor/concern): just book it "
        "normally.\n"
    )
    return greeting_name, extra


def _cancel_on_shutdown(task):
    """Async shutdown callback that cancels ``task``. LiveKit 1.6 ``await``s
    shutdown callbacks, so a bare ``lambda: task.cancel()`` (Task.cancel returns
    a bool) raised 'object bool can't be used in await' on every call teardown."""
    async def _cb() -> None:
        task.cancel()
    return _cb


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

NEXT_VISIT_PROMPT_EXTRA = (
    "\n\nTHIS IS A TREATMENT FOLLOW-UP CALL. You already know this patient — never "
    "ask who they are or restart the new-patient flow.\n"
    "1) If a message is given, ask it warmly in the clinic's language: \"{message}\".\n"
    "2) If a target date is given ({target_date}), offer to book a visit within 2 "
    "days of it; on agreement use the booking tools (assign a token around that "
    "date) and confirm in one breath.\n"
    "3) You are a MESSENGER, not a doctor: give NO medical advice, NO diagnosis, NO "
    "triage. If the patient reports ANY problem or pain, say warmly: 'I will inform "
    "the doctor and they will get back to you as soon as possible.' Do not advise.\n"
    "Keep every reply to two short sentences."
)

DOCTOR_ADVICE_PROMPT_EXTRA = (
    "\n\nTHIS IS A DOCTOR-ADVICE RELAY CALL. The doctor reviewed the patient's "
    "concern and wrote a message. RELAY it warmly and faithfully in the clinic's "
    "language — do NOT add, interpret, or invent any medical content of your own "
    "(RULE 7). The doctor's message: \"{message}\".\n"
    "After relaying, ask if they have more concerns; if a target date "
    "({target_date}) is given, offer to book within 2 days of it. If they report a "
    "new problem, say 'I will inform the doctor and get back to you as soon as "
    "possible.' Two short sentences per reply."
)

_FOLLOWUP_CALLTYPES = {"next_visit_book", "doctor_advice"}


def _followup_meta_safe(meta: dict) -> dict:
    """RULE 9: the ONLY metadata fields allowed to reach the LLM/agent for a
    follow-up call. Private clinical notes (steps_performed/next_steps) must never
    appear here even if a future caller accidentally includes them."""
    allowed = ("call_type", "message", "target_date", "window",
               "patient_name", "doctor_name", "doctor_id", "task_id")
    return {k: meta[k] for k in allowed if k in meta}



def _build_fallback_llm() -> lk_llm.FallbackAdapter:
    """RULE 9: Gemini primary, GPT-4o-mini automatic fallback.

    attempt_timeout is forwarded to the provider as the HTTP deadline; the
    Google GenAI API rejects anything under 10s with a 400, which silently
    pushed every single turn onto GPT-4o-mini (and its much weaker Telugu).
    """
    from google.genai import types as genai_types

    # IMPORTANT (2026-06-24): do NOT add per-LLM retries or extra Gemini tiers
    # here. A retry/extra-tier variant pushed live TTFT to 9.5s during a Gemini
    # 503 storm (each failed attempt waits before switching) — far worse on a
    # phone than a fast switch to GPT-4o-mini. Fail FAST to the fallback.
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


async def update_call_duration(call_log_id, seconds: int) -> None:
    """Set a CallLog row's duration in its own short-lived session (metering
    heartbeat). Separate session because the call's main `db` is busy with the
    booking flow and an async session is not safe for concurrent use."""
    from sqlalchemy import update as _u

    from backend.models.schema import CallLog as _CL

    async with AsyncSessionLocal() as s:
        await s.execute(
            _u(_CL).where(_CL.id == call_log_id).values(duration_seconds=int(seconds))
        )
        await s.commit()


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


_PHONE_DIGITS_RE = re.compile(r"\d{4,}")


def _mask_pii_for_transcript(text: str) -> str:
    """Best-effort PII reduction before a transcript is stored. Masks any run of
    4+ consecutive digits (phone numbers, OTP-like sequences) to '[number]'.
    NOTE: spoken digits transcribed as words ("nine six six...") are NOT masked —
    this is reduction, not guarantee; the row is still tenant-scoped + retention-
    pruned. Names/ages are left (needed to study STT mishears) but the whole row
    is treated as PII (DPDP) and dropped on the transcript-retention schedule."""
    return _PHONE_DIGITS_RE.sub("[number]", text or "")


def _extract_call_record(session) -> tuple[int, str | None]:
    """From the live session's chat history build (patient_turns, transcript).

    Returns the count of patient (user) turns and a role-tagged, phone-masked
    transcript string, or (0, None) if history is unavailable. Never raises —
    transcript capture must never break call teardown."""
    try:
        history = getattr(session, "history", None)
        items = getattr(history, "items", None) if history is not None else None
        if not items:
            return 0, None
        lines_out: list[str] = []
        patient_turns = 0
        for it in items:
            role = getattr(it, "role", None)
            if role not in ("user", "assistant"):
                continue  # skip system / tool items
            # content may be a list of parts or a plain string across SDK versions
            txt = getattr(it, "text_content", None)
            if not txt:
                content = getattr(it, "content", None)
                if isinstance(content, str):
                    txt = content
                elif isinstance(content, (list, tuple)):
                    txt = " ".join(str(c) for c in content if isinstance(c, str))
            txt = (txt or "").strip()
            if not txt:
                continue
            who = "patient" if role == "user" else "agent"
            if role == "user":
                patient_turns += 1
            lines_out.append(f"{who}: {txt}")
        if not lines_out:
            return patient_turns, None
        return patient_turns, _mask_pii_for_transcript("\n".join(lines_out))
    except Exception:  # noqa: BLE001 — capture is best-effort, never fatal
        return 0, None


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

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        """ECHO GUARD (self-talk loop). A phone line can bounce the agent's own
        TTS back; Sarvam STT then transcribes it as if the CALLER said it, and
        the agent answers itself — an endless self-talk loop (BVCTelephony AEC
        does not always fully cancel carrier line echo). Drop a user turn that is
        a near-verbatim echo of the agent's immediately preceding utterance.

        Thresholds are deliberately strict (long text, ~85% match) so a REAL
        patient turn is never discarded — a false negative (occasional echo slips
        through) is far safer than a false positive (ignoring the patient)."""
        try:
            import difflib

            norm_user = self._normalize_for_echo(self._message_text(new_message))
            if len(norm_user) < 20:
                return  # too short to be a confident full-sentence echo
            last_agent = ""
            for item in reversed(getattr(turn_ctx, "items", None) or []):
                if getattr(item, "role", None) == "assistant":
                    last_agent = self._message_text(item)
                    break
            norm_agent = self._normalize_for_echo(last_agent)
            if len(norm_agent) < 20:
                return
            ratio = difflib.SequenceMatcher(None, norm_user, norm_agent).ratio()
            if ratio >= 0.85 or (len(norm_user) >= 25 and norm_user in norm_agent):
                from livekit.agents import StopResponse

                logger.warning(
                    "echo_turn_discarded ratio=%.2f len=%d branch_id=%s",
                    ratio, len(norm_user), str(self._state.branch_id),
                )
                raise StopResponse()
        except Exception as e:
            # StopResponse is the intended control-flow signal — re-raise it.
            from livekit.agents import StopResponse

            if isinstance(e, StopResponse):
                raise
            # Any other error must NEVER swallow a real turn — let it through.
            logger.warning("echo_guard_error: %s", e)

    @staticmethod
    def _message_text(m) -> str:
        t = getattr(m, "text_content", None)
        if isinstance(t, str) and t:
            return t
        c = getattr(m, "content", None)
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(x for x in c if isinstance(x, str))
        return ""

    @staticmethod
    def _normalize_for_echo(s: str) -> str:
        """Lowercase and strip whitespace + ASCII punctuation so spacing/STT
        punctuation differences don't hide an echo. Script letters (Telugu etc.)
        are preserved — only separators are removed."""
        import re

        return re.sub(r"[\s\W_]+", "", (s or "").lower())

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
        _say_lookup_filler(context)  # cover the routing-LLM/DB beat (no dead air)
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
        _say_lookup_filler(context)  # cover the DB lookup beat (no dead air)
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
            # APPOINTMENT (schedule) doctors have NO patient-facing queue number —
            # the returned token_number is an internal slot index. Surfacing it to
            # the LLM is exactly how it gets spoken as a "token number" on schedule
            # bookings (recurring live bug — FIXLOG #97/#103/#104). Prompt rules
            # alone kept being ignored, so we never put the number in front of the
            # model: it only receives the time it may read back. The real number
            # stays in self._state.token_number for confirm_booking.
            if result.get("booking_type") == "appointment":
                return {
                    "success": True,
                    "booking_type": "appointment",
                    "appointment_time": result.get("appointment_time"),
                    "announce": "time_only",
                    "instruction": (
                        "Schedule doctor — confirm ONLY the date and time. NEVER "
                        "say a token or queue number."
                    ),
                }
        return result

    @function_tool()
    async def confirm_booking(
        self,
        context: RunContext,
        doctor_id: str,
        patient_name: str,
        complaint: str,
        booking_date: str,
        followup_consent: bool,
        patient_phone: str | None = None,
        appointment_time: str | None = None,
        patient_age: int | None = None,
        patient_gender: str | None = None,
        different_person: bool = False,
        # OPTIONAL: appointment (time) bookings have no queue token, so the LLM
        # omits it. The body resolves the real number from the server-side hold
        # (assign_token) regardless — never trust the LLM's echo. Required arg
        # before made bookings hard-fail with "token_number Field required".
        token_number: int | None = None,
    ) -> dict:
        """Finalize the booking AFTER the patient explicitly confirms. Writes the
        token to the database and creates the calendar event. patient_name is the
        PATIENT being seen (may differ from the caller — family bookings);
        patient_phone defaults to the caller's number when omitted.
        patient_gender: 'male' | 'female' | 'other' if known.
        different_person: True ONLY when the caller explicitly books for a
        DIFFERENT family member who already has a booking that day."""
        # Booking touches the DB + writes the calendar (the slowest step) — cover
        # that beat with a spoken filler so the patient never hears dead air mid-
        # booking. Non-blocking + fully guarded (never affects the booking).
        _say_lookup_filler(context)
        if self._calendar is None:
            logger.error("confirm_booking_no_calendar_service")
            return {"success": False, "error": "booking_system_unavailable"}

        # iter1 #11/#19: bound the untrusted, LLM-supplied free-text/numeric
        # fields at the tool boundary (mirror the walk-in desk Field limits).
        patient_name = (patient_name or "").strip()
        if not patient_name:
            raise ToolError("patient_name is required.")
        if len(patient_name) > MAX_PATIENT_NAME_LEN:
            raise ToolError(
                f"patient_name too long (max {MAX_PATIENT_NAME_LEN} chars)."
            )
        complaint = (complaint or "").strip()
        if len(complaint) > MAX_COMPLAINT_LEN:
            raise ToolError(f"complaint too long (max {MAX_COMPLAINT_LEN} chars).")
        if patient_age is not None and not (
            MIN_PATIENT_AGE <= patient_age <= MAX_PATIENT_AGE
        ):
            raise ToolError(
                f"patient_age out of range ({MIN_PATIENT_AGE}-{MAX_PATIENT_AGE})."
            )

        # iter1 #11: phone defaults to the VERIFIED caller-ID. Only honor an
        # LLM-passed override when different_person=True (an explicit family
        # booking for someone else); a caller's own booking is ALWAYS attributed
        # to the number they dialed from, never an LLM-asserted phone.
        if different_person and patient_phone:
            phone = patient_phone
        else:
            phone = self._state.patient_phone

        # iter1 #11: cap family bookings per call so a hijacked/looping model
        # can't mass-book different people under one caller-ID.
        if different_person and (
            self._state.different_person_bookings
            >= MAX_DIFFERENT_PERSON_BOOKINGS_PER_CALL
        ):
            logger.warning(
                "different_person_booking_cap_hit count=%d session=%s",
                self._state.different_person_bookings,
                self._state.session_id,
            )
            raise ToolError(
                "Too many separate family bookings on one call. Please call "
                "again for additional family members."
            )

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
            if different_person:
                # iter1 #11: count only CONFIRMED family bookings toward the cap.
                self._state.different_person_bookings += 1
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
        # Release any hold THIS session already placed before re-assigning. The
        # caller often first asks to "book" the new time (the LLM assigns a hold),
        # then we steer them to reschedule the existing booking instead. That
        # stale hold — frequently on the SAME slot they now want — makes the
        # assign_token below see the slot as full and wrongly report it
        # "unavailable". Releasing it first lets the re-assign see true capacity.
        if self._state.token_held and self._state.token_redis_key:
            await self._release_hold({"redis_key": self._state.token_redis_key})
            self._clear_hold()
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

        # TD-020: the PATIENT is cancelling their own booking on the call —
        # distinct from a clinic cascade-cancel (doctor leave). Keeping them
        # separate stops analytics conflating the two and stops a self-cancelled
        # patient ever getting a rebook call (rebook context filters on
        # cancelled_by_clinic only).
        token.status = "cancelled_by_patient"
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
        self._state.transfer_requested = True  # quality signal (CallLog)
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
    # Treatment follow-up loop (M2): next_visit_book / doctor_advice.
    is_followup = meta.get("call_type") in _FOLLOWUP_CALLTYPES
    # RULE 9 — the LLM/agent only ever sees the allowlisted operational fields of a
    # follow-up call; private clinical notes (steps_performed/next_steps) never reach
    # the prompt. SIP routing (phone_number/branch_id/outbound_trunk_id) still reads
    # the RAW `meta`, so build the safe view separately rather than overwriting it.
    followup_meta = _followup_meta_safe(meta) if is_followup else {}

    # LATENCY: warm a DB connection NOW, before the outbound dial / SIP wait below
    # (both are dead time — the phone is ringing). Every call runs on a FRESH event
    # loop, so the pool is COLD and the first query otherwise pays a ~1.8s Neon
    # TLS+auth handshake right before the greeting. For OUTBOUND this matters most:
    # branch resolution runs the instant the patient answers, so the handshake must
    # already be done. Fire-and-forget; never blocks or fails the call.
    from sqlalchemy import text as _sql_text

    async def _warm_db_pool() -> None:
        try:
            eng = get_loop_engine()
            async with eng.connect() as _wc:
                await _wc.execute(_sql_text("SELECT 1"))
        except Exception as _we:  # noqa: BLE001 — warming is best-effort
            logger.warning("db_pool_warm_failed: %s", _we)

    _warm_task = asyncio.create_task(_warm_db_pool())

    if outbound_number:
        logger.info("Outbound: dialing ...%s", outbound_number[-4:])
        try:
            # Per-clinic Vobiz sub-account: the dispatching job stamps this
            # branch's outbound trunk into the metadata. Fall back to the global
            # trunk so single-account clinics keep working unchanged.
            _out_trunk = meta.get("outbound_trunk_id") or os.getenv("OUTBOUND_TRUNK_ID", "")
            await ctx.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    room_name=ctx.room.name,
                    sip_trunk_id=_out_trunk,
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
    # Pre-greeting latency anchor: measures answer -> first spoken word, to
    # localise the "10s before it talks" complaint (setup vs session-connect).
    import time as _perf
    _t_answer = _perf.monotonic()

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

    # Per-clinic voice language (Branch.language → Sarvam STT/TTS codes + the
    # spoken lines + system-prompt directive). Resolved ONCE here so both the
    # service-gate path and the main call path speak the clinic's language.
    # get_lang/get_lines fall back to Telugu for None/unknown/legacy rows, so a
    # bad value can never break a live call (RULE 8).
    lang_code = getattr(branch, "language", None) or "te"
    lang_cfg = get_lang(lang_code)
    lines = get_lines(lang_code)

    # Super-admin service gate: paused/cancelled org, expired trial, or
    # hard-block with the month's minutes exhausted -> answer, speak ONE line,
    # hang up (RULE 8). Also captures the org plan for the call-duration cap.
    blocked_reason = None
    org_plan = "clinic"
    # iter1 #23: the gate must FAIL CLOSED for known terminal states. We record
    # the org's last-known status the moment we read it; if a LATER step in this
    # block raises (e.g. the minutes-sum query), the except handler refuses the
    # call when that status is paused/cancelled — a billing/DB hiccup must not
    # grant free service to an org the owner has already shut off. Genuinely
    # transient/unknown lookups (org row not even read yet) still fail open so a
    # blip never hangs up on a paying, active clinic.
    last_known_status: str | None = None
    try:
        from zoneinfo import ZoneInfo as _ZoneInfo

        from backend.models.schema import CallLog, Organization
        from backend.services.billing_math import call_blocked

        org = (
            await db.execute(select(Organization).where(Organization.id == branch.org_id))
        ).scalar_one_or_none()
        if org is not None:
            last_known_status = (org.status or "").lower()
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

                # LATENCY: one round-trip, not two. The org's branch ids are an
                # in-DB scalar subquery instead of a separate SELECT-then-IN.
                _org_branch_ids = select(Branch.id).where(Branch.org_id == org.id)
                secs = (
                    await db.execute(
                        select(_func.coalesce(_func.sum(CallLog.duration_seconds), 0)).where(
                            and_(
                                CallLog.branch_id.in_(_org_branch_ids),
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
    except Exception as e:
        # iter1 #23: fail CLOSED for a known terminal status, fail OPEN otherwise.
        # If we already learned the org is paused/cancelled/suspended, a downstream
        # error must NOT let the call through (free service to a shut-off org).
        blocked_reason = _gate_failure_blocked_reason(last_known_status)
        if blocked_reason:
            logger.warning(
                "service_gate_check_failed_failing_closed status=%s err=%s",
                last_known_status,
                e,
            )
        else:
            logger.warning("service_gate_check_failed_failing_open: %s", e)

    if blocked_reason:
        logger.warning(
            "call_blocked reason=%s branch_id=%s did=...%s",
            blocked_reason,
            str(branch.id),
            did[-4:],
        )
        gate_session = AgentSession(
            stt=sarvam.STT(api_key=settings.sarvam_api_key, model="saaras:v3", language=lang_cfg.stt_code),
            llm=ctx.proc.userdata.get("llm") or _build_fallback_llm(),
            # TTS = smallest.ai Waves (STT stays Sarvam Saaras). voice falls back
            # to the language's default smallest voice when the clinic hasn't set one.
            tts=smallestai.TTS(
                api_key=settings.smallest_api_key,
                model=settings.smallest_model,
                voice_id=(getattr(branch, "tts_voice", None) or "").strip() or lang_cfg.default_voice,
                language=lang_cfg.tts_code,
                sample_rate=settings.smallest_sample_rate,
                output_format="pcm",
            ),
            vad=ctx.proc.userdata.get("vad") or silero.VAD.load(),
        )
        await gate_session.start(
            room=ctx.room,
            agent=Agent(instructions="Say nothing. The call is being ended."),
        )
        await gate_session.say(sanitize_for_tts(lines.service_blocked))
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
        # Speak the clinic name in the call's script (RULE 6): "Datta" must be
        # HEARD as "దత్త", not English "data". Use the stored spoken form; if it
        # is unset, transliterate once and store it asynchronously (off the call
        # path) so later calls read it instantly. Best-effort — never blocks.
        _stored_spoken = (getattr(branch, "name_spoken", None) or "").strip()
        if _stored_spoken:
            branch_name = _stored_spoken
        else:
            try:
                _tl_clinic = await spoken_name(branch.name, lang_code)
            except Exception:  # noqa: BLE001 — RULE 8
                _tl_clinic = branch.name
            if _tl_clinic and _tl_clinic != branch.name:
                branch_name = _tl_clinic

                async def _store_clinic_spoken(_bid=branch_id, _val=_tl_clinic) -> None:
                    try:
                        from sqlalchemy import update as _u
                        async with AsyncSessionLocal() as _s:
                            await _s.execute(
                                _u(Branch).where(Branch.id == _bid).values(name_spoken=_val)
                            )
                            await _s.commit()
                    except Exception as _e:  # noqa: BLE001
                        logger.warning("name_spoken_store_failed: %s", _e)

                asyncio.create_task(_store_clinic_spoken())
        emergency_contact = branch.emergency_contact or ""
        # smallest.ai voice_id (clinic-chosen or cloned); fall back to the
        # language's default smallest voice when unset (TTS provider = smallest).
        tts_voice = (getattr(branch, "tts_voice", None) or "").strip() or lang_cfg.default_voice
        state.branch_id = branch_id

        # INSTANT CLIP (kills the silence between answer and first word — see
        # welcome_audio). A SHORT "namaskaram <clinic> clinic ki swagatham" bridge,
        # synth'd + published into the room the moment the branch is resolved, run
        # concurrently with the rest of setup, then awaited+unpublished right before
        # the AgentSession is built. Deliberately SHORT (not the full greeting):
        # the real greeting (reminder/rebook/disclosure) is still spoken AFTER
        # session.start so STT is live and the patient can be heard when they reply.
        # Applies to inbound AND outbound (outbound reminder/rebook had the worst
        # post-answer silence). RULE 8: any failure is swallowed; the real greeting
        # still plays regardless.
        _welcome_task = None
        if branch_name:
            _welcome_tts = smallestai.TTS(
                api_key=settings.smallest_api_key,
                model=settings.smallest_model,
                voice_id=tts_voice,
                language=lang_cfg.tts_code,
                sample_rate=settings.smallest_sample_rate,
                output_format="pcm",
            )
            _welcome_task = asyncio.create_task(
                play_welcome(
                    ctx.room,
                    sanitize_for_tts(get_welcome(lang_code).format(clinic=branch_name)),
                    _welcome_tts,
                )
            )
        state.emergency_contact = emergency_contact
        state.plan = org_plan  # was always "clinic" — solo cap could never fire
        state.language = lang_code  # quality/feedback signal (CallLog + transcript)

        # AGENT-SIDE METERING (TD-027/F6) — OFF by default. The Vobiz CDR sync
        # job is the authoritative, agent-independent source of calls + minutes
        # (it survives dropped/crashed/local calls, which the agent path did
        # not). These writes stay behind settings.agent_call_log_enabled so they
        # don't DOUBLE-count alongside CDR rows; enable only where no Vobiz CDR
        # is available.
        if settings.agent_call_log_enabled:
            try:
                from backend.models.schema import CallLog as _CallLog

                _start_row = _CallLog(
                    branch_id=branch_id,
                    call_type=state.call_type or "inbound",
                    caller_last4=(state.patient_phone or "")[-4:] or None,
                    answered=True,
                    started_at=state.call_start or datetime_cls.now(timezone_utc),
                    duration_seconds=0,
                    booking_made=False,
                )
                db.add(_start_row)
                await db.commit()
                state.call_log_id = _start_row.id
            except Exception as _e:
                logger.warning("call_log_start_write_failed: %s", _e)
                try:
                    await db.rollback()
                except Exception:
                    pass

            # METERING HEARTBEAT: update the row's duration every 15s during the
            # call in its OWN short-lived session (the main `db` is busy with the
            # booking flow — an async session is not safe for concurrent use).
            # Makes minutes show even when the call DROPS before the clean-
            # shutdown finalize. The shutdown callback still writes the precise
            # final duration.
            if state.call_log_id is not None:
                _hb_call_log_id = state.call_log_id
                _hb_start = state.call_start or datetime_cls.now(timezone_utc)

                async def _meter_heartbeat() -> None:
                    while True:
                        await asyncio.sleep(15)
                        try:
                            dur = max(
                                0,
                                int(
                                    (datetime_cls.now(timezone_utc) - _hb_start).total_seconds()
                                ),
                            )
                            await update_call_duration(_hb_call_log_id, dur)
                        except asyncio.CancelledError:
                            raise
                        except Exception as _hbe:
                            logger.warning("meter_heartbeat_failed: %s", _hbe)

                _hb_task = asyncio.create_task(_meter_heartbeat())
                ctx.add_shutdown_callback(_cancel_on_shutdown(_hb_task))

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
        # Explicit date table (build_date_context) — LLM weekday math was
        # off-by-one (booked Tuesday on Wednesday's date); now it looks up.
        date_context = build_date_context(now_b)

        # CALLER IDENTIFICATION (requirement 2026-06-14): on a normal INBOUND
        # call, look the caller up by their number BEFORE the greeting so we can
        # welcome a returning patient by name and hand the agent their future
        # bookings (new-vs-existing handling). Skip for outbound/reminder/rebook
        # (those already know the patient from dispatch metadata). RULE 1: the
        # lookup is branch-scoped; a failure must never block answering (RULE 8).
        caller_greeting_name: str | None = None
        caller_prompt_extra = ""
        if not outbound_number and not is_reminder and not is_rebook_call and state.patient_phone:
            try:
                _caller_rows = await find_bookings_by_phone(
                    state.branch_id, state.patient_phone, db
                )
                caller_greeting_name, caller_prompt_extra = _build_caller_context(
                    _caller_rows, now_b.date()
                )
                # No active booking gave a name, but the caller may be a past
                # patient — recognise them by their stored Patient record so a
                # returning caller is greeted by name even years later, not
                # asked "who are you?". Only when nothing ambiguous is on file.
                if caller_greeting_name is None and not caller_prompt_extra:
                    _known = await recognize_caller_name(
                        state.branch_id, state.patient_phone, db
                    )
                    if _known:
                        caller_greeting_name = _known
                        caller_prompt_extra = (
                            "\n\nCALLER IDENTIFICATION: this number belongs to an "
                            f"EXISTING patient, {_known}, with no upcoming booking. "
                            "The greeting already welcomed them by name. Greet warmly, "
                            "ask their concern, and proceed with the normal booking "
                            "flow — do NOT ask for their name again unless they say "
                            "the booking is for a different person."
                        )
            except Exception as e:
                logger.warning("caller_lookup_failed: %s", e)

        instructions = (
            build_system_prompt(
                clinic_name=branch_name,
                doctors=doctor_contexts,
                emergency_contact=emergency_contact,
                plan=state.plan or "clinic",
                language=lang_code,
                clinic_address=getattr(branch, "address", None),
            )
            + date_context
            + lines.brevity
            + caller_prompt_extra
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
        elif meta.get("call_type") == "next_visit_book":
            # Treatment follow-up: ask the doctor's question + book ±2 days. Values
            # come from followup_meta (RULE 9 — the allow-listed safe dict), never
            # the raw metadata, so private notes can never reach the prompt.
            instructions += NEXT_VISIT_PROMPT_EXTRA.format(
                message=followup_meta.get("message", ""),
                target_date=followup_meta.get("target_date", ""),
            )
            state.call_type = "next_visit_book"
        elif meta.get("call_type") == "doctor_advice":
            instructions += DOCTOR_ADVICE_PROMPT_EXTRA.format(
                message=followup_meta.get("message", ""),
                target_date=followup_meta.get("target_date", ""),
            )
            state.call_type = "doctor_advice"

        # Reuse the prewarmed CalendarService (Google client build is the slow
        # part of pre-session setup); rebuild only if prewarm missed it.
        calendar_service: CalendarService | None = ctx.proc.userdata.get("calendar")
        if calendar_service is None:
            try:
                # SA path resolved against repo root — settings default is the
                # relative './google-service-account.json', which breaks when the
                # worker's cwd is livekit_minimal/.
                sa_path = _REPO_ROOT / "google-service-account.json"
                calendar_service = CalendarService(
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

        logger.info("lat_pre_session_build answer_to_build=%.2fs", _perf.monotonic() - _t_answer)

        _t_build = _perf.monotonic()
        session = AgentSession(
            # Per-clinic spoken-language fillers ride here so _say_lookup_filler
            # speaks the clinic's language (falls back to Telugu).
            userdata={"fillers": lines.fillers, "language": lang_code},
            stt=sarvam.STT(
                api_key=settings.sarvam_api_key,
                model="saaras:v3",
                # STRICT per-call clinic language (Vinay 2026-06-17): auto-detect
                # ("unknown") was tried but rejected — shared words across Indian
                # languages ("amma", numbers) make Sarvam mis-infer the language and
                # degrade transcription. A true mid-call switch is also not feasible
                # here (LiveKit session.stt is read-only — no hot-swap), so we keep
                # one fixed language per call for reliable understanding.
                language=lang_cfg.stt_code,
                flush_signal=True,  # final transcript on client VAD end (-1-2s/turn)
            ),
            llm=ctx.proc.userdata.get("llm") or _build_fallback_llm(),
            # TTS = smallest.ai Waves Lightning (replaced Sarvam Bulbul 2026-06-15).
            # STT above stays Sarvam Saaras. voice_id is the clinic's smallest voice
            # (or a cloned voice); language is the clinic's short code (smallest uses
            # the same te/hi/ta/... codes). output_format pcm streams to LiveKit.
            tts=smallestai.TTS(
                api_key=settings.smallest_api_key,
                model=settings.smallest_model,
                voice_id=tts_voice,
                language=lang_cfg.tts_code,
                sample_rate=settings.smallest_sample_rate,
                output_format="pcm",
            ),
            vad=ctx.proc.userdata.get("vad") or silero.VAD.load(),
            # LATENCY (biggest network-independent win): a SEMANTIC turn detector.
            # Without it, turn-end was decided by VAD silence alone, forcing a long
            # max_endpointing_delay so the patient isn't cut off mid-sentence. The
            # model commits the turn as soon as the utterance is grammatically
            # complete (often 200-400ms), letting the silence timers drop below.
            # Prewarmed once per process in _prewarm (no per-call load cost).
            # Built here (not prewarm): livekit-agents 1.6 binds the model to the
            # job's inference executor, which only exists inside the entrypoint.
            turn_detection=MultilingualModel(),
            preemptive_generation=True,
            # With the semantic turn detector backstopping, the silence timers can
            # shrink: the detector fires on a complete utterance; these only catch
            # the case where it's unsure. min 0.4->0.2, max 1.5->1.0.
            min_endpointing_delay=0.2,
            max_endpointing_delay=1.0,
            # BARGE-IN FIX (Vinay 2026-06-22: "when I interrupt mid-sentence the
            # agent skips the sentence it was supposed to say"). Telugu/Indian
            # callers backchannel constantly while the agent speaks ("haan",
            # "ఊ", "సరే", "mm"). With LiveKit's defaults a single such sound
            # truncates the agent's turn AND the LLM moves on, so a half-said
            # confirmation (token, doctor, time) is lost. Two guards:
            #  - min_interruption_words=2 + min_interruption_duration=0.6: a lone
            #    backchannel word/short sound no longer counts as an interruption.
            #  - resume_false_interruption=True: if the "interruption" turns out
            #    to be nothing real (no transcript within the timeout), the agent
            #    RESUMES the very sentence it was cut off on instead of skipping
            #    it. A genuine interruption (real words) still stops the agent.
            min_interruption_duration=0.6,
            min_interruption_words=2,
            resume_false_interruption=True,
            false_interruption_timeout=2.0,
        )
        logger.info("lat_agentsession_ctor=%.2fs", _perf.monotonic() - _t_build)

        # Per-turn latency breakdown so the 7s "stop speaking -> agent speaks"
        # gap is attributable to a stage (STT finalize / LLM TTFT / TTS TTFB /
        # end-of-utterance delay) instead of guessed. log_metrics keeps the
        # existing structured line; the extra line surfaces the key numbers.
        @session.on("metrics_collected")
        def _on_metrics(ev: MetricsCollectedEvent) -> None:
            metrics.log_metrics(ev.metrics)
            m = ev.metrics
            tn = type(m).__name__
            if tn == "EOUMetrics":
                logger.info("lat_eou end_of_utterance_delay=%.2fs", getattr(m, "end_of_utterance_delay", 0.0))
            elif tn == "LLMMetrics":
                logger.info("lat_llm ttft=%.2fs", getattr(m, "ttft", 0.0))
            elif tn == "TTSMetrics":
                logger.info("lat_tts ttfb=%.2fs", getattr(m, "ttfb", 0.0))
            elif tn == "STTMetrics":
                logger.info("lat_stt duration=%.2fs", getattr(m, "duration", 0.0))

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
                # FINALIZE the at-start row (TD-027/F6) with the real duration +
                # booking outcome. Fall back to an INSERT if the start row was
                # never written (start-time metering failure).
                try:
                    from sqlalchemy import update as _sa_update

                    from backend.models.schema import CallLog

                    started = state.call_start or datetime_cls.now(timezone_utc)
                    duration = max(
                        0,
                        int((datetime_cls.now(timezone_utc) - started).total_seconds()),
                    )
                    await db.rollback()  # clear any failed tx before logging
                    if state.call_log_id is not None:
                        # Finalize the agent-written at-start row (agent logging on).
                        await db.execute(
                            _sa_update(CallLog)
                            .where(CallLog.id == state.call_log_id)
                            .values(
                                duration_seconds=duration,
                                booking_made=state.token_confirmed,
                            )
                        )
                        await db.commit()
                    elif settings.agent_call_log_enabled:
                        # Start-row failed but agent logging is on — INSERT now.
                        # (When agent logging is OFF, Vobiz CDR is the only writer
                        # — do NOT insert here or it double-counts.)
                        db.add(
                            CallLog(
                                branch_id=state.branch_id,
                                call_type=state.call_type or "inbound",
                                caller_last4=(state.patient_phone or "")[-4:] or None,
                                answered=True,
                                started_at=started,
                                duration_seconds=duration,
                                booking_made=state.token_confirmed,
                            )
                        )
                        await db.commit()
                except Exception as e:
                    logger.warning("call_log_write_failed: %s", e)

                # CALL QUALITY + TRANSCRIPT (monitoring + feedback loop). Written
                # for EVERY call, independent of agent_call_log_enabled (CallLog is
                # billing; this is quality). Own try/except — must never break
                # teardown or the RULE-3 token release above.
                try:
                    from backend.models.schema import CallQuality

                    abandoned = bool(state.token_held and not state.token_confirmed)
                    fail_reason = state.fail_reason or ("abandoned_hold" if abandoned else None)
                    turns, transcript = _extract_call_record(session)
                    if not settings.transcript_capture_enabled:
                        transcript = None  # capture disabled → outcome only, no text
                    await db.rollback()  # fresh tx (the CallLog write may have committed/failed)
                    db.add(
                        CallQuality(
                            branch_id=state.branch_id,
                            call_log_id=state.call_log_id,
                            session_id=state.session_id,
                            call_type=state.call_type or "inbound",
                            language=state.language,
                            duration_seconds=duration,
                            turns=turns,
                            booking_made=state.token_confirmed,
                            booking_abandoned=abandoned,
                            transfer_requested=state.transfer_requested,
                            fail_reason=fail_reason,
                            transcript=transcript,
                        )
                    )
                    await db.commit()
                except Exception as e:  # noqa: BLE001
                    logger.warning("call_quality_write_failed: %s", e)
                    try:
                        await db.rollback()
                    except Exception:
                        pass

                # TREATMENT FOLLOW-UP write-back (Task 9): for next_visit_book /
                # doctor_advice calls, persist the patient's spoken reply onto the
                # FollowupTask so the doctor reads it in the thread. Own short-lived
                # session — never the live call's `db`; best-effort, must not break
                # teardown. (Task 8 set status=completed on dispatch; this enriches
                # response_summary and is idempotent.) RULE 9: health self-report —
                # branch_id-scoped, retention-wiped by the data_retention job.
                _task_id = meta.get("task_id")
                if _task_id:
                    try:
                        _replies = []
                        _hist = getattr(session, "history", None)
                        for _it in (getattr(_hist, "items", None) or []):
                            if getattr(_it, "role", None) != "user":
                                continue
                            _t = (getattr(_it, "text_content", None) or "").strip()
                            if _t:
                                _replies.append(_t)
                        _summary = (" | ".join(_replies))[:500] or "(no reply captured)"
                        import backend.database as _dbm2
                        from sqlalchemy import update as _sa_upd

                        from backend.models.schema import FollowupTask as _FT2

                        async with _dbm2.AsyncSessionLocal() as _fdb:
                            await _fdb.execute(
                                _sa_upd(_FT2)
                                .where(
                                    _FT2.id == UUID(_task_id),
                                    _FT2.branch_id == state.branch_id,
                                )
                                .values(response_summary=_summary, status="completed")
                            )
                            await _fdb.commit()
                    except Exception as _fe:  # noqa: BLE001
                        logger.warning("followup_response_writeback_failed: %s", _fe)
            finally:
                await db.close()

        ctx.add_shutdown_callback(_cleanup_on_shutdown)

        # OVERLAP the session connect with the welcome clip so the session is ready
        # the moment the clip ends — no silent gap before the real greeting (Vinay
        # 06-21: clip fixed the start-silence but left a ~3s gap before the
        # reminder). session.start()'s connect (~3s) runs CONCURRENTLY with the
        # clip's playout; the agent's track stays silent during connect, so it
        # doesn't collide with the clip's audible track, and the clip unpublishes
        # itself when done. We then await the clip, then the connect, then greet.
        logger.info("lat_setup answer_to_session_start=%.2fs", _perf.monotonic() - _t_answer)
        _start_task = asyncio.create_task(
            session.start(
                room=ctx.room,
                agent=vachanam_agent,
                room_input_options=RoomInputOptions(
                    noise_cancellation=noise_cancellation.BVCTelephony(),
                ),
            )
        )
        if _welcome_task is not None:
            try:
                await _welcome_task
            except Exception as _we:  # noqa: BLE001
                logger.warning("welcome_await_failed: %s", _we)
        await _start_task
        logger.info("lat_session_connect total_answer_to_ready=%.2fs", _perf.monotonic() - _t_answer)

        # RULE 6: single short opening utterance, sanitized. (The short welcome
        # clip already played pre-session; this is the real greeting, spoken with
        # STT live so the patient's reply is heard.)
        #
        # Names enter the greeting in the CALL'S script so the TTS speaks them as
        # names, not spelled letters (fix 2026-06-23: "Srinivas" → "S R I N I").
        # spoken_name() is best-effort and cached; it no-ops for already-Indic
        # names and falls back to the raw name on any failure.
        _spk_patient = await spoken_name(meta.get("patient_name", ""), lang_code)
        _spk_doctor = await spoken_name(meta.get("doctor_name", ""), lang_code)
        if is_reminder:
            # Raw "16:30" gets read digit-by-digit by TTS. For Telugu speak it in
            # Telugu words; for other languages a clean "04:30 PM" reads naturally
            # (Telugu number-words inside e.g. a Hindi sentence would be wrong).
            _appt_raw = meta.get("appointment_time", "")
            try:
                _t = time_cls.fromisoformat(_appt_raw)
                _spoken_time = telugu_time(_t) if lang_code == "te" else _t.strftime("%I:%M %p").lstrip("0")
            except (ValueError, TypeError):
                _spoken_time = _appt_raw
            await session.say(
                sanitize_for_tts(
                    lines.reminder_greeting.format(
                        patient=_spk_patient,
                        clinic=branch_name,
                        doctor=_spk_doctor,
                        time=_spoken_time,
                    )
                )
            )
        elif is_rebook_call:
            # ISO date would be read digit-by-digit by TTS. Telugu → Telugu words;
            # other languages → a readable "12 June" (loan month name reads fine).
            _raw_date = meta.get("cancelled_date", "")
            try:
                _d = date_cls.fromisoformat(_raw_date)
                spoken_date = telugu_date(_d) if lang_code == "te" else _d.strftime("%d %B").lstrip("0")
            except ValueError:
                spoken_date = _raw_date
            await session.say(
                sanitize_for_tts(
                    lines.rebook_greeting.format(
                        patient=_spk_patient,
                        clinic=branch_name,
                        doctor=_spk_doctor,
                        date=spoken_date,
                    )
                )
            )
        elif is_followup:
            # Outbound treatment follow-up — greet the known patient by name; the
            # NEXT_VISIT_PROMPT_EXTRA / DOCTOR_ADVICE_PROMPT_EXTRA then drives the
            # conversation. NOT the inbound disclosure path (this is an outbound
            # call — no inbound Consent record).
            await session.say(
                sanitize_for_tts(
                    lines.known_caller_greeting.format(
                        patient=_spk_patient, clinic=branch_name
                    )
                )
            )
        else:
            # Returning patient → greet by name; new caller → standard greeting.
            if caller_greeting_name:
                _greeting = lines.known_caller_greeting.format(
                    patient=caller_greeting_name, clinic=branch_name
                )
            else:
                _greeting = lines.disclosure_greeting.format(clinic=branch_name)
            await session.say(sanitize_for_tts(_greeting))

            # DPDP s.5 demonstrable notice: the greeting just spoken contains the
            # AI-assistant / data-processing disclosure. Record that notice was
            # served on this inbound call (own short-lived session — never touch
            # the live call's DB session; fire-and-forget, must never break a call).
            try:
                import backend.database as _dbm
                from backend.models.schema import Consent as _Consent

                async with _dbm.AsyncSessionLocal() as _cdb:
                    _cdb.add(_Consent(
                        branch_id=state.branch_id,
                        session_id=state.session_id,
                        patient_phone=state.patient_phone,
                        consent_type="data_processing",
                        notice_version="1.0",
                        method="verbal",
                    ))
                    await _cdb.commit()
            except Exception as _ce:
                logger.warning("consent_record_failed: %s", _ce)

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
                        await session.say(sanitize_for_tts(lines.cap_warning))
                    await asyncio.sleep(10)
                    await session.say(
                        sanitize_for_tts(lines.cap_goodbye)
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
            ctx.add_shutdown_callback(_cancel_on_shutdown(_cap_task))


_TERMINAL_ORG_STATES = frozenset({"paused", "cancelled", "suspended"})


def _gate_failure_blocked_reason(last_known_status: str | None) -> str | None:
    """iter1 #23: decide how the service gate behaves when its check RAISES.

    Fail CLOSED (return a blocked reason) for a known terminal org status —
    paused/cancelled/suspended — so a billing/DB error can't grant free service
    to an org the owner already shut off. Fail OPEN (return None) for any other
    or unknown status, so a transient blip never hangs up on an active clinic.
    """
    status = (last_known_status or "").lower()
    if status in _TERMINAL_ORG_STATES:
        return f"service_{status}"
    return None


_keepalive_started = False


def _start_render_keepalive() -> None:
    """Keep the Render free-tier backend awake so its in-process APScheduler
    (30-min reminders, cascade-rebook, retention) keeps firing — free services
    sleep after ~15 min idle. The Fly agent is always-on, so it makes a reliable
    external pinger (GitHub Actions cron drifts and lost the race). Disabled by
    setting BACKEND_HEALTH_URL empty. ponytail: stdlib thread, 5-min interval (3×
    margin on the 15-min sleep) — swap for an external monitor if the agent ever
    isn't always-on. Best-effort: a failed ping never touches the call path."""
    global _keepalive_started
    if _keepalive_started:
        return
    url = os.getenv("BACKEND_HEALTH_URL", "https://vachanam-backend.onrender.com/health")
    if not url:
        return
    _keepalive_started = True

    import threading
    import time
    import urllib.request

    def _loop() -> None:
        while True:
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    r.read(1)
            except Exception as e:  # noqa: BLE001 — keepalive is best-effort
                logger.warning("render_keepalive_ping_failed: %s", str(e)[:120])
            time.sleep(300)  # 5 min — well under Render's ~15-min idle sleep

    threading.Thread(target=_loop, name="render-keepalive", daemon=True).start()
    logger.info("render_keepalive_started url=%s interval=300s", url)


def _prewarm(proc) -> None:
    """Load the Silero VAD model ONCE per worker process (latency fix).

    silero.VAD.load() was called inside every call's AgentSession setup, adding
    its init cost (~hundreds of ms) to each call's startup before the greeting.
    Loading it here, once, and reusing it across all calls removes that from the
    per-call path. Standard LiveKit pattern.

    NOTE: the semantic turn detector (MultilingualModel) is NOT prewarmed here.
    livekit-agents 1.6 binds it to the job's inference executor at construction,
    which only exists inside a job entrypoint — building it in prewarm raises
    "no job context found". It is constructed in the AgentSession instead (the
    inference runs in the shared worker inference executor, so the per-call cost
    is just a lightweight handle, not the model weights).
    """
    proc.userdata["vad"] = silero.VAD.load()
    # The Gemini+GPT FallbackAdapter is clinic-agnostic — build it ONCE per
    # process and reuse, so its construction is off every call's pre-greeting
    # path (part of the ~3s lat_setup before the agent can speak).
    proc.userdata["llm"] = _build_fallback_llm()
    # CalendarService builds a Google API client (the slow part of the ~2.9s
    # pre-session work). The SA is global, so build it once and reuse.
    try:
        _sa = _REPO_ROOT / "google-service-account.json"
        proc.userdata["calendar"] = CalendarService(
            sa_json_path=str(_sa) if _sa.exists() else None
        )
    except Exception as e:  # noqa: BLE001 — prewarm best-effort; entrypoint rebuilds
        logger.warning("prewarm_calendar_failed: %s", e)


if __name__ == "__main__":
    # Start the Render keep-warm pinger in the MAIN worker process (always-on),
    # NOT in _prewarm — prewarm runs in the job subprocess, which may not spawn
    # until the first call, and Render sleeps precisely when there are NO calls.
    _start_render_keepalive()
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=_prewarm,
            agent_name=AGENT_NAME,
        )
    )
