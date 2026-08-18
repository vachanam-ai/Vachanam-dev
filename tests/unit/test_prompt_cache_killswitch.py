"""VOICE_PROMPT_CACHE=0 must close EVERY route to a Vertex CachedContent.

The cache buys no latency (llm_ttft p50 556ms cached vs 563ms uncached over
1,529 turns, 2026-08-11) and storage runs ~Rs650/mo per clinic-language, so it
only pays above ~660 talk-minutes/month. Basic includes 500.

There are four entry points and missing one still bills: the creator, the Redis
loader that adopts another worker's cache, the builder that attaches
`cached_content` to the Vertex LLM, and the resolver that combines them.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from agent.livekit_minimal import agent as ag
from backend.config import settings

KEY = ("11111111-2222-3333-4444-555555555555", "te", "2026-08-12", "digest")


@pytest.fixture
def cache_off(monkeypatch):
    monkeypatch.setattr(settings, "voice_prompt_cache", False)
    monkeypatch.setattr(settings, "llm_provider", "gemini")


def test_creator_is_closed(cache_off):
    assert asyncio.run(ag._create_prompt_cache(KEY, "instructions", [])) is False


def test_redis_loader_is_closed(cache_off, monkeypatch):
    def boom():  # touching Redis at all means the switch leaked
        raise AssertionError("read Redis with the cache switch off")

    monkeypatch.setattr("backend.redis_client.get_redis", boom)
    assert asyncio.run(ag._load_shared_prompt_cache(KEY, "instructions")) is False


def test_builder_ignores_an_already_warm_entry(cache_off):
    """A cache warmed BEFORE the switch was flipped must not be attached."""
    ag._PROMPT_CACHE[KEY] = ("projects/x/locations/asia-south1/cachedContents/1",
                             "instructions")
    try:
        assert ag._cached_primary_llm(KEY, "instructions") is None
        assert asyncio.run(ag._resolve_cached_primary_llm(KEY, "instructions")) is None
    finally:
        ag._PROMPT_CACHE.pop(KEY, None)


def test_switch_defaults_off_so_new_deployments_do_not_bill_storage():
    from backend.config import Settings

    assert Settings.model_fields["voice_prompt_cache"].default is False


def test_every_cache_entry_point_checks_the_switch():
    """Guard against a fifth entry point being added without the check."""
    tree = ast.parse(Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8"))
    gated = {
        "_load_shared_prompt_cache", "_create_prompt_cache",
        "_cached_primary_llm", "_resolve_cached_primary_llm",
    }
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in gated:
            continue
        src = ast.dump(node)
        assert "voice_prompt_cache" in src, f"{node.name} does not check the switch"
        seen.add(node.name)
    assert seen == gated, f"missing cache entry points: {gated - seen}"
