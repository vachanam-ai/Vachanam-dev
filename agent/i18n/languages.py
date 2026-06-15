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
    stt_code: str      # Sarvam Saaras language= (STT)
    tts_code: str      # smallest.ai Waves `language` (TTS) — short code, same as `code`
    default_voice: str  # smallest.ai voice_id when the clinic hasn't chosen one

    @property
    def tts_lang(self) -> str:
        """smallest.ai TTS language code. smallest uses the same short codes as
        our internal keys (te/hi/ta/kn/ml/mr/bn/or), so this is just `code`."""
        return self.tts_code


# TTS = smallest.ai Waves Lightning v3.1. Language codes match smallest's short
# codes exactly (verified against GET /lightning-v3.1/get_voices, 2026-06-15).
# Default voices picked from the live catalog: `padmaja` covers the Dravidian
# pool (te/ta/kn/ml); `niharika` covers hi/mr/bn/or. STT stays Sarvam Saaras
# (the *-IN codes). Telugu first (reference/default).
LANGUAGES: dict[str, LangConfig] = {
    "te": LangConfig("te", "Telugu", "తెలుగు", "Telugu", "te-IN", "te", "padmaja"),
    "hi": LangConfig("hi", "Hindi", "हिन्दी", "Devanagari", "hi-IN", "hi", "niharika"),
    "ta": LangConfig("ta", "Tamil", "தமிழ்", "Tamil", "ta-IN", "ta", "padmaja"),
    "kn": LangConfig("kn", "Kannada", "ಕನ್ನಡ", "Kannada", "kn-IN", "kn", "padmaja"),
    "ml": LangConfig("ml", "Malayalam", "മലയാളം", "Malayalam", "ml-IN", "ml", "padmaja"),
    "mr": LangConfig("mr", "Marathi", "मराठी", "Devanagari", "mr-IN", "mr", "niharika"),
    "bn": LangConfig("bn", "Bengali", "বাংলা", "Bengali", "bn-IN", "bn", "niharika"),
    "or": LangConfig("or", "Odia", "ଓଡ଼ିଆ", "Odia", "od-IN", "or", "niharika"),
}

DEFAULT_LANG = "te"


def get_lang(code: str | None) -> LangConfig:
    """Resolve a Branch.language code to its config, falling back to Telugu for
    None / unknown / legacy rows so a bad value can NEVER break a live call."""
    return LANGUAGES.get((code or "").lower().strip(), LANGUAGES[DEFAULT_LANG])
