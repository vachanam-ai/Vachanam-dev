"""Unit tests for agent/prompts/system_prompt.py.

Covers:
  - DPDP s.5 disclosure constants exist and contain the required substrings
  - build_disclosure_utterance() returns all three language variants
  - sanitize_for_tts() does NOT strip Telugu characters (sanitizer bug guard)
  - build_system_prompt() output contains the Step 0 section header
  - build_system_prompt() output contains the Telugu disclosure text

All tests are pure string-match — no LLM call, no DB, no async.
"""


from agent.prompts.system_prompt import (
    DISCLOSURE_ENGLISH,
    DISCLOSURE_HINDI,
    DISCLOSURE_TELUGU,
    DISCLOSURE_UTTERANCE,
    DoctorContext,
    build_disclosure_utterance,
    build_system_prompt,
)
from agent.services.tts_sanitizer import sanitize_for_tts


# ──────────────────────────────────────────────────────────────────────────
# Disclosure constant tests
# ──────────────────────────────────────────────────────────────────────────


def test_telugu_disclosure_contains_ai_assistant():
    """Telugu variant must contain 'AI assistant' substring (spec §9.3)."""
    assert "AI assistant" in DISCLOSURE_TELUGU


def test_telugu_disclosure_mentions_name_and_phone():
    """Telugu variant must mention collecting name ('peru') and phone ('phone number')."""
    assert "peru" in DISCLOSURE_TELUGU
    assert "phone number" in DISCLOSURE_TELUGU


def test_english_disclosure_exact_text():
    """English variant must match spec §9.3 verbatim."""
    expected = "This is an AI assistant. We collect your name and phone for your appointment."
    assert DISCLOSURE_ENGLISH == expected


def test_hindi_disclosure_contains_ai_assistant():
    """Hindi variant must contain 'AI assistant' substring (spec §9.3)."""
    assert "AI assistant" in DISCLOSURE_HINDI


def test_hindi_disclosure_mentions_name_and_phone():
    """Hindi variant must mention collecting name ('naam') and phone ('phone number')."""
    assert "naam" in DISCLOSURE_HINDI
    assert "phone number" in DISCLOSURE_HINDI


def test_disclosure_utterance_contains_all_three_languages():
    """Combined utterance must contain substrings from Telugu, English, and Hindi."""
    assert "AI assistant" in DISCLOSURE_UTTERANCE
    assert "This is an AI assistant" in DISCLOSURE_UTTERANCE
    assert "yeh AI assistant hai" in DISCLOSURE_UTTERANCE


def test_build_disclosure_utterance_returns_combined():
    """build_disclosure_utterance() must return the same string as DISCLOSURE_UTTERANCE."""
    result = build_disclosure_utterance()
    assert result == DISCLOSURE_UTTERANCE


# ──────────────────────────────────────────────────────────────────────────
# sanitize_for_tts does NOT strip Telugu characters (RED FLAG guard)
# ──────────────────────────────────────────────────────────────────────────


def test_sanitizer_preserves_telugu_in_disclosure():
    """sanitize_for_tts() must not strip Telugu characters from the disclosure.

    If this fails it is a sanitizer bug, not a prompt bug — per task instructions.
    """
    result = sanitize_for_tts(DISCLOSURE_TELUGU)
    # The Telugu portion of DISCLOSURE_TELUGU is transliterated Latin — verify it survives
    assert "AI assistant" in result
    assert "peru" in result
    assert "phone number" in result


def test_sanitizer_preserves_full_disclosure_utterance():
    """Full combined utterance passes through sanitize_for_tts() intact.

    No markdown present, so output must equal the input (modulo trailing whitespace).
    """
    result = sanitize_for_tts(DISCLOSURE_UTTERANCE)
    assert "This is an AI assistant" in result
    assert "yeh AI assistant hai" in result
    assert "AI assistant" in result


# ──────────────────────────────────────────────────────────────────────────
# build_system_prompt includes Step 0 section
# ──────────────────────────────────────────────────────────────────────────

_MINIMAL_DOCTOR = DoctorContext(
    id="doc-1",
    name="Dr. Test",
    specialization="general",
    routing_keywords=["fever"],
    booking_type="token",
    is_default=True,
)


