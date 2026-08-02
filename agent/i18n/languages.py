"""Language registry for Soniox voice calls and optional Sarvam fallback.

The short code drives Soniox language hints and TTS. ``stt_code`` retains the
regional form required only by the explicitly configured Sarvam STT or
transliteration fallback.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class LangConfig:
    code: str          # internal short key (Branch.language)
    name: str          # English name, used in the system prompt directive
    native_name: str   # endonym, shown in the Settings dropdown
    script: str        # script name, used in the system prompt directive
    stt_code: str      # regional code for optional Sarvam fallback
    tts_code: str      # Soniox TTS language code — same as internal `code`
    default_voice: str  # Soniox catalog voice when the clinic hasn't chosen one

    @property
    def tts_lang(self) -> str:
        """Soniox TTS language code."""
        return self.tts_code


# Soniox tts-rt is multilingual; Priya is the default across languages. Clinics
# can choose any of the four catalog voices through Settings.
LANGUAGES: dict[str, LangConfig] = {
    "te": LangConfig("te", "Telugu", "తెలుగు", "Telugu", "te-IN", "te", "Priya"),
    # Indian English (en-IN fallback) — added 2026-07-03 for the
    # per-caller language mapping ("can you speak English?").
    "en": LangConfig("en", "English", "English", "Latin", "en-IN", "en", "Priya"),
    "hi": LangConfig("hi", "Hindi", "हिन्दी", "Devanagari", "hi-IN", "hi", "Priya"),
    "ta": LangConfig("ta", "Tamil", "தமிழ்", "Tamil", "ta-IN", "ta", "Priya"),
    "kn": LangConfig("kn", "Kannada", "ಕನ್ನಡ", "Kannada", "kn-IN", "kn", "Priya"),
    "ml": LangConfig("ml", "Malayalam", "മലയാളം", "Malayalam", "ml-IN", "ml", "Priya"),
    "mr": LangConfig("mr", "Marathi", "मराठी", "Devanagari", "mr-IN", "mr", "Priya"),
    "bn": LangConfig("bn", "Bengali", "বাংলা", "Bengali", "bn-IN", "bn", "Priya"),
}

DEFAULT_LANG = "te"


def get_lang(code: str | None) -> LangConfig:
    """Resolve a Branch.language code to its config, falling back to Telugu for
    None / unknown / legacy rows so a bad value can NEVER break a live call."""
    return LANGUAGES.get((code or "").lower().strip(), LANGUAGES[DEFAULT_LANG])
