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
from livekit.agents import stt as lk_stt  # noqa: E402
from livekit.agents import tts as lk_tts  # noqa: E402
from livekit.agents.llm import ChatContext  # noqa: E402
from livekit.agents import utils as _lk_utils  # noqa: E402
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS as _DEFAULT_CONN  # noqa: E402
from livekit.plugins import google, noise_cancellation, openai, sarvam, silero, smallestai  # noqa: E402
from livekit.plugins.turn_detector.multilingual import MultilingualModel  # noqa: E402

import redis.asyncio as aioredis  # noqa: E402
from sqlalchemy import and_, select  # noqa: E402

from agent.i18n import LANGUAGES, get_lang, get_lines, get_switch_ack  # noqa: E402
from agent.i18n.backchannels import suppress_backchannel  # noqa: E402
from agent.i18n.transliterate import spoken_name, spoken_text  # noqa: E402
from agent.prompts.system_prompt import (  # noqa: E402
    DoctorContext,
    build_date_context,
    build_system_prompt,
)
# CalendarService (legacy-signature shim), NOT GoogleCalendarService —
# booking_tools.confirm_booking calls the legacy create_booking_event kwargs.
from agent.services.calendar_proxy import CalendarService  # noqa: E402
from agent.services.meta_stub import MetaService  # noqa: E402
from agent.services.telugu_dates import telugu_date  # noqa: E402
from agent.livekit_minimal.greeting import (  # noqa: E402
    inbound_greeting_texts,
    normalize_pcm,
    outbound_greeting_texts,
    play_wavs,
    synth_and_play,
    synth_wavs,
)
from agent.services.tts_sanitizer import sanitize_for_tts  # noqa: E402
from agent.session_state import SessionState  # noqa: E402
from agent.tools.booking_tools import (  # noqa: E402
    assign_token,
    check_availability,
    confirm_booking,
    find_bookings_by_phone,
    get_preferred_language,
    queue_position_by_phone,
    recognize_caller_name,
    route_to_doctor,
    set_preferred_language,
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


def _wav_to_pcm(wav: bytes) -> tuple[bytes, int, int]:
    """Decode a WAV clip to (normalized PCM bytes, sample_rate, channels)."""
    import io
    import wave

    wf = wave.open(io.BytesIO(wav), "rb")
    sr, ch, n = wf.getframerate(), wf.getnchannels(), wf.getnframes()
    pcm = normalize_pcm(wf.readframes(n))
    wf.close()
    return pcm, sr, ch


async def _pcm_frames(pcm: bytes, sr: int, ch: int):
    """Yield 10ms AudioFrames from cached PCM — fed to session.say(audio=...)
    so a pre-rendered filler plays with ZERO TTS latency."""
    from livekit import rtc

    spf = sr // 100
    fb = spf * 2 * ch
    for i in range(0, len(pcm), fb):
        chunk = pcm[i : i + fb]
        if len(chunk) < fb:
            chunk = chunk + b"\x00" * (fb - len(chunk))
        yield rtc.AudioFrame(
            data=chunk, sample_rate=sr, num_channels=ch, samples_per_channel=spf
        )


async def cache_filler_clips(session, texts, voice_id: str, lang_code: str) -> None:
    """Pre-render the lookup fillers ONCE at session start and stash the decoded
    PCM on session.userdata['filler_clips'] (Vinay 2026-07-06: "cache a response
    and speak it instantly while checking"). _say_lookup_filler then replays the
    cached audio with no live synth. Best-effort — on any failure the filler
    falls back to live session.say(text). Never blocks or breaks the call."""
    try:
        wavs = await synth_wavs(list(texts), voice_id, lang_code)
        clips = []
        for text, wav in zip(texts, wavs):
            pcm, sr, ch = _wav_to_pcm(wav)
            clips.append({"text": text, "pcm": pcm, "sr": sr, "ch": ch})
        ud = getattr(session, "userdata", None)
        if isinstance(ud, dict):
            ud["filler_clips"] = clips
        logger.info("filler_clips_cached=%d", len(clips))
    except Exception as e:  # noqa: BLE001 — a filler must never affect booking
        logger.warning("filler_cache_failed: %s", str(e)[:120])


def _say_lookup_filler(context) -> None:
    """Speak a short 'let me check' filler over the dead air while a lookup tool
    runs. Plays a PRE-CACHED clip (instant, no synth) when available; otherwise
    live-synthesizes the clinic-language filler. Non-blocking and fully guarded —
    it must NEVER affect booking."""
    try:
        sess = getattr(context, "session", None)
        ud = getattr(sess, "userdata", None)
        if ud is None:
            ud = getattr(context, "userdata", None)
        ud = ud if isinstance(ud, dict) else {}
        clips = ud.get("filler_clips") or []
        if clips:
            clip = random.choice(clips)
            context.session.say(
                clip["text"],
                audio=_pcm_frames(clip["pcm"], clip["sr"], clip["ch"]),
                add_to_chat_ctx=False,
            )
            return
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


def _phone_override_error(
    caller_phone: str | None, patient_phone: str | None, different_person: bool
) -> str | None:
    """Vinay 2026-07-03 live test: a DICTATED different number sent with
    different_person=false was silently discarded (iter1 #11 keeps a caller's
    own booking on their caller-ID) and the booking landed on the caller's own
    number. That combination is always a mistake — return the LLM-facing error
    so the tool fails loudly and the model self-corrects with
    different_person=true. None = combination is fine."""
    if not patient_phone or different_person:
        return None
    caller_d = "".join(ch for ch in (caller_phone or "") if ch.isdigit())[-10:]
    given_d = "".join(ch for ch in patient_phone if ch.isdigit())[-10:]
    if caller_d and given_d and given_d != caller_d:
        return (
            "You passed a phone number DIFFERENT from the caller's own "
            "number, but different_person=false. A caller's own booking "
            "always uses the number they are calling from. If this "
            "booking is for SOMEONE ELSE (a family member), call "
            "confirm_booking again with different_person=true, that "
            "person's name and age, and this patient_phone."
        )
    return None


def _availability_caller_phone(state) -> str | None:
    """The caller_phone to pass to check_availability for the #279 upfront
    existing-booking surface — suppressed once the caller is on the
    reschedule/cancel track (find_my_bookings ran, existing_booking_intent set).
    Otherwise the caller's OWN booking being moved is flagged as blocking and the
    reschedule dead-ends (live call 2026-07-06, FIXLOG #281)."""
    return None if state.existing_booking_intent else state.patient_phone


def _voice_for_lang(branch, lang_code: str) -> str:
    """The TTS voice_id to speak `lang_code` for this branch. Vinay 2026-07-05:
    the agent speaks ONLY clinic-provided voices — one clone per language — so
    the clinic's clone REGISTERED FOR this language always wins (that's what a
    language switch inherits too). A cloned voice is language-bound (the te
    clone spoke 0.45s of noise for an English sentence, measured 2026-07-03),
    so a clone never crosses languages. Order: clinic clone for THIS language →
    the clinic's chosen tts_voice unless it's a clone of ANOTHER language →
    the language's catalog default (RULE 8 — a language the clinic hasn't
    voiced yet must still get a working call; logged for the Settings badge)."""
    cfg = get_lang(lang_code)
    clones = [
        cv for cv in (getattr(branch, "cloned_voices", None) or [])
        if isinstance(cv, dict) and cv.get("voice_id")
    ]
    for cv in clones:
        if (cv.get("language") or "").lower().strip() == cfg.code:
            return cv["voice_id"]
    v = (getattr(branch, "tts_voice", None) or "").strip()
    if not v:
        logger.info("voice_fallback_catalog lang=%s reason=no_clinic_voice", cfg.code)
        return cfg.default_voice
    for cv in clones:
        if cv.get("voice_id") != v:
            continue
        clone_lang = (cv.get("language") or "").lower().strip()
        if clone_lang and clone_lang != cfg.code:
            logger.info(
                "voice_fallback_catalog lang=%s reason=clinic_voice_is_%s_bound",
                cfg.code, clone_lang,
            )
            return cfg.default_voice
    return v


KNOWN_CALLER_BOOKING_EXTRA = (
    "\n\nCALLER IDENTIFICATION: this number belongs to an EXISTING patient, "
    "{name}, with no upcoming booking. The greeting already welcomed them by "
    "name.\n"
    "WHO IS THE PATIENT: LISTEN for a relation word first. If the caller "
    "ALREADY said who it is for ('for my father', 'my son needs...', 'నా "
    "అమ్మకి', 'mere bhai ke liye'), that IS the answer — it is for SOMEONE "
    "ELSE; do NOT ask 'for you or someone else?'. Only when they did NOT say, "
    "ask ONCE whether the appointment is for THEMSELVES or for SOMEONE ELSE "
    "(spoken naturally in the call's language).\n"
    "- FOR THEMSELVES: do NOT ask their name or age again — you already know "
    "them as {name}. Take only the concern (route_to_doctor) and their "
    "preferred time, then confirm_booking with patient_name='{name}' and "
    "different_person=false.\n"
    "- FOR SOMEONE ELSE: take that person's NAME and AGE. Then ask ONE "
    "question about the number: should the booking be on THIS number they are "
    "calling from, or on that person's own number? (e.g. 'ఈ నంబర్ మీదే బుక్ "
    "చేయమంటారా, లేక వాళ్ళ నంబర్ వేరే ఉందా?'). If they say this number (or have "
    "no other), omit patient_phone — it defaults to the caller's number. If "
    "they give a different number, apply the PHONE NUMBER RULES (exactly 10 "
    "digits; read it back in English digits and get a YES before booking) and "
    "pass it as patient_phone. confirm_booking MUST then be called with "
    "different_person=true — with different_person=false the other number is "
    "REJECTED and the booking fails. Then confirm_booking with that person's "
    "name and age and different_person=true."
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
    "- If they want to CANCEL outright (not move it): call cancel_booking("
    "token_id above). Say it is cancelled ONLY after the tool returns "
    "success=true — NEVER claim a cancellation you did not perform; an "
    "unperformed 'cancel' becomes a no-show against the patient.\n"
    "- If they want a different doctor or time, follow the normal availability "
    "negotiation rules. Keep every reply to two short sentences."
)

NEXT_VISIT_PROMPT_EXTRA = (
    "\n\nTHIS IS A TREATMENT FOLLOW-UP CALL. You already know this patient — never "
    "ask who they are or restart the new-patient flow.\n"
    "DOCTOR IS ALREADY KNOWN: this follow-up is for {doctor}, the same doctor who "
    "treated this patient. NEVER ask the patient which doctor, NEVER call "
    "route_to_doctor — the visit is with {doctor}. Use {doctor} directly for "
    "check_availability and the booking.\n"
    "1) Your OPENING line already asked the doctor's question (\"{message}\"). Do "
    "NOT ask it again — just listen to their answer and respond warmly in one line.\n"
    "2) BOOKING — only on a GOOD report. The doctor has asked this patient to come "
    "back around {target_date}, so IF their answer is fine/normal (\"అంతా బాగానే "
    "ఉంది\"), tell them the doctor wants them back on that date and offer to book. "
    "On agreement, FIRST ask what time of day suits them (\"ఏ టైమ్ వీలవుతుందండి?\") — "
    "NEVER pick a time yourself; the patient chooses the time, you check it with "
    "check_availability. Then assign a slot with {doctor} within 2 days of that date "
    "and confirm in one breath. SPEAK the date using the words BEFORE the parenthesis "
    "(e.g. 'ఇరవై తొమ్మిది'); the value in parentheses is the ISO date for the tools "
    "ONLY — never read the parenthesis or digits aloud.\n"
    "3) You are a MESSENGER, not a doctor: give NO medical advice, NO diagnosis, NO "
    "triage. IF the patient reports ANY problem, pain, or discomfort: say warmly "
    "'I will inform the doctor and they will get back to you as soon as possible', "
    "and do NOT push the booking — the doctor will decide the next step when they "
    "get back. (Vinay 2026-07-03: a problem report ends with inform-doctor, not a "
    "sales pitch.) Book in this case ONLY if the patient THEMSELVES explicitly asks "
    "for an appointment. Do not advise.\n"
    "4) BOOKING — the patient is ALREADY on record, so keep it tight (this OVERRIDES "
    "the normal new-patient details flow):\n"
    "   - The patient's name is '{patient}'. Do NOT ask their name, do NOT ask their "
    "age, do NOT read details back. Pass patient_name='{patient}' to confirm_booking; "
    "it does NOT need age for an existing patient — book on their phone-on-record.\n"
    "   - Do NOT mention, check, or read out any OTHER appointment they already have. "
    "This call is ONLY about the follow-up visit — never say 'you already have an "
    "appointment on <date>'.\n"
    "   - {doctor} is an APPOINTMENT (time-slot) doctor: confirm ONLY the date and "
    "time. NEVER say a token or queue number — tokens are meaningless for an "
    "appointment doctor.\n"
    "5) ONCE BOOKED — confirm_booking returned success=true — the follow-up is DONE. "
    "You have ALREADY booked this visit. NEVER offer to book again, NEVER ask 'shall I "
    "book', NEVER call assign_token or confirm_booking a second time (it will be "
    "rejected as a duplicate). Just give the ONE confirmation, and when they "
    "acknowledge, say a short goodbye and end_call. Remember what you have already "
    "done in this call.\n"
    "Keep every reply to two short sentences."
)

DOCTOR_ADVICE_PROMPT_EXTRA = (
    "\n\nTHIS IS A DOCTOR-ADVICE RELAY CALL. The doctor reviewed the patient's "
    "concern and wrote a message. RELAY it warmly and faithfully in the clinic's "
    "language — do NOT add, interpret, or invent any medical content of your own "
    "(RULE 7). The doctor's message: \"{message}\".\n"
    "After relaying, ask if they have more concerns. Offer a booking ONLY if the "
    "doctor's message itself asks them to come in (then a target date "
    "{target_date} may be given — book within 2 days of it; SPEAK the date using "
    "the words before the parenthesis; the parenthesis is the ISO for tools only) "
    "OR the patient explicitly asks for an appointment — never push one otherwise. "
    "If they report a new problem, say 'I will inform the doctor and get back to "
    "you as soon as possible' and do NOT offer a booking. Two short sentences per "
    "reply."
)

_FOLLOWUP_CALLTYPES = {"next_visit_book", "doctor_advice"}


def _followup_meta_safe(meta: dict) -> dict:
    """RULE 9: the ONLY metadata fields allowed to reach the LLM/agent for a
    follow-up call. Private clinical notes (steps_performed/next_steps) must never
    appear here even if a future caller accidentally includes them."""
    allowed = ("call_type", "message", "target_date", "window",
               "patient_name", "doctor_name", "doctor_id", "task_id")
    return {k: meta[k] for k in allowed if k in meta}


def _spoken_target_date(raw: str, lang_code: str) -> str:
    """Render an ISO target date for the follow-up prompt as 'Telugu words (ISO)'
    so the agent SPEAKS it correctly (29 → ఇరవై తొమ్మిది, not '29th') while still
    having the ISO date for the booking tools. Falls back to raw on parse failure."""
    if not raw:
        return raw
    try:
        d = date_cls.fromisoformat(raw)
    except (ValueError, TypeError):
        return raw
    spoken = telugu_date(d) if lang_code == "te" else d.strftime("%d %B").lstrip("0")
    return f"{spoken} ({raw})"


async def _localize_message(message: str, lang_code: str) -> str:
    """Speak the doctor's follow-up note in the CALL's language. If the doctor wrote
    it in English (mostly Latin), translate to natural spoken <lang> (so it's clear,
    not fast English over a Telugu TTS); if already in an Indic script, keep it.
    Best-effort — returns the original on any failure."""
    msg = (message or "").strip()
    letters = [c for c in msg if c.isalpha()]
    if not letters:
        return message
    if sum(1 for c in letters if c.isascii()) / len(letters) < 0.5:
        return message  # already mostly non-Latin → assume the call's language
    cfg = get_lang(lang_code)
    if cfg.code == "en":
        return message
    try:
        from google import genai
        from google.genai import types as gt

        client = genai.Client(api_key=settings.gemini_api_key)
        prompt = (
            f"Translate this clinic follow-up note into natural, warm, SPOKEN "
            f"{cfg.name} for a phone call to a patient. Keep common English everyday "
            f"loanwords as people actually say them. CRITICAL: medicine / tablet / "
            f"brand names (e.g. Cytrizine, Dolo, Augmentin) are NOT regular words — "
            f"transliterate each one accurately into {cfg.name} script so the patient "
            f"hears the SAME medicine name clearly and can recognize it at the "
            f"pharmacy; never translate or alter a drug name's meaning. Output ONLY "
            f"the translation, nothing else:\n\n{msg}"
        )
        resp = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=gt.GenerateContentConfig(
                thinking_config=gt.ThinkingConfig(thinking_budget=0)
            ),
        )
        out = (resp.text or "").strip()
        if out:
            logger.info("localized_doctor_msg lang=%s", cfg.code)
            return out
        return message
    except Exception as e:  # noqa: BLE001 — never block a call
        logger.warning("localize_message_failed: %s", str(e)[:120])
        return message


