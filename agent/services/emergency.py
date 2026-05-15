_EMERGENCY_KEYWORDS = [
    "heart attack",
    "chest pain",
    "unconscious",
    "not breathing",
    "severe bleeding",
    "padipōyāḍu",
    "stroke",
    "seizure",
    "collapsed",
    "fainted",
]


def is_emergency(text: str) -> bool:
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in _EMERGENCY_KEYWORDS)
