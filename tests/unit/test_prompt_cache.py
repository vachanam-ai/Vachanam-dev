"""#417 explicit Vertex prompt caching — gating tests.

Measured proof (2026-07-19, asia-south1, real 14.2k-token prompt):
plain warm ttft 0.71-0.74s → 0.53-0.55s with CachedContent
(cached_tokens=14179/14188); baked tools still fire function calls
(check_availability with args, cached=1188). These tests guard the SAFETY
MODEL: cache used only on byte-identical instructions, rides the AGENT (not
the session) so language-switch handoffs fall back to the plain LLM, and any
miss/mismatch/no-creds returns None (plain path)."""
import inspect

import agent.livekit_minimal.agent as agent_mod
from agent.livekit_minimal.agent import (
    _PROMPT_CACHE,
    _cached_primary_llm,
    _prompt_cache_key,
)


def setup_function(_):
    _PROMPT_CACHE.clear()


def test_key_is_branch_lang_ist_day():
    k = _prompt_cache_key("b-123", "te")
    assert k[0] == "b-123" and k[1] == "te"
    assert len(k[2]) == 10  # YYYY-MM-DD — retires yesterday's date table


def test_miss_returns_none():
    assert _cached_primary_llm(("b", "te", "2026-07-19"), "PROMPT") is None


def test_byte_mismatch_returns_none():
    # A prompt edit deployed mid-day must NOT ride yesterday's baked text.
    _PROMPT_CACHE[("b", "te", "2026-07-19")] = ("caches/x", "OLD PROMPT")
    assert _cached_primary_llm(("b", "te", "2026-07-19"), "NEW PROMPT") is None


def test_no_vertex_creds_returns_none(monkeypatch):
    _PROMPT_CACHE[("b", "te", "2026-07-19")] = ("caches/x", "PROMPT")
    monkeypatch.setattr(agent_mod, "_vertex_credentials", lambda: None)
    assert _cached_primary_llm(("b", "te", "2026-07-19"), "PROMPT") is None


def test_hit_builds_adapter_with_cached_primary(monkeypatch):
    _PROMPT_CACHE[("b", "te", "2026-07-19")] = ("caches/x", "PROMPT")
    monkeypatch.setattr(agent_mod, "_vertex_credentials", lambda: ("/tmp/sa.json", "proj"))
    adapter = _cached_primary_llm(("b", "te", "2026-07-19"), "PROMPT")
    assert adapter is not None
    primary = adapter._llm_instances[0] if hasattr(adapter, "_llm_instances") else adapter._llms[0]
    # the Vertex primary carries the cache resource; fallbacks stay plain
    assert getattr(primary._opts, "cached_content", None) == "caches/x" or \
        "caches/x" in repr(vars(primary._opts))


def test_eligibility_and_agent_ride_source_guard():
    """The entrypoint must gate on NO per-call extras and put the cached LLM
    on the AGENT (llm=...), never on the session — a language-switch handoff
    (new agent, no llm override) then inherits the plain session LLM."""
    src = inspect.getsource(agent_mod)
    assert "_cache_eligible = not caller_prompt_extra and not extra_tail" in src
    assert "llm=_cached_llm," in src
    # background bake happens only on an eligible miss
    assert "_create_prompt_cache(" in src


def test_create_prompt_cache_never_raises(monkeypatch):
    # RULE 8: creation failure logs and leaves the plain path untouched.
    import asyncio

    monkeypatch.setattr(agent_mod, "_vertex_credentials",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    asyncio.run(agent_mod._create_prompt_cache(("b", "te", "d"), "P", []))
    assert ("b", "te", "d") not in _PROMPT_CACHE