async def _inbound_pending_followup(branch_id, phone: str, db) -> dict | None:
    """For an INBOUND caller, find a pending next_visit_book follow-up so the agent
    can deliver the doctor's question + offer the scheduled visit when the patient
    missed the outbound call and rang back. Branch-scoped (RULE 1). Best-effort —
    returns None on anything missing/failed."""
    try:
        from sqlalchemy import select as _sel

        from backend.models.schema import (
            Doctor as _D,
            FollowupTask as _FT,
            Patient as _P,
            TreatmentNote as _TN,
        )

        # Match on the LAST 10 DIGITS so caller-ID format (+91/91/bare) never breaks
        # it; join by phone (a number can map to several Patient rows — find the task
        # on ANY of them).
        digits = "".join(c for c in (phone or "") if c.isdigit())[-10:]
        if len(digits) < 10:
            return None
        task = (await db.execute(
            _sel(_FT).join(_P, _FT.patient_id == _P.id).where(
                _FT.branch_id == branch_id,
                _P.phone.like(f"%{digits}"),
                _FT.task_type == "next_visit_book",
                _FT.status == "pending",
            ).order_by(_FT.scheduled_date.asc())
        )).scalars().first()
        if task is None:
            return None
        doc = (await db.execute(_sel(_D).where(_D.id == task.doctor_id))).scalars().first()
        target_iso = ""
        if task.treatment_note_id:
            tn = (await db.execute(
                _sel(_TN).where(_TN.id == task.treatment_note_id)
            )).scalars().first()
            if tn is not None and tn.next_reporting_date:
                target_iso = tn.next_reporting_date.isoformat()
        return {
            "task_id": str(task.id),
            "doctor_id": str(task.doctor_id),
            "doctor_name": doc.name if doc else "the doctor",
            "message": task.what_to_ask or "",
            "target_date": target_iso,
        }
    except Exception as e:  # noqa: BLE001 — never block answering
        logger.warning("inbound_followup_lookup_failed: %s", e)
        return None



