"""#362/#363 (Vinay real call 2026-07-14): after a language switch the agent
(1) left an audible gap before the new voice spoke, and (2) kept playing the
OLD language's cached filler clips ("సరే అండి…" in an English call).

Contracts guarded here (source-inspection — the switch path needs a live
LiveKit session to run end-to-end):
  - switch_language drops the stale filler_clips cache and re-caches clips in
    the NEW language in the background;
  - switch_language pre-synthesizes the FULL ack (not just an "ok" prime) and
    stashes frames on the new agent;
  - on_enter replays the cached frames (zero-synth ack) and falls back to
    live synth when absent.
"""
import inspect

from agent.livekit_minimal.agent import VachanamAgent


def _src(name):
    return inspect.getsource(getattr(VachanamAgent, name))


def test_switch_clears_stale_filler_clips():
    src = _src("switch_language")
    assert 'ud["filler_clips"] = []' in src


def test_switch_recaches_fillers_in_new_language():
    src = _src("switch_language")
    assert "cache_filler_clips(" in src
    # background, never blocking the handoff
    assert "create_task" in src


def test_switch_presynthesizes_full_ack():
    src = _src("switch_language")
    assert "_switch_ack_frames" in src
    # the old prime synthesized a throwaway "ok" — must be gone
    assert 'synthesize("ok")' not in src


def test_on_enter_replays_presynth_frames_with_fallback():
    src = _src("on_enter")
    assert "_switch_ack_frames" in src
    assert "audio=_replay()" in src
    # fallback live-say path must survive for presynth failures (RULE 8)
    assert "else:" in src
