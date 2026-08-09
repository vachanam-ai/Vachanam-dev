from unittest.mock import AsyncMock
from uuid import uuid4
from types import SimpleNamespace

import pytest

from agent.livekit_minimal import agent as agent_mod
from agent.livekit_minimal.agent import VachanamAgent
from agent.session_state import SessionState


def _agent(state: SessionState) -> VachanamAgent:
    return VachanamAgent(
        instructions='test',
        state=state,
        db=None,
        room=None,
        calendar_service=None,
        meta_service=None,
        transfer_to='',
    )


@pytest.mark.asyncio
async def test_failed_confirm_clears_in_flight_and_token_doctor_can_reach_core(
    monkeypatch,
):
    state = SessionState(
        branch_id=uuid4(),
        patient_phone='+919999999999',
        last_user_utterance='please book it',
        caller_asked_to_book=True,
        token_held=True,
        token_number=1,
    )
    agent = _agent(state)
    doctor_id = uuid4()
    monkeypatch.setattr(
        agent, '_resolve_doctor_id', AsyncMock(return_value=doctor_id)
    )
    core = AsyncMock(return_value={'success': False, 'reason': 'full'})
    monkeypatch.setattr(agent_mod, 'confirm_booking', core)

    result = await agent.confirm_booking(
        context=None,
        doctor_id=str(doctor_id),
        patient_name='Patient',
        booking_date='2026-08-10',
        patient_age=30,
    )

    assert result == {'success': False, 'reason': 'full'}
    assert state.mutation_in_flight is None
    assert state.caller_asked_to_book is True
    assert core.await_args.kwargs['calendar_service'] is None


@pytest.mark.asyncio
async def test_failed_reschedule_clears_in_flight(monkeypatch):
    state = SessionState(
        branch_id=uuid4(),
        patient_phone='+919999999999',
        last_user_utterance='please reschedule it',
        caller_asked_to_reschedule=True,
    )
    agent = _agent(state)
    monkeypatch.setattr(
        agent,
        '_do_reschedule',
        AsyncMock(return_value={'success': False, 'error': 'booking_not_found'}),
    )

    result = await agent.reschedule_booking(
        None, str(uuid4()), '2026-08-10', '10:00'
    )

    assert result['error'] == 'booking_not_found'
    assert state.mutation_in_flight is None
    assert state.caller_asked_to_reschedule is True


@pytest.mark.asyncio
async def test_failed_cancel_clears_in_flight(monkeypatch):
    state = SessionState(
        branch_id=uuid4(),
        patient_phone='+919999999999',
        last_user_utterance='please cancel my appointment',
        caller_asked_to_cancel=True,
    )
    agent = _agent(state)
    monkeypatch.setattr(
        agent,
        '_do_cancel',
        AsyncMock(return_value={'success': False, 'error': 'already_cancelled'}),
    )

    result = await agent.cancel_booking(None, str(uuid4()))

    assert result['error'] == 'already_cancelled'
    assert state.mutation_in_flight is None
    assert state.caller_asked_to_cancel is True


@pytest.mark.asyncio
async def test_unexpected_mutation_exception_also_clears_in_flight(monkeypatch):
    state = SessionState(
        branch_id=uuid4(),
        patient_phone='+919999999999',
        last_user_utterance='please reschedule it',
    )
    agent = _agent(state)
    monkeypatch.setattr(
        agent, '_do_reschedule', AsyncMock(side_effect=RuntimeError('db down'))
    )

    with pytest.raises(RuntimeError, match='db down'):
        await agent.reschedule_booking(
            None, str(uuid4()), '2026-08-10', '10:00'
        )

    assert state.mutation_in_flight is None


@pytest.mark.asyncio
async def test_followup_commit_failure_rolls_back_session():
    state = SessionState(
        branch_id=uuid4(),
        followup_task_id=uuid4(),
    )
    agent = _agent(state)
    task = SimpleNamespace(status='pending', response_summary=None)
    query_result = SimpleNamespace(scalar_one_or_none=lambda: task)
    agent._db = SimpleNamespace(
        execute=AsyncMock(return_value=query_result),
        commit=AsyncMock(side_effect=RuntimeError('commit failed')),
        rollback=AsyncMock(),
    )

    assert await agent._complete_followup_task('done') is False
    agent._db.rollback.assert_awaited_once()
