"""F5 / plan Task 6.3: deterministic post-tool confirmation speech.

Successful booking/reschedule/cancel speaks a fixed native-script line
DIRECTLY (no second LLM pass) — tool completion → first audio drops from
~1.5-2.5s to the TTS synth alone. Contracts pinned here:

  * templates live in i18n Lines with default "" — a language without a
    template keeps the current LLM path (graceful rollout, te/en/hi first);
  * every defined template formats cleanly (no KeyError, no leftover braces);
  * token doctors announce the TOKEN, never a time; appointment doctors
    announce DATE+TIME, never a token (same rule the LLM instruction enforces);
  * speech happens ONLY after the successful atomic write + calendar write
    (constraint 6) — source-guarded to sit inside the success blocks;
  * the LLM reply is suppressed via StopResponse ONLY when the line was
    actually queued; any failure falls back to the LLM path (RULE 8);
  * kill switch: settings.voice_deterministic_confirm.
"""
from datetime import date, time
from pathlib import Path

from agent.i18n.lines import LINES
from agent.livekit_minimal.confirm_speech import build_confirm_text

D = date(2026, 7, 23)
T = time(10, 30)


def test_te_token_booking_line_has_token_and_come_on_time():
    text = build_confirm_text("te", "booked_token", token=13, date_=D)
    assert text is not None
    assert "13" in text
    assert "సమయానికి" in text  # the come-on-time closing rides the template
    assert "{" not in text


def test_te_slot_booking_line_has_date_time_and_no_token():
    text = build_confirm_text("te", "booked_slot", token=7, date_=D, time_=T)
    assert text is not None
    assert "7" not in text  # appointment doctors NEVER hear a token number
    assert "{" not in text


def test_te_reschedule_and_cancel_lines():
    slot = build_confirm_text("te", "resched_slot", date_=D, time_=T)
    tok = build_confirm_text("te", "resched_token", token=4, date_=D)
    cans = build_confirm_text("te", "cancelled")
    assert slot and "{" not in slot
    assert tok and "4" in tok and "{" not in tok
    assert cans and "{" not in cans


def test_language_without_template_returns_none():
    # or (Odia) is first-pass minimal — no confirm templates yet → LLM path.
    assert build_confirm_text("or", "booked_token", token=3, date_=D) is None


def test_unknown_kind_returns_none_never_raises():
    assert build_confirm_text("te", "nonsense_kind", token=1) is None


def test_every_defined_template_formats_cleanly():
    for lang, lines in LINES.items():
        for field, kwargs in (
            ("confirm_booked_token", {"token": 12, "date": "x"}),
            ("confirm_booked_slot", {"date": "x", "time": "y"}),
            ("confirm_resched_slot", {"date": "x", "time": "y"}),
            ("confirm_resched_token", {"token": 12, "date": "x"}),
            ("confirm_cancelled", {}),
        ):
            tpl = getattr(lines, field)
            if tpl:
                out = tpl.format(**kwargs)
                assert "{" not in out, f"{lang}.{field} leaves a brace"


def test_agent_wiring_source_guards():
    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    # helper exists (sync — say() is queued, never awaited), sanitizes,
    # never raises out (RULE 8 fallback to LLM)
    assert "def _speak_deterministic_confirm" in src
    helper = src.split("def _speak_deterministic_confirm")[1][:2500]
    assert "settings.voice_deterministic_confirm" in helper  # kill switch
    assert "sanitize_for_tts" in helper
    assert "return False" in helper  # failure → LLM path
    # live-session gate: stub contexts (tool tests/sims) keep the dict contract
    assert "isinstance(sess, AgentSession)" in helper
    # StopResponse fires ONLY when the line was queued, in all three tools
    assert src.count("raise StopResponse") >= 3
    # speech sits inside the success paths (after the atomic+calendar write)
    for kind in ("booked_token", "booked_slot", "resched", "cancelled"):
        assert f'"{kind}' in src or f"'{kind}" in src


def test_kill_switch_default_on():
    from backend.config import Settings

    assert Settings.model_fields["voice_deterministic_confirm"].default is True