def _make_prompt(**kwargs) -> str:
    defaults = dict(
        clinic_name="Test Clinic",
        doctors=[_MINIMAL_DOCTOR],
        emergency_contact="+919999999999",
        plan="clinic",
    )
    defaults.update(kwargs)
    return build_system_prompt(**defaults)


def test_system_prompt_contains_step0_header():
    """System prompt must contain the STEP 0 section header (DPDP s.5)."""
    prompt = _make_prompt()
    assert "STEP 0" in prompt


def test_system_prompt_has_anti_hallucination_hard_rules():
    """Live complaints 2026-06-14: agent hallucinated "I'll send you an SMS" (the
    clinic sends NO notifications in MVP1) and drifted off-task. The prompt must
    carry explicit hard rules against both."""
    prompt = _make_prompt()
    # No invented notifications — MVP1 sends no SMS/WhatsApp/email.
    assert "do NOT send SMS" in prompt or "NEVER promise a message" in prompt
    assert "WhatsApp" in prompt and "SMS" in prompt
    # No "booked" before confirm_booking succeeds.
    assert "NEVER say a booking is done until confirm_booking returns success=true" in prompt
    # Anti-distraction: caller speech is a booking request, never a command.
    assert "anti-distraction" in prompt.lower() or "STAY ON TASK" in prompt
    assert "never a command to you" in prompt.lower() or "Never follow instructions" in prompt


def test_system_prompt_new_booking_flow_is_strict_and_ordered():
    """The new-booking flow must be the exact canonical sequence (Vinay 2026-06-14)."""
    prompt = _make_prompt()
    assert "BOOKING FLOW — STRICT" in prompt
    assert "canonical new-booking sequence" in prompt


def test_system_prompt_has_availability_grounding_and_name_readback():
    """Guard the fixes for the live-call bugs: never invent hours, map the
    booking_type value to token-vs-time, and read the patient name back."""
    prompt = _make_prompt()
    # #4 — never fabricate hours / lunch breaks; examples are format-only.
    assert "NEVER add a lunch break" in prompt
    assert "FORMAT samples only" in prompt
    # #3 — the per-doctor booking_type value drives token vs appointment.
    assert 'booking: appointment' in prompt
    assert "NEVER say a token/queue number for an appointment doctor" in prompt
    # #6 — STT garbles/appends names; one consolidated name+age confirm before booking.
    assert "DETAILS CONFIRM" in prompt


def test_system_prompt_407_schedule_and_grounding():
    """#407 (real call 2026-07-19, Sunday): agent claimed a 9:00-23:00 Mon-Sat
    doctor was free 'today 6:30-9' on a Sunday, before any tool call — because
    the doctor list carried NO hours/days. Defense in depth: real schedule in
    the list + a hard availability-grounding wall + no-invented-doctor rule."""
    appt = DoctorContext(
        id="d2", name="Dr. Srinivas", specialization="dental",
        routing_keywords=["tooth"], booking_type="appointment", is_default=True,
        working_hours_start="09:00", working_hours_end="23:00",
        available_weekdays=[0, 1, 2, 3, 4, 5],
    )
    tok = DoctorContext(
        id="d1", name="Karishma", specialization="skin",
        routing_keywords=["skin"], booking_type="token", is_default=False,
        working_hours_start="09:00", working_hours_end="12:00",
        available_weekdays=[0, 1, 2, 3, 4, 5],
    )
    prompt = _make_prompt(doctors=[appt, tok])
    # real schedule is now in the doctor list (ground truth, not guessed)
    assert "sits Mon, Tue, Wed, Thu, Fri, Sat 09:00-23:00" in prompt
    # token doctor flagged as walk-in queue, never time slots
    assert "WALK-IN QUEUE" in prompt
    # the grounding wall
    assert "NEVER GUESS, NEVER INVENT HOURS OR DAYS" in prompt
    assert "call check_availability for that date" in prompt
    assert "NEVER offer a clock time or time range for them" in prompt  # token
    # no-invented-doctor (torture BOOK3: agent invented a diabetic specialist)
    assert "NEVER invent a doctor" in prompt


