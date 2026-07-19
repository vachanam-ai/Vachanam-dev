import re
import unicodedata

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
    mer = "am" if daypart in _AM_WORDS else "pm"
    if h >= 13:
        mer = "pm"
    return f"{_time_words(h, mi)} {mer}"


def _bare_time_sub(m: re.Match) -> str:
    h, mi = int(m.group(1)), int(m.group(2))
    # 24h clock proves the meridiem; 12:xx is noon in clinic reality (#415).
    if h >= 13 or h == 0:
        return f"{_time_words(h, mi)} {'am' if h == 0 else 'pm'}"
    if h == 12:
        return f"{_time_words(h, mi)} pm"
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
    text = _TIME.sub(_bare_time_sub, text)
    text = _LONG_RUN.sub(lambda m: " ".join(_ONES[int(c)] for c in m.group()), text)
    text = _SHORT_NUM.sub(lambda m: _cardinal(int(m.group())), text)
    # #408 also: Hindi TTS clips "डॉक्टर" to "doc" — the phonetic spelling
    # "डाक्टर" says the full word (Vinay picked it from live samples).
    return text.replace("डॉक्टर", "डाक्टर")


def sanitize_for_tts(text: str) -> str:
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'^\*\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'#(\d+)', r'\1', text)
    text = re.sub(r'^(\d+)\.\s+', r'\1 ', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*-\s+', '', text, flags=re.MULTILINE)
    text = _strip_emoji(text)
    text = spoken_english_numbers(text)
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
