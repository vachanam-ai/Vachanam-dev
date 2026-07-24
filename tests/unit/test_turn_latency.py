"""Turn-gap latency — final state after the #394-#399 arc.

#399 REVERT (real call 06:29Z 2026-07-18): eager Soniox endpointing + forced
finalize-on-VAD-end CORRUPTED Telugu recognition ("కరిష్మా" → "హరీష్ కుమార్",
utterances chopped into fragments), and the thinking-ack misfired between the
agent's own reply sentences on two consecutive attempts. Both retired.

What latency work REMAINS in force (overlap + model-side, zero answer-quality risk):
  * gemini thinking_level=minimal (#397 — kills 3.2s thinking bursts)
  * preemptive LLM+TTS + call-setup concurrency (#390)
  * prompt-side spoken lead-in (#387)
These guards pin BOTH directions: the reverts stay reverted, the keepers stay.
"""
from pathlib import Path

SRC = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")


def test_soniox_uses_isolated_conservative_latency_profile():
    stt = SRC.split("def _build_stt")[1][:5000]
    assert "endpoint_latency_adjustment_level=settings.soniox_endpoint_latency_level" in stt
    assert "max_endpoint_delay_ms=settings.soniox_max_endpoint_delay_ms" in stt
    assert "endpoint_sensitivity=settings.soniox_endpoint_sensitivity" in stt
    assert "max_endpoint_delay_ms=800" not in stt
    assert "endpoint_sensitivity=0.3" not in stt


def test_delayed_finalize_is_session_scoped_and_thinking_ack_stays_removed():
    assert "class _FinalizingSonioxSTT(soniox.STT)" in SRC
    assert "class _SonioxFinalizeController" in SRC
    assert "_soniox_finalize_all" not in SRC
    assert "thinking_ack" not in SRC
    assert '{"type": "finalize"}' in SRC
    assert "old_state == 'speaking' and new_state == 'listening'" in SRC
    assert "_soniox_finalizer.cancel()" in SRC
    assert "weakref.WeakSet()" in SRC
    # the do-not-re-add note stands where the ack lived
    assert "THINKING ACK: REMOVED (#399)" in SRC


def test_llm_side_latency_work_stays():
    assert SRC.count('thinking_level="minimal"') >= 2  # #397, turn + routing
    assert 'thinking_level="low"' not in SRC
    assert "async def _prewarm_llm" not in SRC
    assert '"preemptive_tts": True' in SRC
    assert '"max_retries": 2' in SRC
    assert "await asyncio.gather(" in SRC               # #390 setup concurrency


def test_tool_lookup_fillers_untouched():
    # the PROVEN filler (inside tool calls) survives the ack removal.
    # #429 gave _play_cached_filler a bucket arg and split the wait phrase out;
    # both helpers must still exist and still be driven from tool calls only
    # (never a state-gated ack — that is the banned #399 pattern).
    assert "def _play_cached_filler(sess, key" in SRC
    assert "_say_lookup_filler(context)" in SRC
    assert "_say_wait_filler(context)" in SRC


def test_soniox_context_biasing_400():
    """#400 (real call: "కరిష్మా" heard as "హరీష్ కుమార్"): the clinic's doctor
    names + clinic name ride Soniox context biasing on every live STT build
    (session + language-switch handoff). Accuracy lever — endpointing stays
    at plugin defaults."""
    stt = SRC.split("def _build_stt")[1][:6000]
    assert "soniox.ContextObject(" in stt and "terms=terms[:120]" in stt
    assert "ContextGeneralItem" in stt
    assert "_stt_terms = [d.name for d in doctor_contexts]" in SRC
    assert SRC.count("finalize_controller=_soniox_finalizer") == 2
    # #401: a switch ask must survive cross-language transcription — the
    # language names ride the bias terms in both scripts.
    assert '"English", "ఇంగ్లీష్", "Hindi", "హిందీ"' in SRC


def test_hello_immune_barge_in_403():
    """#403: a lone "hello"/backchannel must never CUT the agent — interruption
    commits only on >=2 transcribed words; a false (one-word) barge-in resumes
    the same sentence. VAD still pauses instantly, so real barge-in stays fast."""
    assert '"min_words": 2' in SRC
    assert '"resume_false_interruption": True' in SRC
    assert "min_interruption_words=0" not in SRC


def test_vertex_mumbai_primary_404(tmp_path, monkeypatch):
    """#404: with SA creds present, the turn LLM chain is Vertex Mumbai
    2.5-flash first (measured ttft 0.67-0.69s at prod prompt size vs
    1.05-1.28s global), then the unchanged global-API pair (RULE 8)."""
    from agent.livekit_minimal import agent as ag

    sa = tmp_path / "sa.json"
    sa.write_text('{"project_id": "vachanam-498912"}')
    monkeypatch.setattr(ag.settings, "google_sa_json_b64", None, raising=False)
    monkeypatch.setattr(
        ag.settings, "google_application_credentials", str(sa), raising=False
    )

    adapter = ag._build_fallback_llm()
    opts = [llm._opts for llm in adapter._llm_instances]
    assert opts[0].model == "gemini-2.5-flash"
    assert opts[0].vertexai is True
    assert opts[0].project == "vachanam-498912"
    assert opts[0].location == "asia-south1"
    # fallbacks: exactly the pre-#404 global chain
    assert opts[1].model == "gemini-3.1-flash-lite"
    assert opts[1].vertexai is False
    assert opts[2].model == "gemini-2.5-flash"
    assert opts[2].vertexai is False


def test_soniox_region_configurable_406():
    """#406: Soniox WS endpoint rides the Japan-only regional setting.
    4ms from Fly bom vs 230ms US — measured 2026-07-18). Keys are region-scoped,
    so the flip is env-only. #442 changes endpoint controls independently."""
    from backend.config import settings as s

    stt = SRC.split("def _build_stt")[1][:6000]
    assert "base_url=settings.soniox_jp_stt_ws_url" in stt
    assert s.soniox_jp_stt_ws_url == "wss://stt-rt.jp.soniox.com/transcribe-websocket"
    assert "endpoint_latency_adjustment_level=settings.soniox_endpoint_latency_level" in stt
    assert "max_endpoint_delay_ms=settings.soniox_max_endpoint_delay_ms" in stt
    assert "endpoint_sensitivity=settings.soniox_endpoint_sensitivity" in stt


def test_vertex_missing_creds_falls_back_404(tmp_path, monkeypatch):
    """#404 RULE 8: no SA creds -> chain is exactly the old global config;
    a broken Vertex setup must never block call handling."""
    from agent.livekit_minimal import agent as ag

    monkeypatch.setattr(ag.settings, "google_sa_json_b64", None, raising=False)
    monkeypatch.setattr(
        ag.settings,
        "google_application_credentials",
        str(tmp_path / "missing.json"),
        raising=False,
    )
    assert ag._vertex_credentials() is None

    adapter = ag._build_fallback_llm()
    opts = [llm._opts for llm in adapter._llm_instances]
    assert [o.model for o in opts] == ["gemini-3.1-flash-lite", "gemini-2.5-flash"]
    assert all(o.vertexai is False for o in opts)
