"""Caller selections and audible confirmations bind every booking write."""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agent.livekit_minimal import agent as agent_mod
from agent.livekit_minimal.agent import (
    VachanamAgent,
    _explicit_clock_time,
    _guard_unverified_action_speech_stream,
)
from agent.livekit_minimal.confirm_speech import build_booking_failure_text
from agent.prompts.system_prompt import DoctorContext
from agent.services.caller_datetime import explicit_clock_times
from agent.session_state import SessionState


class _DB:
    def __init__(self):
        self.execute = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.add = MagicMock()


class _SpeechHandle:
    def __init__(self, playout: str):
        self._playout = playout

    async def wait_for_playout(self):
        if self._playout == "interrupted":
            raise RuntimeError("speech interrupted")
        if self._playout == "never":
            raise TimeoutError("speech never played")


class _Session:
    def __init__(self, *, playout: str = "complete"):
        self._playout = playout
        self.userdata = {
            "language": "en",
            "wait_clips": [],
            "wait_fillers": ("One moment, please. [long pause]",),
        }
        self.said = []

    def say(self, text, **kwargs):
        self.said.append((text, kwargs))
        if self.playout == "missing_wait":
            return SimpleNamespace()
        return _SpeechHandle(self.playout)

    @property
    def playout(self):
        return self._playout

    @playout.setter
    def playout(self, value):
        self._playout = value


class _Context:
    def __init__(self, *, playout: str = "complete"):
        self.session = _Session(playout=playout)
        self.pinned = False

    def disallow_interruptions(self):
        self.pinned = True


def _agent(
    state: SessionState,
    db: _DB,
    *,
    doctor_contexts: list[DoctorContext] | None = None,
) -> VachanamAgent:
    return VachanamAgent(
        instructions="test",
        state=state,
        db=db,
        room=None,
        calendar_service=object(),
        meta_service=None,
        transfer_to="",
        lang_code="en",
        doctor_contexts=doctor_contexts,
    )


async def _chunks(text: str):
    yield text


def _doctor(
    doctor_id,
    *,
    booking_type: str = "appointment",
    name: str = "Dr Rao",
) -> DoctorContext:
    return DoctorContext(
        id=str(doctor_id),
        name=name,
        specialization="general medicine",
        routing_keywords=[],
        booking_type=booking_type,
        is_default=True,
    )


def _booking_snapshot(
    doctor_id,
    booking_date: date,
    *,
    appointment_time: str | None = "17:00",
    patient_name: str = "Patient",
    doctor_name: str = "Dr Rao",
    booking_type: str = "appointment",
) -> dict[str, str | bool | None]:
    return {
        "patient_name": patient_name,
        "doctor_id": str(doctor_id),
        "doctor_name": doctor_name,
        "booking_date": booking_date.isoformat(),
        "appointment_time": appointment_time,
        "booking_type": booking_type,
        "followup_consent": True,
    }


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("Book it at 5 PM", "17:00"),
        ("5:15 p.m.", "17:15"),
        ("17:00", "17:00"),
        ("५:३० PM", "17:30"),
        ("Book me at 5", None),
        ("Come at 5 o'clock", None),
        ("5 గంటలకు బుక్ చేయండి", None),
        ("५ बजे बुक कर दीजिए", None),
        ("5 மணிக்கு புக் செய்யுங்கள்", None),
        ("5 ಗಂಟೆಗೆ ಬುಕ್ ಮಾಡಿ", None),
        ("5 മണിക്ക് ബുക്ക് ചെയ്യൂ", None),
        ("५ वाजता बुक करा", None),
        ("৫টায় বুক করুন", None),
        ("age 5", None),
        ("aged 5 years", None),
        ("token 5", None),
        ("phone number 5", None),
        ("age 5:15", None),
        ("phone 5:15", None),
        ("Appointment on 21.08.2026", None),
        ("5 PM or 6 PM", None),
        ("at 5 or 6", None),
    ],
)
def test_explicit_clock_time_is_conservative(utterance, expected):
    assert _explicit_clock_time(utterance) == expected


@pytest.mark.parametrize("hour", [1, 5, 11])
def test_bare_service_hour_preserves_am_pm_ambiguity(hour):
    assert explicit_clock_times(f"Book me at {hour}") == (
        f"{hour:02d}:00",
        f"{hour + 12:02d}:00",
    )
    assert _explicit_clock_time(f"Book me at {hour}") is None