# Unicode block → smallest.ai language code. Guards the synth boundary: if the
# LLM drifts and emits text in a script that doesn't match the session's TTS
# language (live call 2026-07-05: Telugu reply after an English switch), smallest
# reads the script under the wrong language model and the caller hears garbled
# "wrong-language" audio. Speaking the DETECTED script's language is always the
# lesser evil (RULE 8). Latin text carries no signal (te calls are code-mixed) —
# keep the configured language.
_SCRIPT_LANGS = (
    ((0x0C00, 0x0C7F), "te"),
    ((0x0900, 0x097F), "hi"),   # Devanagari — hi unless the call is already mr
    ((0x0B80, 0x0BFF), "ta"),
    ((0x0C80, 0x0CFF), "kn"),
    ((0x0D00, 0x0D7F), "ml"),
    ((0x0980, 0x09FF), "bn"),
    ((0x0B00, 0x0B7F), "or"),
)


def _detect_script_lang(text: str, configured: str) -> str:
    """Language whose script dominates `text`, else `configured`."""
    counts: dict[str, int] = {}
    for ch in text:
        cp = ord(ch)
        for (lo, hi), lang in _SCRIPT_LANGS:
            if lo <= cp <= hi:
                counts[lang] = counts.get(lang, 0) + 1
                break
    if not counts:
        return configured
    best = max(counts, key=counts.get)  # type: ignore[arg-type]
    if best == "hi" and configured == "mr":
        return "mr"  # Devanagari is shared; trust the session's choice
    return best


class _RawRestChunked(lk_tts.ChunkedStream):
    """Synthesize ONE utterance via the RAW smallest.ai REST /tts (WAV) and emit it
    as PCM frames — the exact path the welcome clip uses (reliable + correct speed).
    The plugin's own WS path Connection-errors on Fly, and its HTTP ChunkedStream
    played the audio at the wrong SPEED ('5x', 2026-06-25)."""

    def __init__(self, *, tts, input_text, conn_options) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._mytts = tts

    async def _run(self, output_emitter) -> None:
        import io
        import wave

        from backend.services.welcome_synth import synth_wav

        opts = self._mytts._opts
        # Script guard (FIXLOG #270): text in a different script than the session
        # language must be synthesized AS its own language or it comes out as
        # garbled foreign-sounding audio. ponytail: voice_id stays the session's
        # voice — swapping to the matching-language clinic voice per utterance
        # needs _voice_for_lang plumbing; add if accent complaints appear.
        lang = _detect_script_lang(self._input_text, opts.language)
        if lang != opts.language:
            logger.warning(
                "tts_script_lang_mismatch configured=%s detected=%s", opts.language, lang
            )
        # speed 1.0: Vinay 2026-07-06 — normal speed (1.1 sounded rushed on
        # phone). Bump back up only if it sounds too slow.
        wav = await asyncio.to_thread(
            synth_wav, self._input_text, opts.voice_id, lang, 1.0
        )
        wf = wave.open(io.BytesIO(wav), "rb")
        sr = wf.getframerate()
        ch = wf.getnchannels()
        n = wf.getnframes()
        # Loudness: smallest voices differ ~13 dB (padmaja vs anitha, measured
        # 2026-07-05, Vinay "voice is low") — normalize every utterance so any
        # catalog/cloned voice lands at consistent phone volume.
        from agent.livekit_minimal.greeting import normalize_pcm
        pcm = normalize_pcm(wf.readframes(n))
        wf.close()
        output_emitter.initialize(
            request_id=_lk_utils.shortuuid(),
            sample_rate=sr,
            num_channels=ch,
            mime_type="audio/pcm",
        )
        output_emitter.push(pcm)
        output_emitter.flush()


