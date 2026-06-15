# Multilingual voice lines — review & refine

> **Status (2026-06-15):** per-clinic language infra is LIVE. A clinic picks its
> language in **Settings → Agent language**; the agent then speaks that language
> end-to-end (Sarvam STT/TTS codes + spoken lines + a PRIMARY-LANGUAGE prompt
> directive). Telugu is the validated reference. The other 7 are **first-pass**
> and need a native speaker's pass before that clinic goes live.

## How a language is wired

| Layer | Source | Per-language? |
|---|---|---|
| STT / TTS language code | `agent/i18n/languages.py` | yes (`stt_code`, `tts_code`) |
| TTS speaker (voice) | `Branch.tts_voice` | no — Bulbul speakers voice any language |
| Hardcoded spoken lines (greetings, fillers, reminder/rebook, service-blocked, caps) | `agent/i18n/lines.py` | yes |
| LLM speech (booking flow) | `agent/prompts/system_prompt.py` PRIMARY-LANGUAGE directive | yes (directive); examples stay Telugu as style refs |

**To add/refine a language:** edit `agent/i18n/lines.py` (the `Lines` block for
that code) and, if needed, `languages.py`. Re-run
`tests/unit/test_multilingual.py` (it script-checks every line).

## Language status

| Code | Language | Sarvam STT/TTS | Spoken-lines status |
|---|---|---|---|
| `te` | Telugu (తెలుగు) | te-IN | ✅ REFERENCE — Vinay-validated |
| `hi` | Hindi (हिन्दी) | hi-IN | first-pass (reasonable) |
| `ta` | Tamil (தமிழ்) | ta-IN | ⚠ FIRST-PASS — needs native review |
| `kn` | Kannada (ಕನ್ನಡ) | kn-IN | ⚠ FIRST-PASS — needs native review |
| `ml` | Malayalam (മലയാളം) | ml-IN | ⚠ FIRST-PASS — needs native review |
| `mr` | Marathi (मराठी) | mr-IN | ⚠ FIRST-PASS — needs native review |
| `bn` | Bengali (বাংলা) | bn-IN | ⚠ FIRST-PASS — needs native review |
| `or` | Odia (ଓଡ଼ିଆ) | **od-IN** | ⚠ FIRST-PASS — needs native review |

## Spoken lines per language (the 9 hardcoded strings)

Each language defines: `disclosure_greeting`, `known_caller_greeting`,
`reminder_greeting`, `rebook_greeting`, `service_blocked`, `cap_warning`,
`cap_goodbye`, plus 4 `fillers`. Placeholders `{clinic} {patient} {doctor}
{time} {date}` are filled at runtime — keep them.

**To flag a line:** tell me the language code + which line + your version, and
I'll drop it in verbatim (same flow as the Telugu review in
`telugu_static_lines.md`).

## Known first-pass limitations

- **Date/time words in reminder & rebook calls** render in **Telugu number-words
  only for Telugu clinics**; other languages get a plain `04:30 PM` / `12 June`
  (loanword reading) — natural enough, but not localized number-words yet.
- **System-prompt examples** remain in Telugu script as style references; the
  PRIMARY-LANGUAGE directive instructs the model to speak the equivalent in the
  clinic's language. Works well on Gemini/GPT, but spot-check each language on a
  real call before launch.
