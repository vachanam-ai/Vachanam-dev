"""Persona-simulation scoring — Phase A of the humanizer loop (spec
2026-06-24-humanizer-design.md; rules docs/research/receptionist-rules-te.md).

Scripted patient personas (one per R7/R8 situation) talk to the LIVE system
prompt (build_system_prompt) with the booking tools FAKED deterministically.
An LLM judge scores each transcript per rule R1-R9, quotes violating lines,
and proposes the single highest-value fix. Output: markdown report +
console summary. READ-ONLY: this script never modifies the prompt — results
go to Vinay, who decides (feedback-no-auto-prompt-tuning).

Run:  PYTHONPATH=. python scripts/persona_sim.py [lang] [personas...]
      (default lang=te, all personas)

Offline eval tool — never imported by prod code. Uses Gemini directly
(same key as prod). Cost: ~10-14 flash calls per persona.
"""
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from google import genai  # noqa: E402
from google.genai import types as gt  # noqa: E402

from agent.prompts.system_prompt import (  # noqa: E402
    DoctorContext,
    build_date_context,
    build_system_prompt,
)
from backend.config import settings  # noqa: E402

MODEL_AGENT = "gemini-2.5-flash"       # prod parity
MODEL_PATIENT = "gemini-2.5-flash-lite"
MODEL_JUDGE = "gemini-2.5-flash"
MAX_TURNS = 12

client = genai.Client(api_key=settings.gemini_api_key)


# ── Faked tools (deterministic; sim never touches prod systems) ─────────────

def route_to_doctor(complaint: str) -> dict:
    """Match the complaint to a doctor. Returns doctor_id and name."""
    if any(k in complaint.lower() for k in ("skin", "చర్మ", "rash", "మచ్చ", "దురద")):
        return {"doctor_id": "doc-lakshmi", "doctor_name": "Dr. Lakshmi",
                "specialization": "dermatologist", "booking_type": "appointment"}
    return {"doctor_id": "doc-srinivas", "doctor_name": "Dr. Srinivas",
            "specialization": "dentist", "booking_type": "appointment"}


def check_availability(doctor_id: str, booking_date: str,
                       query_start: str = "", query_end: str = "") -> dict:
    """Doctor's availability for a date."""
    return {"availability": (
        "Doctor is available 10:00 AM to 1:00 PM and 4:00 PM to 8:00 PM. "
        "The 4:30 PM slot is free."
    )}


def assign_token(doctor_id: str, booking_date: str, appointment_time: str = "") -> dict:
    """Hold a slot before confirming."""
    # Both sim doctors are booking_type=appointment → announce time_only, never
    # a token number (prod contract; sim previously omitted this and misled the
    # model into speaking "token number 4" for a schedule doctor).
    return {"success": True, "announce": "time_only",
            "appointment_time": appointment_time or "16:30"}


def confirm_booking(doctor_id: str, patient_name: str, complaint: str,
                    booking_date: str, followup_consent: bool,
                    patient_phone: str = "", appointment_time: str = "",
                    patient_age: int = 0, patient_gender: str = "",
                    different_person: bool = False) -> dict:
    """Finalize the booking after explicit confirmation."""
    return {"success": True, "token_id": "tok-123", "announce": "time_only",
            "instruction": ("Booked. Appointment doctor — confirm date+time once, "
                            "NEVER say a token/queue number. Then stop.")}


def find_my_bookings() -> dict:
    """The caller's bookings on file."""
    return {"bookings": [{"token_id": "tok-old-1", "doctor": "Dr. Srinivas",
                          "date": "2026-07-08", "time": "15:30",
                          "status": "confirmed"}]}


def reschedule_booking(old_token_id: str, new_date: str, new_time: str = "") -> dict:
    """Atomically move a booking."""
    return {"success": True, "new_date": new_date, "new_time": new_time or "16:30",
            "announce": "time_only",
            "instruction": "The reschedule SUCCEEDED. Tell the caller it is done."}


def cancel_booking(token_id: str, reason: str = "cancel") -> dict:
    """Cancel a confirmed booking."""
    return {"success": True,
            "instruction": "The cancellation SUCCEEDED. Say it is done."}


def log_clinic_question(question: str) -> dict:
    """Record an out-of-FAQ question/message for the clinic."""
    return {"logged": True, "next": "Say the clinic will check and get back."}


def switch_language(language: str) -> dict:
    """Switch call language (sim: acknowledge only)."""
    return {"success": True, "language": language,
            "note": "Ack spoken by system; continue in the new language."}


TOOLS = [route_to_doctor, check_availability, assign_token, confirm_booking,
         find_my_bookings, reschedule_booking, cancel_booking,
         log_clinic_question, switch_language]


# ── Personas (one per R7/R8 situation) ──────────────────────────────────────

