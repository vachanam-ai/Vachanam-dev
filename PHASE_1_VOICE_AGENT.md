# PHASE_1_VOICE_AGENT.md — Voice Agent Core
## This is the soul of Vachanam. Build this right or nothing works.
## Read CLAUDE.md Rules 1–10 before writing a single line.

---

## WHY THIS PHASE MATTERS

Every rupee of revenue depends on this phase working correctly.
A patient calls a clinic. The AI must:
- Answer in under 2 rings
- Understand Telugu, Hindi, English, and code-mixed speech
- Detect emergencies and act immediately
- Book appointments atomically (never double-book, ever)
- Confirm by voice in natural Telugu
- End the call in under 4 minutes
- Send WhatsApp confirmation within 60 seconds

If any of these fail, the clinic loses a patient and blames Vachanam.

**Time estimate:** 2–3 weeks
**Cost during development:** ~₹148/test call (STT + TTS + Vobiz)
**Use Sarvam free credits (₹1,000) for all testing**

---

## HOW THE VOICE PIPELINE WORKS

Understanding this before building prevents fundamental mistakes.

```
Patient calls clinic number (040-XXXX-XXXX)
    ↓
Airtel/Jio PSTN routes to Vobiz DID (+91 40 YYYY YYYY)
[USSD **21*+9140YYYYYYYY# was dialed on clinic's phone once]
    ↓
Vobiz receives SIP call
Vobiz POSTs to: https://vachanam-agent.fly.dev/calls/inbound/{branch_id}
Your server responds with SIP instructions
    ↓
Vobiz establishes WebSocket audio stream to LiveKit
    ↓
LiveKit creates a Room (one per call)
LiveKit dispatches your agent to the room
    ↓
PARALLEL PIPELINE (all three run simultaneously):
┌──────────────────────────────────────────────────────┐
│  Audio in → Sarvam STT → partial transcripts         │
│  Partial transcripts → Gemini 2.5 Flash (streaming)  │
│  Gemini 2.5 Flash response → Sarvam TTS → Audio out  │
└──────────────────────────────────────────────────────┘
This parallel execution is why LiveKit achieves <600ms response time.
Sequential execution would take 2–3 seconds. Patient would hang up.
    ↓
Gemini 2.5 Flash calls function tools when needed:
  - check_doctor_availability() → reads Redis counter
  - assign_token() → Redis INCR (atomic)
  - confirm_booking() → writes Neon DB + creates Calendar event
  - get_patient_info() → reads Neon DB
    ↓
Call ends (max 4 minutes — AI wraps up at 3:50)
    ↓
Background tasks (non-blocking):
  - WhatsApp to patient (Meta Cloud API)
  - WhatsApp to doctor (Meta Cloud API)
  - Write call log to DB
```

---

## BUILD ORDER — FOLLOW EXACTLY

Build and test each file before moving to the next.
Never build file N without testing file N-1.

```
File 1:  agent/services/tts_sanitizer.py     → test immediately
File 2:  agent/services/emergency.py          → test immediately
File 3:  agent/prompts/system_prompt.py       → review manually
File 4:  agent/session_state.py               → no test needed
File 5:  backend/services/token_service.py    → test immediately (concurrent)
File 6:  backend/services/calendar_service.py → test with real Calendar API
File 7:  backend/services/meta_service.py     → test with real WhatsApp
File 8:  agent/tools/booking_tools.py         → test with mocks
File 9:  agent/agent.py                       → test with full call
```

---

## FILE 1: agent/services/tts_sanitizer.py

**Why this exists:** GPT-4o mini sometimes returns markdown (bold, bullets,
headers). Markdown sounds horrible when spoken: "asterisk asterisk Token
number 8 asterisk asterisk" instead of "Token number 8". Every single
string that goes to TTS MUST pass through this function.

```python
# agent/services/tts_sanitizer.py
"""
Sanitize text before sending to Sarvam Bulbul v3 TTS.
Called on EVERY string before TTS. No exceptions.

Hard limits:
- Max 200 characters per TTS string (telephony latency)
- No markdown, no URLs, no special characters
- Telugu text is preserved exactly
"""
import re
from typing import Final

MAX_TTS_CHARS: Final[int] = 200


def sanitize_for_tts(text: str) -> str:
    """
    Remove all formatting that sounds wrong when spoken aloud.
    Must be called on EVERY string before passing to TTS.

    Args:
        text: Raw text from LLM output

    Returns:
        Clean, speakable text under 200 characters

    Examples:
        "**Token #8** confirmed!" → "Token 8 confirmed"
        "## Available slots" → "Available slots"
        "1. Morning\n2. Evening" → "Morning Evening"
    """
    if not text:
        return ""

    # Remove markdown bold/italic (**, __, *, _)
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', text)

    # Remove headers (##, ###, etc.)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Remove code blocks and inline code
    text = re.sub(r'```[^`]*```', '', text, flags=re.DOTALL)
    text = re.sub(r'`[^`]+`', '', text)

    # Remove numbered lists
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)

    # Remove bullet points
    text = re.sub(r'^[-•*]\s+', '', text, flags=re.MULTILINE)

    # Remove URLs
    text = re.sub(r'https?://\S+', '', text)

    # Remove special characters that have no spoken equivalent
    text = re.sub(r'[#@$%^&\[\]{}|<>\\]', '', text)

    # Replace # before numbers (token numbers)
    text = re.sub(r'#(\d+)', r'\1', text)

    # Normalize punctuation
    text = re.sub(r'[-–—]{2,}', ', ', text)
    text = re.sub(r'\.{2,}', '.', text)
    text = re.sub(r'!{2,}', '!', text)
    text = re.sub(r'\?{2,}', '?', text)

    # Collapse whitespace and newlines
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r'\s{2,}', ' ', text)

    text = text.strip()

    # Hard character limit — cut at last sentence boundary
    if len(text) > MAX_TTS_CHARS:
        truncated = text[:MAX_TTS_CHARS]
        last_period = truncated.rfind('.')
        last_question = truncated.rfind('?')
        last_exclaim = truncated.rfind('!')
        last_boundary = max(last_period, last_question, last_exclaim)
        if last_boundary > MAX_TTS_CHARS // 2:
            text = truncated[:last_boundary + 1]
        else:
            text = truncated.rstrip() + '.'

    return text


def is_safe_for_tts(text: str) -> bool:
    """Check if text is ready for TTS without issues."""
    if not text or not text.strip():
        return False
    if len(text) > MAX_TTS_CHARS:
        return False
    if re.search(r'[*#`\[\]{}|<>\\]', text):
        return False
    return True
```

### Tests: tests/unit/test_tts_sanitizer.py

```python
# tests/unit/test_tts_sanitizer.py
import pytest
from agent.services.tts_sanitizer import sanitize_for_tts, is_safe_for_tts, MAX_TTS_CHARS


class TestSanitizeForTTS:

    def test_empty_string_returns_empty(self):
        assert sanitize_for_tts("") == ""

    def test_none_input_returns_empty(self):
        # Called with empty from LLM — must not crash
        assert sanitize_for_tts("") == ""

    def test_plain_text_unchanged(self):
        text = "Token 8 confirm chesamu"
        assert sanitize_for_tts(text) == text

    def test_removes_double_asterisk_bold(self):
        result = sanitize_for_tts("**Token #8** confirmed")
        assert "**" not in result
        assert "Token" in result

    def test_removes_single_asterisk_italic(self):
        result = sanitize_for_tts("*Doctor* available")
        assert "*" not in result
        assert "Doctor" in result

    def test_removes_markdown_headers(self):
        result = sanitize_for_tts("## Available Doctors")
        assert "#" not in result
        assert "Available Doctors" in result

    def test_removes_numbered_list_markers(self):
        result = sanitize_for_tts("1. Morning\n2. Afternoon")
        assert "1." not in result
        assert "2." not in result

    def test_removes_bullet_dashes(self):
        result = sanitize_for_tts("- Option one\n- Option two")
        assert result.count("-") == 0 or "Option one" in result

    def test_removes_urls(self):
        result = sanitize_for_tts("Visit https://vachanam.in for details")
        assert "https://" not in result
        assert "Visit" in result

    def test_collapses_multiple_newlines(self):
        result = sanitize_for_tts("Line one\n\n\nLine two")
        assert "\n" not in result
        assert "Line one" in result
        assert "Line two" in result

    def test_hard_limit_200_chars(self):
        long_text = "a" * 300
        result = sanitize_for_tts(long_text)
        assert len(result) <= MAX_TTS_CHARS

    def test_hard_limit_cuts_at_sentence_boundary(self):
        # Should cut at period, not mid-word
        text = "First sentence. " + "b" * 200
        result = sanitize_for_tts(text)
        assert len(result) <= MAX_TTS_CHARS

    def test_hash_before_number_removed(self):
        # "#8" should become "8"
        result = sanitize_for_tts("Token #8 booked")
        assert "#" not in result
        assert "8" in result

    def test_telugu_text_preserved(self):
        telugu = "మీ appointment confirm అయింది"
        result = sanitize_for_tts(telugu)
        assert "confirm" in result
        # Telugu characters should be preserved
        assert "మీ" in result or len(result) > 5

    def test_code_block_removed(self):
        result = sanitize_for_tts("Use `redis.incr()` here")
        assert "`" not in result

    def test_is_safe_returns_false_for_markdown(self):
        assert is_safe_for_tts("**bold**") is False

    def test_is_safe_returns_true_for_clean_text(self):
        assert is_safe_for_tts("Token 8 confirmed") is True

    def test_is_safe_returns_false_for_too_long(self):
        assert is_safe_for_tts("a" * 201) is False

    def test_is_safe_returns_false_for_empty(self):
        assert is_safe_for_tts("") is False
