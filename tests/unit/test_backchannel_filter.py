"""Backchannel filter (Vinay 2026-07-04): "aha / okay / hmm / acha" while the
agent is talking must not interrupt it — in every language. Real content and
anything said while the agent is silent must always pass."""
import inspect

from agent.i18n.backchannels import is_backchannel, suppress_backchannel
from agent.livekit_minimal.agent import VachanamAgent


# ── lexicon ──

def test_pure_backchannels_detected_across_languages():
    for t in (
        "okay", "Okay.", "hmm", "aha", "acha", "haan", "ok ok",
        "ఓకే", "ఆ", "హా", "హ్మ్", "అచ్చా",
        "हाँ", "हम्म", "अच्छा", "ओके",
        "ம்ம்", "ಹೂಂ", "ഉം", "হুম", "ହଁ",
        "uh huh", "mm-hm",
    ):
        assert is_backchannel(t), t


def test_real_content_never_matches():
    for t in (
        "okay cancel it",            # backchannel + real content
        "no",                        # an ANSWER, not a listening noise
        "yes",                       # answer
        "అవును",                     # Telugu yes — answer
        "సరే",                       # Telugu consent — answer
        "no no wait",                # real interruption
        "cancel my appointment",
        "हाँ जी बुक कर दो",
        "",
        "   ",
    ):
        assert not is_backchannel(t), t


def test_more_than_three_tokens_passes_through():
    assert not is_backchannel("okay okay okay okay")


# ── the decision: only while the agent is speaking ──

def test_suppressed_only_while_agent_speaking():
    assert suppress_backchannel("hmm", agent_speaking=True)
    assert suppress_backchannel("ఓకే", agent_speaking=True)
    # Agent silent -> the same word is a real (short) user turn.
    assert not suppress_backchannel("hmm", agent_speaking=False)
    assert not suppress_backchannel("ఓకే", agent_speaking=False)
    # Real content passes even mid-speech.
    assert not suppress_backchannel("no no wait", agent_speaking=True)


# ── wiring: the filter sits in the STT node, fail-open ──

def test_stt_node_filters_and_fails_open():
    src = inspect.getsource(VachanamAgent.stt_node)
    assert "suppress_backchannel" in src
    assert "INTERIM_TRANSCRIPT" in src and "FINAL_TRANSCRIPT" in src
    # Any filter error must NEVER eat real speech — event still yielded.
    assert "backchannel_filter_error" in src
    assert src.rstrip().endswith("yield ev")


import pytest
from types import SimpleNamespace

from agent.livekit_minimal import agent as agent_mod
from agent.session_state import SessionState
from livekit.agents import Agent, stt as lk_stt


def _agent():
    return VachanamAgent(
        instructions="x", state=SessionState(), db=None, room=None,
        calendar_service=None, meta_service=None, transfer_to="",
    )


def _ev(text, final=True):
    return SimpleNamespace(
        type=(lk_stt.SpeechEventType.FINAL_TRANSCRIPT if final
              else lk_stt.SpeechEventType.INTERIM_TRANSCRIPT),
        alternatives=[SimpleNamespace(text=text)],
    )


@pytest.mark.asyncio
async def test_stt_node_drops_backchannels_only_while_speaking(monkeypatch):
    events = [_ev("hmm"), _ev("ఓకే", final=False), _ev("no no wait"), _ev("okay cancel it")]

    async def fake_default(agent, audio, model_settings):
        for e in events:
            yield e

    monkeypatch.setattr(Agent.default, "stt_node", fake_default)

    a = _agent()
    # Agent SPEAKING -> backchannels dropped, real content passes.
    monkeypatch.setattr(
        VachanamAgent, "session",
        property(lambda self: SimpleNamespace(agent_state="speaking")),
    )
    got = [e async for e in a.stt_node(None, None)]
    assert [e.alternatives[0].text for e in got] == ["no no wait", "okay cancel it"]

    # Agent LISTENING -> everything passes.
    monkeypatch.setattr(
        VachanamAgent, "session",
        property(lambda self: SimpleNamespace(agent_state="listening")),
    )
    got = [e async for e in a.stt_node(None, None)]
    assert len(got) == 4


def test_alagey_is_backchannel_mid_speech_but_consent_when_silent():
    """Vinay 2026-07-04: 'okay/aha/alagey' mid-dictation must not interrupt;
    the SAME word after a completed question is consent and must pass."""
    for t in ("అలాగే", "alagey", "okay"):
        assert suppress_backchannel(t, agent_speaking=True), t
        assert not suppress_backchannel(t, agent_speaking=False), t