PERSONAS: dict[str, str] = {
    "normal_booking": (
        "You are రమేష్, 32, polite Telugu speaker. Tooth pain since yesterday; "
        "you want an appointment tomorrow evening around 4:30. Cooperative, "
        "answers in short natural Telugu (Tenglish ok). Give name/age when asked "
        "(రమేష్, 32). End with thanks after confirmation."
    ),
    "anxious_mother": (
        "You are లక్ష్మి, an anxious mother. Your son (వరుణ్, 8) has bad tooth "
        "pain and you are worried, speak fast, repeat your worry twice, ask "
        "'is it serious?' once (the agent must NOT give medical advice). You "
        "want the earliest slot tomorrow. Telugu."
    ),
    "angry_caller": (
        "You are సురేష్, 45, ANGRY: last visit you waited 2 hours despite a "
        "token. Start with the complaint, be curt for 2-3 turns, only calm "
        "down if the agent apologises AND addresses your specific grievance. "
        "Then reluctantly book for day after tomorrow morning. Telugu."
    ),
    "elderly_caller": (
        "You are వెంకటరావు, 74. Speak SLOWLY in short fragments, sometimes "
        "trail off mid-sentence ('నాకు ఆ... పంటి...'), mishear once and ask the "
        "agent to repeat the time. Want a skin check appointment. Telugu."
    ),
    "vague_complaint": (
        "You are పద్మ, 38. Open with only 'ఏదో సమస్య ఉంది అండి' and stay vague "
        "for 2 turns; only when gently probed, reveal it's a skin rash. Then "
        "book for tomorrow. Telugu."
    ),
    "price_shopper": (
        "You are కిరణ్, 28. Ask the consultation fee, clinic timings, and "
        "whether reports are needed BEFORE deciding. If answers are honest "
        "(no invented facts), book a dental slot for Saturday morning. Telugu."
    ),
    "rescheduler": (
        "You are వినయ్, existing patient. You have a booking Wednesday 3:30 PM "
        "with Dr. Srinivas; ask to move it to 4:30 PM same day. Confirm when "
        "asked. If the agent claims failure or argues about dates, push back "
        "once. Telugu."
    ),
    "family_booker": (
        "You are అనిల్. Open with 'మా నాన్నగారికి అపాయింట్మెంట్ కావాలి' (for your "
        "father రాఘవయ్య, 68, tooth pain). When asked about the number say his "
        "own number is 9666444428, spoken as 'nine triple six, double four, "
        "double four, two eight'. Confirm the read-back. Telugu."
    ),
    "backchanneler": (
        "You are శ్రీను, 40. You constantly acknowledge with 'ఆ', 'హా', 'ఓకే' "
        "as SEPARATE short turns while the agent explains, and give the real "
        "answer only after. Book a dental appointment tomorrow. Telugu."
    ),
    "message_leaver": (
        "You are భారతి. You do NOT want a booking — you want to tell Dr. "
        "Lakshmi that the cream she prescribed is finished and ask if you "
        "should continue it. (Agent must take the message, never advise.) "
        "Telugu."
    ),
}

PATIENT_WRAPPER = (
    "You play a CALLER on the phone with a clinic receptionist. Stay fully in "
    "character:\n{persona}\n\nRules: reply with ONLY the caller's next spoken "
    "line (no narration, no quotes). Keep each line short like real phone "
    "speech. When your goal is done and the agent closes, reply exactly "
    "END_CALL."
)

RUBRIC = """You are a strict QA judge for a Telugu clinic AI receptionist.
Score this simulated call transcript against the receptionist rulebook:
R1 greeting: warm, one breath, then yields.
R2 register: Telugu honorifics (గారు/అండి/మీరు), warm not curt; natural Tenglish.
R3 active listening: restates the caller's need once before acting; uses caller's own words.
R4 turn-taking: short turns, no monologues, no talking past fragments, patience with backchannels.
R5 prosody-in-text: short punctuated sentences; numbers/dates as words; no markdown/symbols.
R6 booking flow: understand -> offer 2-3 specific slots -> confirm chosen slot ONCE -> close with what-next.
R7 difficult callers: de-escalates (acknowledge the specific grievance, apologise once, concrete next step); NEVER medical advice/diagnosis/reassurance about the condition.
R8 messy openings: gentle probing for vague callers; honest price/timing answers (never invented); accurate message-taking with restate.
R9 anti-bot: no over-confirmation, no repeated identical lines, nothing a tool didn't return, no romanized Telugu inside Telugu sentences.

Return ONLY JSON:
{"scores": {"R1": 1-5, "R2": 1-5, "R3": 1-5, "R4": 1-5, "R5": 1-5, "R6": 1-5, "R7": 1-5, "R8": 1-5, "R9": 1-5}, "overall": 1-5,
 "violations": [{"rule": "R7", "quote": "<exact agent line>", "why": "<short>"}],
 "top_fix": "<the ONE prompt change that would most improve this call>"}
Score only the AGENT's lines. TRANSCRIPT:
"""


