"""#417 explicit Vertex prompt caching — gating tests.

Measured proof (2026-07-19, asia-south1, real 14.2k-token prompt):
plain warm ttft 0.71-0.74s → 0.53-0.55s with CachedContent
(cached_tokens=14179/14188); baked tools still fire function calls
(check_availability with args, cached=1188). These tests guard the SAFETY
MODEL: cache used only on byte-identical instructions, rides the AGENT (not
the session) so language-switch handoffs fall back to the plain LLM, and any
miss/mismatch/no-creds returns None (plain path)."""
import inspect
import asyncio

import agent.livekit_minimal.agent as agent_mod
from agent.livekit_minimal.agent import (
    _PROMPT_CACHE,
    _cached_primary_llm,
    _decode_branch_faq,
    _prompt_cache_redis_key,
    _prompt_cache_key,
)


def setup_function(_):
    _PROMPT_CACHE.clear()


def test_key_is_branch_lang_ist_day_and_exact_prompt_digest():
    k = _prompt_cache_key("b-123", "te", "PROMPT")
    assert k[0] == "b-123" and k[1] == "te"
    assert len(k[2]) == 10  # YYYY-MM-DD — retires yesterday's date table
    assert len(k[3]) == 12
    assert k[3] != _prompt_cache_key("b-123", "te", "OTHER")[3]
    assert "b-123" in _prompt_cache_redis_key(k)


def test_miss_returns_none():
    assert _cached_primary_llm(("b", "te", "2026-07-19", "abc"), "PROMPT") is None


def test_byte_mismatch_returns_none():
    # A prompt edit deployed mid-day must NOT ride yesterday's baked text.
    key = ("b", "te", "2026-07-19", "abc")
    _PROMPT_CACHE[key] = ("caches/x", "OLD PROMPT")
    assert _cached_primary_llm(key, "NEW PROMPT") is None


def test_no_vertex_creds_returns_none(monkeypatch):
    key = ("b", "te", "2026-07-19", "abc")
    _PROMPT_CACHE[key] = ("caches/x", "PROMPT")
    monkeypatch.setattr(agent_mod, "_vertex_credentials", lambda: None)
    assert _cached_primary_llm(key, "PROMPT") is None


def test_hit_builds_adapter_with_cached_primary(monkeypatch):
    key = ("b", "te", "2026-07-19", "abc")
    _PROMPT_CACHE[key] = ("caches/x", "PROMPT")
    monkeypatch.setattr(agent_mod, "_vertex_credentials", lambda: ("/tmp/sa.json", "proj"))
    adapter = _cached_primary_llm(key, "PROMPT")
    assert adapter is not None
    primary = adapter._llm_instances[0] if hasattr(adapter, "_llm_instances") else adapter._llms[0]
    # the Vertex primary carries the cache resource; fallbacks stay plain
    assert getattr(primary._opts, "cached_content", None) == "caches/x" or \
        "caches/x" in repr(vars(primary._opts))


def test_exact_variant_and_agent_ride_source_guard():
    """Stable clinic prompt is cached; private call context is not."""
    src = inspect.getsource(agent_mod)
    assert "_cache_eligible" not in src
    assert "_prompt_cache_key(branch.id, lang_code, instructions)" in src
    assert "llm=_cached_llm," in src
    assert "_resolve_cached_primary_llm" in src
    assert "voice:prompt-cache:" in src
    assert "<private_session_context>" in src
    compose = src.split("def _compose_instructions", 1)[1].split(
        "def _compose_runtime_context", 1
    )[0]
    assert "caller_prompt_extra" not in compose
    assert "date_context" not in compose
    runtime = src.split("def _compose_runtime_context", 1)[1][:1200]
    assert "caller_prompt_extra" in runtime and "date_context" in runtime
    # background bake happens on an exact-variant miss
    assert "_create_prompt_cache(" in src


def test_create_prompt_cache_never_raises(monkeypatch):
    # RULE 8: creation failure logs and leaves the plain path untouched.
    monkeypatch.setattr(agent_mod, "_vertex_credentials",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    key = ("b", "te", "d", "abc")
    asyncio.run(agent_mod._create_prompt_cache(key, "P", []))
    assert key not in _PROMPT_CACHE


def test_proactive_warmer_covers_active_clinics_and_saved_languages():
    src = inspect.getsource(agent_mod._warm_all_clinic_prompt_caches)
    assert "b.status = 'active'" in src
    assert "preferred_language" in src
    assert "supported_codes" in src
    assert "recording_variants" in src
    assert "_create_prompt_cache" in src


def test_raw_database_faq_is_normalized_without_breaking_warmup():
    assert _decode_branch_faq('[{"q":"Hours?","a":"Nine"}]') == [
        {"q": "Hours?", "a": "Nine"}
    ]
    assert _decode_branch_faq({"q": "wrong shape"}) == []
    assert _decode_branch_faq("not json") == []
