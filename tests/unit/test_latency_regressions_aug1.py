"""Regressions for the 2026-08-01 end-to-end latency audit."""
from __future__ import annotations

import asyncio

import agent.livekit_minimal.agent as agent_mod
from agent.services.tts_sanitizer import internal_trace_prefix_len
from agent.tools.booking_tools import _redis_int_values


async def test_safe_speech_reaches_tts_without_fixed_24_character_buffer():
    release = asyncio.Event()

    async def chunks():
        yield "సరే అండి, "
        await release.wait()
        yield "చూస్తాను."

    stream = agent_mod._guard_internal_speech_stream(chunks())
    first = await asyncio.wait_for(anext(stream), timeout=0.1)
    assert first == "సరే అండి, "
    release.set()
    assert "".join([part async for part in stream]) == "చూస్తాను."


async def test_stream_guard_still_holds_and_drops_split_private_marker():
    async def chunks():
        yield "సరే. check_avai"
        yield "lability doctor_id=secret. తర్వాత చెబుతాను."

    out = "".join([
        part async for part in agent_mod._guard_internal_speech_stream(chunks())
    ])
    assert "check" not in out.lower()
    assert "doctor_id" not in out.lower()
    assert out == "సరే.  తర్వాత చెబుతాను."


def test_prefix_carry_is_targeted_not_unconditional():
    assert internal_trace_prefix_len("safe receptionist reply") == 0
    assert internal_trace_prefix_len("safe check_avai") == len("check_avai")
    assert internal_trace_prefix_len("safe response_") == len("response_")


async def test_slot_counters_are_fetched_in_one_redis_round_trip():
    class Redis:
        def __init__(self):
            self.calls = []

        async def mget(self, keys):
            self.calls.append(keys)
            return [None, "2", 3]

    redis = Redis()
    keys = ["slot:1", "slot:2", "slot:3"]
    assert await _redis_int_values(redis, keys) == [0, 2, 3]
    assert redis.calls == [keys]


async def test_shared_prompt_cache_uses_sync_client_accessor(monkeypatch):
    class Redis:
        async def get(self, key):
            return "projects/p/locations/asia-south1/cachedContents/one"

    monkeypatch.setattr("backend.redis_client.get_redis", lambda: Redis())
    agent_mod._PROMPT_CACHE.clear()
    key = ("branch", "te", "2026-08-01", "digest")
    assert await agent_mod._load_shared_prompt_cache(key, "prompt") is True
    assert agent_mod._PROMPT_CACHE[key][1] == "prompt"
async def test_greeting_and_clinic_cache_reach_redis_commands(monkeypatch):
    import agent.livekit_minimal.greeting as greeting
    from backend.services import clinic_cache

    class Redis:
        def __init__(self):
            self.get_calls = 0

        async def get(self, key):
            self.get_calls += 1
            return None

    redis = Redis()
    monkeypatch.setattr("backend.redis_client.get_redis", lambda: redis)
    assert await greeting._greeting_cache_get("missing") is None
    assert await clinic_cache.get_doctors("branch") is None
    assert redis.get_calls == 2


async def test_booking_tools_reuse_shared_loop_client(monkeypatch):
    from agent.tools import booking_tools

    sentinel = object()
    monkeypatch.setattr("backend.redis_client.get_redis", lambda: sentinel)
    async with booking_tools._redis() as redis:
        assert redis is sentinel


def test_tool_loop_is_bounded_without_breaking_two_step_booking_flows():
    source = open(agent_mod.__file__, encoding="utf-8").read()
    main_session = source.split("        session = AgentSession(", 1)[1]
    assert "max_tool_steps=2" in main_session[:500]