def test_system_prompt_407_full_weekdays_render_every_day():
    """A doctor sitting all 7 days renders 'every day', not a 7-item list."""
    d = DoctorContext(
        id="d", name="Dr. All", specialization="general", routing_keywords=["x"],
        booking_type="appointment", is_default=True,
        working_hours_start="08:00", working_hours_end="20:00",
        available_weekdays=[0, 1, 2, 3, 4, 5, 6],
    )
    assert "sits every day 08:00-20:00" in _make_prompt(doctors=[d])


def test_system_prompt_bans_mid_flow_reconfirmation():
    """Live call 2026-07-06: agent asked 'shall I book at X?' at the availability
    step AND again at the end. The prompt must ban the mid-flow mini-confirm on
    both a patient-named free time AND a patient-picked offered time — the only
    yes-question is the step-6 readback."""
    prompt = _make_prompt()
    # Named free time → straight to details, no 'shall I book' mini-confirm.
    assert "go STRAIGHT to PATIENT DETAILS" in prompt
    assert 'shall i book' in prompt.lower()
    assert "ONLY yes-question in the whole call is the step-6 readback" in prompt
    # Picking/accepting an offered time is itself the decision.
    assert "PATIENT PICKS / ACCEPTS an offered time" in prompt
    assert "acceptance IS the" in prompt  # '...IS the decision' wraps across a line
    # Timetable dump reserved for the no-time-given case only.
    assert "never dump a timetable when the patient already named" in prompt


def test_system_prompt_surfaces_existing_booking_upfront():
    """#279: when check_availability returns ALREADY_BOOKED, the agent must tell
    the caller immediately and stop — not walk the whole flow first."""
    prompt = _make_prompt()
    assert "ALREADY_BOOKED" in prompt
    assert "EXISTING BOOKING FIRST" in prompt
    assert "different_person=true" in prompt


def test_system_prompt_allows_reschedule_anytime_including_after_booking():
    """#284 (Vinay 2026-07-07): a caller may change/reschedule as many times as
    they like, even immediately after booking — never refuse or claim a limit."""
    prompt = _make_prompt()
    assert "reschedule as many times as they like" in prompt
    assert "immediately after booking" in prompt


def test_system_prompt_single_confirmation_no_stacked_yes_questions():
    """FIXLOG #271 (live call 2026-07-05: agent asked 3 yes-questions before one
    booking, and re-asked 'shall I go ahead?' after the caller already said yes
    to a reschedule). Exactly ONE confirmation question per booking; reschedule
    never re-asks after a yes."""
    prompt = _make_prompt()
    assert "THE ONE CONFIRMATION" in prompt
    # The standalone details/phone confirm questions are explicitly banned
    # (the phrases still appear once — as quoted don't-say examples).
    assert 'Do NOT ask "ఈ డిటైల్స్ కన్ఫర్మ్ చేయమంటారా?"' in prompt
    assert "stacking confirmation questions" in prompt
    # Readback carries the number implicitly so the caller can object.
    assert "ఇదే నంబర్‌కి" in prompt
    # Reschedule: one yes-question max, no post-availability re-ask.
    assert "ONE yes-question maximum" in prompt
    # Post-success close repeats no numbers (time was in the readback).
    assert "NO numbers" in prompt


def test_system_prompt_contains_greeting_with_ai_disclosure():
    """STEP 0 embeds the spoken greeting; the AI self-identification is the DPDP
    s.5 disclosure that must always be in it. (2026-06-25: disclosure now in Telugu
    script 'ఏఐ అసిస్టెంట్' per Vinay's reworded greeting.)"""
    prompt = _make_prompt()
    assert "ఏఐ అసిస్టెంట్" in prompt  # AI self-identification (DPDP disclosure)


def test_system_prompt_moves_collection_notice_to_point_of_collection():
    """Name/phone notice now spoken when collecting details, not in greeting."""
    prompt = _make_prompt()
    assert "అపాయింట్‌మెంట్ కోసం" in prompt


def test_system_prompt_instructs_llm_not_to_repeat_disclosure():
    """LLM must be told NOT to repeat the greeting — it was already spoken."""
    prompt = _make_prompt()
    assert "Do NOT repeat it" in prompt


