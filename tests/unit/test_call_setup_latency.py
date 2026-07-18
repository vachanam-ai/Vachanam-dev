"""Call-setup latency (#390 — real call 2026-07-17: lat_pre_session_build
4.66s, first audio 5.81s, first-turn Gemini ttft 3.35s). Source guards on the
structural fixes so a refactor can't silently re-serialize the setup path:

1. The three independent pre-call DB reads (per-caller language, service gate,
   caller identification) run in ONE asyncio.gather on their own sessions.
2. The gate keeps its iter1 #23 fail-closed semantics inside the moved
   function (a DB hiccup must never grant service to a shut-off org).
3. The session LLM is prewarmed during the greeting cover window.
"""
from pathlib import Path

SRC = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")


def test_pre_call_reads_run_concurrently():
    gather = SRC.split("await asyncio.gather(")[1][:200]
    assert "_read_pref_lang()" in gather
    assert "_service_gate_check(branch)" in gather
    assert "_read_caller()" in gather


def test_gate_keeps_fail_closed_semantics():
    fn = SRC.split("async def _service_gate_check")[1][:4000]
    # fail CLOSED for known terminal status, fail OPEN otherwise (iter1 #23)
    assert "_gate_failure_blocked_reason(_last_status)" in fn
    assert "service_gate_check_failed_failing_closed" in fn
    assert "service_gate_check_failed_failing_open" in fn
    # trial + adjustment still honored (B3)
    assert "trial_ends_at" in fn and "minutes_adjustment" in fn
    # its own pooled session, not the call session
    assert "AsyncSessionLocal()" in fn


def test_blocked_org_still_decided_before_greeting():
    # The gate unpack (and blocked-path return) must appear BEFORE the
    # greeting task is created — a blocked org never hears the greeting.
    # Prefix match: master unpacks 2 values, the sales branch adds
    # org_vertical — the guard must hold on both.
    assert SRC.index("blocked_reason, org_plan") < SRC.index(
        "ctx.room, _greet_texts, tts_voice"
    )


def test_llm_prewarm_fires_at_session_build():
    assert "async def _prewarm_llm" in SRC
    assert "asyncio.create_task(_prewarm_llm())" in SRC
    fn = SRC.split("async def _prewarm_llm")[1][:2500]
    assert "aclose()" in fn  # stream always closed, even on break
    # #393: prewarm must carry the REAL system prompt — an empty-context
    # prewarm leaves the first real turn at ttft ~3.5s (measured 17:10Z call)
    # because Gemini's implicit prefix cache never sees the actual prompt.
    assert 'role="system", content=instructions' in fn


def test_build_breakdown_instrumented():
    # #393: a slow build must name its stage (branch_resolve / reads / rest).
    assert "branch_resolve=%.2fs" in SRC
    assert "_t_branch - _t_answer" in SRC
    assert "_t_reads - _t_branch" in SRC