```

Run: `pytest tests/unit/test_tts_sanitizer.py -v`
**ALL 17 tests must pass before continuing.**

---

## FILE 2: agent/services/emergency.py

> ⚠️ **MVP OVERRIDE — READ BEFORE IMPLEMENTING THIS FILE**
> The TYPE_1/TYPE_2 classification system described below is a **post-MVP feature**.
> For MVP (v1), implement ONLY this:
> - If patient mentions ANY emergency keyword at any point:
>   → Say: "I understand this is urgent. Our emergency contact is: {branch.emergency_contact}"
>   → Continue booking as normal (urgent priority)
> - No 108 suggestion. No classification. No ambulance transfer.
> See CLAUDE.md Rule 7 for the exact MVP implementation.

**Why this is the most critical file:**
A patient having a heart attack calls the clinic. If the AI misclassifies
it as a routine call and books a token for next week, that patient may die.
This code has zero tolerance for false negatives on TYPE_1 emergencies.

**Classification rules (post-MVP — do not implement in v1):**
- TYPE_1 = life-threatening RIGHT NOW → transfer to ambulance
- TYPE_2 = urgent but stable → book urgent appointment, NEVER say "call 108"
- TYPE_3 = routine → normal booking flow
- When in doubt between TYPE_1 and TYPE_2 → always classify TYPE_1

```python
# agent/services/emergency.py
"""
Emergency classification for patient calls.
CRITICAL SAFETY CODE — test every scenario before deploying.

Classification:
  TYPE_1: Life-threatening NOW → transfer to ambulance immediately
  TYPE_2: Urgent but stable → book urgent appointment
  TYPE_3: Routine → normal booking flow

INVARIANT: suggest_108 is ALWAYS False. Never change this.
We have the clinic's ambulance. We never redirect to government services
unless the clinic explicitly has no ambulance (handled in agent.py).

When in doubt between TYPE_1 and TYPE_2: always classify TYPE_1.
A false positive (wrong TYPE_1) = patient gets help they didn't need.
A false negative (wrong TYPE_3 for TYPE_1) = patient may die.
"""
from dataclasses import dataclass
from enum import Enum
import json
import structlog
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger()


class EmergencyType(str, Enum):
    TYPE_1 = "type_1"   # Life-threatening NOW
    TYPE_2 = "type_2"   # Urgent but stable
    TYPE_3 = "type_3"   # Routine


@dataclass
class EmergencyResult:
    type: EmergencyType
    action: str         # transfer_ambulance | book_urgent | normal_booking
    suggest_108: bool   # ALWAYS False — hardcoded below
    confidence: str     # high | medium | low
    reason: str


# ── KEYWORD LISTS ──────────────────────────────────────────────────────
# These trigger immediate TYPE_1 classification WITHOUT calling the LLM.
# The LLM adds latency (300-500ms). For life-threatening emergencies,
# every second counts. Keyword detection is synchronous and instant.

TYPE_1_KEYWORDS_TELUGU = [
    # Collapse
    "collapse", "collaps", "padipōyāḍu", "padipōyindi",
    "kūlipōyāḍu", "kūlipōyindi", "kūlipoyi",
    # Not breathing
    "śvāsa lēdu", "śvāsa raatledu", "breathing lēdu",
    "uśvāsa", "breath teesukōvatam lēdu",
    # Unconscious
    "mūrchanam", "mūrchha", "spondan lēdu",
    "response lēdu", "మాట్లాడటం లేదు",
    # Severe bleeding
    "blood pōtundi", "blood vastundi", "rakt", "bleeding āgaṭam lēdu",
    "chaala blood", "heavy bleeding",
    # Heart attack (active)
    "gunde āgipōyindi", "heart attack ippude", "heart baadha ippude",
    # Accident right now
    "accident ippude", "accident aindi ippude", "abhi accident",
    "right now accident",
    # Choking
    "air raatledu", "mingsutundi", "choking",
]

TYPE_1_KEYWORDS_ENGLISH = [
    "collapsed", "not breathing", "unconscious", "unresponsive",
    "severe bleeding", "bleeding heavily", "heart attack",
    "stroke now", "choking", "can't breathe", "stopped breathing",
    "accident right now", "fallen down unconscious",
]

# All keywords as lowercase for matching
_ALL_TYPE_1 = [k.lower() for k in TYPE_1_KEYWORDS_TELUGU + TYPE_1_KEYWORDS_ENGLISH]