class _HttpSmallestTTS(smallestai.TTS):
    """Session TTS over the RAW REST /tts path (_RawRestChunked). streaming=False
    so AgentSession synthesizes per sentence; reuses smallestai.TTS only for its
    _opts/voice config."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._capabilities = lk_tts.TTSCapabilities(streaming=False)

    def synthesize(self, text, *, conn_options=_DEFAULT_CONN):
        return _RawRestChunked(tts=self, input_text=text, conn_options=conn_options)


def _build_fallback_llm() -> lk_llm.FallbackAdapter:
    """Gemini-only (Vinay 2026-06-25): primary gemini-2.5-flash, fallback
    gemini-3.1-flash-lite. If the primary is overloaded/slow, the FallbackAdapter
    swaps to the faster Flash-lite. thinking is disabled on both to keep TTFT low
    (2.5-flash uses thinking_budget; gemini-3 uses thinking_level).
    """
    from google.genai import types as genai_types

    return lk_llm.FallbackAdapter(
        llm=[
            google.LLM(
                api_key=settings.gemini_api_key,
                model="gemini-2.5-flash",
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            ),
            google.LLM(
                api_key=settings.gemini_api_key,
                model="gemini-3.1-flash-lite",
                thinking_config=genai_types.ThinkingConfig(thinking_level="low"),
            ),
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
    """Plain-text JSON call used by route_to_doctor. Gemini-only (Vinay 2026-06-25:
    no GPT): gemini-3.1-flash-lite (fast for complaint->doctor matching)."""
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=settings.gemini_api_key)
    resp = await client.aio.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents="\n".join(m["content"] for m in messages),
        config=genai_types.GenerateContentConfig(
            thinking_config=genai_types.ThinkingConfig(thinking_level="low"),
            response_mime_type="application/json",
        ),
    )
    return resp.text or ""


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
        lang_code: str = "te",
        agent_factory=None,   # callable(lang_code, chat_ctx=None) -> VachanamAgent
        switch_ack: str | None = None,  # spoken by on_enter right after a language switch
        stt=None,             # per-agent STT override (language switch handoff)
        tts=None,             # per-agent TTS override (language switch handoff)
        chat_ctx=None,        # conversation history carried across the handoff
    ) -> None:
        # Only pass stt/tts to livekit when actually overriding — an explicit
        # None would DISABLE the session-level pipeline, not inherit it.
        overrides = {}
        if stt is not None:
            overrides["stt"] = stt
        if tts is not None:
            overrides["tts"] = tts
        if chat_ctx is not None:
            overrides["chat_ctx"] = chat_ctx
        super().__init__(instructions=instructions, **overrides)
        self._state = state
        self._db = db
        self._room = room
        self._calendar = calendar_service
        self._meta = meta_service
        self._transfer_to = transfer_to
        self._lang_code = lang_code
        self._agent_factory = agent_factory
        self._switch_ack = switch_ack
        # Kept so switch_language can PRIME the new agent's TTS before handoff
        # (livekit's Agent.tts is not a stable public accessor across versions).
        self._tts_override = tts

    async def on_enter(self) -> None:
        """Fires when this agent becomes active. For the initial agent it's a
        no-op (greeting is driven by the entrypoint). For an agent created by
        switch_language it speaks a short deterministic acknowledgement in the
        NEW language so the caller never hears dead air while the STT/TTS
        pipelines are being swapped."""
        if self._switch_ack:
            try:
                # allow_interruptions=False: the intro is ~2s and is the ONLY
                # thing the new voice says — a caller's "okay" over it must not
                # clip it into a half-sentence (live 17:49Z: "Please go[ ahead]").
                await self.session.say(
                    sanitize_for_tts(self._switch_ack), allow_interruptions=False
                )
            except Exception as e:  # noqa: BLE001 — ack is best-effort (RULE 8)
                logger.warning("switch_ack_failed: %s", e)

    async def stt_node(self, audio, model_settings):
        """BACKCHANNEL FILTER (Vinay 2026-07-04): while the agent is SPEAKING,
        drop transcript events that are pure listening noises ("hmm", "okay",
        "acha", "ఆ", "हाँ"...) so the LLM never treats a backchannel as a real
        user turn. (2026-07-06: interruption itself is now VAD-gated —
        min_interruption_words=0, min_interruption_duration=0.4 — so short
        backchannels are filtered by LENGTH; this transcript filter still keeps
        them out of the conversation history / content path.) When the agent is
        silent the same word is a real short turn and passes through.
        Multi-word content ("okay cancel it", "no no wait") always passes."""
        async for ev in Agent.default.stt_node(self, audio, model_settings):
            try:
                if getattr(ev, "type", None) in (
                    lk_stt.SpeechEventType.INTERIM_TRANSCRIPT,
                    lk_stt.SpeechEventType.FINAL_TRANSCRIPT,
                ):
                    alts = getattr(ev, "alternatives", None) or []
                    text = alts[0].text if alts else ""
                    speaking = False
                    try:
                        speaking = self.session.agent_state == "speaking"
                    except Exception:  # noqa: BLE001 — no session yet
                        speaking = False
                    if suppress_backchannel(text, speaking):
                        logger.info(
                            "backchannel_suppressed text=%r", (text or "")[:40]
                        )
                        continue
            except Exception as e:  # noqa: BLE001 — filter must NEVER eat real speech
                logger.warning("backchannel_filter_error: %s", e)
            yield ev

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
            caller_phone=_availability_caller_phone(self._state),
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
        _say_lookup_filler(context)  # cover the atomic-assign beat (no dead air)
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
            # B4: token_confirmed is a per-BOOKING latch, not a per-call one. A
            # single call can hold several sequential bookings (family cap = 2,
            # plus reschedules). If a prior booking left it True, this NEW hold
            # must reset it — otherwise RULE 3 shutdown cleanup skips releasing
            # this hold, and the cancel/end-call guards (which key off
            # not token_confirmed) go inert for exactly the in-progress booking.
            self._state.token_confirmed = False
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
        #
        # Vinay 2026-07-03 live test: the caller DICTATED a different number for
        # a family member but the LLM sent different_person=false — the override
        # was silently discarded and the booking landed on the caller's own
        # number/record. A dictated-different number with different_person=false
        # is ALWAYS a mistake, so fail loudly and let the LLM self-correct
        # instead of booking the wrong phone.
        _override_err = _phone_override_error(
            self._state.patient_phone, patient_phone, different_person
        )
        if _override_err:
            raise ToolError(_override_err)
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

        # B2: the confirm time MUST match the atomically-held slot. state
        # .token_redis_key encodes the held slot as slot:<doc>:<branch>:<date>:
        # <HHMM> — the only slot the Redis gate actually protected. Two hazards
        # the DB re-count alone can't close:
        #   (A) the LLM omits appointment_time at confirm -> a slot doctor would
        #       be written with appointment_time=NULL (no reminder, calendar
        #       defaults to 12:00, queue shows no time). Inherit the held time.
        #   (B) the LLM confirms a DIFFERENT time than it held -> the atomic gate
        #       protected the OLD time; the new time is guarded only by a TOCTOU
        #       re-count that two concurrent callers can both pass. Release the
        #       stale hold (RULE 3) and re-acquire the new time atomically.
        held_key = self._state.token_redis_key or ""
        if self._state.token_held and held_key.startswith("slot:"):
            held_hhmm = held_key.rsplit(":", 1)[-1]  # 'HHMM'
            held_time = None
            if len(held_hhmm) == 4 and held_hhmm.isdigit():
                held_time = time_cls(int(held_hhmm[:2]), int(held_hhmm[2:]))
            if parsed_time is None and held_time is not None:
                # (A) adopt the held slot's time as the confirm time.
                parsed_time = held_time
                appointment_time = held_time.strftime("%H:%M")
            elif (
                parsed_time is not None
                and held_time is not None
                and parsed_time != held_time
            ):
                # (B) confirm time drifted off the hold — re-gate atomically.
                await self._release_hold({"redis_key": held_key})
                self._clear_hold()
                rehold = await assign_token(
                    doctor_id=resolved,
                    branch_id=self._state.branch_id,
                    booking_date=parsed_date,
                    db=self._db,
                    appointment_time=parsed_time,
                )
                if not rehold.get("success"):
                    return rehold  # slot full / past / off-grid — surfaced to LLM
                self._state.token_held = True
                self._state.token_confirmed = False  # B4: fresh hold, fresh state
                self._state.token_number = rehold["token_number"]
                self._state.token_redis_key = rehold.get("redis_key")

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
            self._state.token_confirmed = False  # B4: fresh hold -> fresh latch
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
                # Caller's language mapping: stamped on a patient row created
                # this call so a pre-booking switch still sticks for the future.
                preferred_language=self._state.preferred_language,
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
            # The caller now HAS a booking this call — any further "change it"
            # is a reschedule, not a new booking. Suppress the #279 upfront
            # existing-booking surface so an immediate same-call change isn't
            # blocked by ALREADY_BOOKED on the booking just made (Vinay
            # 2026-07-07, FIXLOG #284).
            self._state.existing_booking_intent = True
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
        # Caller is on the existing-booking track (reschedule/cancel) — suppress
        # the #279 upfront existing-booking surface so it doesn't flag the very
        # booking being moved (FIXLOG #281).
        self._state.existing_booking_intent = True
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
    async def get_queue_status(self, context: RunContext) -> dict:
        """Live queue position for the caller's TODAY token-queue booking.
        Use when the caller asks when their turn comes, which token is
        running now, or how many people are ahead ("నా టోకెన్ ఎప్పుడు?",
        "ఎన్నో నంబర్ నడుస్తోంది?"). Matches the number they are calling from.
        Token-queue doctors only — for a slot-doctor booking just restate
        their appointment time from find_my_bookings instead."""
        result = await queue_position_by_phone(
            self._state.branch_id, self._state.patient_phone, self._db
        )
        if result.get("found"):
            result["instruction"] = (
                "Tell them which token is running now and how many people are "
                "ahead of theirs. now_serving null means the queue has not "
                "started yet — say so. NEVER promise minutes or an exact time; "
                "speak only in token positions."
            )
        return result

    @function_tool()
    async def log_clinic_question(self, context: RunContext, question: str) -> dict:
        """Log a clinic-information question the CLINIC FAQ could not answer
        (fees, timings, facilities, services...). Call this when the caller asks
        about the clinic and the answer is not in your CLINIC FAQ or clinic
        info — the clinic reviews these to improve its FAQ. Then tell the
        caller the clinic will check with the doctor and get back to them.
        Never log booking requests or medical questions here."""
        from backend.models.schema import ClinicQuestion

        q = " ".join((question or "").split())[:300]
        if not q:
            return {"logged": False}
        try:
            self._db.add(ClinicQuestion(
                branch_id=self._state.branch_id,
                question=q,
                caller_last4=(self._state.patient_phone or "")[-4:] or None,
            ))
            await self._db.commit()
        except Exception as e:  # noqa: BLE001 — logging must never break the call
            logger.warning("clinic_question_log_failed: %s", e)
            try:
                await self._db.rollback()
            except Exception:
                pass
            return {"logged": False}
        return {"logged": True, "next": "Tell the caller the clinic will check "
                "with the doctor and get back to them."}

    @function_tool()
    async def switch_language(self, context: RunContext, language: str) -> object:
        """Switch the CALL's spoken language. Call ONLY when the caller
        EXPLICITLY asks to talk in another language ('can you speak English?',
        'Hindi mein baat karo'). NEVER call it just because the caller mixed
        words from another language.

        Args:
            language: te | en | hi | ta | kn | ml | mr | bn | or
        """
        code = (language or "").strip().lower()
        # The LLM sometimes passes the language NAME instead of the code.
        _names = {c.name.lower(): c.code for c in LANGUAGES.values()}
        code = _names.get(code, code)
        if code not in LANGUAGES:
            supported = ", ".join(sorted(LANGUAGES))
            raise ToolError(
                f"'{language}' is not supported. Supported codes: {supported}. "
                "Apologise briefly and continue in the current language."
            )
        if code == self._lang_code:
            return {"success": True, "already_speaking": code}
        if self._agent_factory is None:
            # Defensive: factory is always wired in the entrypoint; without it a
            # pipeline swap is impossible, so keep the call alive in the current
            # language rather than half-switching (RULE 8).
            raise ToolError(
                "Language switching is not available on this call. Apologise "
                "and continue in the current language."
            )
        # Persist the mapping FIRST (survives even if the handoff has trouble):
        # all patient rows on this phone, branch-scoped. 0 rows = caller not on
        # record yet — state.preferred_language makes confirm_booking stamp it
        # on the row it creates later this call.
        try:
            if self._state.patient_phone:
                await set_preferred_language(
                    self._state.branch_id, self._state.patient_phone, code, self._db
                )
        except Exception as e:  # noqa: BLE001 — mapping is best-effort, switch anyway
            logger.warning("set_preferred_language_failed: %s", e)
            try:
                await self._db.rollback()
            except Exception:
                pass
        self._state.preferred_language = code
        self._state.language = code
        # Spoken fillers must match the new language immediately.
        try:
            ud = getattr(self.session, "userdata", None)
            if isinstance(ud, dict):
                ud["fillers"] = get_lines(code).fillers
                ud["language"] = code
        except Exception:  # noqa: BLE001
            pass
        logger.info(
            "language_switched from=%s to=%s branch_id=%s",
            self._lang_code, code, str(self._state.branch_id),
        )
        # LiveKit agent handoff: returning (new_agent, result) swaps the active
        # agent — the new one carries its OWN Sarvam STT + smallest TTS in the
        # target language plus rebuilt instructions. Its on_enter speaks the
        # acknowledgement deterministically. The conversation history MUST ride
        # along (live test 2026-07-03: without it the new agent forgot the
        # doctor/flow — 'Unknown doctor' tool errors, re-asking, Telugu endings).
        try:
            _cc = self.chat_ctx.copy()
        except Exception as e:  # noqa: BLE001 — a switch without history still beats no switch
            logger.warning("chat_ctx_copy_failed: %s", e)
            _cc = None
        new_agent = self._agent_factory(code, chat_ctx=_cc)
        # PRIME the new TTS BEFORE the handoff. smallest cold-connects on its
        # first synth and on Fly that often throws "Connection error" + 2s
        # retries — exactly the post-switch dead air / self-interruption of the
        # 2026-07-03 live test (tts_failed x12 at 17:03Z). A tiny synth here
        # absorbs the cold connect so the spoken ack starts instantly.
        try:
            _new_tts = getattr(new_agent, "_tts_override", None)
            if _new_tts is not None:
                async with asyncio.timeout(8):
                    async for _ in _new_tts.synthesize("ok"):
                        break
        except Exception as e:  # noqa: BLE001 — priming is best-effort (RULE 8)
            logger.warning("switch_tts_prime_failed: %s", e)
        # Cut the OLD voice's in-flight sentence ("Okay, I can speak in
        # English. How can I..." — live 17:49Z: THREE utterances played). The
        # LLM streams spoken text alongside the tool call and the old TTS
        # voices it; interrupting here leaves at most a clipped "Okay".
        try:
            sp = getattr(self.session, "current_speech", None)
            if sp is not None:
                sp.interrupt()
        except Exception:  # noqa: BLE001
            pass
        # Return the Agent ALONE (no result payload): livekit generates a
        # post-tool reply only when the tool returned an output
        # (generation.make_tool_output: reply_required = fnc_out is not None).
        # A bare Agent → handoff with NO extra LLM utterance — on_enter's ack
        # is the ONLY thing spoken, exactly the single-intro Vinay specified.
        return new_agent

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
            # The passed token is STALE — a prior reschedule in THIS same call
            # already moved it (that reschedule cancels the old token and creates
            # a NEW confirmed one), but the LLM still holds the ORIGINAL id from
            # find_my_bookings. Rescheduling again then failed
            # "not_reschedulable_cancelled_by_patient" (live call 2026-07-07,
            # FIXLOG #283). Recover deterministically: reschedule the patient's
            # CURRENT confirmed booking with the SAME doctor (the replacement)
            # instead of failing. RULE 1: branch + patient + doctor scoped.
            replacement = (
                await self._db.execute(
                    select(Token)
                    .where(
                        and_(
                            Token.branch_id == self._state.branch_id,
                            Token.doctor_id == old_token.doctor_id,
                            Token.patient_id == old_token.patient_id,
                            Token.status == "confirmed",
                        )
                    )
                    .order_by(Token.date.desc(), Token.appointment_time.desc())
                )
            ).scalars().first()
            if replacement is None:
                return {"success": False, "error": f"not_reschedulable_{old_token.status}"}
            logger.info(
                "reschedule_stale_token_recovered old=%s new=%s",
                str(old_token.id), str(replacement.id),
            )
            old_token = replacement

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
            # B1: confirm_booking core did db.add()+flush() of a 'confirmed'
            # Token BEFORE the calendar write raised. That row is pending in THIS
            # still-open session; any later commit (a retry, a cancel, a
            # follow-up complete) would persist a phantom booking with no
            # calendar event. Roll the session back — mirroring the tool-wrapper
            # confirm_booking (FIXLOG #67) — BEFORE releasing the hold, so the
            # stray row can never ride a subsequent commit.
            try:
                await self._db.rollback()
            except Exception:
                pass
            await self._release_hold(assigned)  # RULE 3: don't leak the new hold
            self._clear_hold()  # so shutdown cleanup doesn't DECR it a 2nd time
            return {"success": False, "step": "confirm", "error": "booking_failed"}
        if not confirmed.get("success"):
            # B1: an in-band failure path (dup guard / capacity) may return
            # after the core flushed the Token. Roll back so no half-written row
            # survives to a later commit on this session.
            try:
                await self._db.rollback()
            except Exception:
                pass
            await self._release_hold(assigned)  # RULE 3: dup guard / capacity etc.
            self._clear_hold()
            return {"success": False, "step": "confirm", **confirmed}
        self._state.token_confirmed = True
        self._state.token_number = confirmed.get("token_number") or assigned["token_number"]

        # New booking exists — NOW it is safe to drop the old one.
        cancelled = await self._do_cancel(str(old_token.id))
        # Live call 2026-07-03 16:55Z: a reschedule that SUCCEEDED (DB showed the
        # moved booking) was announced as "unable to reschedule" — the model
        # misread the result. Log it (evidence for next time) and make success
        # unmistakable with an explicit spoken instruction.
        logger.info(
            "reschedule_done new_date=%s new_time=%s old_cancelled=%s branch_id=%s",
            booking_date.isoformat(),
            assigned.get("appointment_time"),
            bool(cancelled.get("success")),
            str(self._state.branch_id),
        )
        return {
            "success": True,
            "new_token_number": assigned["token_number"],
            "new_date": booking_date.isoformat(),
            "new_time": assigned.get("appointment_time"),
            "old_cancelled": bool(cancelled.get("success")),
            "instruction": (
                "The reschedule SUCCEEDED — the appointment is now on the new "
                "date/time above and the old one is cancelled. Tell the caller "
                "it is done, in one breath. Do NOT say it failed."
            ),
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
                    # HARD CAP (live 2026-07-03 18:18Z): this delete's retry
                    # backoff blocked _do_cancel for 36s — the caller heard
                    # dead air and the LLM apologised "I can't cancel" while
                    # the DB cancel had ALREADY succeeded. The DB row is the
                    # booking truth; the calendar event is cleanup — never let
                    # it stall or fail the cancel (mirror of RULE 4's spirit).
                    async with asyncio.timeout(5):
                        await self._calendar.delete_event(
                            cal_id, token.google_calendar_event_id
                        )
            except Exception as e:
                logger.warning("cancel_calendar_delete_failed: %s", e)

        logger.info(
            "booking_cancelled token=%s branch_id=%s",
            token_id[-8:],
            str(self._state.branch_id),
        )
        return {
            "success": True,
            "instruction": (
                "The cancellation SUCCEEDED — the booking is cancelled. Tell "
                "the caller it is done, in one short line. Do NOT say it "
                "failed or that you cannot cancel."
            ),
        }

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

    # OUTBOUND INSTANT OPENING (Vinay 2026-07-05: "the moment we trigger call,
    # trigger all other process — by the time the caller lifts we're ready").
    # Ring time is free compute: resolve branch + caller language and synthesize
    # the FULL real greeting (reminder/rebook/follow-up, patient name, time, in
    # the clinic's voice) WHILE the phone rings. The instant they answer, the
    # pre-synthesized real opening plays (<0.5s) — no canned mask, no synth wait.
    # RULE 8: any failure here just means the live session.say fallback speaks
    # the same segments after connect.
    _out_greet: dict = {}

    async def _outbound_greet_prep() -> None:
        try:
            if not meta.get("branch_id"):
                return
            async with AsyncSessionLocal() as _gdb:
                _gbr = (
                    await _gdb.execute(
                        select(Branch).where(Branch.id == UUID(meta["branch_id"]))
                    )
                ).scalars().first()
                if _gbr is None:
                    return
                _glang = getattr(_gbr, "language", None) or "te"
                try:
                    _gpref = await get_preferred_language(_gbr.id, outbound_number, _gdb)
                    if _gpref and _gpref in LANGUAGES:
                        _glang = _gpref
                except Exception:  # noqa: BLE001 — RULE 8
                    pass
            if is_followup and followup_meta.get("message"):
                followup_meta["message"] = await _localize_message(
                    followup_meta["message"], _glang
                )
                followup_meta["_localized"] = True  # skip the post-answer re-hop
            _gclinic = (getattr(_gbr, "name_spoken", None) or "").strip() or _gbr.name
            texts = outbound_greeting_texts(
                _glang,
                _gclinic,
                await spoken_text(meta.get("patient_name", ""), _glang),
                await spoken_text(meta.get("doctor_name", ""), _glang),
                meta,
                followup_meta,
                is_reminder=is_reminder,
                is_rebook=is_rebook_call,
                is_followup=is_followup,
            )
            wavs = await synth_wavs(texts, _voice_for_lang(_gbr, _glang), _glang)
            _out_greet.update(texts=texts, wavs=wavs, lang=_glang)
            logger.info("outbound_greet_prep_ok segments=%d lang=%s", len(texts), _glang)
        except Exception as _ge:  # noqa: BLE001 — RULE 8: fall back to live greeting
            logger.warning("outbound_greet_prep_failed: %s", _ge)

    _greet_prep_task = (
        asyncio.create_task(_outbound_greet_prep()) if outbound_number else None
    )

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
    branch_lang_code = getattr(branch, "language", None) or "te"
    lang_code = branch_lang_code
    # PER-CALLER LANGUAGE MAPPING (Vinay 2026-07-03): a caller who once asked
    # "can you speak English/Hindi?" is mapped (Patient.preferred_language) and
    # every later call — inbound AND outbound reminder/follow-up (patient_phone
    # is the dialed number there) — starts in THEIR language, not the branch
    # default. Branch context still comes from the DID (RULE 5); only the
    # spoken language is per-caller. Lookup is branch-scoped (RULE 1) and can
    # never block the call (RULE 8).
    try:
        if state.patient_phone:
            _pref = await get_preferred_language(branch.id, state.patient_phone, db)
            if _pref and _pref in LANGUAGES:
                lang_code = _pref
                state.preferred_language = _pref
                logger.info("caller_lang_mapped lang=%s branch_id=%s", _pref, str(branch.id))
    except Exception as e:  # noqa: BLE001
        logger.warning("pref_lang_lookup_failed: %s", e)
    lang_cfg = get_lang(lang_code)
    lines = get_lines(lang_code)

    # A doctor may write the follow-up note in English; speak it in the call's
    # language (clear Telugu), not fast English over a Telugu TTS (Vinay 2026-06-25).
    if (
        is_followup
        and followup_meta.get("message")
        and not followup_meta.get("_localized")  # ring-time prep already did it
    ):
        followup_meta["message"] = await _localize_message(
            followup_meta["message"], lang_code
        )

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
                # B3: honor the trial grant + super-admin minutes_adjustment so
                # the gate blocks at the SAME bucket the dashboard shows.
                adjustment=int(getattr(org, "minutes_adjustment", 0) or 0),
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
        # Clinic's chosen voice, unless it's a clone registered for a different
        # language than this CALL speaks (per-caller mapping may differ from the
        # branch language) — then the target language's default voice.
        tts_voice = _voice_for_lang(branch, lang_code)
        state.branch_id = branch_id

        # REAL GREETING AT ANSWER (Vinay 2026-07-05: "within 2 seconds the agent
        # needs to speak... not prerecorded message but original conversation").
        # The full per-call opening (clinic welcome + disclosure / greet-by-name /
        # reminder / doctor's question) is synthesized fresh and streamed on a
        # temporary track CONCURRENT with session.start() — first audio ~1s after
        # pickup. OUTBOUND: the greeting was synthesized during RING time
        # (_outbound_greet_prep); it plays the instant they answer. The old canned
        # welcome bridge + welcome_short_audio mask are gone (superseded). RULE 8:
        # any failure → _welcome_task returns False and the live session.say
        # fallback below speaks the SAME composed segments after session.start.
        _welcome_task = None
        _greet_texts: list[str] | None = None
        # Clinic name rendered in the CALL language's script (cached HTTP hop;
        # no-op when scripts already match). Needed for the greeting AND later
        # for every spoken line.
        _spk_clinic = await spoken_text(branch_name, lang_code)
        _is_outbound_greet = is_reminder or is_rebook_call or is_followup

        # The LLM has NO clock: without this it guesses today's date (wrong
        # year even), books "tomorrow" in the past, and the past-date guard
        # then refuses everything. Branch-local time, not server time.
        # (Moved above the greeting: the caller lookup below needs now_b.)
        try:
            from zoneinfo import ZoneInfo

            now_b = datetime_cls.now(ZoneInfo(branch.timezone or "Asia/Kolkata"))
        except Exception:
            now_b = datetime_cls.now()
        # Explicit date table (build_date_context) — LLM weekday math was
        # off-by-one (booked Tuesday on Wednesday's date); now it looks up.
        date_context = build_date_context(now_b)

        # CALLER IDENTIFICATION (requirement 2026-06-14): on a normal INBOUND
        # call, look the caller up by their number BEFORE the greeting so the
        # instant opening itself welcomes a returning patient by name. Skip for
        # outbound/reminder/rebook (those already know the patient from dispatch
        # metadata). RULE 1: the lookup is branch-scoped; a failure must never
        # block answering (RULE 8).
        caller_greeting_name: str | None = None
        caller_prompt_extra = ""
        inbound_followup: dict | None = None  # missed-call callback (set below)
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
                        caller_prompt_extra = KNOWN_CALLER_BOOKING_EXTRA.format(
                            name=_known
                        )
                # MISSED-CALL CALLBACK: if this caller has a pending follow-up the
                # doctor scheduled, the agent proactively raises the doctor's question
                # + offers the booking (instead of a plain inbound). Booking marks the
                # task complete (state.followup_task_id), stopping the outbound retry.
                inbound_followup = await _inbound_pending_followup(
                    state.branch_id, state.patient_phone, db
                )
                if inbound_followup:
                    # Speak the doctor's note in the call's language (translate English).
                    if inbound_followup.get("message"):
                        inbound_followup["message"] = await _localize_message(
                            inbound_followup["message"], lang_code
                        )
                    # The GREETING (below) deterministically asks the doctor's question;
                    # this extra just drives the booking offer + locks the doctor.
                    _td = _spoken_target_date(inbound_followup.get("target_date", ""), lang_code)
                    caller_prompt_extra += (
                        "\n\nPENDING FOLLOW-UP: your opening already asked the doctor's "
                        "question. IF the patient's answer is fine/normal, tell them the "
                        f"doctor wants them back around {_td} for a follow-up with "
                        f"{inbound_followup['doctor_name']} and OFFER TO BOOK it — book "
                        f"with {inbound_followup['doctor_name']}, never ask which doctor. "
                        "On agreement, FIRST ask what time of day suits them — NEVER "
                        "pick a time yourself; the patient chooses, you check it with "
                        "check_availability. The patient is already in our records — do "
                        "NOT ask their name or age; book on their existing record. "
                        "IF instead they report a problem/pain: say you will inform the "
                        "doctor and they will get back soon, and do NOT push the booking "
                        "— book only if the patient explicitly asks. Speak the date "
                        "using the words BEFORE the parenthesis; the parenthesis is the "
                        "ISO for tools only."
                    )
                    try:
                        state.followup_task_id = UUID(inbound_followup["task_id"])
                        state.doctor_id = UUID(inbound_followup["doctor_id"])
                    except (ValueError, KeyError):
                        pass
            except Exception as e:
                logger.warning("caller_lookup_failed: %s", e)

        # Names enter the greeting in the CALL'S script so the TTS speaks them
        # as names, not spelled letters (fix 2026-06-23).
        _spk_caller = (
            await spoken_text(caller_greeting_name, lang_code)
            if caller_greeting_name else None
        )
        if _is_outbound_greet:
            # Pre-synthesized during ring time — play instantly. Language guard:
            # if the authoritative post-answer resolution disagrees with the prep
            # (row changed mid-ring), skip the clip; live fallback covers it.
            if _greet_prep_task is not None:
                try:
                    await asyncio.wait_for(_greet_prep_task, timeout=2.0)
                except Exception as _gw:  # noqa: BLE001
                    logger.warning("outbound_greet_prep_wait: %s", _gw)
            if _out_greet.get("wavs") and _out_greet.get("lang") == lang_code:
                _greet_texts = _out_greet["texts"]
                _welcome_task = asyncio.create_task(
                    play_wavs(ctx.room, _out_greet["wavs"], t_answer=_t_answer)
                )
        elif branch_name:
            _greet_texts = inbound_greeting_texts(
                lang_code,
                _spk_clinic,
                spk_caller=_spk_caller,
                followup_message=(inbound_followup or {}).get("message") or None,
            )
            _welcome_task = asyncio.create_task(
                synth_and_play(
                    ctx.room, _greet_texts, tts_voice, lang_code, t_answer=_t_answer
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

        # (now_b/date_context + caller identification moved ABOVE the greeting —
        # the instant opening needs the caller's name and branch-local clock.)

        # Instructions are composed by a FUNCTION of the language so the
        # switch_language handoff can rebuild the FULL prompt (system + date
        # table + brevity + caller/call-type extras) in the new language —
        # only the language-dependent parts change; extras carry over verbatim
        # (their Telugu sample phrases are style references under the PRIMARY
        # LANGUAGE directive).
        extra_tail = ""

        def _compose_instructions(lc: str) -> str:
            return (
                build_system_prompt(
                    clinic_name=branch_name,
                    doctors=doctor_contexts,
                    emergency_contact=emergency_contact,
                    plan=state.plan or "clinic",
                    language=lc,
                    clinic_address=getattr(branch, "address", None),
                    faq=getattr(branch, "faq", None),
                )
                + date_context
                + get_lines(lc).brevity
                + caller_prompt_extra
                + extra_tail
            )

        # Outbound calls carry the doctor in metadata — pre-select so tools
        # never fail with "Unknown doctor" no matter how the LLM names them.
        if meta.get("doctor_id"):
            try:
                state.doctor_id = UUID(meta["doctor_id"])
            except ValueError:
                pass
        if is_reminder:
            extra_tail += REMINDER_PROMPT_EXTRA.format(
                token_id=meta.get("token_id", ""),
                doctor=meta.get("doctor_name", ""),
                time=meta.get("appointment_time", ""),
            )
            state.call_type = "reminder"
        elif is_rebook_call:
            extra_tail += REBOOK_PROMPT_EXTRA.format(
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
            extra_tail += NEXT_VISIT_PROMPT_EXTRA.format(
                message=followup_meta.get("message", ""),
                doctor=followup_meta.get("doctor_name", "the doctor"),
                patient=followup_meta.get("patient_name", "the patient"),
                target_date=_spoken_target_date(
                    followup_meta.get("target_date", ""), lang_code
                ),
            )
            state.call_type = "next_visit_book"
        elif meta.get("call_type") == "doctor_advice":
            extra_tail += DOCTOR_ADVICE_PROMPT_EXTRA.format(
                message=followup_meta.get("message", ""),
                target_date=_spoken_target_date(
                    followup_meta.get("target_date", ""), lang_code
                ),
            )
            state.call_type = "doctor_advice"

        instructions = _compose_instructions(lang_code)

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

        def _agent_for_lang(lc: str, chat_ctx=None) -> VachanamAgent:
            """Build the handoff agent for a mid-call language switch: full
            prompt, Sarvam STT and smallest TTS all in the target language,
            sharing this call's state/db/room + conversation history. Used by
            switch_language."""
            cfg2 = get_lang(lc)
            return VachanamAgent(
                instructions=_compose_instructions(lc),
                chat_ctx=chat_ctx,
                state=state,
                db=db,
                room=ctx.room,
                calendar_service=calendar_service,
                meta_service=MetaService(),
                transfer_to=emergency_contact,
                lang_code=lc,
                agent_factory=_agent_for_lang,
                switch_ack=get_switch_ack(lc),
                stt=sarvam.STT(
                    api_key=settings.sarvam_api_key,
                    model="saaras:v3",
                    language=cfg2.stt_code,
                    flush_signal=True,
                ),
                tts=_HttpSmallestTTS(
                    api_key=settings.smallest_api_key,
                    model=settings.smallest_model,
                    voice_id=_voice_for_lang(branch, lc),
                    language=cfg2.tts_code,
                    sample_rate=settings.smallest_sample_rate,
                    output_format="wav",
                ),
            )

        # The instant greeting bypasses the session pipeline — seed it into the
        # agent's chat history so the LLM knows exactly what was already said
        # and never re-greets or re-discloses.
        _seed_ctx = None
        if _greet_texts and _welcome_task is not None:
            _seed_ctx = ChatContext.empty()
            _seed_ctx.add_message(role="assistant", content=" ".join(_greet_texts))
        vachanam_agent = VachanamAgent(
            instructions=instructions,
            chat_ctx=_seed_ctx,
            state=state,
            db=db,
            room=ctx.room,
            calendar_service=calendar_service,
            meta_service=MetaService(),
            transfer_to=emergency_contact,
            lang_code=lang_code,
            agent_factory=_agent_for_lang,
        )

        logger.info("lat_pre_session_build answer_to_build=%.2fs", _perf.monotonic() - _t_answer)

        _t_build = _perf.monotonic()
        # Session TTS captured in a var so we can PRIME its connection during the
        # masked welcome-clip window. The smallest.ai plugin cold-connects on its
        # FIRST synth and (on Fly) often throws "Connection error" → 3 retries with
        # 2s backoff = ~6s of dead air on the first real response ("silent for 10s
        # after intro", 2026-06-24). Priming it while the clip plays makes that cold
        # connect happen invisibly.
        _session_tts = _HttpSmallestTTS(
            api_key=settings.smallest_api_key,
            model=settings.smallest_model,
            voice_id=tts_voice,
            language=lang_cfg.tts_code,
            sample_rate=settings.smallest_sample_rate,
            # WAV, not pcm: the HTTP /tts endpoint returns a WAV container even when
            # asked for pcm, so declaring "pcm" made the emitter play WAV bytes as
            # raw PCM → garbled/too-fast speech (2026-06-25). "wav" lets the decoder
            # read the real rate from the header.
            output_format="wav",
        )
        session = AgentSession(
            # Per-clinic spoken-language fillers ride here so _say_lookup_filler
            # speaks the clinic's language (falls back to Telugu). filler_clips is
            # filled by cache_filler_clips at session start = instant playback.
            userdata={"fillers": lines.fillers, "language": lang_code,
                      "filler_clips": []},
            stt=sarvam.STT(
                api_key=settings.sarvam_api_key,
                model="saaras:v3",
                # ONE language at a time (Vinay 2026-06-17): auto-detect
                # ("unknown") was tried but rejected — shared words across Indian
                # languages ("amma", numbers) make Sarvam mis-infer the language and
                # degrade transcription. The ONLY way the call changes language is
                # the switch_language tool (explicit caller ask, 2026-07-03): an
                # AGENT HANDOFF carrying its own STT/TTS — never a hot-swap of this
                # session pipeline and never speech-based auto-detection.
                language=lang_cfg.stt_code,
                flush_signal=True,  # final transcript on client VAD end (-1-2s/turn)
            ),
            llm=ctx.proc.userdata.get("llm") or _build_fallback_llm(),
            # TTS = smallest.ai Waves Lightning (replaced Sarvam Bulbul 2026-06-15).
            # STT above stays Sarvam Saaras. voice_id is the clinic's smallest voice
            # (or a cloned voice); language is the clinic's short code (smallest uses
            # the same te/hi/ta/... codes). output_format pcm streams to LiveKit.
            tts=_session_tts,
            vad=ctx.proc.userdata.get("vad") or silero.VAD.load(),
            # LATENCY (biggest network-independent win): a SEMANTIC turn detector.
            # Without it, turn-end was decided by VAD silence alone, forcing a long
            # max_endpointing_delay so the patient isn't cut off mid-sentence. The
            # model commits the turn as soon as the utterance is grammatically
            # complete (often 200-400ms), letting the silence timers drop below.
            # Built here (not prewarm): livekit-agents 1.6 binds the model to the
            # job's inference executor, which only exists inside the entrypoint —
            # so it loads at session.start and adds seconds to the call-start.
            # 2026-06-24: MultilingualModel does NOT support te-IN (logs: "Turn
            # detector does not support language te-IN") — for Telugu it is pure
            # start-up latency with ZERO benefit (turn-end falls to VAD anyway).
            # Skip it for unsupported languages; VAD + the 0.6s endpointing handle
            # turn-end. Keep it only where it actually works.
            turn_detection=(
                None if lang_cfg.stt_code in ("te-IN",) else MultilingualModel()
            ),
            preemptive_generation=True,
            # With the semantic turn detector backstopping, the silence timers can
            # shrink: the detector fires on a complete utterance; these only catch
            # the case where it's unsure. min 0.4->0.2, max 1.5->1.0.
            # te-IN is NOT supported by MultilingualModel (logs: "Turn detector
            # does not support language te-IN") — so for Telugu the semantic
            # detector is inert and turn-end falls to VAD silence alone. The
            # conservative 1.0s max only guarded against cutting a speaker off;
            # trim it to shave ~0.3-0.4s off every Telugu reply (2026-06-24
            # latency pass). Raise back toward 1.0 if speakers get clipped.
            min_endpointing_delay=0.2,
            max_endpointing_delay=0.6,
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
            # 2026-06-24: when the caller barges in, the agent must STOP and STAY
            # stopped. resume_false_interruption=True made it RESUME ("it finishes
            # what it's saying") because Sarvam's Telugu transcript arrives slower
            # than the false-interruption window, so a real interruption looked
            # "false" and the sentence resumed. Disabled — a detected interruption
            # now stays stopped.
            # 2026-07-06 (Vinay real-call): interrupting the agent took 1-2s.
            # Root cause from Fly lat_* — min_interruption_words=1 held the stop
            # until Sarvam transcribed the first Telugu WORD (transcription_delay
            # 0.65-0.85s) on top of VAD (0.2s). Interruption was transcript-gated.
            # Fix: words=0 → yield on VAD speech alone (no transcript wait), and
            # duration 0.2->0.4s so a short backchannel ("haan"/"mm", <0.4s) is
            # filtered by LENGTH instead of by waiting for a transcript. Barge-in
            # ~1-2s -> ~0.4s; the 2026-06-22 backchannel guard is preserved by
            # duration. Raise duration toward 0.6 if longer backchannels cut in.
            min_interruption_duration=0.4,
            min_interruption_words=0,
            resume_false_interruption=False,
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
                # Measured 2026-07-04: eou 1.12-1.35s vs max_endpointing_delay=0.6
                # — the missing ~0.5-0.75s is EITHER the Silero silence window or
                # Sarvam's final-transcript wait. transcription_delay splits them
                # so the next tuning step is attributed, not guessed (FIXLOG #267).
                logger.info(
                    "lat_eou end_of_utterance_delay=%.2fs transcription_delay=%.2fs turn_completed_delay=%.2fs",
                    getattr(m, "end_of_utterance_delay", 0.0),
                    getattr(m, "transcription_delay", 0.0),
                    getattr(m, "on_user_turn_completed_delay", 0.0),
                )
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
                # B14: compute duration OUTSIDE both try blocks. It used to be
                # assigned inside the CallLog try (after an import + a
                # db.rollback that can throw on a torn connection); if that
                # raised before the assignment, the later CallQuality block
                # referenced an unbound `duration` -> NameError -> the quality
                # row was silently dropped for every such teardown.
                started = state.call_start or datetime_cls.now(timezone_utc)
                duration = max(
                    0,
                    int((datetime_cls.now(timezone_utc) - started).total_seconds()),
                )

                # FINALIZE the at-start row (TD-027/F6) with the real duration +
                # booking outcome. Fall back to an INSERT if the start row was
                # never written (start-time metering failure).
                try:
                    from sqlalchemy import update as _sa_update

                    from backend.models.schema import CallLog

                    await db.rollback()  # clear any failed tx before logging
                    if state.call_log_id is not None:
                        # Finalize the agent-written at-start row (agent logging on).
                        # B11: also refresh call_type — the start row was written
                        # BEFORE the type was refined from the generic
                        # "outbound"/"inbound_booking" to reminder / cascade_rebook
                        # / next_visit_book / doctor_advice, so analytics that
                        # segment by call_type undercounted those activities.
                        await db.execute(
                            _sa_update(CallLog)
                            .where(CallLog.id == state.call_log_id)
                            .values(
                                call_type=state.call_type or "inbound",
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
        _t_ss = _perf.monotonic()
        _start_task = asyncio.create_task(
            session.start(
                room=ctx.room,
                agent=vachanam_agent,
                room_input_options=RoomInputOptions(
                    noise_cancellation=noise_cancellation.BVCTelephony(),
                ),
            )
        )
        # Time session.start() ON ITS OWN (not tangled with the welcome-clip await,
        # which previously made lat_session_connect look like the clip's ~6s).
        _start_task.add_done_callback(
            lambda _t: logger.info(
                "lat_real_session_start=%.2fs", _perf.monotonic() - _t_ss
            )
        )

        # PRIME the session TTS connection now (concurrent with the clip + connect),
        # so its cold "Connection error" + retries happen in the masked window and
        # the first real response is hot. Best-effort — never blocks the call.
        async def _warm_session_tts() -> None:
            _t = _perf.monotonic()
            try:
                async for _ in _session_tts.synthesize("సరే"):
                    break  # first frame = connection established; discard audio
                logger.info("tts_warm_ok=%.2fs", _perf.monotonic() - _t)
            except Exception as _e:  # noqa: BLE001
                logger.warning("tts_warm_failed: %s", str(_e)[:100])

        _tts_warm_task = asyncio.create_task(_warm_session_tts())
        # Pre-render the lookup fillers in the clinic voice so the "okay అండి /
        # ఒక్క నిమిషం" ack plays INSTANTLY when a slot lookup runs (Vinay
        # 2026-07-06), no per-call TTS latency. Best-effort, never blocks.
        _filler_cache_task = asyncio.create_task(
            cache_filler_clips(session, lines.fillers, tts_voice, lang_code)
        )
        _pre_greeted = False
        if _welcome_task is not None:
            try:
                _pre_greeted = bool(await _welcome_task)
            except Exception as _we:  # noqa: BLE001
                logger.warning("welcome_await_failed: %s", _we)
        _t_pre_start_await = _perf.monotonic()
        await _start_task
        logger.info(
            "lat_session_connect total_answer_to_ready=%.2fs wait_after_clip=%.2fs",
            _perf.monotonic() - _t_answer,
            _perf.monotonic() - _t_pre_start_await,
        )

        # RULE 6: opening utterances sanitized. Normally the instant greeting
        # already played (pre_greeted) and there is NOTHING to re-speak — the
        # blocks below are the RULE 8 fallback that speaks the SAME composed
        # segments live (STT up) when the pre-greet clip failed.
        #
        # Names enter the greeting in the CALL'S script so the TTS speaks them as
        # names, not spelled letters (fix 2026-06-23: "Srinivas" → "S R I N I").
        # spoken_text handles EVERY direction (Latin→Indic, Indic→Latin,
        # Indic→Indic via a Latin hop) — the old spoken_name skipped English
        # targets, so the en agent greeted with raw Telugu glyphs ("శ్రీ
        # వెంకటేశ్వర" spelled wrongly, live 2026-07-03/04).
        _spk_patient = await spoken_text(meta.get("patient_name", ""), lang_code)
        _spk_doctor = await spoken_text(meta.get("doctor_name", ""), lang_code)
        logger.info("lat_greeting answer_to_greeting=%.2fs", _perf.monotonic() - _t_answer)
        if _pre_greeted:
            logger.info("greeting_pre_played segments=%d", len(_greet_texts or []))
        elif _is_outbound_greet:
            # RULE 8 fallback — ring-time pre-synth failed; speak the SAME
            # composed opening live (time/date wording, doctor's-question
            # segmentation and follow-up frame all live in
            # greeting.outbound_greeting_texts). Follow-up segments stay
            # uninterruptible (patient's "హా/చెప్పండి" barged the doctor's
            # question out, 2026-06-25); reminder/rebook stay interruptible.
            _fb_texts = _greet_texts or outbound_greeting_texts(
                lang_code,
                _spk_clinic,
                _spk_patient,
                _spk_doctor,
                meta,
                followup_meta,
                is_reminder=is_reminder,
                is_rebook=is_rebook_call,
                is_followup=is_followup,
            )
            for _seg in _fb_texts:
                await session.say(
                    sanitize_for_tts(_seg), allow_interruptions=not is_followup
                )
        else:
            # RULE 8 fallback — instant greeting failed; speak the SAME composed
            # segments live (welcome + disclosure / greet-by-name / doctor's
            # question). Missed-call-callback segments stay uninterruptible so
            # the doctor's question always lands in full (2026-06-25).
            _fb_texts = _greet_texts or inbound_greeting_texts(
                lang_code,
                _spk_clinic,
                spk_caller=_spk_caller,
                followup_message=(inbound_followup or {}).get("message") or None,
            )
            _uninterruptible = bool((inbound_followup or {}).get("message"))
            for _seg in _fb_texts:
                await session.say(
                    sanitize_for_tts(_seg), allow_interruptions=not _uninterruptible
                )

        if not _is_outbound_greet:
            # DPDP s.5 demonstrable notice: the opening (instant clip or the
            # fallback just spoken) contains the AI-assistant / data-processing
            # disclosure. Record that notice was served on this inbound call
            # (own short-lived session — never touch the live call's DB session;
            # fire-and-forget, must never break a call).
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
        # Vinay 2026-07-03: solo cap raised 4→10 min after live calls got cut at
        # 5 min mid-booking (MAX_CALL_DURATION_SECONDS secret also moved to 600).
        SOLO_CAP_DEFAULT = 600
        ABSOLUTE_CAP_DEFAULT = 900  # 15 min — never hits a legitimate call
        if state.plan == "solo":
            cap = settings.max_call_duration_seconds or SOLO_CAP_DEFAULT
        else:
            cap = ABSOLUTE_CAP_DEFAULT
        if cap and cap > 15:

            async def _solo_cap_watchdog() -> None:
                try:
                    await asyncio.sleep(cap - 10)
                    # Resolve lines at SPEAK time — switch_language may have
                    # changed the call's language after `lines` was captured.
                    _cur = get_lines(state.language or lang_code)
                    if not state.solo_warning_sent:
                        state.solo_warning_sent = True
                        await session.say(sanitize_for_tts(_cur.cap_warning))
                    await asyncio.sleep(10)
                    await session.say(
                        sanitize_for_tts(_cur.cap_goodbye)
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

    # (The welcome-TTS warmup went with the canned welcome clip — the instant
    # greeting synthesizes over raw REST per call; see greeting.py.)


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