def test_canonical_explicit_am_is_never_reinterpreted_as_pm():
    assert VachanamAgent._parse_time("05:00").strftime("%H:%M") == "05:00"
    assert VachanamAgent._parse_time("5 AM").strftime("%H:%M") == "05:00"
    assert VachanamAgent._parse_time("5:00").strftime("%H:%M") == "17:00"


@pytest.mark.asyncio
async def test_finalized_caller_turn_stores_time_independently_of_tool_arguments(
    monkeypatch,
):
    state = SessionState(language="en")
    agent = _agent(state, _DB())
    monkeypatch.setattr(agent, "_maybe_prefetch_routing", MagicMock())
    turn_context = SimpleNamespace(items=[], add_message=MagicMock())
    message = SimpleNamespace(text_content="5 PM", content="5 PM", role="user")

    await agent.on_user_turn_completed(turn_context, message)

    assert state.caller_booking_time == "17:00"


@pytest.mark.asyncio
async def test_finalized_bare_hour_turn_keeps_both_candidates(monkeypatch):
    state = SessionState(language="en")
    agent = _agent(state, _DB())
    monkeypatch.setattr(agent, "_maybe_prefetch_routing", MagicMock())
    turn_context = SimpleNamespace(items=[], add_message=MagicMock())
    message = SimpleNamespace(
        text_content="Book me at 5",
        content="Book me at 5",
        role="user",
    )

    await agent.on_user_turn_completed(turn_context, message)

    assert state.caller_booking_times == ("05:00", "17:00")
    assert state.caller_booking_time is None


@pytest.mark.asyncio
async def test_model_cannot_hold_six_when_caller_selected_five(monkeypatch):
    state = SessionState(
        session_id="caller-five-hold-six",
        branch_id=uuid4(),
        caller_booking_time="17:00",
    )
    db = _DB()
    agent = _agent(state, db)
    doctor_id = uuid4()
    core_assign = AsyncMock()
    monkeypatch.setattr(agent, "_resolve_doctor_id", AsyncMock(return_value=doctor_id))
    monkeypatch.setattr(agent_mod, "assign_token", core_assign)

    result = await agent.assign_token(
        context=None,
        doctor_id=str(doctor_id),
        booking_date=(date.today() + timedelta(days=7)).isoformat(),
        appointment_time="18:00",
    )

    assert result["success"] is False
    assert result["reason"] == "caller_selection_mismatch"
    assert result["caller_times"] == ["17:00"]
    assert result["received_time"] == "18:00"
    core_assign.assert_not_awaited()
    db.commit.assert_not_awaited()
    assert state.token_held is False


@pytest.mark.asyncio
async def test_fully_played_server_question_arms_exact_confirmation(monkeypatch):
    branch_id = uuid4()
    doctor_id = uuid4()
    day = date.today() + timedelta(days=7)
    state = SessionState(
        branch_id=branch_id,
        patient_phone="+919000000111",
        last_user_utterance="Book me with Dr Rao at 5 PM",
        caller_asked_to_book=False,
        caller_booking_date=day.isoformat(),
        caller_booking_times=("17:00",),
        caller_booking_time="17:00",
        token_held=True,
        token_number=1,
        token_redis_key=f"slot:{doctor_id}:{branch_id}:{day}:1700",
    )
    agent = _agent(state, _DB(), doctor_contexts=[_doctor(doctor_id)])
    context = _Context(playout="complete")
    core_confirm = AsyncMock()
    monkeypatch.setattr(agent_mod, "AgentSession", _Session)
    monkeypatch.setattr(agent_mod, "confirm_booking", core_confirm)

    with pytest.raises(agent_mod.StopResponse):
        await agent.confirm_booking(
            context=context,
            doctor_id=str(doctor_id),
            patient_name="Patient",
            booking_date=day.isoformat(),
            appointment_time="17:00",
        )

    core_confirm.assert_not_awaited()
    assert state.pending_confirmation == "book"
    assert state.booking_confirmation_granted is False
    assert state.booking_confirmation_snapshot == _booking_snapshot(doctor_id, day)
    assert len(context.session.said) == 1
    spoken = context.session.said[0][0]
    assert "Patient" in spoken
    assert "Dr Rao" in spoken
    assert "five P.M." in spoken


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("playout", "error_type"),
    [
        ("missing_wait", agent_mod.ToolError),
        ("interrupted", agent_mod.StopResponse),
        ("never", agent_mod.StopResponse),
    ],
)
async def test_unverified_confirmation_playout_never_arms_write_consent(
    monkeypatch,
    playout,
    error_type,
):
    branch_id = uuid4()
    doctor_id = uuid4()
    day = date.today() + timedelta(days=7)
    state = SessionState(
        branch_id=branch_id,
        patient_phone="+919000000111",
        last_user_utterance="Book me with Dr Rao at 5 PM",
        caller_booking_date=day.isoformat(),
        caller_booking_times=("17:00",),
        caller_booking_time="17:00",
    )
    agent = _agent(state, _DB(), doctor_contexts=[_doctor(doctor_id)])
    context = _Context(playout=playout)
    core_confirm = AsyncMock()
    monkeypatch.setattr(agent_mod, "AgentSession", _Session)
    monkeypatch.setattr(agent_mod, "confirm_booking", core_confirm)

    with pytest.raises(error_type):
        await agent.confirm_booking(
            context=context,
            doctor_id=str(doctor_id),
            patient_name="Patient",
            booking_date=day.isoformat(),
            appointment_time="17:00",
        )

    core_confirm.assert_not_awaited()
    assert state.pending_confirmation is None
    assert state.booking_confirmation_snapshot == {}
    assert state.booking_confirmation_granted is False
    assert state.token_confirmed is False


