"""A clinic may dial only through the outbound trunk assigned to that clinic."""

from __future__ import annotations

import inspect
from types import SimpleNamespace as NS

import pytest

from agent.livekit_minimal import agent
from backend.jobs import (
    cascade_rebook_caller,
    next_visit_followup_caller,
    pre_appt_reminder,
    question_callback_caller,
)


def _branch():
    return NS(id="sri-skincare", outbound_trunk_id=None)


@pytest.mark.asyncio
async def test_reminder_without_branch_trunk_never_dispatches():
    result = await pre_appt_reminder._dispatch_reminder_call(
        _branch(), NS(id="token"), NS(id="doctor"), NS(phone="+910000000000")
    )
    assert result is False


@pytest.mark.asyncio
async def test_followup_without_branch_trunk_never_dispatches():
    result = await next_visit_followup_caller._dispatch(
        NS(id="task"), _branch(), NS(id="doctor"), NS(phone="+910000000000"), None
    )
    assert result is False


@pytest.mark.asyncio
async def test_question_callback_without_branch_trunk_never_dispatches():
    result = await question_callback_caller._dispatch(
        NS(id="question", caller_phone="+910000000000"), _branch(), ""
    )
    assert result is False


@pytest.mark.asyncio
async def test_cascade_without_branch_trunk_never_dispatches():
    result = await cascade_rebook_caller._dispatch_rebook_call(
        NS(id="task"),
        NS(phone="+910000000000"),
        NS(id="doctor"),
        NS(id="token"),
        _branch(),
        "ST_venkateshwara",
    )
    assert result is None


def test_cascade_checks_trunk_before_consuming_an_attempt():
    source = inspect.getsource(cascade_rebook_caller.run_cascade_rebook_calls)
    assert source.index("branch_outbound_trunk_id(branch)") < source.index(
        "task.attempt_count += 1"
    )


def test_voice_worker_revalidates_before_sip_dial_and_has_no_env_fallback():
    source = inspect.getsource(agent.entrypoint)
    validation = source.index("_validated_outbound_trunk(meta, ctx.api.sip)")
    dial = source.index("create_sip_participant")
    assert validation < dial
    assert "OUTBOUND_TRUNK_ID" not in source[validation:dial]


def test_provider_trunk_number_must_match_branch_did():
    branch = NS(did_number="+918046733493")
    trunks = [
        NS(
            sip_trunk_id="ST_venkateshwara",
            numbers=["+918046733493"],
        ),
        NS(sip_trunk_id="ST_skincare", numbers=["+918071387303"]),
    ]
    assert agent._trunk_has_branch_did(branch, "ST_venkateshwara", trunks)
    assert not agent._trunk_has_branch_did(branch, "ST_skincare", trunks)
    assert not agent._trunk_has_branch_did(
        NS(did_number=None), "ST_venkateshwara", trunks
    )
