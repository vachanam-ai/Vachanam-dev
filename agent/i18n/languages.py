"""Language registry: Branch.language code -> Sarvam codes + display names.

Sarvam Saaras v3 (STT) and Bulbul v3 (TTS) both accept the *-IN language codes
below. Bulbul speakers are language-agnostic — the SAME speaker (Branch.tts_voice)
voices any target_language_code — so only the language code changes per clinic,
not the speaker.

NOTE on Odia: ISO code is "or" but Sarvam's API code is "od-IN". We key on "or"
internally and emit "od-IN" to Sarvam.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class LangConfig:
    code: str          # internal short key (Branch.language)
    name: str          # English name, used in the system prompt directive
    native_name: str   # endonym, shown in the Settings dropdown
    script: str        # script name, used in the system prompt directive
    stt_code: str      # Sarvam Saaras language=
    tts_code: str      # Sarvam Bulbul target_language_code=


# Telugu first (reference/default), then the rest of the MVP language set.
LANGUAGES: dict[str, LangConfig] = {
    "te": LangConfig("te", "Telugu", "తెలుగు", "Telugu", "te-IN", "te-IN"),
    "hi": LangConfig("hi", "Hindi", "हिन्दी", "Devanagari", "hi-IN", "hi-IN"),
    "ta": LangConfig("ta", "Tamil", "தமிழ்", "Tamil", "ta-IN", "ta-IN"),
    "kn": LangConfig("kn", "Kannada", "ಕನ್ನಡ", "Kannada", "kn-IN", "kn-IN"),
    "ml": LangConfig("ml", "Malayalam", "മലയാളം", "Malayalam", "ml-IN", "ml-IN"),
    "mr": LangConfig("mr", "Marathi", "मराठी", "Devanagari", "mr-IN", "mr-IN"),
    "bn": LangConfig("bn", "Bengali", "বাংলা", "Bengali", "bn-IN", "bn-IN"),
    "or": LangConfig("or", "Odia", "ଓଡ଼ିଆ", "Odia", "od-IN", "od-IN"),
}

DEFAULT_LANG = "te"


def get_lang(code: str | None) -> LangConfig:
    """Resolve a Branch.language code to its config, falling back to Telugu for
    None / unknown / legacy rows so a bad value can NEVER break a live call."""
    return LANGUAGES.get((code or "").lower().strip(), LANGUAGES[DEFAULT_LANG])
