"""2026-07-04 live fixes: cancel said 'failed' while the DB row was already
cancelled_by_patient (calendar delete blocked _do_cancel for 36s), and the
English agent read Telugu-script names raw ("శ్రీ వెంకటేశ్వర" mangled).
"""
import inspect

import pytest

from agent.i18n.transliterate import _detect_script, spoken_text
from agent.livekit_minimal import agent as agent_mod
from agent.livekit_minimal.agent import VachanamAgent


# ── Cancel: calendar cleanup capped + success unmistakable ──

def test_do_cancel_caps_calendar_delete_and_asserts_success():
    src = inspect.getsource(VachanamAgent._do_cancel)
    assert "asyncio.timeout(5)" in src          # 36s retry stall can't recur
    assert "The cancellation SUCCEEDED" in src  # LLM can't misread the result
    assert "Do NOT say it" in src


# ── Names: every script rendered into the call language ──

def test_detect_script_blocks():
    assert _detect_script("శ్రీ వెంకటేశ్వర") == "te-IN"
    assert _detect_script("वinaय") == "hi-IN"
    assert _detect_script("Vinay") == "en-IN"
    assert _detect_script("தமிழ்") == "ta-IN"


@pytest.mark.asyncio
async def test_spoken_text_noop_when_script_matches():
    # Same script as the call language -> no network, unchanged.
    assert await spoken_text("శ్రీ వెంకటేశ్వర", "te") == "శ్రీ వెంకటేశ్వర"
    assert await spoken_text("Vinay", "en") == "Vinay"
    assert await spoken_text("", "en") == ""


@pytest.mark.asyncio
async def test_spoken_text_romanizes_for_english(monkeypatch):
    async def fake_hop(text, src, tgt):
        assert (src, tgt) == ("te-IN", "en-IN")
        return "Sri Venkateswara"
    monkeypatch.setattr("agent.i18n.transliterate._sarvam_hop", fake_hop)
    out = await spoken_text("శ్రీ వెంకటేశ్వర TEST1", "en")
    assert out == "Sri Venkateswara"


@pytest.mark.asyncio
async def test_spoken_text_indic_to_indic_hops_via_latin(monkeypatch):
    hops = []
    async def fake_hop(text, src, tgt):
        hops.append((src, tgt))
        return "Vinay" if tgt == "en-IN" else "विनय"
    monkeypatch.setattr("agent.i18n.transliterate._sarvam_hop", fake_hop)
    out = await spoken_text("వినయ్ TEST2", "hi")
    assert out == "विनय"
    assert hops == [("te-IN", "en-IN"), ("en-IN", "hi-IN")]


@pytest.mark.asyncio
async def test_spoken_text_falls_back_to_original_on_failure(monkeypatch):
    async def fake_hop(text, src, tgt):
        return None
    monkeypatch.setattr("agent.i18n.transliterate._sarvam_hop", fake_hop)
    assert await spoken_text("వినయ్ TEST3", "en") == "వినయ్ TEST3"


def test_greetings_use_transliterated_clinic_and_caller():
    """No greeting may feed the raw stored clinic/caller name to TTS.

    Greeting composition moved to greeting.py (FIXLOG #264): agent.py must hand
    the greeting helpers ONLY the spoken (transliterated) forms, never the raw
    stored names."""
    src = inspect.getsource(agent_mod)
    assert "clinic=branch_name" not in src
    assert "patient=caller_greeting_name" not in src
    # Every greeting-helper call site rides on the spoken forms.
    assert src.count("_spk_clinic") >= 4
    assert "inbound_greeting_texts(" in src and "outbound_greeting_texts(" in src
    assert "spk_caller=_spk_caller" in src
    # The raw names must not be format args anywhere in the module.
    assert "clinic=branch.name" not in src