def test_system_prompt_contains_vachanam_identity():
    """Prompt carries the agent identity line. (2026-06-25: the language directive
    — 'match the caller' — now legitimately leads the prompt, so the identity is
    present but no longer strictly first.)"""
    prompt = _make_prompt()
    assert "You are Vachanam" in prompt


def test_system_prompt_step0_precedes_booking_flow():
    """STEP 0 section must appear before BOOKING FLOW in the prompt."""
    prompt = _make_prompt()
    step0_pos = prompt.index("STEP 0")
    booking_pos = prompt.index("BOOKING FLOW")
    assert step0_pos < booking_pos


def test_system_prompt_solo_cap_instruction_present():
    """Solo plan cap instruction still present when plan=solo."""
    prompt = _make_prompt(plan="solo")
    assert "CALL TIME LIMIT" in prompt


def test_system_prompt_rebook_instruction_present():
    """Rebook instruction still present when is_rebook=True."""
    prompt = _make_prompt(is_rebook=True, cancelled_date="2026-06-01")
    assert "REBOOKING" in prompt


# ──────────────────────────────────────────────────────────────────────────
# Task 4: Recording disclosure (gated) + human-transfer trigger (unconditional)
# ──────────────────────────────────────────────────────────────────────────


def test_step_0_includes_recording_notice_when_enabled(monkeypatch):
    """When recording_enabled=True, Step 0 must include the Telugu recording sentence."""
    monkeypatch.setattr("backend.config.settings.recording_enabled", True)
    prompt = build_system_prompt(
        clinic_name="Test Clinic",
        doctors=[],
        emergency_contact="+919000000000",
        plan="clinic",
    )
    assert "రికార్డ్" in prompt


def test_step_0_omits_recording_notice_when_disabled(monkeypatch):
    """When recording_enabled=False (default), the recording sentence must be absent."""
    monkeypatch.setattr("backend.config.settings.recording_enabled", False)
    prompt = build_system_prompt(
        clinic_name="Test Clinic",
        doctors=[],
        emergency_contact="+919000000000",
        plan="clinic",
    )
    assert "రికార్డ్" not in prompt


def test_prompt_includes_transfer_trigger_instructions():
    """Prompt body must instruct LLM to call request_human_transfer on explicit ask
    or persistent pressure; must NOT list medical keywords as triggers."""
    prompt = build_system_prompt(
        clinic_name="Test Clinic",
        doctors=[],
        emergency_contact="+919000000000",
        plan="clinic",
    )
    assert "request_human_transfer" in prompt
    assert "explicit_ask" in prompt
    assert "persistent" in prompt  # #350 renamed persistent_pressure → persistent
    # Must NOT instruct keyword-based transfer — LLM judges intent, not keywords
    assert "chest pain" not in prompt.lower()
    assert "heart attack" not in prompt.lower()


# ──────────────────────────────────────────────────────────────────────────
# FIXLOG #139 — caller robustness: angry / abusive / shy / rambling / wrong-
# number / clueless-referral callers, plus grounded clinic-address answers.
# ──────────────────────────────────────────────────────────────────────────


def test_system_prompt_has_difficult_caller_handling_section():
    """The prompt must coach the agent through the full range of real callers —
    not just the cooperative happy path (Vinay 2026-06-17)."""
    prompt = _make_prompt()
    assert "HANDLING DIFFERENT CALLERS" in prompt
    # Each persona the agent must cope with is explicitly named.
    for token in ("ANGRY", "ABUSE", "SHY", "RAMBLING", "WRONG NUMBER", "DOESN'T KNOW THE CLINIC"):
        assert token in prompt, f"missing caller case: {token}"


def test_system_prompt_never_retaliates_or_matches_anger():
    """De-escalation discipline: the agent stays warm, never mirrors abuse."""
    prompt = _make_prompt()
    assert "Never match anger" in prompt
    assert "Never insult back" in prompt
    # Sustained pure-abuse with no booking intent → polite close, not retaliation.
    assert "end_call" in prompt


def test_system_prompt_address_grounded_when_provided():
    """A real address is offered to the agent (so reference callers can be told
    where the clinic is) but only to be spoken when asked."""
    prompt = _make_prompt(clinic_address="12-3, MG Road, Hyderabad 500001")
    assert "12-3, MG Road, Hyderabad 500001" in prompt
    assert "CLINIC ADDRESS" in prompt