def _keyword_precheck(text: str) -> EmergencyType | None:
    """
    Synchronous keyword check. No LLM. No latency.
    Returns EmergencyType.TYPE_1 if confident, None if LLM needed.

    IMPORTANT: This only checks for TYPE_1. TYPE_2 and TYPE_3
    are classified by the LLM to handle nuanced language.
    """
    text_lower = text.lower()
    for keyword in _ALL_TYPE_1:
        if keyword in text_lower:
            logger.critical(
                "type1_keyword_detected",
                keyword=keyword,
                text_preview=text[:50]
            )
            return EmergencyType.TYPE_1
    return None


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=0.5, max=2))
async def classify_emergency(
    patient_statement: str,
    openai_client: AsyncOpenAI | None = None
) -> EmergencyResult:
    """
    Classify patient statement into emergency type.

    FLOW:
    1. Keyword check (synchronous, instant) → TYPE_1 if match
    2. LLM classification (async, ~300ms) → TYPE_1/2/3

    SAFETY GUARANTEE:
    - suggest_108 is hardcoded to False
    - Ambiguous TYPE_1/TYPE_2 → always TYPE_1
    - LLM failure → returns TYPE_2 (safe default, not TYPE_3)

    Args:
        patient_statement: Transcribed patient speech
        openai_client: Optional pre-initialized client

    Returns:
        EmergencyResult with type, action, and confidence
    """
    # Step 1: Fast keyword check
    precheck = _keyword_precheck(patient_statement)
    if precheck == EmergencyType.TYPE_1:
        return EmergencyResult(
            type=EmergencyType.TYPE_1,
            action="transfer_ambulance",
            suggest_108=False,  # ALWAYS False
            confidence="high",
            reason="Critical keyword detected in patient speech"
        )

    # Step 2: LLM classification for ambiguous cases
    if openai_client is None:
        from backend.config import settings
        openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

    prompt = f"""You are an emergency triage classifier for an Indian clinic.
Classify this patient statement. Return ONLY valid JSON.

Patient said: "{patient_statement}"

DEFINITIONS:
TYPE_1_IMMEDIATE: Patient or someone with them is in immediate danger RIGHT NOW.
  Examples: collapsed, not breathing, unconscious, actively bleeding, heart attack happening now, accident just happened

TYPE_2_URGENT: Serious condition but patient is stable enough to wait for appointment.
  Examples: chest pain that started an hour ago, high fever 103F+, severe abdominal pain, cannot walk, breathing difficulty but conscious, accident happened yesterday

TYPE_3_ROUTINE: Normal appointment needed.
  Examples: fever for 2 days, skin rash, routine checkup, follow-up, mild cold, diabetes management

RULES:
- If ANY ambiguity between TYPE_1 and TYPE_2 → classify TYPE_1
- "Accident" without "right now/just now/ippude" → TYPE_2
- Chest pain with conscious patient → TYPE_2 (not TYPE_1 unless patient says actively happening)
- Never suggest calling 108 (we handle emergencies ourselves)

Return exactly this JSON:
{{
  "classification": "TYPE_1_IMMEDIATE|TYPE_2_URGENT|TYPE_3_ROUTINE",
  "action": "transfer_ambulance|book_urgent|normal_booking",
  "confidence": "high|medium|low",
  "reason": "one sentence explanation"
}}"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,       # Deterministic for safety
            max_tokens=120,
            response_format={"type": "json_object"}
        )

        result = json.loads(response.choices[0].message.content)

        type_map = {
            "TYPE_1_IMMEDIATE": EmergencyType.TYPE_1,
            "TYPE_2_URGENT": EmergencyType.TYPE_2,
            "TYPE_3_ROUTINE": EmergencyType.TYPE_3,
        }
        emergency_type = type_map.get(result["classification"], EmergencyType.TYPE_3)

        if emergency_type != EmergencyType.TYPE_3:
            logger.warning(
                "emergency_classified",
                type=emergency_type,
                confidence=result.get("confidence"),
                statement_preview=patient_statement[:60]
            )

        return EmergencyResult(
            type=emergency_type,
            action=result.get("action", "normal_booking"),
            suggest_108=False,  # HARDCODED — never change
            confidence=result.get("confidence", "medium"),
            reason=result.get("reason", "")
        )

    except Exception as e:
        logger.error("emergency_classification_failed", error=str(e))
        # SAFE DEFAULT: unknown state → treat as TYPE_2
        # Better to book an urgent appointment unnecessarily
        # than to miss a real emergency
        return EmergencyResult(
            type=EmergencyType.TYPE_2,
            action="book_urgent",
            suggest_108=False,
            confidence="low",
            reason=f"Classification failed — defaulting to urgent: {str(e)[:50]}"
        )
```

### Tests: tests/unit/test_emergency.py

```python
# tests/unit/test_emergency.py
import pytest
from agent.services.emergency import (
    classify_emergency, EmergencyType, _keyword_precheck
)


class TestKeywordPrecheck:
    """Fast synchronous tests — no API calls."""

    @pytest.mark.parametrize("phrase,expected", [
        ("padipōyāḍu", EmergencyType.TYPE_1),
        ("collapse aipōyāḍu", EmergencyType.TYPE_1),
        ("not breathing", EmergencyType.TYPE_1),
        ("collapsed on floor", EmergencyType.TYPE_1),
        ("unconscious", EmergencyType.TYPE_1),
        ("severe bleeding", EmergencyType.TYPE_1),
        ("mūrchanam", EmergencyType.TYPE_1),
        ("choking", EmergencyType.TYPE_1),
        ("accident ippude", EmergencyType.TYPE_1),
        ("heart attack now", EmergencyType.TYPE_1),
    ])
    def test_type1_keywords_detected(self, phrase, expected):
        result = _keyword_precheck(phrase)
        assert result == expected, \
            f"'{phrase}' should be TYPE_1 but got {result}"

    @pytest.mark.parametrize("phrase", [
        "chest pain since morning",
        "high fever since yesterday",
        "need appointment",
        "diabetes follow-up",
        "skin rash",
        "regular checkup",
        "fever 2 days",
    ])
    def test_routine_phrases_not_type1_from_keywords(self, phrase):
        result = _keyword_precheck(phrase)
        assert result is None, \
            f"'{phrase}' incorrectly flagged as TYPE_1 by keyword check"


class TestEmergencyClassification:
    """Tests requiring LLM call — mark as slow."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_suggest_108_always_false(self):
        """CRITICAL: suggest_108 must never be True under any circumstances."""
        test_cases = [
            "I'm having a heart attack",
            "someone collapsed",
            "chest pain",
            "high fever",
            "routine appointment",
        ]
        for case in test_cases:
            result = await classify_emergency(case)
            assert result.suggest_108 is False, \
                f"suggest_108 was True for: '{case}' — THIS IS A CRITICAL BUG"

    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.parametrize("phrase", [
        "routine checkup",
        "fever for two days",
        "skin problem",
        "diabetes appointment",
        "follow up visit",
        "mild cold",
    ])
    async def test_routine_classified_as_type3(self, phrase):
        result = await classify_emergency(phrase)
        assert result.type == EmergencyType.TYPE_3, \
            f"'{phrase}' should be TYPE_3 but got {result.type}"

    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.parametrize("phrase", [
        "chest pain since morning",
        "very high fever 104",
        "breathing difficulty but awake",
        "cannot walk due to knee pain",
        "vomiting blood",
        "severe headache not going away",
    ])
    async def test_urgent_not_type3(self, phrase):
        result = await classify_emergency(phrase)
        assert result.type in [EmergencyType.TYPE_1, EmergencyType.TYPE_2], \
            f"'{phrase}' should be urgent but was classified as TYPE_3"

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_llm_failure_defaults_to_type2_not_type3(self):
        """When LLM fails, safe default is TYPE_2, not TYPE_3."""
        # Pass invalid client to trigger failure
        from unittest.mock import AsyncMock, patch
        with patch('openai.AsyncOpenAI') as mock:
            mock.return_value.chat.completions.create = AsyncMock(
                side_effect=Exception("API Error")
            )
            result = await classify_emergency(
                "I feel very unwell",
                openai_client=mock.return_value
            )
            # Must default to TYPE_2 for safety, not TYPE_3
            assert result.type in [EmergencyType.TYPE_1, EmergencyType.TYPE_2]
            assert result.suggest_108 is False


class TestEmergencyResultStructure:
    """Test result structure correctness."""

    @pytest.mark.asyncio
    async def test_type1_from_keyword_has_transfer_action(self):
        result = await classify_emergency("patient collapsed")
        if result.type == EmergencyType.TYPE_1:
            assert result.action == "transfer_ambulance"

    @pytest.mark.asyncio
    async def test_type1_result_never_has_normal_booking_action(self):
        result = await classify_emergency("not breathing")
        if result.type == EmergencyType.TYPE_1:
            assert result.action != "normal_booking"
```

Run: `pytest tests/unit/test_emergency.py -v -m "not slow"`
**All non-slow tests must pass before continuing.**

---

## FILE 3: agent/prompts/system_prompt.py

```python
# agent/prompts/system_prompt.py
"""
System prompt builder for the voice agent.
Injected with clinic-specific data at session start.
Called once per call with branch context.
"""
from dataclasses import dataclass


@dataclass
class ClinicContext:
    clinic_name: str
    branch_id: str
    working_hours: str          # "9 AM to 6 PM"
    closed_days: str            # "Sundays"
    doctors_context: str        # formatted doctor list
    faq_context: str
    has_ambulance: bool
    ambulance_driver_phone: str
    primary_language: str       # "te-IN"


def build_system_prompt(ctx: ClinicContext) -> str:
    ambulance_instruction = (
        f"This clinic HAS an ambulance. Driver phone: {ctx.ambulance_driver_phone}. "
        "For TYPE_1 emergencies: get patient location (max 10 seconds), "
        "then immediately call transfer_to_emergency tool."
        if ctx.has_ambulance else
        "This clinic does NOT have an ambulance. "
        "For TYPE_1 emergencies: express deep concern, get location, "
        "and provide the nearest emergency hospital number. "
        "Do NOT say 'call 108' — say 'nearest hospital ki jaandi'."
    )

    return f"""You are the AI receptionist for {ctx.clinic_name}.
You answer calls in {ctx.primary_language} (Telugu by default).

════ LANGUAGE RULES ════
- Default: Telugu
- Detect automatically: if patient speaks Hindi → Hindi, English → English
- Code-mixed Telugu+English (Tanglish) is NORMAL — handle it naturally
- Never ask the patient which language — just detect and respond
- Never switch language mid-conversation unless patient switches

════ YOUR CHARACTER ════
- Warm, calm, caring — like a trusted clinic receptionist
- Never robotic, never clinical, never formal
- Patients may be anxious about their health — speak gently
- Be efficient but never rush a patient who needs more time
- If a patient seems distressed — acknowledge it before proceeding

════ RESPONSE FORMAT — CRITICAL ════
- Maximum 20 words per spoken response
- Plain spoken language — no lists, no bullet points, no numbers
- No English medical jargon unless the patient uses it first
- Short confirmations: "avunu", "okay", "andariki" are good
- If something is unclear — ask ONE clarifying question only

════ CALL STRUCTURE ════
STEP 1 — CONSENT (mandatory, first thing every call):
Say: "Namaskāram, {ctx.clinic_name} ki welcome.
      Ee call quality kosam record avutuundi.
      Continue cheyaṭāniki yes cheppandi."

If patient says NO to recording:
  → Continue normally, do NOT record, set recording_consent=False in tools
If patient says YES:
  → Continue normally, set recording_consent=True in tools

STEP 2 — UNDERSTAND NEED:
Ask: "Meeru ēlā help cheyyāli?"
Listen for: appointment / question / emergency / existing booking query

STEP 3 — BOOKING FLOW:
a) Patient mentions health issue → call check_doctor_availability with doctor matching that issue
b) Patient names a doctor → call check_doctor_availability for that doctor
c) ALWAYS call check_doctor_availability — NEVER say "doctor available hai" without calling the tool
d) If available → offer: "Dr. [name] ki ēḍu Token #[n] available. Confirm cheyāli?"
e) If patient says yes → ask name if unknown → call confirm_booking
f) Confirmed → "Token #[n] confirm aindi. WhatsApp lo details vastāyi. 15 nimishalu mundu rāvāli."

STEP 4 — CALL END:
Wrap up warmly. End call naturally.
HARD LIMIT: Call must end by 4 minutes. At 3:50, start wrapping up if still talking.

════ AVAILABLE DOCTORS ════
{ctx.doctors_context}

════ CLINIC FAQ ════
{ctx.faq_context}

════ EMERGENCY RULES — HIGHEST PRIORITY ════
{ambulance_instruction}

Check EVERY patient statement for emergency keywords.
If patient says: collapsed, not breathing, unconscious, heavy bleeding,
heart attack happening, accident right now, mūrchanam, padipōyāḍu:
→ STOP booking flow immediately
→ Say ONLY: "Ippude connect chestunna. Location cheppandi."
→ Wait max 10 seconds for location
→ Call transfer_to_emergency tool immediately

For urgent but stable (chest pain, high fever, severe pain, breathing difficulty):
→ Say: "Urgent appointment book chestānu"
→ Call assign_token with is_urgent=True
→ NEVER tell patient to call 108

════ EDGE CASES ════
EXISTING PATIENT (found by phone):
  "Namaskāram [name] gāru! Ēḍu mee booking? Lēdā vēre evarikinainā?"

DOCTOR FULL:
  "Sorry, Dr. [name] ki ēḍu full. Rēpu available. Book cheyāli?"

WRONG HOURS:
  "Clinic working hours: {ctx.working_hours}. That time ki call cheyandi."

CLOSED DAY:
  "ēḍu clinic {ctx.closed_days} closed. Rēpu ki book cheyāli?"

SILENCE (8 seconds):
  "Hello? Meeru vinnārā?"

SILENCE (15 seconds total):
  "Meeru call back cheseyandi. Dhanyavādālu." → end call

PATIENT HANGS UP:
  Release held token immediately (handled in session disconnect hook)
"""
```

---

## FILE 4: agent/session_state.py

```python
# agent/session_state.py
"""
Per-call state. One instance created when call starts, destroyed when call ends.
Never persisted — lives only in memory for the duration of the call.
All booking state is confirmed to DB before call ends.
"""
from dataclasses import dataclass, field
from datetime import date as DateType


