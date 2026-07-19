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


def _time_words(m: re.Match) -> str:
    h, mi = int(m.group(1)), int(m.group(2))
    h = h % 12 or 12          # 18:30 → six thirty; 0:xx → twelve xx
    if mi == 0:
        return _cardinal(h)
    if mi < 10:
        return f"{_cardinal(h)} oh {_ONES[mi]}"
    return f"{_cardinal(h)} {_cardinal(mi)}"


def spoken_english_numbers(text: str) -> str:
    """Digits → spoken English words. Order matters: times (colon) first, then
    long runs (phones — one digit at a time), then any leftover short number
    (age, token, day) as a cardinal."""
    text = _TIME.sub(_time_words, text)
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
