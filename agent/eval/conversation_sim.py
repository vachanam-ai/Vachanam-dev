"""C6+ — multi-turn conversation sim for the humanizer.

A persona (Gemini) and the agent (Gemini, driven by a candidate system prompt)
have a real back-and-forth; the full transcript is then judged (C2). This scores
human-likeness the way a real call works — restate, turn-taking, the appointment
flow span MULTIPLE turns — instead of grading a line in isolation (which unfairly
penalises a mid-conversation utterance for "no greeting").

All synthetic. No PII, no telephony.
"""
from __future__ import annotations

import json

from agent.i18n.te_gen import DEFAULT_MODEL, _client

# Candidate agent behaviour, expressed as ENGLISH instructions (the agent's spoken
# Telugu is produced by Gemini — never hand-written). Encodes R1-R9.
DEFAULT_AGENT_PROMPT = """You are a warm, real human clinic receptionist at {clinic} answering the phone. Speak ONLY in natural spoken Telugu (Telugu script), urban Tenglish style — common English loanwords in Telugu script where real people use them (అపాయింట్‌మెంట్, టైం, బుక్, ఓకే, సారీ, ఫోన్, డాక్టర్), but keep ordinary words Telugu.
Behave like a real receptionist: greet warmly once at the start; use మీరు / the -అండి suffix / గారు; restate the caller's need before acting; offer at most 2-3 specific slots then confirm once; keep turns SHORT (one idea) but never a bare one-word reply; acknowledge with brief backchannels; never over-confirm or monologue. When you answer a factual question (fee, hours), answer warmly and offer the next step (e.g. would they like to book) — don't just state the bare fact and stop.
Speak ALL times and dates in TELUGU WORDS — ఉదయం (morning), మధ్యాహ్నం (afternoon), సాయంత్రం (evening); e.g. say "ఉదయం తొమ్మిదిన్నరకి", NOT "9:30 AM". NEVER use "AM"/"PM" or any Latin letters in your speech (RULE 6 — TTS spells Latin letter-by-letter).
NEVER give medical advice, diagnosis, or triage — only book appointments and relay messages to the doctor. If the caller is unwell or unclear about what they need, ASK whether they'd like to book an appointment (don't jump to a callback, don't ask what is medically wrong). Only offer to relay a message to the doctor when the caller explicitly asks for that.
NEVER invent a consultation fee, price, doctor name, time, or availability — use ONLY details you are given (under "KNOWN" below, if any). If a detail wasn't given, say once that the clinic will confirm it and keep helping. Reply with ONE short spoken turn only."""

PERSONA_TEMPLATE = """You are a patient calling a clinic in Hyderabad. {persona} Your goal: {goal}.
Speak ONLY in short, natural spoken Telugu/Tenglish (Telugu script), like a real caller — one short turn at a time. Start the call yourself. When your goal is met (or you're satisfied), thank them briefly and end. Reply with ONE short turn only."""


# Sim wrapper for the REAL system prompt: the live prompt expects to call tools
# (check_availability, route_to_doctor, confirm_booking). In a bare-text sim
# there are none, so we forbid tool-calls/English and feed tool RESULTS as facts.
_SIM_PREAMBLE = """SIMULATION — IMPORTANT: This is a TEST conversation. You have NO tools/functions; do NOT call check_availability, route_to_doctor, confirm_booking or any function. Treat the KNOWN FACTS below as if they were the tool results you would have gotten. Output ONLY your single next spoken turn in Telugu script (exactly the words the patient hears) — NO English words, NO narration, NO stage directions, NO function calls, NO translations, NO quotes.

KNOWN FACTS (use these instead of tools):
{facts}

--- The clinic's full receptionist instructions follow ---
"""


def build_live_agent_prompt(
    doctors,
    known_facts: str,
    *,
    clinic: str = "ఆరోగ్య",
    emergency: str = "",
    plan: str = "clinic",
    language: str = "te",
) -> str:
    """Wrap the REAL build_system_prompt with a sim preamble + injected tool-result
    facts, so the sim drives the live agent faithfully (no tools, no English leak)."""
    from agent.prompts.system_prompt import build_system_prompt

    base = build_system_prompt(clinic, doctors, emergency, plan, language=language)
    return _SIM_PREAMBLE.format(facts=known_facts) + "\n" + base


def _render(transcript: list[dict]) -> str:
    # Render the conversation so far for the model (role-labelled).
    return "\n".join(
        f"{'CALLER' if t['role'] == 'user' else 'RECEPTIONIST'}: {t['text']}"
        for t in transcript
    )


def _turn(client, system: str, transcript: list[dict], model: str, retries: int = 4) -> str:
    import time

    convo = _render(transcript) or "(no turns yet — you speak first)"
    prompt = f"{system}\n\nConversation so far:\n{convo}\n\nYour next single spoken turn:"
    last = None
    for attempt in range(retries):
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            return (resp.text or "").strip()
        except Exception as e:  # noqa: BLE001 — Gemini 503, retry
            last = e
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"conversation turn failed after {retries}: {last}")


def simulate_conversation(
    scenario: dict,
    *,
    client=None,
    agent_prompt: str | None = None,
    clinic: str = "ఆరోగ్య",
    max_turns: int = 6,
    model: str = DEFAULT_MODEL,
    agent_first: bool = False,
) -> list[dict]:
    """Run a persona<->agent conversation. ``scenario`` = {persona, goal}.
    Returns the transcript [{role, text}] (role: user=caller, agent=receptionist).

    ``agent_first`` mirrors a real INBOUND call: the agent greets first, then the
    caller speaks. (Default caller-first is for outbound-style sims.)"""
    client = client or _client()
    persona_sys = PERSONA_TEMPLATE.format(**scenario)
    agent_sys = agent_prompt or DEFAULT_AGENT_PROMPT
    if "{clinic}" in agent_sys:  # the real live prompt is already rendered (no placeholder)
        agent_sys = agent_sys.format(clinic=clinic)

    order = ("agent", "user") if agent_first else ("user", "agent")
    transcript: list[dict] = []
    for i in range(max_turns):
        speaker = order[i % 2]
        sys = agent_sys if speaker == "agent" else persona_sys
        text = _turn(client, sys, transcript, model)
        transcript.append({"role": speaker, "text": text})
        if speaker == "user" and (
            any(w in text for w in ("ధన్యవాద", "థాంక్యూ", "థాంక్స్")) or "bye" in text.lower()
        ):
            break
    return transcript
