import re
import unicodedata

# Internal execution language must never reach a caller. This is a deterministic
# boundary check, not a request to the LLM. Keep patient-safe words such as
# "appointment" and "calendar date" out of this list; match only implementation
# identifiers and explicit execution narration.
_INTERNAL_TRACE = re.compile(
    r"(?i)(?:\bexecuting\b|\btool[ _-]?call\b|\bfunction[ _-]?call\b|"
    r"\bthe user (?:is|has|asked|wants|requested|provided|mentioned)\b|"
    r"\bI (?:need|must|have) to\b|\bI should\b|"
    r"\b(?:this|that) information (?:is|comes)\b|"
    r"\b(?:my|our) (?:task|instructions?|reasoning)\b|"
    r"\b(?:based on|according to) (?:the )?(?:context|instructions?|clinic_facts|tool)\b|"
    r"\bclinic_facts\b|<\/?(?:doctors?|clinic_facts)\b|"
    r"calendar\.tool|\b(?:old_token_id|new_date|new_time|booking_date|appointment_time|token_id|doctor_id|patient_name|"
    r"patient_phone|different_person|booking_for_other)\b\s*[:=]?|"
    r"\b(?:confirm_booking|reschedule_booking|cancel_booking|check_availability|"
    r"route_to_doctor|assign_token|find_my_bookings|get_queue_status)\b)"
)

# Wider fail-closed classifier for free-form meta narration. These are
# structural reasoning forms, not clinic-facing speech.
_INTERNAL_META = re.compile(
    r"(?i)(?:(?:the|this) (?:user|caller|patient)|"
    r"(?:i|we) (?:need|should|must|have|plan) to|"
    r"(?:i|we) (?:will|would|can|cannot|can not|do not) "
    r"(?:use|call|retrieve|look up|proceed)|"
    r"the [a-z_ -]+ tool|(?:available|provided) information|"
    r"`[^`]+`|<[a-z/][^>]*>)"
)

# Model/provider transport labels are not speech.  Some Gemini routes emitted
# this exact token before otherwise valid replies; strip only the label so the
# patient-facing sentence is preserved (unlike the fail-closed tool guard).
_MODEL_CONTROL_TOKEN = re.compile(
    r"(?i)(?:<|\[)?\s*(?:"
    r"response[ _-]?(?:start|end)|"
    r"రెస్పాన్స్\s+(?:స్టార్ట్|ఎండ్)|"
    r"रिस्पॉन्स\s+(?:स्टार्ट|एंड)|रिस्पांस\s+(?:स्टार्ट|एंड)|"
    r"ரெஸ்பான்ஸ்\s+(?:ஸ்டார்ட்|எண்ட்)|"
    r"ರೆಸ್ಪಾನ್ಸ್\s+(?:ಸ್ಟಾರ್ಟ್|ಎಂಡ್)"
    r")\s*(?:>|\])?\s*[.:：।]?[ \t\r\n]*"
)


# Literal cores of every private marker. Their prefixes let the streaming
# firewall retain only a suffix that could still become a marker on the next
# LLM chunk. The old unconditional 24-character carry delayed all safe speech
# (often until a short reply had fully generated) before Soniox could start.
_INTERNAL_STREAM_MARKERS = (
    "the user", "this user", "the caller", "this caller",
    "the patient", "this patient", "we need to", "we should",
    "we must", "we have to", "i plan to", "we plan to",
    "i will use", "i would use", "i can use", "i cannot use",
    "i can not use", "i do not use", "we will use",
    "available information", "provided information", "the tool", "<", "`",
    "executing", "tool call", "tool_call", "tool-call",
    "the user is", "the user has", "the user asked", "the user wants",
    "the user requested", "the user provided", "the user mentioned",
    "i need to", "i should", "i must", "i have to", "this information",
    "that information", "my task", "our task", "my instructions",
    "our instructions", "my reasoning", "our reasoning", "based on the context",
    "according to the context", "based on the instructions",
    "according to the instructions", "clinic_facts", "<doctor", "</doctor",
    "<clinic_facts", "</clinic_facts",
    "function call", "function_call", "function-call", "calendar.tool",
    "old_token_id", "new_date", "new_time", "booking_date",
    "appointment_time", "patient_name", "token_id", "doctor_id",
    "patient_phone", "different_person", "booking_for_other",
    "confirm_booking", "reschedule_booking", "cancel_booking",
    "check_availability", "route_to_doctor", "assign_token",
    "find_my_bookings", "get_queue_status", "response_start", "response_end",
    "response start", "response end", "రెస్పాన్స్ స్టార్ట్", "రెస్పాన్స్ ఎండ్",
    "रिस्पॉन्स स्टार्ट", "रिस्पॉन्स एंड", "रिस्पांस स्टार्ट", "रिस्पांस एंड",
    "ரெஸ்பான்ஸ் ஸ்டார்ட்", "ரெஸ்பான்ஸ் எண்ட்",
    "ರೆಸ್ಪಾನ್ಸ್ ಸ್ಟಾರ್ಟ್", "ರೆಸ್ಪಾನ್ಸ್ ಎಂಡ್",
)
_INTERNAL_STREAM_PREFIXES = frozenset(
    marker[:size]
    for marker in _INTERNAL_STREAM_MARKERS
    for size in range(1, len(marker) + 1)
)
_INTERNAL_STREAM_MAX_PREFIX = max(map(len, _INTERNAL_STREAM_MARKERS))


