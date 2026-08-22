"""Deterministic transcript checks that the post-call LLM judge cannot waive."""

from __future__ import annotations


_CHECK_PROMISE_MARKERS = (
    # English / common code-switching.
    "let me check",
    "i'll check",
    "i will check",
    "i'm checking",
    "i am checking",
    "check and tell",
    "check karke bat",
    # Telugu.
    "చెక్ చేసి చెప్త",
    "చెక్ చేసి చెబుత",
    "చెక్ చేస్తున్న",
    "చూసి చెప్త",
    # Other supported-language phrases seen in receptionist speech.
    "चेक करके बता",
    "जाँच करके बता",
    "செக் பண்ணி சொல்",
    "ಚೆಕ್ ಮಾಡಿ ಹೇಳ",
    "तपासून सांग",
    "ചെക്ക് ചെയ്ത് പറയ",
    "চেক করে বল",
)

_LINE_WATCHDOG_MARKERS = (
    "hello are you there",
    "are you still on the line",
    "are you on the line",
    "మీరు ఉన్నారా",
    "లైన్ లో ఉన్నారా",
    "లైన్ లోనే ఉన్నారా",
    "आप लाइन पर हैं",
    "லைனில் இருக்கீங்களா",
    "ಲೈನ್ ನಲ್ಲಿ ಇದ್ದೀರಾ",
    "लाइनवर आहात",
    "ലൈനിൽ ഉണ്ടോ",
    "লাইনে আছেন",
)


def _normalized(text: str) -> str:
    return " ".join(
        text.casefold()
        .replace("’", "'")
        .replace("‌", " ")
        .replace("-", " ")
        .translate(str.maketrans("", "", ",.?!…"))
        .split()
    )


def has_unresolved_check(transcript: str | None) -> bool:
    """Return true when a promised lookup is followed by a liveness failure.

    Patient turns do not settle a pending promise. The next agent turn must
    deliver an answer; another checking promise or a line-presence watchdog is
    deterministic evidence that the promised lookup was left unresolved.
    """
    if not transcript:
        return False

    pending_check = False
    for raw_line in transcript.splitlines():
        role, separator, content = raw_line.partition(":")
        if not separator or role.strip().casefold() != "agent":
            continue

        text = _normalized(content)
        promises_check = any(marker in text for marker in _CHECK_PROMISE_MARKERS)
        line_watchdog = any(marker in text for marker in _LINE_WATCHDOG_MARKERS)

        if pending_check and (promises_check or line_watchdog):
            return True
        if promises_check:
            pending_check = True
        elif pending_check:
            # A different agent turn is treated as the owed answer. This keeps
            # the rule narrow: it does not try to judge medical/booking truth.
            pending_check = False

    # A completed transcript that ends on the promise is itself unresolved.
    # There may be no later agent turn when the caller gives up during the
    # silence, which was the exact failure this rule is meant to surface.
    return pending_check