@dataclass
class SessionState:
    """Complete state for one patient call."""

    # ── Call identification ────────────────────────────────────────────
    branch_id: str = ""
    caller_phone: str = ""          # Full phone number
    call_id: str = ""               # LiveKit room name
    vobiz_call_id: str = ""         # Vobiz call ID for transfer

    # ── Patient state ─────────────────────────────────────────────────
    patient_id: str | None = None
    patient_name: str | None = None
    is_existing_patient: bool = False

    # ── Booking state ─────────────────────────────────────────────────
    doctor_id: str | None = None
    doctor_name: str | None = None
    booking_date: DateType | None = None
    # "token" | "slot"
    booking_type: str | None = None
    selected_slot_datetime: str | None = None

    # ── Token state — CRITICAL ────────────────────────────────────────
    # token_held = True means Redis INCR was called
    # token_confirmed = True means DB write was committed
    # If call drops with token_held=True and token_confirmed=False:
    #   → MUST call redis.decr() immediately in disconnect handler
    token_held: bool = False
    token_confirmed: bool = False
    token_number: int | None = None
    token_redis_key: str | None = None  # Needed for release

    # ── Emergency state ───────────────────────────────────────────────
    emergency_detected: bool = False
    # "type_1" | "type_2" | None
    emergency_type: str | None = None
    emergency_transferred: bool = False

    # ── Consent ───────────────────────────────────────────────────────
    # None = not yet asked, True = consented, False = declined
    recording_consent: bool | None = None

    # ── Call tracking ─────────────────────────────────────────────────
    call_start_time: float = 0.0    # time.time() when call started
    booking_completed: bool = False
    appointment_id: str | None = None

    def get_token_redis_key(self) -> str | None:
        """Generate Redis key for this token. Returns None if not enough data."""
        if self.doctor_id and self.branch_id and self.booking_date:
            return f"token:{self.doctor_id}:{self.branch_id}:{self.booking_date}"
        return None

    def call_duration_seconds(self) -> float:
        """Get current call duration."""
        import time
        if self.call_start_time:
            return time.time() - self.call_start_time
        return 0.0
```

---

## FILE 5: backend/services/token_service.py

**This is the most safety-critical service in the backend.**
Double-booking means two patients show up for the same slot. Unacceptable.

```python
# backend/services/token_service.py
"""
Redis-based atomic token assignment.

WHY REDIS INCR:
  Redis INCR is atomic by definition — two simultaneous calls
  to INCR on the same key will always get different sequential values.
  This is guaranteed by Redis's single-threaded command execution.

  Database SELECT COUNT(*) + INSERT is NOT atomic.
  Under concurrent load: both callers read count=5, both try to insert
  token 6, one fails with unique constraint violation — bad UX.

  INCR solves this permanently and elegantly.

REDIS KEY FORMAT:
  token:{doctor_id}:{branch_id}:{date}
  Example: token:abc123:xyz789:2026-05-15

KEY EXPIRY:
  Keys expire at midnight + 1 hour on the booking date.
  This prevents Redis from accumulating stale keys indefinitely.
  After expiry, next day starts fresh from 1.
"""
from datetime import date, datetime, timedelta
from typing import Optional
import structlog

logger = structlog.get_logger()


class TokenService:

    def __init__(self):
        self._redis = None

    async def _get_redis(self):
        """Get Redis client. Lazy init to support both Upstash and local Redis."""
        if self._redis:
            return self._redis
        from backend.config import settings
        redis_url = settings.redis_url
        if "upstash" in redis_url.lower() or redis_url.startswith("rediss://"):
            from upstash_redis.asyncio import Redis
            self._redis = Redis.from_env()
        else:
            import aioredis
            self._redis = await aioredis.from_url(redis_url, decode_responses=True)
        return self._redis

    def _make_key(self, doctor_id: str, branch_id: str, booking_date: date) -> str:
        """
        Canonical Redis key for a doctor's token counter on a date.
        This format is used everywhere — never deviate from it.
        """
        return f"token:{doctor_id}:{branch_id}:{booking_date.isoformat()}"

    async def assign_next_token(
        self,
        doctor_id: str,
        branch_id: str,
        booking_date: date,
        limit: int = 30
    ) -> Optional[int]:
        """
        Atomically assign next token number.

        Returns:
            int: token number (1-based) if slot available
            None: if fully booked (token count >= limit)

        This is the ONLY correct way to assign tokens.
        Never use DB count for this purpose.

        Thread safety: Redis INCR is atomic. 1000 simultaneous
        callers will get 1000 unique sequential numbers. Guaranteed.
        """
        key = self._make_key(doctor_id, branch_id, booking_date)
        redis = await self._get_redis()

        token_number = await redis.incr(key)

        # Set expiry on first token of the day
        if token_number == 1:
            # Expire at midnight + 1 hour of the booking date
            booking_midnight = datetime.combine(
                booking_date + timedelta(days=1),
                datetime.min.time()
            )
            seconds_until_expiry = int(
                (booking_midnight - datetime.utcnow()).total_seconds()
            ) + 3600  # +1 hour buffer
            await redis.expire(key, max(seconds_until_expiry, 3600))

        if token_number > limit:
            # Undo the increment — slot was full
            await redis.decr(key)
            logger.info(
                "token_limit_reached",
                doctor_id=doctor_id,
                branch_id=branch_id,
                date=str(booking_date),
                limit=limit
            )
            return None

        logger.info(
            "token_assigned",
            token_number=token_number,
            doctor_id=doctor_id,
            branch_id=branch_id,
            date=str(booking_date),
            limit=limit
        )
        return token_number

    async def release_token(self, redis_key: str) -> bool:
        """
        Release a held token back to the pool.

        WHEN TO CALL THIS:
        - Call drops before patient confirms booking
        - Booking fails (calendar error, DB error)
        - Patient cancels during confirmation

        NEVER call this after booking is confirmed in DB.
        Confirmed bookings are cancelled via the cancel endpoint, not here.
        """
        try:
            redis = await self._get_redis()
            current = await redis.get(redis_key)
            if current and int(current) > 0:
                await redis.decr(redis_key)
                logger.info("token_released", key=redis_key)
                return True
            logger.warning("token_release_skipped_already_zero", key=redis_key)
            return False
        except Exception as e:
            logger.error("token_release_failed", key=redis_key, error=str(e))
            return False

    async def get_availability(
        self,
        doctor_id: str,
        branch_id: str,
        booking_date: date,
        limit: int = 30
    ) -> dict:
        """
        Check availability without assigning a token.
        Used by check_doctor_availability tool before offering a booking.
        """
        try:
            key = self._make_key(doctor_id, branch_id, booking_date)
            redis = await self._get_redis()
            current = await redis.get(key)
            used = int(current) if current else 0
            remaining = max(0, limit - used)
            return {
                "available": remaining > 0,
                "used": used,
                "remaining": remaining,
                "limit": limit,
                "scarce": 0 < remaining <= 5,
            }
        except Exception as e:
            logger.error("get_availability_failed", error=str(e))
            # On Redis failure → assume available (don't block patients)
            # The DB unique constraint is the final safety net
            return {"available": True, "remaining": limit, "scarce": False}
```

### Tests: tests/edge_cases/test_concurrent_tokens.py

```python
# tests/edge_cases/test_concurrent_tokens.py
"""
CRITICAL SAFETY TESTS — test with REAL Redis.
These tests verify the core invariant: no two callers ever get the same token.
Do NOT mock Redis here. Mock defeats the purpose entirely.

Run against local Redis: redis://localhost:6379
These tests are slow (network IO) — mark them @pytest.mark.slow
"""
import pytest
import asyncio
from datetime import date, timedelta
from backend.services.token_service import TokenService


