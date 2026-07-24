import re
import unicodedata

# Internal execution language must never reach a caller. This is a deterministic
# boundary check, not a request to the LLM. Keep patient-safe words such as
# "appointment" and "calendar date" out of this list; match only implementation
# identifiers and explicit execution narration.
_INTERNAL_TRACE = re.compile(
    r"(?i)(?:\bexecuting\b|\btool[ _-]?call\b|\bfunction[ _-]?call\b|"
    r"calendar\.tool|\b(?:old_token_id|new_date|new_time|token_id|doctor_id|"
    r"patient_phone|different_person|booking_for_other)\b\s*[:=]?|"
    r"\b(?:confirm_booking|reschedule_booking|cancel_booking|check_availability|"
    r"route_to_doctor|assign_token|find_my_bookings|get_queue_status)\b)"
)


def internal_trace_match(text: str):
    """Return the first private-execution marker in speech, if present."""
    return _INTERNAL_TRACE.search(text or "")


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
    text = strip_internal_tool_speech(text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'^\*\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'#(\d+)', r'\1', text)
    text = re.sub(r'^(\d+)\.\s+', r'\1 ', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*-\s+', '', text, flags=re.MULTILINE)
    text = _strip_emoji(text)
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