def test_system_prompt_address_not_invented_when_absent():
    """No address set → the agent is explicitly forbidden from inventing one
    (HARD RULE 2 grounding), and the real address string is obviously absent."""
    prompt = _make_prompt(clinic_address=None)
    assert "CLINIC ADDRESS" in prompt
    assert "do NOT invent an address" in prompt


def test_system_prompt_exploratory_ask_is_not_a_booking_command():
    """#287 (torture round 2): "what if I come Thursday at 12?" is an
    availability QUESTION — answer + offer, never book on a hypothetical."""
    prompt = _make_prompt()
    assert "EXPLORATORY ASK" in prompt
    assert "Booking on a hypothetical is a serious" in prompt


def test_system_prompt_audio_chaos_rules_pinned():
    """#287: the audio-reality conduct rules (long pauses/fragments, background
    noise, multiple voices, silence, language gap, no tools on fragments) must
    never be edited away — they are the phone-line survival kit."""
    prompt = _make_prompt()
    assert "INCOMPLETE UTTERANCES" in prompt          # pauses / trailing off
    assert "NO TOOLS ON FRAGMENTS" in prompt          # half-sentence tool calls
    assert "BACKGROUND NOISE / SEVERAL VOICES" in prompt
    assert "SILENT CALLER" in prompt
    assert "UNINTELLIGIBLE STREAK" in prompt
    assert "FAILURE RECOVERY" in prompt               # never freeze, never loop


def test_system_prompt_conversational_humanity_rules():
    """#290 (live 2026-07-08): the call felt mechanical — agent repeated a
    sentence VERBATIM (turns 7 vs 12), burned whole turns on bare "అర్థమైంది"
    acknowledgements (turns 5, 17), and never recovered a barge-in-cut thought
    (turns 19/22/42). These three anti-mechanical rules must stay pinned."""
    prompt = _make_prompt()
    assert "NEVER REPEAT A SENTENCE VERBATIM" in prompt
    assert "REPHRASE it shorter" in prompt
    assert "AN ACKNOWLEDGEMENT ALONE IS A WASTED TURN" in prompt
    assert "MOVE the call forward" in prompt
    assert "IF THE CALLER INTERRUPTS YOU" in prompt
    assert "do not" in prompt and "resume or re-read" in prompt


def test_mic_gate_wired_around_welcome_clip():
    """#289 (live 2026-07-08, "intros colliding"): session STT goes live while
    the uninterruptible greeting clip still plays; an early 'hello' produced a
    spoken reply OVER the clip. The entrypoint must gate session audio input
    (set_audio_enabled False -> await clip -> True) around the welcome await."""
    import inspect
    import agent.livekit_minimal.agent as ag

    src = inspect.getsource(ag)
    gate_off = src.find("session.input.set_audio_enabled(False)")
    clip_await = src.find("_pre_greeted = bool(await _welcome_task)")
    gate_on = src.find("session.input.set_audio_enabled(True)")
    assert gate_off != -1, "mic gate disable missing"
    assert gate_on != -1, "mic gate re-enable missing"
    assert gate_off < clip_await < gate_on, "gate must wrap the clip await"


def test_system_prompt_performance_prosody_rules():
    """#292 (Vinay 2026-07-08): 'add life to voice' — the LLM must WRITE the
    performance (punctuation = prosody for lightning_v3.1's semantic pauses),
    react like a human first, and vary sentence melody. Sanitizer is verified
    to preserve ... ! ? , so this markup reaches the TTS intact."""
    prompt = _make_prompt()
    assert "WRITE THE PERFORMANCE, NOT A TRANSCRIPT" in prompt
    assert "thinking pause" in prompt
    # #438 (Vinay 2026-07-21: "why ok endi/avunu/alagey/ayyo unnecessarily"):
    # reaction words are gated to REAL feeling, and replies answer directly
    # instead of opening every turn with a filler ack.
    assert "REACT ONLY WHEN THERE IS REAL FEELING" in prompt
    assert "ANSWER DIRECTLY" in prompt
    assert "must NOT appear on every turn" in prompt
    assert "MELODY" in prompt