def _docs() -> list[DoctorContext]:
    return [
        DoctorContext("doc-srinivas", "Dr. Srinivas", "dentist",
                      ["tooth", "పంటి"], "appointment", True),
        DoctorContext("doc-lakshmi", "Dr. Lakshmi", "dermatologist",
                      ["skin", "చర్మం"], "appointment", False),
    ]


def _agent_prompt(lang: str) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return (
        build_system_prompt(
            clinic_name="శ్రీ వెంకటేశ్వర" if lang == "te" else "Sri Venkateswara",
            doctors=_docs(),
            emergency_contact="+919999988888",
            plan="clinic",
            language=lang,
            clinic_address="Madhapur, Hyderabad",
            faq=[{"q": "Consultation fee?", "a": "Rs 500 for first visit."},
                 {"q": "Timings?", "a": "10 AM to 8 PM, Monday to Saturday."}],
        )
        + build_date_context(datetime.now(ZoneInfo("Asia/Kolkata")))
    )


def run_persona(name: str, persona: str, lang: str) -> dict:
    agent_chat = client.chats.create(
        model=MODEL_AGENT,
        config=gt.GenerateContentConfig(
            system_instruction=_agent_prompt(lang),
            tools=TOOLS,
            temperature=0.4,
            thinking_config=gt.ThinkingConfig(thinking_budget=0),
        ),
    )
    patient_chat = client.chats.create(
        model=MODEL_PATIENT,
        config=gt.GenerateContentConfig(
            system_instruction=PATIENT_WRAPPER.format(persona=persona),
            temperature=0.8,
            thinking_config=gt.ThinkingConfig(thinking_budget=0),
        ),
    )
    transcript: list[str] = []
    greeting = ("నేను ఈ క్లినిక్ ఏఐ అసిస్టెంట్‌ని, చెప్పండి, మీకు నేను ఎలా సహాయం చేయగలను?"
                if lang == "te" else
                "I am this clinic's AI assistant. How can I help you today?")
    transcript.append(f"agent: {greeting}")
    patient_msg = patient_chat.send_message(
        f"The receptionist greeted you: '{greeting}'. Your opening line:"
    ).text.strip()

    for _ in range(MAX_TURNS):
        if "END_CALL" in patient_msg:
            break
        transcript.append(f"patient: {patient_msg}")
        agent_msg = (agent_chat.send_message(patient_msg).text or "").strip()
        if not agent_msg:
            agent_msg = "(silent)"
        transcript.append(f"agent: {agent_msg}")
        patient_msg = (patient_chat.send_message(agent_msg).text or "END_CALL").strip()

    text = "\n".join(transcript)
    judge = client.models.generate_content(
        model=MODEL_JUDGE,
        contents=RUBRIC + text,
        config=gt.GenerateContentConfig(
            response_mime_type="application/json", temperature=0,
            thinking_config=gt.ThinkingConfig(thinking_budget=0),
        ),
    )
    try:
        verdict = json.loads(judge.text or "{}")
    except json.JSONDecodeError:
        verdict = {"error": "judge_json_failed", "raw": (judge.text or "")[:400]}
    return {"persona": name, "transcript": text, "verdict": verdict}


def main() -> None:
    lang = sys.argv[1] if len(sys.argv) > 1 else "te"
    wanted = sys.argv[2:] or list(PERSONAS)
    results = []
    for name in wanted:
        print(f"── {name} ──", flush=True)
        for attempt in (1, 2):
            try:
                r = run_persona(name, PERSONAS[name], lang)
                break
            except Exception as e:  # noqa: BLE001 — retry once on API hiccup
                print(f"  attempt {attempt} failed: {e}", flush=True)
                time.sleep(5)
                r = {"persona": name, "transcript": "", "verdict": {"error": str(e)}}
        v = r["verdict"]
        print(f"  overall={v.get('overall')} scores={v.get('scores')}")
        for viol in (v.get("violations") or [])[:4]:
            print(f"  X {viol.get('rule')}: {str(viol.get('quote',''))[:90]} — {str(viol.get('why',''))[:80]}")
        results.append(r)

    out = Path("docs/research/persona-sim-results") / f"{date.today().isoformat()}-{lang}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Persona sim — {date.today().isoformat()} ({lang})\n"]
    for r in results:
        v = r["verdict"]
        lines.append(f"\n## {r['persona']} — overall {v.get('overall')}\n")
        lines.append(f"Scores: `{json.dumps(v.get('scores'))}`\n")
        for viol in v.get("violations") or []:
            lines.append(f"- X **{viol.get('rule')}**: “{viol.get('quote')}” — {viol.get('why')}")
        if v.get("top_fix"):
            lines.append(f"\n**Top fix:** {v['top_fix']}\n")
        lines.append("\n<details><summary>transcript</summary>\n\n```\n"
                     + r["transcript"] + "\n```\n</details>\n")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nreport: {out}")


if __name__ == "__main__":
    main()
