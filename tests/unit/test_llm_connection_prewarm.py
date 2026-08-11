"""The LLM connection must be warmed in the idle subprocess, never per call.

A per-call dummy request was tried and removed once already: it raced a fast
caller's real request and could double generation. So the contract this guards
is narrow — warm exactly once per subprocess at prewarm, off the call path,
and never let a failure touch the call.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from agent.livekit_minimal import agent as ag
from backend.config import settings


class _FakeStream:
    def __init__(self, calls): self._calls = calls; self.closed = False
    def __aiter__(self): return self
    async def __anext__(self): return object()      # one chunk, then we break
    async def aclose(self): self.closed = True; self._calls.append("closed")


class _FakeLLM:
    def __init__(self): self.calls = []; self.streams = []
    def chat(self, *, chat_ctx, **kw):
        self.calls.append(chat_ctx)
        s = _FakeStream(self.calls); self.streams.append(s); return s


def _proc(llm): return SimpleNamespace(userdata={"llm": llm})


def _settle(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_prewarm_issues_exactly_one_request(monkeypatch):
    monkeypatch.setattr(settings, "voice_llm_prewarm", True)
    llm = _FakeLLM()
    ag._prewarm_llm_connection(_proc(llm))
    assert _settle(lambda: len(llm.calls) >= 1), "no warm request was issued"
    time.sleep(0.3)
    assert len([c for c in llm.calls if c != "closed"]) == 1, "warmed more than once"
    assert llm.streams[0].closed, "warm stream was left open"


def test_switch_off_issues_nothing(monkeypatch):
    monkeypatch.setattr(settings, "voice_llm_prewarm", False)
    llm = _FakeLLM()
    ag._prewarm_llm_connection(_proc(llm))
    time.sleep(0.3)
    assert llm.calls == []


def test_missing_llm_is_not_an_error(monkeypatch):
    monkeypatch.setattr(settings, "voice_llm_prewarm", True)
    ag._prewarm_llm_connection(SimpleNamespace(userdata={}))  # must not raise


def test_a_failing_warm_never_propagates(monkeypatch):
    """Prewarm runs before a call; an exception here must not kill the worker."""
    monkeypatch.setattr(settings, "voice_llm_prewarm", True)

    class _Boom:
        def chat(self, **kw): raise RuntimeError("vertex down")

    ag._prewarm_llm_connection(_proc(_Boom()))   # must not raise
    time.sleep(0.3)


def test_prewarm_hook_calls_it():
    """Guard the wiring: _prewarm must actually invoke the warmer."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_prewarm")
    assert "_prewarm_llm_connection" in ast.dump(fn), \
        "_prewarm no longer warms the LLM connection"


def test_switch_defaults_on():
    from backend.config import Settings
    assert Settings.model_fields["voice_llm_prewarm"].default is True
