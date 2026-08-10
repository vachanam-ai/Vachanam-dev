"""TTS provider swap for the Cartesia sandbox (Vinay 2026-08-07).

    "create a sandbox and replace TTS with Cartesia instead of soniox...
     just a test sandbox without disturbing existing things."

The point of these tests is the LAST clause. Production must be unable to pick
up Cartesia by accident, and the tuned Soniox path must be unchanged.
"""
from __future__ import annotations

import inspect


def test_the_default_provider_is_still_soniox():
    """Nothing changes unless a deployment explicitly opts in."""
    from backend.config import Settings

    assert Settings().tts_provider == "soniox"


def test_the_soniox_path_is_untouched_by_the_swap():
    """The Cartesia branch is a separate function, not an edit to the tuned one."""
    import agent.livekit_minimal.agent as a

    soniox_src = inspect.getsource(a._build_soniox_tts)
    assert "cartesia" not in soniox_src.lower()
    assert "settings.soniox_tts_model" in soniox_src


def test_cartesia_is_only_reachable_by_explicit_opt_in():
    import agent.livekit_minimal.agent as a

    src = inspect.getsource(a._build_session_tts)
    assert 'settings.tts_provider or "soniox"' in src
    assert '== "cartesia"' in src


def test_a_cartesia_deployment_needs_no_soniox_key():
    """The provider check must come BEFORE the Soniox key requirement, or a
    Cartesia-only sandbox cannot boot."""
    import agent.livekit_minimal.agent as a

    src = inspect.getsource(a._build_session_tts)
    assert src.index('== "cartesia"') < src.index("SONIOX_JP_API_KEY is required")


def test_a_missing_cartesia_key_fails_loudly():
    import agent.livekit_minimal.agent as a

    src = inspect.getsource(a._build_session_tts)
    assert "CARTESIA_API_KEY is unset" in src


def test_cartesia_has_a_sandbox_only_short_first_chunk():
    """Cartesia starts short acknowledgements without changing Soniox."""
    import agent.livekit_minimal.agent as a

    assert "min_sentence_len=8" in inspect.getsource(a._build_soniox_tts)
    cartesia_src = inspect.getsource(a._build_cartesia_tts)
    assert "settings.cartesia_min_sentence_len" in cartesia_src
    assert "stream_context_len=4" in cartesia_src


def test_the_sandbox_selection_is_logged():
    """A sandbox you cannot tell apart from prod in the logs is a trap."""
    import agent.livekit_minimal.agent as a

    assert "tts_provider_cartesia" in inspect.getsource(a._build_cartesia_tts)


def test_cartesia_is_prewarmed_off_the_first_reply_path():
    import agent.livekit_minimal.agent as a

    src = inspect.getsource(a._build_session_tts)
    cartesia_branch = src.split('== "cartesia"', 1)[1].split(
        "SONIOX_JP_API_KEY is required", 1
    )[0]
    assert "primary.prewarm()" in cartesia_branch


def test_cartesia_keeps_its_warm_socket_by_skipping_speculative_tts(monkeypatch):
    """Tool calls cancel speculative speech; the plugin then discards its
    pooled WebSocket and the real answer pays a fresh connection handshake."""
    import agent.livekit_minimal.agent as a

    monkeypatch.setattr(a.settings, "tts_provider", "cartesia")
    assert a._preemptive_tts_enabled() is False
    monkeypatch.setattr(a.settings, "tts_provider", "soniox")
    assert a._preemptive_tts_enabled() is True


def test_cartesia_connection_reuse_is_visible_in_runtime_metrics():
    import agent.livekit_minimal.agent as a

    src = inspect.getsource(a._on_metrics) if hasattr(a, "_on_metrics") else inspect.getsource(a)
    assert "acquire=%.2fs reused=%s cancelled=%s" in src


def test_the_sandbox_registers_under_its_own_agent_name():
    """Two workers sharing a LiveKit agent name are BOTH eligible for the same
    call, so a sandbox using the production name would answer real patients."""
    import agent.livekit_minimal.agent as a

    src = inspect.getsource(a)
    assert 'AGENT_NAME = os.getenv("LIVEKIT_AGENT_NAME", "vachanam-agent")' in src
    assert a.AGENT_NAME == "vachanam-agent", "unset in this environment = prod name"


def test_the_sandbox_fly_config_cannot_collide_with_production():
    import pathlib

    cfg = pathlib.Path("infra/fly.agent-sandbox.toml").read_text(encoding="utf-8")
    prod = pathlib.Path("infra/fly.agent.toml").read_text(encoding="utf-8")
    assert 'app = "vachanam-agent-sandbox"' in cfg
    assert 'app = "vachanam-agent"' in prod
    assert 'LIVEKIT_AGENT_NAME = "vachanam-sandbox"' in cfg
    assert 'TTS_PROVIDER = "cartesia"' in cfg
    assert 'CARTESIA_MIN_SENTENCE_LEN = "4"' in cfg
    # Production now carries the proven Soniox/16 kHz profile, never Cartesia
    # or the sandbox worker identity.
    assert 'TTS_PROVIDER = "soniox"' in prod
    assert 'SONIOX_TTS_SAMPLE_RATE = "16000"' in prod
    assert "LIVEKIT_AGENT_NAME" not in prod
    assert "cartesia" not in prod.lower()