@pytest.mark.asyncio
async def test_model_cannot_override_confirmed_five_with_six(monkeypatch):
    branch_id = uuid4()
    doctor_id = uuid4()
    day = date.today() + timedelta(days=7)
    state = SessionState(
        session_id="caller-five-confirm-six",
        branch_id=branch_id,
        patient_phone="+919000001111",
        last_user_utterance="please book it",
        caller_asked_to_book=True,
        booking_confirmation_granted=True,
        booking_confirmation_snapshot=_booking_snapshot(doctor_id, day),
        caller_booking_date=day.isoformat(),
        caller_booking_times=("17:00",),
        caller_booking_time="17:00",
        token_held=True,
        token_number=1,
        token_redis_key=f"slot:{doctor_id}:{branch_id}:{day}:1700",
        appointment_time="17:00",
    )
    db = _DB()
    agent = _agent(state, db, doctor_contexts=[_doctor(doctor_id)])
    context = _Context()
    core_assign = AsyncMock()
    core_confirm = AsyncMock(return_value={
        "success": True,
        "token_id": str(uuid4()),
        "patient_id": str(uuid4()),
        "announce": "time_only",
    })
    deterministic_speech = MagicMock(return_value=False)
    monkeypatch.setattr(agent, "_resolve_doctor_id", AsyncMock(return_value=doctor_id))
    monkeypatch.setattr(agent, "_speak_deterministic_confirm", deterministic_speech)
    release_hold = AsyncMock()
    monkeypatch.setattr(agent, "_release_hold", release_hold)
    monkeypatch.setattr(agent_mod, "assign_token", core_assign)
    monkeypatch.setattr(agent_mod, "confirm_booking", core_confirm)

    result = await agent.confirm_booking(
        context=context,
        doctor_id=str(doctor_id),
        patient_name="Patient",
        booking_date=day.isoformat(),
        appointment_time="18:00",
        patient_age=30,
    )

    assert result["success"] is True
    core_assign.assert_not_awaited()
    core_confirm.assert_awaited_once()
    assert core_confirm.await_args.kwargs["appointment_time"].strftime("%H:%M") == "17:00"
    assert state.token_confirmed is True
    assert state.token_held is False
    assert state.token_redis_key is None
    release_hold.assert_not_awaited()