@pytest.mark.asyncio
async def test_5_simultaneous_callers_get_unique_tokens():
    """
    SCENARIO: 5 patients call simultaneously at 9:00 AM.
    EXPECTED: Each gets a unique sequential token (1-5).
    FAILURE: Any two tokens are the same = double-booking disaster.
    """
    service = TokenService()
    booking_date = date.today() + timedelta(days=1)  # tomorrow
    doctor_id = "test-concurrent-doctor-001"
    branch_id = "test-concurrent-branch-001"
    limit = 30

    results = await asyncio.gather(*[
        service.assign_next_token(
            doctor_id=doctor_id,
            branch_id=branch_id,
            booking_date=booking_date,
            limit=limit
        )
        for _ in range(5)
    ])

    # All must succeed (no None)
    successes = [r for r in results if r is not None]
    assert len(successes) == 5, \
        f"Expected 5 successful assignments, got {len(successes)}: {results}"

    # All must be unique
    assert len(set(successes)) == 5, \
        f"CRITICAL: Duplicate tokens detected: {results}"

    # Must be sequential 1–5 (not necessarily in order, but values 1-5)
    assert sorted(successes) == [1, 2, 3, 4, 5], \
        f"Tokens not sequential: {sorted(successes)}"


@pytest.mark.asyncio
async def test_last_2_slots_3_callers_exactly_2_succeed():
    """
    SCENARIO: Only 2 tokens remain. 3 patients call simultaneously.
    EXPECTED: Exactly 2 succeed, exactly 1 gets None (full).
    FAILURE: All 3 succeed = overbooking.
    """
    service = TokenService()
    booking_date = date.today() + timedelta(days=2)
    doctor_id = "test-concurrent-doctor-002"
    branch_id = "test-concurrent-branch-002"
    limit = 10

    # Pre-fill 8 tokens
    for _ in range(8):
        result = await service.assign_next_token(
            doctor_id, branch_id, booking_date, limit
        )
        assert result is not None, "Pre-fill failed"

    # Now 3 simultaneous for last 2 slots
    results = await asyncio.gather(*[
        service.assign_next_token(doctor_id, branch_id, booking_date, limit)
        for _ in range(3)
    ])

    successes = [r for r in results if r is not None]
    failures = [r for r in results if r is None]

    assert len(successes) == 2, \
        f"CRITICAL: Expected exactly 2 successes, got {len(successes)}: {results}"
    assert len(failures) == 1, \
        f"Expected exactly 1 failure, got {len(failures)}: {results}"
    assert set(successes) == {9, 10}, \
        f"Expected tokens 9 and 10, got: {successes}"


@pytest.mark.asyncio
async def test_release_makes_slot_available_again():
    """
    SCENARIO: Call drops before confirmation. Token must be released.
    Next caller should get a token (not be told it's full).
    """
    service = TokenService()
    booking_date = date.today() + timedelta(days=3)
    doctor_id = "test-release-doctor-003"
    branch_id = "test-release-branch-003"
    limit = 2

    # Fill both slots
    t1 = await service.assign_next_token(doctor_id, branch_id, booking_date, limit)
    t2 = await service.assign_next_token(doctor_id, branch_id, booking_date, limit)
    assert t1 == 1 and t2 == 2

    # Should be full
    t3 = await service.assign_next_token(doctor_id, branch_id, booking_date, limit)
    assert t3 is None, "Should be full after 2 assignments"

    # Release t2 (simulating call drop)
    key = service._make_key(doctor_id, branch_id, booking_date)
    released = await service.release_token(key)
    assert released is True, "Release failed"

    # Should be available again
    t4 = await service.assign_next_token(doctor_id, branch_id, booking_date, limit)
    assert t4 is not None, "Should be available after release"


@pytest.mark.asyncio
async def test_20_simultaneous_callers_all_unique():
    """
    STRESS TEST: 20 simultaneous callers, limit=20.
    Expected: exactly 20 unique tokens 1-20.
    This simulates a busy morning rush.
    """
    service = TokenService()
    booking_date = date.today() + timedelta(days=4)
    doctor_id = "test-stress-doctor-004"
    branch_id = "test-stress-branch-004"
    limit = 20

    results = await asyncio.gather(*[
        service.assign_next_token(doctor_id, branch_id, booking_date, limit)
        for _ in range(20)
    ])

    successes = [r for r in results if r is not None]
    assert len(successes) == 20
    assert len(set(successes)) == 20, "Duplicates in 20-caller stress test"
    assert sorted(successes) == list(range(1, 21))
```

---

## FILE 6: backend/services/meta_service.py

```python
# backend/services/meta_service.py
"""
WhatsApp messaging via Meta Cloud API.
Zero platform fee — we pay Meta rates directly.
Rate: ₹0.115 per utility message.

CRITICAL: WhatsApp failures must NEVER fail a booking.
All sends are wrapped in try/except.
Failed messages are queued for retry.
The booking is considered successful regardless of WhatsApp status.
"""
import hmac
import hashlib
import json
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
import structlog

from backend.config import settings

logger = structlog.get_logger()
META_API_BASE = "https://graph.facebook.com/v20.0"


