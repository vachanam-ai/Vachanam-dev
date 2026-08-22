from unittest.mock import AsyncMock
from uuid import uuid4
from types import SimpleNamespace

import pytest

from agent.livekit_minimal import agent as agent_mod
from agent.livekit_minimal.agent import VachanamAgent
from agent.session_state import SessionState


def _agent(
    state: SessionState, *, doctor_contexts=None, calendar_service=None
) -> VachanamAgent:
    return VachanamAgent(
        instructions='test',
        state=state,
        db=None,
        room=None,
        calendar_service=calendar_service,
        meta_service=None,
        transfer_to='',
        doctor_contexts=doctor_contexts,
    )


@pytest.mark.asyncio
async def test_failed_confirm_clears_in_flight_and_token_doctor_can_reach_core(
    monkeypatch,
):
    doctor_id = uuid4()
    branch_id = uuid4()
    snapshot = {
        'patient_name': 'Patient',
        'doctor_id': str(doctor_id),
        'doctor_name': 'Dr Test',
        'booking_date': '2026-08-10',
        'appointment_time': None,
        'booking_type': 'token',
    }
    state = SessionState(
        branch_id=branch_id,
        patient_phone='+919999999999',
        last_user_utterance='yes please',
        caller_asked_to_book=True,
        booking_confirmation_granted=True,
        booking_confirmation_snapshot=snapshot,
        token_held=True,
        token_number=1,
        token_redis_key=(
            f'token:{doctor_id}:{branch_id}:2026-08-10'
        ),
    )
    agent = _agent(
        state,
        doctor_contexts=[
            SimpleNamespace(id=doctor_id, name='Dr Test', booking_type='token')
        ],
    )
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
    old_token_id = uuid4()
    choice = {
        'token_id': str(old_token_id),
        'status': 'confirmed',
        'booking_type': 'token',
        'patient_name': 'Patient',
        'doctor': 'Dr Test',
    }
    state = SessionState(
        branch_id=uuid4(),
        patient_phone='+919999999999',
        last_user_utterance='please reschedule it',
        caller_asked_to_reschedule=True,
        identity_verified=True,
        verified_patient_ids={uuid4()},
        verified_booking_choices={str(old_token_id): choice},
    )
    agent = _agent(state)
    monkeypatch.setattr(
        agent,
        '_do_reschedule',
        AsyncMock(return_value={'success': False, 'error': 'booking_not_found'}),
    )

    result = await agent.reschedule_booking(
        None, str(old_token_id), '2026-08-10', '10:00'
    )

    assert result['error'] == 'booking_not_found'
    assert state.mutation_in_flight is None
    assert state.caller_asked_to_reschedule is True


@pytest.mark.asyncio
async def test_failed_cancel_clears_in_flight(monkeypatch):
    token_id = uuid4()
    choice = {
        'token_id': str(token_id),
        'status': 'confirmed',
        'booking_type': 'token',
        'patient_name': 'Patient',
        'doctor': 'Dr Test',
        'date': '2026-08-10',
        'token_number': 1,
    }
    state = SessionState(
        branch_id=uuid4(),
        patient_phone='+919999999999',
        last_user_utterance='please cancel my appointment',
        caller_asked_to_cancel=True,
        identity_verified=True,
        verified_patient_ids={uuid4()},
        cancellation_confirmation_granted=True,
        cancellation_confirmation_snapshot=choice,
        verified_booking_choices={str(token_id): choice},
    )
    agent = _agent(state)
    monkeypatch.setattr(
        agent,
        '_do_cancel',
        AsyncMock(return_value={'success': False, 'error': 'already_cancelled'}),
    )

    result = await agent.cancel_booking(None, str(token_id))

    assert result['error'] == 'already_cancelled'
    assert state.mutation_in_flight is None
    assert state.caller_asked_to_cancel is True


@pytest.mark.asyncio
async def test_unexpected_mutation_exception_also_clears_in_flight(monkeypatch):
    old_token_id = uuid4()
    choice = {
        'token_id': str(old_token_id),
        'status': 'confirmed',
        'booking_type': 'token',
        'patient_name': 'Patient',
        'doctor': 'Dr Test',
    }
    state = SessionState(
        branch_id=uuid4(),
        patient_phone='+919999999999',
        last_user_utterance='please reschedule it',
        identity_verified=True,
        verified_patient_ids={uuid4()},
        verified_booking_choices={str(old_token_id): choice},
    )
    agent = _agent(state)
    monkeypatch.setattr(
        agent, '_do_reschedule', AsyncMock(side_effect=RuntimeError('db down'))
    )

    with pytest.raises(RuntimeError, match='db down'):
        await agent.reschedule_booking(
            None, str(old_token_id), '2026-08-10', '10:00'
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
