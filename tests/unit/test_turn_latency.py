"""Turn-gap latency — final state after the #394-#399 arc.

#399 REVERT (real call 06:29Z 2026-07-18): eager Soniox endpointing + forced
finalize-on-VAD-end CORRUPTED Telugu recognition ("కరిష్మా" → "హరీష్ కుమార్",
utterances chopped into fragments), and the thinking-ack misfired between the
agent's own reply sentences on two consecutive attempts. Both retired.

What latency work REMAINS in force (LLM-side only, zero accuracy risk):
  * gemini thinking_level=minimal (#397 — kills 3.2s thinking bursts)
  * real-prompt LLM prewarm (#393) + call-setup concurrency (#390)
  * prompt-side spoken lead-in (#387)
These guards pin BOTH directions: the reverts stay reverted, the keepers stay.
"""
from pathlib import Path

SRC = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")


def test_soniox_runs_at_plugin_defaults():
    stt = SRC.split("def _build_stt")[1][:2500]
    assert "max_endpoint_delay_ms" not in stt
    assert "endpoint_sensitivity" not in stt
    # the revert reason stays documented at the tuning site
    assert "PLUGIN DEFAULTS" in stt


def test_no_forced_finalize_and_no_thinking_ack():
    assert "_FinalizingSonioxSTT" not in SRC
    assert "_soniox_finalize_all" not in SRC
    assert "thinking_ack" not in SRC
    assert '{"type": "finalize"}' not in SRC
    # the do-not-re-add note stands where the ack lived
    assert "THINKING ACK: REMOVED (#399)" in SRC


def test_llm_side_latency_work_stays():
    assert SRC.count('thinking_level="minimal"') >= 2  # #397, turn + routing
    assert 'thinking_level="low"' not in SRC
    assert "async def _prewarm_llm" in SRC              # #393
    assert 'role="system", content=instructions' in SRC
    assert "await asyncio.gather(" in SRC               # #390 setup concurrency


def test_tool_lookup_fillers_untouched():
    # the PROVEN filler (inside tool calls) survives the ack removal
    assert "def _play_cached_filler(sess)" in SRC
    assert "_say_lookup_filler(context)" in SRC


def test_soniox_context_biasing_400():
    """#400 (real call: "కరిష్మా" heard as "హరీష్ కుమార్"): the clinic's doctor
    names + clinic name ride Soniox context biasing on every live STT build
    (session + language-switch handoff). Accuracy lever — endpointing stays
    at plugin defaults."""
    stt = SRC.split("def _build_stt")[1][:3500]
    assert "soniox.ContextObject(terms=" in stt
    assert "_stt_terms = [d.name for d in doctor_contexts]" in SRC
    assert "_build_stt(lang_cfg, _stt_terms)" in SRC   # session pipeline
    assert "_build_stt(cfg2, _stt_terms)" in SRC       # switch_language handoff