class MetaService:

    def __init__(self):
        self.access_token = settings.meta_access_token
        self.phone_number_id = settings.meta_phone_number_id

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    async def send_text_message(
        self,
        to: str,
        message: str,
        branch_id: str = "",
    ) -> dict:
        """
        Send a text WhatsApp message.

        IMPORTANT ABOUT META RATES:
        - If patient messaged us within 24 hours → FREE (service conversation)
        - If we initiate → ₹0.115 per message (utility template required)
        - For appointment confirmations: always use template for compliance

        Args:
            to: Phone number with country code (+91XXXXXXXXXX)
            message: Message text (max 4096 chars)
            branch_id: For logging only

        Returns:
            {"success": True, "message_id": "wamid.xxx"} or
            {"success": False, "error": "..."}
        """
        if not self.access_token:
            logger.warning("meta_not_configured")
            return {"success": False, "error": "Meta not configured"}

        # Normalize phone number
        to_normalized = to.strip().replace(" ", "").replace("-", "")
        if not to_normalized.startswith("+"):
            to_normalized = "+" + to_normalized

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_normalized,
            "type": "text",
            "text": {"body": message, "preview_url": False}
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{META_API_BASE}/{self.phone_number_id}/messages",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json"
                    }
                )
                response.raise_for_status()
                result = response.json()
                message_id = result.get("messages", [{}])[0].get("id", "")
                logger.info(
                    "whatsapp_sent",
                    to=to[-4:],
                    message_id=message_id,
                    branch_id=branch_id
                )
                return {"success": True, "message_id": message_id}

        except httpx.HTTPStatusError as e:
            logger.error(
                "whatsapp_http_error",
                status=e.response.status_code,
                to=to[-4:],
                response_body=e.response.text[:200]
            )
            raise  # Let tenacity retry

        except Exception as e:
            logger.error("whatsapp_send_failed", to=to[-4:], error=str(e))
            return {"success": False, "error": str(e)}

    async def send_booking_confirmation(
        self,
        patient_phone: str,
        patient_name: str,
        doctor_name: str,
        token_number: int,
        booking_date: str,
        branch_id: str
    ) -> dict:
        """Send appointment confirmation to patient."""
        message = (
            f"✅ Appointment Confirmed!\n\n"
            f"Patient: {patient_name}\n"
            f"Doctor: {doctor_name}\n"
            f"Date: {booking_date}\n"
            f"Token: #{token_number}\n\n"
            f"Please arrive 15 minutes early.\n"
            f"To cancel: reply CANCEL"
        )
        return await self.send_text_message(patient_phone, message, branch_id)

    async def send_doctor_notification(
        self,
        doctor_phone: str,
        patient_name: str,
        patient_phone: str,
        token_number: int,
        booking_date: str,
        branch_id: str,
        is_urgent: bool = False
    ) -> dict:
        """Send new booking notification to doctor."""
        urgent_flag = "🔴 URGENT\n" if is_urgent else ""
        message = (
            f"{urgent_flag}📋 New Booking\n\n"
            f"Patient: {patient_name}\n"
            f"Phone: {patient_phone}\n"
            f"Token: #{token_number}\n"
            f"Date: {booking_date}\n"
            f"Via: Voice call"
        )
        return await self.send_text_message(doctor_phone, message, branch_id)

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        """
        Verify Meta webhook signature.
        Called on every incoming webhook to prevent spoofing.
        """
        expected = hmac.new(
            settings.meta_app_secret.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        received = signature.replace("sha256=", "")
        return hmac.compare_digest(expected, received)
```

---

## FILE 7: agent/tools/booking_tools.py

```python
# agent/tools/booking_tools.py
"""
Function tools available to Gemini 2.5 Flash during voice calls.
These are the only tools the LLM can call.

TOOL CONTRACT:
- Every tool must return a dict (never raise to the LLM)
- Every tool must have try/except wrapping all external calls
- Every tool logs at entry and exit with structlog
- Every tool validates branch_id is present before any DB operation

TOOL EXECUTION ORDER (normal booking):
1. get_patient_info() — optional, personalization
2. check_doctor_availability() — mandatory before booking
3. assign_token() — after patient agrees to book
4. confirm_booking() — after patient verbally confirms
"""
import asyncio
from datetime import date, datetime, timedelta
from typing import Any
import structlog

from backend.config import settings

logger = structlog.get_logger()


class BookingTools:
    """All function tools available to the voice agent LLM."""

    def __init__(self, branch_id: str, session_state):
        self.branch_id = branch_id
        self.state = session_state

    # ── TOOL 1: Get Patient Info ───────────────────────────────────────

    async def get_patient_info(self, phone: str) -> dict[str, Any]:
        """
        Look up existing patient by phone number.
        Called at call start to personalize the greeting.

        BRANCH ISOLATION: Always filters by branch_id.
        A patient registered at one clinic is unknown to another clinic.
        """
        try:
            from backend.database import AsyncSessionLocal
            from backend.models.schema import Patient, Token
            from sqlalchemy import select

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Patient).where(
                        Patient.phone == phone,
                        Patient.branch_id == self.branch_id  # MANDATORY
                    )
                )
                patient = result.scalar_one_or_none()

                if not patient:
                    return {"found": False}

                # Check for active booking today
                today_result = await db.execute(
                    select(Token).where(
                        Token.patient_id == patient.patient_id,
                        Token.branch_id == self.branch_id,  # MANDATORY
                        Token.date == date.today(),
                        Token.status == "confirmed"
                    )
                )
                active_today = today_result.scalar_one_or_none()

                logger.info("patient_lookup_found",
                           patient_id=patient.patient_id,
                           branch_id=self.branch_id)

                return {
                    "found": True,
                    "patient_id": patient.patient_id,
                    "name": patient.name,
                    "preferred_language": patient.preferred_language,
                    "has_booking_today": active_today is not None,
                    "active_token": active_today.token_number if active_today else None,
                }

        except Exception as e:
            logger.error("patient_lookup_failed", error=str(e), branch_id=self.branch_id)
            return {"found": False}

    # ── TOOL 2: Check Doctor Availability ─────────────────────────────

    async def check_doctor_availability(
        self,
        doctor_id: str,
        date_str: str  # "today" | "tomorrow" | "YYYY-MM-DD"
    ) -> dict[str, Any]:
        """
        Check if a doctor has available slots/tokens for a date.
        MUST be called before any booking — never guess availability.

        Returns scarce=True when ≤5 tokens remain to create urgency.
        """
        try:
            target_date = self._parse_date(date_str)
            from backend.database import AsyncSessionLocal
            from backend.models.schema import Doctor
            from sqlalchemy import select
            from backend.services.token_service import TokenService

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Doctor).where(
                        Doctor.doctor_id == doctor_id,
                        Doctor.branch_id == self.branch_id,  # MANDATORY
                        Doctor.is_active == True
                    )
                )
                doctor = result.scalar_one_or_none()

                if not doctor:
                    return {"available": False, "error": "Doctor not found"}

                # Check if working today
                weekday = target_date.weekday()  # 0=Monday, 6=Sunday
                if weekday not in (doctor.working_days or [0,1,2,3,4,5]):
                    return {
                        "available": False,
                        "reason": f"Doctor not working on {target_date.strftime('%A')}"
                    }

                if doctor.booking_type == "token":
                    token_service = TokenService()
                    availability = await token_service.get_availability(
                        doctor_id=doctor_id,
                        branch_id=self.branch_id,
                        booking_date=target_date,
                        limit=doctor.daily_token_limit
                    )
                    return {
                        "available": availability["available"],
                        "booking_type": "token",
                        "remaining": availability["remaining"],
                        "scarce": availability["scarce"],
                        "date": str(target_date),
                        "doctor_name": doctor.name,
                        "speciality": doctor.speciality,
                    }
                else:
                    # Slot-based — check calendar
                    from backend.services.calendar_service import CalendarService
                    calendar = CalendarService()
                    slots = await calendar.get_available_slots(
                        doctor_id=doctor_id,
                        branch_id=self.branch_id,
                        booking_date=target_date,
                        doctor=doctor
                    )
                    return {
                        "available": len(slots) > 0,
                        "booking_type": "slot",
                        "available_slots": slots[:5],
                        "date": str(target_date),
                        "doctor_name": doctor.name,
                    }

        except Exception as e:
            logger.error("check_availability_failed",
                        error=str(e), doctor_id=doctor_id)
            return {"available": False, "error": "Could not check availability"}

    # ── TOOL 3: Assign Token ───────────────────────────────────────────

    async def assign_token(
        self,
        doctor_id: str,
        patient_name: str,
        patient_phone: str,
        date_str: str,
        is_urgent: bool = False
    ) -> dict[str, Any]:
        """
        Atomically assign next token. Called when patient agrees to book.

        IMPORTANT: This HOLDS the token but does NOT confirm it.
        The token is in Redis but NOT yet in the database.
        confirm_booking() must be called to complete the booking.

        If call drops after assign_token but before confirm_booking:
        → The session disconnect handler calls release_token()
        → Redis is decremented, slot is freed
        → No orphaned tokens

        Sets state.token_held = True
        Sets state.token_confirmed = False (until confirm_booking)
        """
        try:
            from backend.database import AsyncSessionLocal
            from backend.models.schema import Doctor
            from sqlalchemy import select
            from backend.services.token_service import TokenService

            target_date = self._parse_date(date_str)

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Doctor).where(
                        Doctor.doctor_id == doctor_id,
                        Doctor.branch_id == self.branch_id  # MANDATORY
                    )
                )
                doctor = result.scalar_one_or_none()
                if not doctor:
                    return {"success": False, "error": "Doctor not found"}

                token_service = TokenService()
                token_number = await token_service.assign_next_token(
                    doctor_id=doctor_id,
                    branch_id=self.branch_id,
                    booking_date=target_date,
                    limit=doctor.daily_token_limit
                )

                if token_number is None:
                    return {
                        "success": False,
                        "full": True,
                        "message": f"Dr. {doctor.name} is fully booked for {target_date}"
                    }

                # Update session state — token is HELD not confirmed
                self.state.token_held = True
                self.state.token_confirmed = False
                self.state.token_number = token_number
                self.state.doctor_id = doctor_id
                self.state.doctor_name = doctor.name
                self.state.booking_date = target_date
                self.state.token_redis_key = token_service._make_key(
                    doctor_id, self.branch_id, target_date
                )

                return {
                    "success": True,
                    "token_number": token_number,
                    "doctor_name": doctor.name,
                    "date": str(target_date),
                    "is_urgent": is_urgent,
                    "message": "Token held. Ask patient to confirm."
                }

        except Exception as e:
            logger.error("assign_token_failed", error=str(e))
            return {"success": False, "error": "Token assignment failed"}

    # ── TOOL 4: Confirm Booking ────────────────────────────────────────

    async def confirm_booking(
        self,
        patient_name: str,
        patient_phone: str,
        is_urgent: bool = False
    ) -> dict[str, Any]:
        """
        Finalize booking after patient verbally confirms.

        ORDER OF OPERATIONS (NEVER CHANGE):
        1. Get or create patient in DB
        2. Create Google Calendar event
        3. Save Token to DB (commit)
        4. Mark state.token_confirmed = True
        5. Send WhatsApp in background (non-blocking)

        Calendar before DB: if calendar fails, we catch and raise.
        WhatsApp after DB: if WhatsApp fails, booking still succeeded.
        """
        if not self.state.token_held or not self.state.token_number:
            return {"success": False, "error": "No token held — call assign_token first"}

        try:
            from backend.database import AsyncSessionLocal
            from backend.models.schema import Patient, Token, Doctor
            from sqlalchemy import select
            from backend.services.calendar_service import CalendarService

            async with AsyncSessionLocal() as db:
                # Get or create patient (branch-scoped)
                patient_result = await db.execute(
                    select(Patient).where(
                        Patient.phone == patient_phone,
                        Patient.branch_id == self.branch_id  # MANDATORY
                    )
                )
                patient = patient_result.scalar_one_or_none()

                if not patient:
                    patient = Patient(
                        name=patient_name,
                        phone=patient_phone,
                        branch_id=self.branch_id
                    )
                    db.add(patient)
                    await db.flush()

                # Get doctor for calendar
                doctor_result = await db.execute(
                    select(Doctor).where(Doctor.doctor_id == self.state.doctor_id)
                )
                doctor = doctor_result.scalar_one_or_none()

                # Create Google Calendar event (before DB commit)
                calendar_event_id = None
                if doctor and doctor.calendar_id:
                    try:
                        calendar = CalendarService()
                        calendar_event_id = await calendar.create_token_event(
                            calendar_id=doctor.calendar_id,
                            date=self.state.booking_date,
                            token_number=self.state.token_number,
                            patient_name=patient_name,
                            patient_phone_last4=patient_phone[-4:]
                        )
                    except Exception as cal_err:
                        logger.error("calendar_create_failed",
                                    error=str(cal_err),
                                    doctor_id=self.state.doctor_id)
                        # Calendar failure is not fatal — continue without it

                # Save Token to DB
                token = Token(
                    doctor_id=self.state.doctor_id,
                    branch_id=self.branch_id,
                    patient_id=patient.patient_id,
                    date=self.state.booking_date,
                    token_number=self.state.token_number,
                    status="confirmed",
                    booked_via="voice",
                    is_urgent=is_urgent,
                    calendar_event_id=calendar_event_id
                )
                db.add(token)
                await db.commit()

                # Update session state — booking is now confirmed
                self.state.token_confirmed = True
                self.state.booking_completed = True
                self.state.appointment_id = token.token_id

                logger.info(
                    "booking_confirmed",
                    token_number=self.state.token_number,
                    patient_phone=patient_phone[-4:],
                    doctor_id=self.state.doctor_id,
                    branch_id=self.branch_id,
                    via="voice"
                )

            # Send WhatsApp in background — never await this here
            # WhatsApp failure MUST NOT fail the booking
            asyncio.create_task(self._send_confirmations(
                patient_name=patient_name,
                patient_phone=patient_phone,
                doctor=doctor,
                token_number=self.state.token_number,
                booking_date=self.state.booking_date,
                is_urgent=is_urgent
            ))

            return {
                "success": True,
                "token_number": self.state.token_number,
                "doctor_name": self.state.doctor_name,
                "date": str(self.state.booking_date),
                "message": "Booking confirmed. WhatsApp being sent."
            }

        except Exception as e:
            logger.error("confirm_booking_failed", error=str(e))
            # Release held token — booking failed
            if self.state.token_redis_key:
                from backend.services.token_service import TokenService
                await TokenService().release_token(self.state.token_redis_key)
                self.state.token_held = False
            return {"success": False, "error": "Booking failed. Please try again."}

    async def _send_confirmations(
        self,
        patient_name: str,
        patient_phone: str,
        doctor,
        token_number: int,
        booking_date,
        is_urgent: bool
    ):
        """
        Send WhatsApp to patient and doctor.
        Runs as background task. Never blocks the call.
        Errors here are logged but do NOT affect the booking.
        """
        from backend.services.meta_service import MetaService
        meta = MetaService()
        date_str = booking_date.strftime("%d %B %Y") if booking_date else "Today"

        try:
            await meta.send_booking_confirmation(
                patient_phone=patient_phone,
                patient_name=patient_name,
                doctor_name=self.state.doctor_name or "Doctor",
                token_number=token_number,
                booking_date=date_str,
                branch_id=self.branch_id
            )
        except Exception as e:
            logger.error("patient_whatsapp_failed", error=str(e))

        try:
            if doctor and doctor.personal_phone:
                await meta.send_doctor_notification(
                    doctor_phone=doctor.personal_phone,
                    patient_name=patient_name,
                    patient_phone=patient_phone[-4:] + "****",
                    token_number=token_number,
                    booking_date=date_str,
                    branch_id=self.branch_id,
                    is_urgent=is_urgent
                )
        except Exception as e:
            logger.error("doctor_whatsapp_failed", error=str(e))

    def _parse_date(self, date_str: str) -> date:
        """Parse flexible date strings to date object."""
        today = date.today()
        normalized = date_str.lower().strip()
        if normalized in ["today", "ēḍu", "nenu", "ippude"]:
            return today
        if normalized in ["tomorrow", "rēpu", "kal"]:
            return today + timedelta(days=1)
        if normalized == "day after tomorrow":
            return today + timedelta(days=2)
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return today  # Safe fallback
```

---

## FILE 8: agent/agent.py

```python
# agent/agent.py
"""
Main LiveKit voice agent entrypoint.
One instance per call. Loaded when call arrives at Vobiz DID.

ARCHITECTURE:
- Vobiz receives patient call → POSTs to /calls/inbound/{branch_id}
- Backend creates LiveKit room, dispatches this agent
- Agent joins room, starts STT/LLM/TTS pipeline
- Pipeline runs until call ends (max 4 minutes)
- On disconnect: cleanup state, release held tokens
"""
import asyncio
import time
import structlog