def test_phone_english_hard_rule_and_no_mechanics_leak():
    """#295 (live 2026-07-08): agent read the phone number in Telugu and told the
    patient 'you have to say different person' (internal mechanic leaked). Two
    HARD RULES must be pinned: phones are always English digits (Telugu only on
    explicit request), and internal tool params are never voiced."""
    prompt = _make_prompt()
    # HARD RULE 7 — phones written as digits; #408 converter speaks them in
    # English one-by-one (the old "Telugu on explicit request" escape is GONE:
    # Vinay 2026-07-19 — "never in any language", no exceptions).
    assert "PHONE NUMBERS: write the plain digits" in prompt
    assert "one digit at a time in ENGLISH" in prompt
    assert "No exceptions" in prompt
    # HARD RULE 8 — never voice mechanics; different_person handled silently
    assert "NEVER voice your own internal mechanics" in prompt
    assert "different person" in prompt.lower()
    assert "SILENTLY pass different_person=true" in prompt
    assert "never explain the plumbing" in prompt
    # auto-tag the moment they signal it's for someone else — no re-ask
    assert "THE MOMENT the patient signals it is for someone else" in prompt
    assert "set different_person=true and REMEMBER it" in prompt
    assert "Never ask them to confirm it's a different person" in prompt
    # #296: friend booking must pass booking_for_other + never surface caller's own
    assert "pass booking_for_other=true to check_availability" in prompt
    assert "that is the caller's" in prompt.lower() or "it is the caller" in prompt.lower()
    # phone native-number-words ban stays pinned (#408)
    assert "NEVER write a phone number in Telugu/native number" in prompt


def test_system_prompt_lead_in_rule():
    """Vinay 2026-07-21: answers start with substance; acknowledgement words
    are occasional warmth, never a repetitive opener on every turn."""
    prompt = _make_prompt()
    compact = " ".join(prompt.split())
    assert "ANSWER DIRECTLY — DO NOT OPEN EVERY REPLY WITH A FILLER WORD" in compact
    assert "roughly one reply in four" in compact
    assert "NEVER two replies in a row" in compact
    assert "Most replies must BEGIN WITH THE SUBSTANCE" in compact
    # verbose filler sentences stay banned — the cached checking-filler covers tools
    assert "ఒక్క నిమిషం" in prompt


def test_no_availability_claims_without_tool_result_402():
    """#402 (real call 2026-07-18, Hindi): agent said '1:30 not available'
    from its own guess while reschedule_booking was RUNNING; the tool then
    succeeded and it contradicted itself ('why faking?' — Vinay). Availability
    words, positive or NEGATIVE, only from a held tool result."""
    prompt = _make_prompt()
    assert "THE SAME RULE CUTS THE OTHER WAY" in prompt
    assert "NOT available either" in prompt
    assert "उपलब्ध नहीं है" in prompt  # the real failure, named


def test_hello_never_interrupts_403():
    """Vinay 2026-07-18: "Hello should never interrupt the conversation.
    Always ignore hello." Prompt: bare hello = line check, continue in place."""
    prompt = _make_prompt()
    assert "HELLO IS NEVER A REQUEST" in prompt
    assert "CHECKING THE LINE" in prompt


def test_offer_more_help_before_closing_428():
    """The help offer is available once, but never repeated after every answer."""
    prompt = _make_prompt()
    assert "OFFER MORE HELP BEFORE CLOSING" in prompt
    assert "ఇంకేమైనా సహాయం కావాలా" in prompt          # Vinay's dictated line
    assert "Do you need any other help?" in prompt     # English gloss
    assert "optional once per call, never automatic or repetitive" in prompt


def test_say_it_once_no_reprompting_428():
    """Vinay 2026-07-20: "prompting multiple times about appointment / the
    rescheduling ... repetition should not be happening. enforce it." The
    prompt must carry an explicit no-re-prompt / no-re-confirm rule that names
    the reschedule loop."""
    prompt = _make_prompt()
    assert "SAY IT ONCE" in prompt
    assert "NO RE-PROMPTING" in prompt
    # Names the reschedule case specifically and the capture-once principle.
    assert "RESCHEDULE" in prompt and "ask for the new" in prompt
    assert "it is CAPTURED" in prompt