@pytest.mark.asyncio
async def test_spoken_snapshot_overrides_untrusted_retry_arguments(monkeypatch):
    branch_id = uuid4()
    doctor_id = uuid4()
    day = date.today() + timedelta(days=7)
    state = SessionState(
        session_id="held-five-tool-six",
        branch_id=branch_id,
        patient_phone="+919000002222",
        last_user_utterance="please book it",
        caller_asked_to_book=True,
        booking_confirmation_granted=True,
        booking_confirmation_snapshot=_booking_snapshot(doctor_id, day),
        caller_booking_time=None,
        token_held=True,
        token_number=1,
        token_redis_key=f"slot:{doctor_id}:{branch_id}:{day}:1700",
        appointment_time="17:00",
    )
    db = _DB()
    agent = _agent(state, db, doctor_contexts=[_doctor(doctor_id)])
    context = _Context()
    core_assign = AsyncMock()
    token_id = uuid4()
    patient_id = uuid4()
    core_confirm = AsyncMock(
        return_value={
            "success": True,
            "token_id": str(token_id),
            "patient_id": str(patient_id),
            "announce": "time_only",
        }
    )
    monkeypatch.setattr(agent, "_resolve_doctor_id", AsyncMock(return_value=doctor_id))
    monkeypatch.setattr(agent, "_speak_deterministic_confirm", MagicMock(return_value=False))
    monkeypatch.setattr(agent_mod, "assign_token", core_assign)
    monkeypatch.setattr(agent_mod, "confirm_booking", core_confirm)

    result = await agent.confirm_booking(
        context=context,
        doctor_id=str(doctor_id),
        patient_name="Patient",
        booking_date=day.isoformat(),
        appointment_time="18:00",
        patient_age=30,
    )

    assert result["success"] is True
    core_assign.assert_not_awaited()
    core_confirm.assert_awaited_once()
    assert core_confirm.await_args.kwargs["appointment_time"].strftime("%H:%M") == "17:00"
    assert core_confirm.await_args.kwargs["booking_date"] == day
    assert core_confirm.await_args.kwargs["doctor_id"] == doctor_id
    assert state.token_confirmed is True
    assert state.last_confirmed_token_id == token_id
    assert state.booking_confirmation_snapshot == {}


@pytest.mark.asyncio
async def test_live_time_mismatch_uses_spoken_snapshot_not_model_argument(monkeypatch):
    branch_id = uuid4()
    doctor_id = uuid4()
    day = date.today() + timedelta(days=7)
    state = SessionState(
        session_id="mismatch-owed-answer",
        branch_id=branch_id,
        patient_phone="+919000003333",
        last_user_utterance="please book it",
        caller_asked_to_book=True,
        booking_confirmation_granted=True,
        booking_confirmation_snapshot=_booking_snapshot(doctor_id, day),
        caller_booking_date=day.isoformat(),
        caller_booking_times=("17:00",),
        caller_booking_time="17:00",
        token_held=True,
        token_number=1,
        token_redis_key=f"slot:{doctor_id}:{branch_id}:{day}:1700",
        appointment_time="17:00",
        language="en",
    )
    agent = _agent(state, _DB(), doctor_contexts=[_doctor(doctor_id)])
    context = _Context()
    monkeypatch.setattr(agent_mod, "AgentSession", _Session)
    monkeypatch.setattr(agent, "_resolve_doctor_id", AsyncMock(return_value=doctor_id))
    monkeypatch.setattr(agent, "_release_hold", AsyncMock())
    monkeypatch.setattr(agent_mod, "assign_token", AsyncMock())
    core_confirm = AsyncMock(return_value={
        "success": True,
        "token_id": str(uuid4()),
        "patient_id": str(uuid4()),
        "announce": "time_only",
    })
    monkeypatch.setattr(agent_mod, "confirm_booking", core_confirm)

    with pytest.raises(agent_mod.StopResponse):
        await agent.confirm_booking(
            context=context,
            doctor_id=str(doctor_id),
            patient_name="Patient",
            booking_date=day.isoformat(),
            appointment_time="18:00",
            patient_age=30,
        )

    spoken = [text for text, _ in context.session.said]
    assert spoken[0] == "One moment, please. [long pause]"
    assert "five P.M." in spoken[-1]
    assert "six P.M." not in spoken[-1]
    core_confirm.assert_awaited_once()
    assert core_confirm.await_args.kwargs["appointment_time"].strftime("%H:%M") == "17:00"
    assert state.token_held is False
    assert state.caller_asked_to_book is False


