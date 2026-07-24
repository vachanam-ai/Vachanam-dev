"""Per-language configuration for the Vachanam voice agent.

Two pieces:
  - languages.py: the registry mapping a clinic's chosen language (Branch.language)
    to its Sarvam STT/TTS codes and display names.
  - lines.py: every hardcoded spoken line (greetings, fillers, reminders, etc.)
    translated per language. These bypass the LLM, so they must be exact.

A clinic picks its language in Settings; the agent reads Branch.language and
resolves both the speech-provider config and the spoken lines through here.
Telugu ("te") is the reference/default and is always present.
"""
from .languages import DEFAULT_LANG, LANGUAGES, LangConfig, get_lang
from .lines import Lines, get_lines, get_recording_notice, get_switch_ack, get_welcome

__all__ = [
    "DEFAULT_LANG",
    "LANGUAGES",
    "LangConfig",
    "get_lang",
    "Lines",
    "get_lines",
    "get_recording_notice",
    "get_switch_ack",
    "get_welcome",
]