def internal_trace_prefix_len(text: str) -> int:
    """Return the trailing length that may complete a private marker."""
    folded = (text or "").casefold()
    for size in range(min(len(folded), _INTERNAL_STREAM_MAX_PREFIX), 0, -1):
        if folded[-size:] in _INTERNAL_STREAM_PREFIXES:
            return size
    return 0


def strip_model_control_tokens(text: str) -> str:
    """Remove non-spoken response boundary labels from model output."""
    return _MODEL_CONTROL_TOKEN.sub("", text or "")


def internal_trace_match(text: str):
    """Return the first private-execution marker in speech, if present."""
    value = text or ""
    return (
        _INTERNAL_TRACE.search(value)
        or _INTERNAL_META.search(value)
    )


def strip_internal_tool_speech(text: str) -> str:
    """Remove any sentence/line that exposes tool execution details.

    This intentionally fails closed: losing one generated sentence is preferable
    to reading identifiers, JSON, or calendar operations to a patient.
    """
    if not internal_trace_match(text):
        return text
    pieces = re.split(r"(?<=[.!?।])|\r?\n", text)
    return " ".join(p.strip() for p in pieces if p.strip() and not internal_trace_match(p))

# ── #408 (Vinay 2026-07-19): every digit the agent speaks is ENGLISH, always —
# phone numbers one-by-one ("eight zero nine six…"), times as "six thirty",
# ages as "forty eight" — never Telugu/Hindi number words, in ANY language.
# The prompt already ordered this (rule 7) and the LLM still spoke Telugu
# number words on a real call, so the conversion is DETERMINISTIC here at the
# TTS boundary: whatever script the model writes digits in, they leave as
# English words. (Native-language number WORDS the model writes can't be
# caught here — the prompt now tells it to always write digits.)

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven",
         "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
         "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]


