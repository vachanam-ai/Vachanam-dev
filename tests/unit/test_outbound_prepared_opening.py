"""An outbound call that exists to SAY something must open by saying it.

Real report 2026-08-03 (Vinay): "followup call is taking 10 secs just to speak
1st word. and it is starting with 'how can i help you' instead of saying
reminder message."

Root cause: the greeting gate was

    _is_outbound_greet = is_reminder or is_rebook_call or is_followup

and `is_followup` means `call_type in _FOLLOWUP_CALLTYPES`, i.e. "owns a
FollowupTask" — a different question from "opens with a prepared message".
question_answer owns no FollowupTask, so it was excluded, and two things
followed from that single omission:

  1. the call fell through to the INBOUND greeting, so a patient who had been
     promised an answer was rung up and asked "how can I help you?";
  2. it skipped the wait on _greet_prep_task, so the clip already synthesized
     during ring time was discarded and the opening line was rebuilt cold on
     the live call — the ~10s of silence.

The prep side (_outbound_greet_prep) always handled question_answer correctly.
Only the playback gate disagreed, which is why the audio was built and binned.
"""
import pytest
import inspect

import agent.livekit_minimal.agent as agent_module
from agent.livekit_minimal.agent import (
    _FOLLOWUP_CALLTYPES,
    opens_with_prepared_message,
)


@pytest.mark.parametrize(
    "call_type",
    ["reminder", "cascade_rebook", "next_visit_book", "doctor_advice", "question_answer"],
)
def test_every_message_carrying_call_opens_with_its_prepared_line(call_type):
    assert opens_with_prepared_message(call_type) is True


def test_question_answer_is_included_despite_owning_no_followup_task():
    """The exact regression: excluded from the followup set for a good reason,
    then wrongly inherited that exclusion here."""
    assert "question_answer" not in _FOLLOWUP_CALLTYPES
    assert opens_with_prepared_message("question_answer") is True


@pytest.mark.parametrize("call_type", [None, "", "inbound", "inbound_booking", "unknown"])
def test_an_inbound_call_still_waits_for_the_caller_to_speak(call_type):
    assert opens_with_prepared_message(call_type) is False


def test_the_dispatched_call_type_matches_what_the_job_actually_sends():
    """Guards the string itself: the callback job and this gate must agree, and
    a typo in either would silently restore the bug."""
    from backend.jobs.question_callback_caller import _dispatch  # noqa: F401
    import inspect

    from backend.jobs import question_callback_caller

    source = inspect.getsource(question_callback_caller)
    assert '"call_type": "question_answer"' in source
    assert opens_with_prepared_message("question_answer")


def test_outbound_playback_is_launched_at_answer_before_tenant_prompt_work():
    src = inspect.getsource(agent_module.entrypoint)
    answered = src.index("_t_answer = _perf.monotonic()")
    launched = src.index("_outbound_answer_play_task = asyncio.create_task")
    did_reads = src.index("# Resolve the dialed DID")
    assert answered < launched < did_reads


def test_outbound_hot_path_has_no_eight_second_prep_wait():
    src = inspect.getsource(agent_module.entrypoint)
    assert "wait_for(_greet_prep_task, timeout=8.0)" not in src
    assert "prepare_outbound_prefix_items" in src
    assert "wav_items" in src
