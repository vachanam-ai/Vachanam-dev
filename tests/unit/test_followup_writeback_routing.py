"""#347: the teardown response_summary write-back must fire for INBOUND
pending-follow-up calls too, not just outbound dispatches with meta.task_id.
Cascade rebooks (followup_task_id only) must stay excluded — completing them
here would silently kill their 30-minute retry loop."""
from uuid import uuid4

from agent.livekit_minimal.agent import _writeback_task_id
from agent.session_state import SessionState


def _state(**kw) -> SessionState:
    s = SessionState(branch_id=uuid4())
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_outbound_meta_task_id_wins():
    tid = str(uuid4())
    assert _writeback_task_id({"task_id": tid}, _state()) == tid


def test_inbound_falls_back_to_state():
    tid = uuid4()
    got = _writeback_task_id({}, _state(followup_writeback_task_id=tid))
    assert got == str(tid)


def test_cascade_rebook_never_written_back():
    # cascade sets ONLY followup_task_id — write-back must not touch it.
    assert _writeback_task_id({}, _state(followup_task_id=uuid4())) is None


def test_plain_call_no_task():
    assert _writeback_task_id({}, _state()) is None
