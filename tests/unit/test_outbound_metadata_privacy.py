"""LiveKit dispatch carries opaque references, never patient PII."""
import ast
import importlib
import inspect
import textwrap

import agent.livekit_minimal.agent as agent_mod


def _dict_keys(function) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    return {
        key.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def test_dispatch_metadata_contains_no_patient_pii():
    cases = (
        ("backend.jobs.pre_appt_reminder", "_dispatch_reminder_call"),
        ("backend.jobs.next_visit_followup_caller", "_dispatch"),
        ("backend.jobs.cascade_rebook_caller", "_dispatch_rebook_call"),
        ("backend.jobs.question_callback_caller", "_dispatch"),
    )
    forbidden = {"phone_number", "patient_name", "patient_phone", "message"}
    for module_name, function_name in cases:
        function = getattr(importlib.import_module(module_name), function_name)
        assert _dict_keys(function).isdisjoint(forbidden), module_name


def test_worker_hydrates_every_outbound_type_from_branch_scoped_ids():
    source = inspect.getsource(agent_mod._hydrate_outbound_meta)
    for call_type in (
        "reminder",
        "cascade_rebook",
        "question_answer",
    ):
        assert call_type in source
    assert agent_mod._FOLLOWUP_CALLTYPES == {"next_visit_book", "doctor_advice"}
    assert "Token.branch_id == branch_id" in source
    assert "FollowupTask.branch_id == branch_id" in source
    assert "question.branch_id != branch_id" in source