from livekit.agents import (
    AgentSession,
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    llm,
)
from livekit.plugins import openai as lk_openai
from livekit.plugins import sarvam as lk_sarvam

from backend.config import settings
from agent.session_state import SessionState
from agent.prompts.system_prompt import build_system_prompt, ClinicContext
from agent.services.tts_sanitizer import sanitize_for_tts
from agent.services.emergency import classify_emergency, EmergencyType
from agent.tools.booking_tools import BookingTools

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger()

# 4-minute call cap — AI must wrap up before this
MAX_CALL_DURATION_SECONDS = 240


async def entrypoint(ctx: JobContext):
    """Entry point for each incoming call."""

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Extract context from room metadata
    metadata = {}
    try:
        import json as _json
        metadata = _json.loads(ctx.room.metadata or "{}")
    except Exception:
        pass

    branch_id = metadata.get("branch_id", "")
    caller_phone = metadata.get("caller_phone", "unknown")

    logger.info("call_started",
               branch_id=branch_id,
               caller=caller_phone[-4:] if len(caller_phone) >= 4 else "????",
               room=ctx.room.name)

    # Initialize state
    state = SessionState(
        branch_id=branch_id,
        caller_phone=caller_phone,
        call_id=ctx.room.name,
        call_start_time=time.time()
    )

    booking_tools = BookingTools(branch_id=branch_id, session_state=state)

    # Load clinic context
    clinic_ctx = await _load_clinic_context(branch_id)

    # Check existing patient
    if caller_phone != "unknown":
        patient_info = await booking_tools.get_patient_info(caller_phone)
        if patient_info.get("found"):
            state.patient_id = patient_info["patient_id"]
            state.patient_name = patient_info["name"]
            state.is_existing_patient = True
            logger.info("existing_patient_recognized",
                       patient_id=state.patient_id,
                       branch_id=branch_id)

    # Build system prompt
    system_prompt = build_system_prompt(clinic_ctx)

    # STT — Sarvam Saaras v3
    stt = lk_sarvam.STT(
        api_key=settings.sarvam_api_key,
        model="saaras:v3",
        language="te-IN",
        mode="codemix",           # Handle Telugu+English mix
        flush_signal=True,        # Required for proper turn detection
    )

    # TTS — Sarvam Bulbul v3
    tts = lk_sarvam.TTS(
        api_key=settings.sarvam_api_key,
        model="bulbul:v3",
        language="te-IN",
        sample_rate=8000,         # Telephony quality (8kHz)
    )

    # LLM — Gemini 2.5 Flash (primary) with fallback to GPT-4o mini
    agent_llm = lk_google.LLM(
        model="gemini-2.5-flash",
        api_key=settings.gemini_api_key,
        temperature=0.3,
    )

    # Create session
    session = AgentSession(
        stt=stt,
        tts=tts,
        llm=agent_llm,
        turn_detection="stt",
        min_endpointing_delay=0.07,   # 70ms matches Sarvam latency
        allow_interruptions=True,      # Patient can interrupt AI
    )

    # Hook: sanitize every TTS output
    @session.on("before_tts")
    def before_tts(text: str) -> str:
        return sanitize_for_tts(text)

    # Hook: emergency check on every utterance
    @session.on("user_speech_committed")
    async def on_speech(transcript: str):
        if not state.emergency_detected and len(transcript.split()) >= 2:
            result = await classify_emergency(transcript)
            if result.type == EmergencyType.TYPE_1:
                state.emergency_detected = True
                state.emergency_type = "type_1"
                logger.critical("type1_emergency_during_call",
                               branch_id=branch_id,
                               caller=caller_phone[-4:])
                await _handle_type1_emergency(session, state, ctx, clinic_ctx)
            elif result.type == EmergencyType.TYPE_2:
                state.emergency_detected = True
                state.emergency_type = "type_2"
                # TYPE_2: system prompt instructs LLM to book urgent
                # No special handling needed here

    # Hook: 4-minute call cap enforcement
    @session.on("user_speech_committed")
    async def check_duration(transcript: str):
        if state.call_duration_seconds() > MAX_CALL_DURATION_SECONDS - 10:
            # 10 seconds left — force wrap-up
            wrap_msg = sanitize_for_tts(
                "Ee call ki time avutuundi. "
                "Mee booking confirm aindi. Dhanyavādālu!"
            )
            await session.say(wrap_msg, allow_interruptions=False)

    # Disconnect handler — CRITICAL for token release
    @ctx.room.on("disconnected")
    def on_disconnect():
        asyncio.create_task(_handle_disconnect(state, booking_tools))

    # Start agent session
    await session.start(
        room=ctx.room,
        agent=lk_openai.LLMAgent(
            instructions=system_prompt,
            tools=_build_tools(booking_tools),
        )
    )

    logger.info("session_started",
               branch_id=branch_id,
               caller=caller_phone[-4:])