def _cardinal(n: int) -> str:
    """0-9999 in English words (ages, token numbers, day-of-month)."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _TENS[t] + (f" {_ONES[o]}" if o else "")
    if n < 1000:
        h, r = divmod(n, 100)
        return f"{_ONES[h]} hundred" + (f" {_cardinal(r)}" if r else "")
    th, r = divmod(n, 1000)
    return f"{_cardinal(th)} thousand" + (f" {_cardinal(r)}" if r else "")


_TIME = re.compile(r"\b(\d{1,2}):([0-5]\d)\b")
_LONG_RUN = re.compile(r"\d{5,}")
_PHONE_RUN = re.compile(r"(?<!\d)\d{10,15}(?!\d)")
_SHORT_NUM = re.compile(r"\d{1,4}")

# ── #415 (Vinay 2026-07-19): times speak WITH am/pm — "5pm", "3:30pm", "10am"
# — instead of "5 గంటలకి" / bare "five thirty". Deterministic, meridiem taken
# from what the text itself proves: the native day-part word next to the time
# (సాయంత్రం 6:30 → pm) or a 24-hour clock (18:30 → pm). The model's writing
# style is untouched (still digits + native day-part per #408); the day-part
# word and the "గంటలకి/बजे" o'clock-word are consumed because am/pm now
# carries that meaning.
_AM_WORDS = ("ఉదయం", "పొద్దున్నే", "పొద్దున", "सुबह", "morning")
_PM_WORDS = ("మధ్యాహ్నం", "సాయంత్రం", "రాత్రి", "दोपहर", "शाम", "रात",
             "afternoon", "evening", "night")
_DAYPART_RE = "|".join(_AM_WORDS + _PM_WORDS)
_HOUR_WORD = r"(?:గంటలకి|గంటలకు|గంటలక|గంటకి|గంటలు|గంటల|बजे)"
_DP_TIME = re.compile(
    rf"(?:({_DAYPART_RE})\s*)(\d{{1,2}})(?::([0-5]\d))?(?:\s*{_HOUR_WORD})?"
)
# #421-call follow-up: "10:00 గంటలకు" WITHOUT a day-part word slipped through
# and spoke "ten gantalaku". Bare time + o'clock-word: consume the hour word
# too; meridiem only when the number proves it (24h / 12 = clinic noon).
_HW_TIME = re.compile(rf"\b(\d{{1,2}})(?::([0-5]\d))?\s*{_HOUR_WORD}")
# TTS read lowercase "am" as the word "amm" (Vinay, real call 2026-07-19).
# Dotted capitals are the letter-by-letter rendering every TTS agrees on.
_MER = {"am": "A.M.", "pm": "P.M."}
# A time that STATES its meridiem needs no inference — and the meridiem has to
# be rewritten too, or "10:00 am" keeps the bare "am" that TTS says as "amm"
# (the very reason _MER exists). Matched before every other time pass so the
# written meridiem always wins over one guessed from a day-part word.
_TIME_MER = re.compile(r"\b(\d{1,2}):([0-5]\d)\s*([ap])\.?\s*m\.?", re.IGNORECASE)


def _time_words(h: int, mi: int) -> str:
    h = h % 12 or 12          # 18:30 → six thirty; 0:xx → twelve xx
    if mi == 0:
        return _cardinal(h)
    if mi < 10:
        return f"{_cardinal(h)} oh {_ONES[mi]}"
    return f"{_cardinal(h)} {_cardinal(mi)}"


def _dp_time_sub(m: re.Match) -> str:
    daypart, h = m.group(1), int(m.group(2))
    mi = int(m.group(3) or 0)
    if h > 23 or (daypart in _AM_WORDS and h > 12):
        return m.group(0)  # not a plausible clock reading — leave untouched
    mer = _MER["am"] if daypart in _AM_WORDS else _MER["pm"]
    if h >= 13:
        mer = _MER["pm"]
    return f"{_time_words(h, mi)} {mer}"


def _hw_time_sub(m: re.Match) -> str:
    h = int(m.group(1))
    mi = int(m.group(2) or 0)
    if h > 23:
        return m.group(0)
    if h >= 13 or h == 12:
        return f"{_time_words(h, mi)} {_MER['pm']}"
    if h == 0:
        return f"{_time_words(h, mi)} {_MER['am']}"
    return _time_words(h, mi)  # 1-11, no day-part: no meridiem to prove


def _time_mer_sub(m: re.Match) -> str:
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23:
        return m.group(0)
    return f"{_time_words(h, mi)} {_MER[m.group(3).lower() + 'm']}"


def _bare_time_sub(m: re.Match) -> str:
    h, mi = int(m.group(1)), int(m.group(2))
    # 24h clock proves the meridiem; 12:xx is noon in clinic reality (#415).
    if h >= 13 or h == 0:
        return f"{_time_words(h, mi)} {_MER['am'] if h == 0 else _MER['pm']}"
    if h == 12:
        return f"{_time_words(h, mi)} {_MER['pm']}"
    return _time_words(h, mi)  # 1-11 with no context: no meridiem to prove


# ── #419 (Vinay 2026-07-19): currency speaks as ENGLISH "rupees" in every
# language — "500 rupees", never "500 రూపాయలు" / "रुपये". Deterministic like
# the digits: native rupee words → "rupees"; a leading ₹/Rs swaps behind the
# amount ("₹500" → "500 rupees") so the cardinal pass then makes it
# "five hundred rupees".
_RUPEE_WORDS = re.compile(
    r"రూపాయల[ుో]?|రూపాయలు|రూపాయిలు|రూపాయి|రూపాయ|रुपये|रुपए|रुपया|rupaye"
)
_RUPEE_PREFIX = re.compile(r"(?:₹|Rs\.?|రూ\.?)\s*(\d[\d,]*)")


def spoken_english_numbers(text: str) -> str:
    """Digits → spoken English words. Order matters: currency prefix swap and
    rupee words first, then day-part times (they own their digits + meridiem),
    then bare colon-times, then long runs (phones — one digit at a time), then
    any leftover short number (age, token, day) as a cardinal."""
    text = _RUPEE_PREFIX.sub(lambda m: f"{m.group(1).replace(',', '')} rupees", text)
    text = _RUPEE_WORDS.sub("rupees", text)
    text = _DP_TIME.sub(_dp_time_sub, text)
    text = _HW_TIME.sub(_hw_time_sub, text)
    text = _TIME.sub(_bare_time_sub, text)
    text = _LONG_RUN.sub(lambda m: " ".join(_ONES[int(c)] for c in m.group()), text)
    text = _SHORT_NUM.sub(lambda m: _cardinal(int(m.group())), text)
    # #408 also: Hindi TTS clips "डॉक्टर" to "doc" — the phonetic spelling
    # "डाक्टर" says the full word (Vinay picked it from live samples).
    return text.replace("डॉक्टर", "डाक्टर")


def spoken_clock_times(text: str) -> str:
    """Clock times → spoken words, in EVERY language.

    Vinay 2026-08-08: "time is getting read as 6 colon zero zero instead of
    6pm sometimes."

    These three passes have existed since #415/#421 but only ever ran inside
    spoken_english_numbers, which stopped being the production TTS boundary
    when sanitize_for_tts moved to spoken_phone_digits — and that one leaves
    times untouched on the theory that "Soniox can render them naturally in
    the call language". It cannot: a bare "6:00" comes out as the literal
    characters. "Sometimes" is the tell — the model writes "సాయంత్రం ఆరు"
    on most turns and a numeric "6:00" on the rest, and only the numeric ones
    broke. RULE 6: nothing reaches TTS unsanitized, and a colon is a symbol.

    Word order matters. The day-part pass owns its digits and meridiem, then
    the o'clock-word pass, then bare colon-times — narrowest first, so
    "సాయంత్రం 6:30 గంటలకు" is consumed once rather than three times.

    English words inside a Telugu sentence are deliberate, not a slip: #415 is
    Vinay asking for exactly that ("times speak WITH am/pm — 5pm, 3:30pm,
    10am — instead of 5 గంటలకి"), validated on real calls.
    """
    text = _TIME_MER.sub(_time_mer_sub, text or "")
    text = _DP_TIME.sub(_dp_time_sub, text)
    text = _HW_TIME.sub(_hw_time_sub, text)
    text = _TIME.sub(_bare_time_sub, text)
    # An o'clock-word swallowed by _HW_TIME can leave the sentence stop
    # stranded next to the meridiem's own dot ("six P.M..").
    return re.sub(r"\.\.+(?=\s|$)", ".", text)


def spoken_phone_digits(text: str) -> str:
    """Read only phone-length digit runs one digit at a time in English.

    Times, dates, ages, fees, and token numbers remain untouched so the model
    and Soniox can render them naturally in the call language. The old
    ``spoken_english_numbers`` helper remains for compatibility, but is no
    longer the production TTS boundary.
    """
    text = _PHONE_RUN.sub(
        lambda m: " ".join(_ONES[int(c)] for c in m.group()), text or ""
    )
    return text.replace("डॉक्टर", "डाक्टर")


def sanitize_for_tts(text: str) -> str:
    text = strip_model_control_tokens(text)
    text = strip_internal_tool_speech(text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'^\*\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'#(\d+)', r'\1', text)
    text = re.sub(r'^(\d+)\.\s+', r'\1 ', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*-\s+', '', text, flags=re.MULTILINE)
    text = _strip_emoji(text)
    # Before the phone pass: times are 1-2 digit groups and phone runs are
    # 10-15, so they cannot collide — but a time left as digits here would be
    # the last chance to catch it.
    text = spoken_clock_times(text)
    text = spoken_phone_digits(text)
    text = re.sub(r'  +', ' ', text)
    return text.strip()


def _strip_emoji(text: str) -> str:
    result = []
    for char in text:
        cat = unicodedata.category(char)
        if cat[0] == 'S' and cat != 'Sc':
            continue
        result.append(char)
    return ''.join(result)
