"""Spoken-Telugu dates for TTS.

An ISO date dropped into a TTS template gets read digit-by-digit
("sunna aaru okati rendu..."). Phone callers need month + day words:
2026-06-12 -> "జూన్ పన్నెండు, రెండువేల ఇరవై ఆరు" (year optional).
"""
from datetime import date, time

MONTHS_TE = [
    "జనవరి", "ఫిబ్రవరి", "మార్చి", "ఏప్రిల్", "మే", "జూన్",
    "జులై", "ఆగస్టు", "సెప్టెంబర్", "అక్టోబర్", "నవంబర్", "డిసెంబర్",
]

_ONES = [
    "", "ఒకటి", "రెండు", "మూడు", "నాలుగు", "ఐదు", "ఆరు", "ఏడు",
    "ఎనిమిది", "తొమ్మిది", "పది", "పదకొండు", "పన్నెండు", "పదమూడు",
    "పద్నాలుగు", "పదిహేను", "పదహారు", "పదిహేడు", "పద్దెనిమిది", "పంతొమ్మిది",
]
_TENS = {20: "ఇరవై", 30: "ముప్పై", 40: "నలభై", 50: "యాభై",
         60: "అరవై", 70: "డెబ్బై", 80: "ఎనభై", 90: "తొంభై"}


def telugu_number(n: int) -> str:
    """1-99 in Telugu words (good enough for days and 20xx year remainders)."""
    if n < 0 or n > 99:
        return str(n)
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    word = _TENS[tens * 10]
    return f"{word} {_ONES[ones]}".strip()


def telugu_year(y: int) -> str:
    if 2000 <= y <= 2099:
        rem = y - 2000
        return "రెండువేల" if rem == 0 else f"రెండువేల {telugu_number(rem)}"
    return str(y)


def telugu_date(d: date, with_year: bool = False) -> str:
    """'జూన్ పన్నెండు' / with_year: 'జూన్ పన్నెండు, రెండువేల ఇరవై ఆరు'."""
    spoken = f"{MONTHS_TE[d.month - 1]} {telugu_number(d.day)}"
    return f"{spoken}, {telugu_year(d.year)}" if with_year else spoken


# 12-hour day-part words. A raw "16:30" into TTS reads digit-by-digit
# ("పదహారు ముప్పై") — a clinic time must be spoken like a person says it.
def telugu_time(t: time) -> str:
    """'మధ్యాహ్నం మూడున్నర' style: day-part + hour (+ 'అర' for :30).

    Falls back to plain hour+minute words for off-half times. Covers the
    common slot grid (:00 and :30)."""
    h24, minute = t.hour, t.minute
    if h24 < 12:
        part = "ఉదయం"
    elif h24 < 16:
        part = "మధ్యాహ్నం"
    elif h24 < 20:
        part = "సాయంత్రం"
    else:
        part = "రాత్రి"
    h12 = h24 % 12 or 12
    hour_word = telugu_number(h12)
    if minute == 0:
        return f"{part} {hour_word} గంటలకి"
    if minute == 30:
        return f"{part} {hour_word}న్నర"  # "X-and-a-half"
    return f"{part} {hour_word} {telugu_number(minute)}"