@pytest.mark.asyncio
async def test_confirm_uses_spoken_date_over_different_tool_date(monkeypatch):
    branch_id = uuid4()
    doctor_id = uuid4()
    day = date.today() + timedelta(days=7)
    wrong_day = day + timedelta(days=1)
    state = SessionState(
        branch_id=branch_id,
        patient_phone="+919000004444",
        last_user_utterance="yes",
        caller_asked_to_book=True,
        booking_confirmation_granted=True,
        booking_confirmation_snapshot=_booking_snapshot(doctor_id, day),
        caller_booking_date=day.isoformat(),
        caller_booking_times=("17:00",),
        token_held=True,
        token_number=1,
        token_redis_key=f"slot:{doctor_id}:{branch_id}:{day}:1700",
    )
    agent = _agent(state, _DB(), doctor_contexts=[_doctor(doctor_id)])
    release_hold = AsyncMock()
    core_confirm = AsyncMock(return_value={
        "success": True,
        "token_id": str(uuid4()),
        "patient_id": str(uuid4()),
        "announce": "time_only",
    })
    monkeypatch.setattr(agent, "_resolve_doctor_id", AsyncMock(return_value=doctor_id))
    monkeypatch.setattr(agent, "_release_hold", release_hold)
    monkeypatch.setattr(agent_mod, "confirm_booking", core_confirm)

    result = await agent.confirm_booking(
        context=_Context(),
        doctor_id=str(doctor_id),
        patient_name="Patient",
        booking_date=wrong_day.isoformat(),
        appointment_time="17:00",
    )

    assert result["success"] is True
    core_confirm.assert_awaited_once()
    assert core_confirm.await_args.kwargs["booking_date"] == day
    release_hold.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_dimension", ["doctor", "date", "branch"])
async def test_full_hold_identity_is_reacquired_before_confirm(
    monkeypatch,
    stale_dimension,
):
    branch_id = uuid4()
    doctor_id = uuid4()
    stale_doctor_id = uuid4()
    stale_branch_id = uuid4()
    day = date.today() + timedelta(days=7)
    stale_day = day + timedelta(days=1)
    exact_key = f"slot:{doctor_id}:{branch_id}:{day}:1700"
    stale_parts = {
        "doctor": (stale_doctor_id, branch_id, day),
        "date": (doctor_id, branch_id, stale_day),
        "branch": (doctor_id, stale_branch_id, day),
    }
    key_doctor, key_branch, key_day = stale_parts[stale_dimension]
    stale_key = f"slot:{key_doctor}:{key_branch}:{key_day}:1700"
    token_id = uuid4()
    patient_id = uuid4()
    state = SessionState(
        branch_id=branch_id,
        patient_phone="+919000005555",
        last_user_utterance="yes",
        caller_asked_to_book=True,
        booking_confirmation_granted=True,
        booking_confirmation_snapshot=_booking_snapshot(doctor_id, day),
        caller_booking_date=day.isoformat(),
        caller_booking_times=("17:00",),
        token_held=True,
        token_number=8,
        token_redis_key=stale_key,
    )
    agent = _agent(state, _DB(), doctor_contexts=[_doctor(doctor_id)])
    release_hold = AsyncMock()
    core_assign = AsyncMock(
        return_value={
            "success": True,
            "booking_type": "appointment",
            "token_number": 9,
            "redis_key": exact_key,
            "appointment_time": "17:00",
        }
    )
    core_confirm = AsyncMock(
        return_value={
            "success": True,
            "token_id": str(token_id),
            "patient_id": str(patient_id),
            "announce": "time_only",
        }
    )
    monkeypatch.setattr(agent, "_resolve_doctor_id", AsyncMock(return_value=doctor_id))
    monkeypatch.setattr(agent, "_release_hold", release_hold)
    monkeypatch.setattr(agent, "_speak_deterministic_confirm", MagicMock(return_value=False))
    monkeypatch.setattr(agent_mod, "assign_token", core_assign)
    monkeypatch.setattr(agent_mod, "confirm_booking", core_confirm)

    result = await agent.confirm_booking(
        context=_Context(),
        doctor_id=str(doctor_id),
        patient_name="Patient",
        booking_date=day.isoformat(),
        appointment_time="17:00",
    )

    assert result["success"] is True
    release_hold.assert_awaited_once_with({"redis_key": stale_key})
    core_assign.assert_awaited_once()
    assert core_assign.await_args.kwargs["doctor_id"] == doctor_id
    assert core_assign.await_args.kwargs["branch_id"] == branch_id
    assert core_assign.await_args.kwargs["booking_date"] == day
    assert core_assign.await_args.kwargs["appointment_time"].strftime("%H:%M") == "17:00"
    core_confirm.assert_awaited_once()
    assert state.token_redis_key is None
    assert state.token_held is False
    assert state.token_confirmed is True


