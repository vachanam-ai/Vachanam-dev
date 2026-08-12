"""A voice changed in the dashboard must reach the greeting without a redeploy.

The DID->clinic map is a snapshot taken when the job subprocess starts. Before
this fix the only thing compared against the authoritative row was the tenant
id, so a voice changed afterwards kept greeting in the OLD voice while the
conversation used the new one — one call, two voices (Vinay 2026-08-12).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent.livekit_minimal.greeting import greeting_voice_key

SRC = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")


def test_entrypoint_compares_the_voice_not_only_the_tenant():
    assert "_early_voice_stale" in SRC, "no voice comparison in the entrypoint"
    assert "early_greeting_voice_stale" in SRC, "stale voice is not logged"
    # The cancel must be reachable from the voice check, not just tenant.
    assert "or _early_voice_stale" in SRC


def test_module_still_parses():
    ast.parse(SRC)


@pytest.mark.parametrize("cached, live, stale", [
    ("Priya", "Meera", True),      # changed in the dashboard -> must refresh
    ("Meera", "Meera", False),     # unchanged -> keep the head start
    ("Priya", None, False),        # branch has no voice -> nothing to compare
    ("Priya", "priya", False),     # same voice, different case
    ("nonsense-voice", "Meera", True),   # unknown cached name resolves to the
                                          # default, still != Meera
])
def test_voice_key_comparison_semantics(cached, live, stale):
    """The entrypoint's comparison, isolated.

    greeting_voice_key is what both the cache key and the synth agree on, so
    comparing through it avoids a false mismatch between 'Priya' and a voice
    that merely resolves to Priya.
    """
    got = greeting_voice_key(cached) != greeting_voice_key(live or cached)
    assert got is stale
