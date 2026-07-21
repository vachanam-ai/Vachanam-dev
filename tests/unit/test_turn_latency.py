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
    assert "async def _prewarm_llm" in SRC              # #393
    assert 'role="system", content=instructions' in SRC
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
    assert "min_interruption_words=2" in SRC
    assert "resume_false_interruption=True" in SRC
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


def test_streaming_tts_chain_405():
    """#405: session TTS = WS-streaming primary (measured first-audio 0.2-0.46s
    vs 1.09-1.26s REST) + the exact pre-#405 REST path as RULE 8 fallback.
    Pro-catalog voices (sravani) ride lightning_v3.1_pro; clones stay standard."""
    from agent.i18n import get_lang
    from agent.livekit_minimal import agent as ag

    adapter = ag._build_session_tts("sravani", "te")
    prim, fb = adapter._tts_instances
    assert type(prim).__name__ == "_StreamingSmallestTTS"
    assert prim.capabilities.streaming is True
    assert prim._opts.model == "lightning_v3.1_pro"
    assert prim._opts.voice_id == "sravani"
    assert type(fb).__name__ == "_HttpSmallestTTS"
    assert fb.capabilities.streaming is False
    assert fb._opts.output_format == "wav"  # 2026-06-25 WAV-header rule holds

    clone = ag._build_session_tts("clinic-clone-abc", "te")
    assert clone._tts_instances[0]._opts.model == "lightning_v3.1"

    # sravani is the Telugu catalog default (Vinay 2026-07-18)
    assert get_lang("te").default_voice == "sravani"
    from backend.services.welcome_synth import model_for_voice

    assert model_for_voice("sravani") == "lightning_v3.1_pro"
    assert model_for_voice("padmaja") == "lightning_v3.1"


def test_streaming_agc_405():
    """#405: running-peak AGC replaces whole-clip normalize_pcm on the streaming
    path — quiet voices boosted (capped 6x), loud audio untouched, and gain
    never INCREASES mid-segment after loud audio raised the peak."""
    import numpy as np

    from agent.livekit_minimal import agent as ag

    class _Sink:
        def __init__(self):
            self.chunks = []

        def push(self, d):
            self.chunks.append(d)

    sink = _Sink()
    p = ag._AgcEmitterProxy(sink)
    p.push((np.ones(500, dtype=np.int16) * 1000).tobytes())
    assert np.frombuffer(sink.chunks[0], dtype=np.int16).max() == 6000  # 6x cap
    p.push((np.ones(500, dtype=np.int16) * 30000).tobytes())
    assert np.frombuffer(sink.chunks[1], dtype=np.int16).max() == 30000  # no clip
    # after the loud chunk raised the running peak, a quiet chunk gets the
    # REDUCED gain (target/30000 ≈ 0.97 → no boost), not the old 6x
    p.push((np.ones(500, dtype=np.int16) * 1000).tobytes())
    assert np.frombuffer(sink.chunks[2], dtype=np.int16).max() == 1000


def test_streaming_script_guard_and_warm_405():
    """#405: the WS stream carries the #270 script guard, and the session warm
    probe exercises the STREAMING path (not synthesize) so a broken WS falls
    back during the masked window."""
    assert "class _GuardedSmallestStream(_SmallestSynthStream)" in SRC
    guard = SRC.split("class _GuardedSmallestStream")[1][:1500]
    assert "_detect_script_lang" in guard
    assert "_AgcEmitterProxy(output_emitter)" in guard
    warm = SRC.split("async def _warm_session_tts")[1][:900]
    assert "_session_tts.stream()" in warm
    # one-shot synthesize on the streaming class must NEVER hit the plugin's
    # HTTP ChunkedStream (5x-speed bug) — it rides _RawRestChunked
    stream_cls = SRC.split("class _StreamingSmallestTTS")[1][:2200]
    assert "_RawRestChunked" in stream_cls


def test_soniox_region_configurable_406():
    """#406: Soniox WS endpoint rides settings.soniox_ws_url (US default; JP is
    4ms from Fly bom vs 230ms US — measured 2026-07-18). Keys are region-scoped,
    so the flip is env-only. #442 changes endpoint controls independently."""
    from backend.config import settings as s

    stt = SRC.split("def _build_stt")[1][:6000]
    assert "base_url=settings.soniox_ws_url" in stt
    assert s.soniox_ws_url.startswith("wss://stt-rt")
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
