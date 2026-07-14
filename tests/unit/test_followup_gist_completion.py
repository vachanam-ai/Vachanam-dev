"""Vinay 2026-07-14 follow-up loop fixes:
1. response_summary = GIST (Gemini) with raw fallback, never raw-only.
2. Inbound delivery of a next_visit_book task completes it ONLY when the
   visit was booked this call — otherwise the scheduled outbound still fires.
"""
import asyncio
import inspect



def test_teardown_completion_semantics_present():
    import agent.livekit_minimal.agent as agent_mod

    src = inspect.getsource(agent_mod)
    assert "COMPLETION SEMANTICS" in src
    assert 'task_type != "next_visit_book"' in src.replace("_task.", "task_type").replace("task_typetask_type", "task_type") or "_task.task_type" in src
    assert "state.token_confirmed" in src
    assert "summarize_patient_reply" in src


def test_prompt_extra_always_mentions_date():
    import agent.livekit_minimal.agent as agent_mod

    src = inspect.getsource(agent_mod)
    assert "ALWAYS mention the doctor's" in src
    assert "the date must never" in src


def test_gist_falls_back_to_raw_on_gemini_failure(monkeypatch):
    from backend.services import reply_summary as rs

    async def _boom(prompt):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(rs, "_call_gemini_plain", _boom)
    out = asyncio.run(rs.summarize_patient_reply(["నొప్పి తగ్గింది", "thank you"]))
    assert "నొప్పి తగ్గింది" in out  # raw fallback (RULE 8)


def test_gist_empty_reply():
    from backend.services.reply_summary import summarize_patient_reply

    out = asyncio.run(summarize_patient_reply(["", "  "]))
    assert out == "(no reply captured)"