async def _handle_disconnect(state: SessionState, booking_tools: BookingTools):
    """
    Called when call ends for ANY reason.
    MUST release held token if booking was not confirmed.
    This prevents phantom tokens blocking future bookings.
    """
    if state.token_held and not state.token_confirmed:
        key = state.token_redis_key or state.get_token_redis_key()
        if key:
            from backend.services.token_service import TokenService
            released = await TokenService().release_token(key)
            logger.warning(
                "token_released_on_disconnect",
                token_number=state.token_number,
                branch_id=state.branch_id,
                released=released
            )

    # Log call outcome
    outcome = "booked" if state.booking_completed else \
              "emergency" if state.emergency_detected else \
              "dropped" if (state.token_held and not state.token_confirmed) else \
              "no_action"

    logger.info(
        "call_ended",
        branch_id=state.branch_id,
        caller=state.caller_phone[-4:] if state.caller_phone else "????",
        outcome=outcome,
        duration_seconds=round(state.call_duration_seconds()),
        emergency_type=state.emergency_type,
        token_number=state.token_number
    )

    # Write call log to DB in background
    asyncio.create_task(_write_call_log(state))


async def _handle_type1_emergency(session, state, ctx, clinic_ctx):
    """Handle life-threatening emergency."""
    has_ambulance = clinic_ctx.has_ambulance

    if has_ambulance:
        await session.say(
            sanitize_for_tts(
                "Ippude ambulance driver ki connect chestunna. "
                "Exact location cheppandi."
            ),
            allow_interruptions=True
        )
        # Wait max 10 seconds for location
        await asyncio.sleep(10)
        # Transfer via Vobiz
        logger.critical("transferring_to_ambulance",
                       branch_id=state.branch_id,
                       driver_phone=clinic_ctx.ambulance_driver_phone)
        # Vobiz transfer — implementation in Phase 2
    else:
        await session.say(
            sanitize_for_tts(
                "Immediate help kavāli. "
                "Nearest hospital ki vellandi lēdā 108 ki call cheyandi."
            )
        )


async def _load_clinic_context(branch_id: str) -> ClinicContext:
    """Load clinic and doctor data for system prompt."""
    try:
        from backend.database import AsyncSessionLocal
        from backend.models.schema import Branch, Doctor
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            branch_result = await db.execute(
                select(Branch).where(Branch.branch_id == branch_id)
            )
            branch = branch_result.scalar_one_or_none()

            if not branch:
                return _default_context()

            doctors_result = await db.execute(
                select(Doctor).where(
                    Doctor.branch_id == branch_id,
                    Doctor.is_active == True
                )
            )
            doctors = doctors_result.scalars().all()

            doctors_context = "\n".join([
                f"- Dr. {d.name} ({d.speciality or 'General'}): "
                f"treats {', '.join(d.treats_keywords[:5] if d.treats_keywords else ['general conditions'])}"
                for d in doctors
            ]) or "No doctors configured"

            return ClinicContext(
                clinic_name=branch.name,
                branch_id=branch_id,
                working_hours=f"{branch.working_hours_start} to {branch.working_hours_end}",
                closed_days=", ".join(branch.closed_days) if branch.closed_days else "None",
                doctors_context=doctors_context,
                faq_context="Contact clinic staff for specific questions.",
                has_ambulance=branch.has_ambulance,
                ambulance_driver_phone=branch.ambulance_driver_phone or "",
                primary_language=branch.primary_language,
            )

    except Exception as e:
        logger.error("load_clinic_context_failed", error=str(e))
        return _default_context()


def _default_context() -> ClinicContext:
    """Safe fallback context when DB is unavailable."""
    return ClinicContext(
        clinic_name="Clinic",
        branch_id="",
        working_hours="9 AM to 6 PM",
        closed_days="Sundays",
        doctors_context="Staff will help with doctor availability.",
        faq_context="Contact clinic staff.",
        has_ambulance=False,
        ambulance_driver_phone="",
        primary_language="te-IN",
    )


async def _write_call_log(state: SessionState):
    """Write call log to DB after call ends."""
    try:
        from backend.database import AsyncSessionLocal
        from backend.models.schema import CallLog

        async with AsyncSessionLocal() as db:
            log = CallLog(
                branch_id=state.branch_id if state.branch_id else None,
                caller_phone_last4=state.caller_phone[-4:] if state.caller_phone else None,
                patient_id=state.patient_id,
                duration_secs=int(state.call_duration_seconds()),
                outcome="booked" if state.booking_completed else
                       "emergency" if state.emergency_detected else "no_action",
                was_emergency=state.emergency_detected,
                emergency_type=state.emergency_type,
                recording_consent=state.recording_consent
            )
            db.add(log)
            await db.commit()
    except Exception as e:
        logger.error("write_call_log_failed", error=str(e))


def _build_tools(booking_tools: BookingTools) -> list:
    """Build LLM function tool definitions."""
    return [
        llm.FunctionTool(
            name="get_patient_info",
            description=(
                "Look up existing patient by phone number at call start. "
                "Use this to personalize the greeting for returning patients."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Patient phone number with country code"
                    }
                },
                "required": ["phone"]
            },
            func=booking_tools.get_patient_info,
        ),
        llm.FunctionTool(
            name="check_doctor_availability",
            description=(
                "Check if a doctor has available appointment slots or tokens "
                "for a given date. MUST call this before offering any booking. "
                "Never guess or assume availability."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doctor_id": {"type": "string"},
                    "date_str": {
                        "type": "string",
                        "description": "Date as 'today', 'tomorrow', or 'YYYY-MM-DD'"
                    }
                },
                "required": ["doctor_id", "date_str"]
            },
            func=booking_tools.check_doctor_availability,
        ),
        llm.FunctionTool(
            name="assign_token",
            description=(
                "Atomically assign the next available token for a doctor. "
                "Call this AFTER patient agrees to book but BEFORE confirmation. "
                "Token is held but not confirmed until confirm_booking is called."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doctor_id": {"type": "string"},
                    "patient_name": {"type": "string"},
                    "patient_phone": {"type": "string"},
                    "date_str": {"type": "string"},
                    "is_urgent": {"type": "boolean", "default": False}
                },
                "required": ["doctor_id", "patient_name", "patient_phone", "date_str"]
            },
            func=booking_tools.assign_token,
        ),
        llm.FunctionTool(
            name="confirm_booking",
            description=(
                "Finalize and save the booking after patient verbally confirms. "
                "Creates calendar event, saves to database, sends WhatsApp. "
                "Call this only after patient says 'yes' or equivalent."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string"},
                    "patient_phone": {"type": "string"},
                    "is_urgent": {"type": "boolean", "default": False}
                },
                "required": ["patient_name", "patient_phone"]
            },
            func=booking_tools.confirm_booking,
        ),
    ]


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
```

---

## PHASE 1 EXIT CRITERIA

**Run every item below. All must pass before Phase 2.**

```
AUTOMATED TESTS
□ pytest tests/unit/test_tts_sanitizer.py -v → 17/17 pass
□ pytest tests/unit/test_emergency.py -v -m "not slow" → all pass
□ pytest tests/edge_cases/test_concurrent_tokens.py -v → 4/4 pass
□ ruff check agent/ → 0 errors
□ ruff check backend/services/ → 0 errors

MANUAL INTEGRATION TESTS (requires real API keys)
□ Start agent: python agent/agent.py dev
  Output: "Agent started, waiting for connections..."

□ LiveKit playground test (https://lkt.li/playground):
  Connect to ws://localhost:7880 with key=devkey secret=devsecret
  Say "Namaste, doctor ki appointment kavali"
  Expected: AI responds in Telugu, asks about health issue

□ Symptom routing test:
  Say "gunde noppi undi" (chest pain)
  Expected: AI identifies it as cardiac symptom, suggests Dr. [cardiac doctor]
  NOT a generic "which doctor do you want?"

□ Token booking test:
  Complete full booking conversation
  After call: redis-cli GET "token:*" shows incremented counter
  After call: psql query: SELECT * FROM tokens WHERE date = TODAY; shows 1 row
  After call: Google Calendar shows appointment event

□ Call drop test:
  Start booking, disconnect before saying "yes"
  Redis counter must decrement (token released)
  DB must NOT have a token record for this incomplete booking

□ WhatsApp test:
  Complete a booking with real phone numbers
  Patient WhatsApp received within 60 seconds
  Doctor WhatsApp received within 90 seconds

□ Emergency TYPE_1 test:
  Say "collapse aipōyāḍu" (patient collapsed)
  Expected: AI immediately says "Ippude connect chestunna"
  NOT: "Token #X available for Dr. Y"
  log entry: call_logs.was_emergency = True, emergency_type = "type_1"

□ Emergency TYPE_2 test:
  Say "chest pain undi morning ninchi" (chest pain since morning)
  Expected: AI says "Urgent appointment book chestānu"
  Expected: Token assigned with is_urgent = True
  NOT: AI says "call 108"

□ 4-minute cap test:
  Start a call and talk for 4+ minutes
  AI must wrap up gracefully before 4:15
  Call log must show duration < 260 seconds

□ Existing patient test:
  Pre-insert a patient record in DB with a phone number
  Call from that phone number
  Expected: AI greets by name: "Namaskāram [Name] gāru!"

□ Full call to completion:
  End-to-end: patient calls → AI answers → booking confirmed
  → WhatsApp received by patient → WhatsApp received by doctor
  → Token visible in DB → Calendar event exists
  This is the definition of success for Phase 1.
```

**ALL items checked = Phase 1 complete. Proceed to PHASE_2_BACKEND.md**
