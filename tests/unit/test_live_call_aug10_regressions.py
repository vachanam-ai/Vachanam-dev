"""Regression proof for the 2026-08-10 Venkateshwara live call."""

from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agent.livekit_minimal import agent as agent_mod
from agent.livekit_minimal.agent import (
    VachanamAgent,
    _explicit_roster_doctor_id,
    _is_incomplete_fragment,
    _is_reminder_policy_question,
    _reminder_policy_text,
    cache_filler_clips,
)
from agent.prompts.grounded_prompt import _doctor_rows
from agent.prompts.system_prompt import DoctorContext
from agent.services.spoken_words import speech_map
from agent.session_state import SessionState


def _doctor(name: str, doctor_id=None) -> DoctorContext:
    return DoctorContext(
        id=str(doctor_id or uuid4()),
        name=name,
        specialization="test",
        routing_keywords=[],
        booking_type="appointment",
        is_default=False,
    )


def test_telugu_lakshmi_name_overrides_stale_srinivas_context():
    lakshmi = _doctor("Dr. Lakshmi")
    srinivas = _doctor("Dr. Srinivas")
    assert _explicit_roster_doctor_id(
        "డాక్టర్ లక్ష్మి గారి గురించి మాట్లాడుతున్నానండి",
        [srinivas, lakshmi],
    ) == uuid_from(lakshmi)


def test_two_explicit_doctor_names_are_never_guessed():
    lakshmi = _doctor("Lakshmi")
    srinivas = _doctor("Srinivas")
    assert _explicit_roster_doctor_id(
        "Lakshmi or Srinivas", [lakshmi, srinivas]
    ) is None


def uuid_from(doctor: DoctorContext):
    from uuid import UUID

    return UUID(doctor.id)


@pytest.mark.asyncio
async def test_pinned_caller_doctor_beats_llm_stale_uuid():
    lakshmi_id, srinivas_id = uuid4(), uuid4()
    state = SessionState(
        doctor_id=lakshmi_id,
        caller_named_doctor_id=lakshmi_id,
    )
    fake = SimpleNamespace(_state=state, _db=AsyncMock())
    resolved = await VachanamAgent._resolve_doctor_id(fake, str(srinivas_id))
    assert resolved == lakshmi_id
    fake._db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_routing_tool_cannot_replace_explicit_caller_choice():
    lakshmi = _doctor("Dr. Lakshmi")
    lakshmi_id = uuid_from(lakshmi)
    state = SessionState(
        doctor_id=lakshmi_id,
        caller_named_doctor_id=lakshmi_id,
    )
    fake = SimpleNamespace(
        _state=state,
        _doctor_contexts=[lakshmi, _doctor("Dr. Srinivas")],
    )
    result = await VachanamAgent.route_to_doctor.__wrapped__(
        fake, SimpleNamespace(), "old dental context"
    )
    assert result["doctor_id"] == str(lakshmi_id)
    assert result["doctor_name"] == "Dr. Lakshmi"


@pytest.mark.parametrize("fragment", ["డా", "డా.", "dr", "Dr."])
def test_clipped_doctor_title_waits_for_caller_to_finish(fragment):
    assert _is_incomplete_fragment(fragment)


def test_reminder_questions_are_intercepted_before_the_llm():
    assert _is_reminder_policy_question(
        "నాకు రిమైండర్ ఆరు గంటల ముందు వస్తుందా?"
    )
    assert _is_reminder_policy_question("Will I get a reminder?")


def test_scheduler_policy_promises_only_thirty_minute_reminder():
    english = _reminder_policy_text("en", "enabled").casefold()
    assert "thirty minutes" in english
    assert "one day" not in english
    assert "twenty-four" not in english


@pytest.mark.asyncio
async def test_real_token_lead_time_selects_thirty_minute_policy():
    token = SimpleNamespace(
        date=date(2026, 8, 11),
        appointment_time=time(12, 0),
        created_at=datetime(2026, 8, 10, 13, 30, tzinfo=timezone.utc),
    )
    doctor = SimpleNamespace(
        booking_type="appointment",
        pre_appointment_reminder=True,
    )
    first_result = SimpleNamespace(first=lambda: (token, doctor))
    db = SimpleNamespace(execute=AsyncMock(return_value=first_result))
    fake = SimpleNamespace(
        _state=SessionState(
            branch_id=uuid4(),
            last_confirmed_token_id=uuid4(),
        ),
        _db=db,
        _timezone_name="Asia/Kolkata",
    )
    speech = await VachanamAgent._reminder_policy_speech(fake, "en")
    assert "thirty minutes before" in speech
    assert "one day before" not in speech


@pytest.mark.asyncio
async def test_old_language_filler_cannot_install_after_handoff(monkeypatch):
    session = SimpleNamespace(userdata={"language": "te", "wait_clips": []})

    async def _fake_synth(*_args, **_kwargs):
        return [b"wav"]

    monkeypatch.setattr(agent_mod, "synth_wavs", _fake_synth)
    monkeypatch.setattr(agent_mod, "_wav_to_pcm", lambda _wav: (b"pcm", 16000, 1))
    await cache_filler_clips(
        session,
        ["ज़रा देख लेते हैं... [long pause]"],
        "voice",
        "hi",
        key="wait_clips",
    )
    assert session.userdata["wait_clips"] == []
    assert session.userdata.get("wait_clips_language") != "hi"


def test_prompt_doctor_order_is_deterministic_for_cache_key():
    a, b = _doctor("Lakshmi"), _doctor("Srinivas")
    assert _doctor_rows([a, b]) == _doctor_rows([b, a])


def test_english_clock_words_are_normalized_on_telugu_audio_boundary():
    mapping = speech_map("te")
    assert mapping["nine"] != "nine"
    assert mapping["twelve"] != "twelve"
    assert mapping["p.m."] == "పీ ఎం"