@pytest.mark.asyncio
async def test_wrong_reacquired_hold_key_cannot_reach_booking_write(monkeypatch):
    branch_id = uuid4()
    doctor_id = uuid4()
    stale_doctor_id = uuid4()
    wrong_doctor_id = uuid4()
    day = date.today() + timedelta(days=7)
    stale_key = f"slot:{stale_doctor_id}:{branch_id}:{day}:1700"
    wrong_key = f"slot:{wrong_doctor_id}:{branch_id}:{day}:1700"
    state = SessionState(
        branch_id=branch_id,
        patient_phone="+919000006666",
        last_user_utterance="yes",
        caller_asked_to_book=True,
        booking_confirmation_granted=True,
        booking_confirmation_snapshot=_booking_snapshot(doctor_id, day),
        caller_booking_date=day.isoformat(),
        caller_booking_times=("17:00",),
        token_held=True,
        token_number=8,
        token_redis_key=stale_key,
    )
    agent = _agent(state, _DB(), doctor_contexts=[_doctor(doctor_id)])
    release_hold = AsyncMock()
    core_assign = AsyncMock(
        return_value={
            "success": True,
            "booking_type": "appointment",
            "token_number": 9,
            "redis_key": wrong_key,
            "appointment_time": "17:00",
        }
    )
    core_confirm = AsyncMock()
    monkeypatch.setattr(agent, "_resolve_doctor_id", AsyncMock(return_value=doctor_id))
    monkeypatch.setattr(agent, "_release_hold", release_hold)
    monkeypatch.setattr(agent_mod, "assign_token", core_assign)
    monkeypatch.setattr(agent_mod, "confirm_booking", core_confirm)

    result = await agent.confirm_booking(
        context=_Context(),
        doctor_id=str(doctor_id),
        patient_name="Patient",
        booking_date=day.isoformat(),
        appointment_time="17:00",
    )

    assert result["success"] is False
    assert result["reason"] == "caller_selection_mismatch"
    core_confirm.assert_not_awaited()
    assert release_hold.await_count == 2
    assert release_hold.await_args_list[0].args == ({"redis_key": stale_key},)
    assert release_hold.await_args_list[1].args[0]["redis_key"] == wrong_key
    assert state.token_confirmed is False


@pytest.mark.asyncio
async def test_failed_time_binding_cannot_authorize_wrong_success_speech():
    state = SessionState(
        language="en",
        caller_asked_to_book=True,
        caller_booking_time="17:00",
    )
    wrong_claim = "Done. Your appointment is confirmed for 6:00 PM."

    output = "".join([
        part
        async for part in _guard_unverified_action_speech_stream(
            _chunks(wrong_claim),
            "en",
            verified_state=state,
            pending_action="booking",
        )
    ])

    assert output == build_booking_failure_text("en")
    assert "6:00" not in output


@pytest.mark.asyncio
async def test_token_queue_ignores_stray_clock_and_reuses_one_token_hold(monkeypatch):
    branch_id = uuid4()
    doctor_id = uuid4()
    day = date.today() + timedelta(days=7)
    state = SessionState(
        branch_id=branch_id,
        caller_booking_time="17:00",
    )
    doctor = DoctorContext(
        id=str(doctor_id),
        name="Dr Queue",
        specialization="general medicine",
        routing_keywords=[],
        booking_type="token",
        is_default=True,
    )
    agent = _agent(state, _DB(), doctor_contexts=[doctor])
    core_assign = AsyncMock(return_value={
        "success": True,
        "booking_type": "token",
        "token_number": 4,
        "redis_key": f"token:{doctor_id}:{branch_id}:{day}",
        "appointment_time": None,
    })
    monkeypatch.setattr(agent, "_resolve_doctor_id", AsyncMock(return_value=doctor_id))
    monkeypatch.setattr(agent_mod, "assign_token", core_assign)

    first = await agent.assign_token(
        context=None,
        doctor_id=str(doctor_id),
        booking_date=day.isoformat(),
        appointment_time="18:00",
    )
    second = await agent.assign_token(
        context=None,
        doctor_id=str(doctor_id),
        booking_date=day.isoformat(),
        appointment_time="19:00",
    )

    assert first["success"] is True
    assert second["success"] is True
    assert second["already_held"] is True
    assert second["booking_type"] == "token"
    assert second["appointment_time"] is None
    core_assign.assert_awaited_once()
    assert core_assign.await_args.kwargs["appointment_time"] is None
    assert state.token_redis_key == f"token:{doctor_id}:{branch_id}:{day}"
