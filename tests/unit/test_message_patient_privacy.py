"""Patient messages never guess a family member from a shared phone."""

import asyncio

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agent.livekit_minimal.agent import VachanamAgent
from agent.session_state import SessionState


def _db_returning(row=None):
    result = MagicMock()
    result.first.return_value = row
    return SimpleNamespace(
        execute=AsyncMock(return_value=result),
        add=MagicMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )


def _agent(state: SessionState, db):
    return SimpleNamespace(
        _state=state,
        _db=db,
        _faq_rows=[],
        _lang_code="en",
    )


def _context():
    # A non-live session keeps these tests on the returned-dict path.
    return SimpleNamespace(session=None)


def _assert_identity_scope(statement, patient_id, branch_id, phone):
    sql = str(statement)
    assert "patients.id" in sql
    assert "patients.branch_id" in sql
    assert "patients.phone" in sql
    values = tuple(statement.compile().params.values())
    assert patient_id in values
    assert branch_id in values
    assert phone in values


@pytest.mark.asyncio
async def test_question_on_shared_phone_is_not_attached_to_an_arbitrary_patient():
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919000001111",
        verified_patient_ids={uuid4(), uuid4()},
    )
    db = _db_returning((uuid4(),))

    result = await VachanamAgent.log_clinic_question.__wrapped__(
        _agent(state, db), _context(), "Does the clinic have parking?"
    )

    assert result["logged"] is True
    db.execute.assert_not_awaited()
    assert db.add.call_args.args[0].patient_id is None


@pytest.mark.asyncio
async def test_message_on_shared_phone_keeps_the_caller_provided_name(monkeypatch):
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919000002222",
        patient_name="Current Caller",
        verified_patient_ids={uuid4(), uuid4()},
    )
    db = _db_returning((uuid4(), "Wrong Family Member"))
    notified = {}
    notification_sent = asyncio.Event()

    async def _notify(branch_id, *, caller_name, caller_last4):
        notified.update(
            branch_id=branch_id,
            caller_name=caller_name,
            caller_last4=caller_last4,
        )
        notification_sent.set()

    monkeypatch.setattr(
        "backend.services.support_email.notify_clinic_message", _notify
    )
    result = await VachanamAgent.take_message.__wrapped__(
        _agent(state, db), _context(), "Please call me back", urgent=True
    )

    assert result["logged"] is True
    assert not notification_sent.is_set()  # caller ack does not wait on email
    await asyncio.wait_for(notification_sent.wait(), timeout=1)
    db.execute.assert_not_awaited()
    assert db.add.call_args.args[0].patient_id is None
    assert state.patient_name == "Current Caller"
    assert notified["caller_name"] == "Current Caller"


@pytest.mark.asyncio
async def test_question_attaches_the_one_verified_patient_with_full_scope():
    patient_id = uuid4()
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919000003333",
        verified_patient_ids={patient_id},
    )
    db = _db_returning((patient_id,))

    result = await VachanamAgent.log_clinic_question.__wrapped__(
        _agent(state, db), _context(), "Is wheelchair access available?"
    )

    assert result["logged"] is True
    assert db.add.call_args.args[0].patient_id == patient_id
    _assert_identity_scope(
        db.execute.await_args.args[0], patient_id, state.branch_id, state.patient_phone
    )


@pytest.mark.asyncio
async def test_message_uses_stored_name_only_for_the_one_verified_scoped_row(
    monkeypatch,
):
    patient_id = uuid4()
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919000004444",
        patient_name="Caller Supplied",
        verified_patient_ids={patient_id},
    )
    db = _db_returning((patient_id, "Verified Stored Name"))
    notified = {}
    notification_sent = asyncio.Event()

    async def _notify(_branch_id, *, caller_name, caller_last4):
        notified.update(caller_name=caller_name, caller_last4=caller_last4)
        notification_sent.set()

    monkeypatch.setattr(
        "backend.services.support_email.notify_clinic_message", _notify
    )
    result = await VachanamAgent.take_message.__wrapped__(
        _agent(state, db), _context(), "I am running late", urgent=True
    )

    assert result["logged"] is True
    assert not notification_sent.is_set()
    await asyncio.wait_for(notification_sent.wait(), timeout=1)
    assert db.add.call_args.args[0].patient_id == patient_id
    assert notified["caller_name"] == "Verified Stored Name"
    _assert_identity_scope(
        db.execute.await_args.args[0], patient_id, state.branch_id, state.patient_phone
    )


@pytest.mark.asyncio
async def test_missing_scoped_patient_row_stays_unlinked_and_keeps_call_name(
    monkeypatch,
):
    patient_id = uuid4()
    state = SessionState(
        branch_id=uuid4(),
        patient_phone="+919000005555",
        patient_name="Caller Supplied",
        verified_patient_ids={patient_id},
    )
    db = _db_returning(None)
    notified = {}
    notification_sent = asyncio.Event()

    async def _notify(_branch_id, *, caller_name, caller_last4):
        notified.update(caller_name=caller_name, caller_last4=caller_last4)
        notification_sent.set()

    monkeypatch.setattr(
        "backend.services.support_email.notify_clinic_message", _notify
    )
    result = await VachanamAgent.take_message.__wrapped__(
        _agent(state, db), _context(), "Please call about my report", urgent=True
    )

    assert result["logged"] is True
    assert not notification_sent.is_set()
    await asyncio.wait_for(notification_sent.wait(), timeout=1)
    assert db.add.call_args.args[0].patient_id is None
    assert state.patient_name == "Caller Supplied"
    assert notified["caller_name"] == "Caller Supplied"
    _assert_identity_scope(
        db.execute.await_args.args[0], patient_id, state.branch_id, state.patient_phone
    )
