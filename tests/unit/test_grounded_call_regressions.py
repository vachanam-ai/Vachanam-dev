"""Production regressions reported from the 2026-07-21 calls."""
from pathlib import Path

import pytest

from agent.livekit_minimal.agent import (
    REMINDER_PROMPT_EXTRA,
    _guard_internal_speech_stream,
)
from agent.prompts.system_prompt import DoctorContext, build_system_prompt
from agent.services.tts_sanitizer import sanitize_for_tts


def _prompt():
    return build_system_prompt(
        "Test Clinic",
        [
            DoctorContext("skin", "Dr Lakshmi", "skin", ["skin"], "appointment", False),
            DoctorContext(
                "dental", "Dr Srinivas", "dental", ["tooth", "పంటి"], "appointment", False
            ),
            DoctorContext("ent", "Dr Rao", "ENT", ["throat", "గొంతు"], "appointment", False),
        ],
        "+919999999999",
        "clinic",
    )


def test_current_symptom_replaces_previous_route_in_prompt():
    p = _prompt()
    assert "Only the latest COMPLETE utterance sets the need" in p
    assert "A new symptom replaces the old one" in p
    assert "never reuse the prior doctor" in p


def test_prompt_requires_panti_pani_contrastive_repair():
    p = _prompt()
    assert "పంటి సమస్యా, పని సమస్యా?" in p
    assert "A correction\nvoids the old route" in p


def test_reminder_prompt_has_no_speakable_tool_signature():
    assert "private_context" in REMINDER_PROMPT_EXTRA
    for forbidden in ("new_date", "new_time", "old_token_id", "calendar.tool", "executing"):
        assert forbidden not in REMINDER_PROMPT_EXTRA.lower()


def test_whole_text_sanitizer_removes_tool_trace_but_keeps_safe_sentence():
    raw = "సరే. Executing calendar.tool new_date: 2026-07-22. మీ అపాయింట్‌మెంట్ మారింది."
    out = sanitize_for_tts(raw)
    assert "Executing" not in out and "new_date" not in out and "calendar.tool" not in out
    assert "సరే" in out and "మీ అపాయింట్‌మెంట్ మారింది" in out


@pytest.mark.asyncio
async def test_stream_guard_catches_marker_split_across_chunks():
    async def chunks():
        for chunk in ("సరే. Exec", "uting calendar.", "tool new_", "date: tomorrow. ", "మార్చాను."):
            yield chunk

    out = "".join([part async for part in _guard_internal_speech_stream(chunks())])
    assert "Executing" not in out and "calendar" not in out and "new_date" not in out
    assert "సరే" in out and "మార్చాను" in out


def test_soniox_context_includes_specialties_and_medical_terms():
    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    assert "ContextGeneralItem" in src
    assert "d.routing_keywords" in src
    for term in ("పంటి సమస్య", "పళ్ళు", "గొంతు నొప్పి", "throat"):
        assert term in src


def test_route_tool_clears_stale_doctor_before_await():
    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    method = src.split("async def route_to_doctor(self", 1)[1].split("async def check_availability", 1)[0]
    # stale doctor cleared BEFORE the routing await (now routed via _consume_or_route,
    # #5 — prefetch consumption also happens after the clear).
    assert method.index("self._state.doctor_id = None") < method.index("await self._consume_or_route(")
