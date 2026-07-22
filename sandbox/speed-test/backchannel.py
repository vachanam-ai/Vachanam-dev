"""Pure backchannel picker — no livekit import, so it unit-tests standalone.

The ~700-1000ms STT-final wait is the architectural floor (proven
provider-independent 2026-07-22: Soniox JP ~690ms vs Sarvam Mumbai ~865ms).
Can't cut it, so MASK it: play one of these instant pure-acks on VAD speech-end
while the real reply generates behind it. Zero commitment, interruptible.
"""
from __future__ import annotations

import random

BACKCHANNELS = ["హా.", "అలాగే.", "సరే.", "ఒక్క క్షణం."]


def pick_backchannel(prev: str | None) -> str:
    """Random ack, never the same one twice running (repetition reads robotic)."""
    pool = [b for b in BACKCHANNELS if b != prev] or BACKCHANNELS
    return random.choice(pool)
