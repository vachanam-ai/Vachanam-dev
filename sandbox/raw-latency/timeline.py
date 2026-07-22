"""Per-call event timeline — stamps EVERY pipeline event in ms from call start.

Vinay 2026-07-22: a RAW stt+llm+tts line (no roster, no tools, no masking) to
find the exact latency. Every event becomes one line:

    RAWLAT id=<call> t=<ms-since-connect> dt=<ms-since-prev> ev=<name> k=v ...

`t` is wall-time from the call connecting; `dt` is the gap since the previous
event — the gaps are where latency hides. Pure Python with an injectable clock,
so ordering + format are unit-testable with no LiveKit/room.
"""
from __future__ import annotations

import hashlib
import time
from typing import Callable


def _clean(v: object) -> str:
    """k=v stays space-delimited: collapse whitespace in string values so a
    transcript ('నాకు అపాయింట్మెంట్') can't split into fake extra fields."""
    if isinstance(v, str):
        return "_".join(v.split()) or "∅"
    return str(v)


class CallTimeline:
    def __init__(self, call_id: str, emit: Callable[[str], None],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._id = hashlib.sha256(call_id.encode()).hexdigest()[:8]
        self._emit = emit
        self._clock = clock
        self._t0 = clock()
        self._last = self._t0

    def mark(self, event: str, **kv: object) -> None:
        now = self._clock()
        t = round((now - self._t0) * 1000, 1)
        dt = round((now - self._last) * 1000, 1)
        self._last = now
        parts = [f"RAWLAT id={self._id} t={t} dt={dt} ev={event}"]
        parts += [f"{k}={_clean(v)}" for k, v in kv.items()]
        self._emit(" ".join(parts))


if __name__ == "__main__":  # smallest runnable check
    seq: list[float] = [0.0, 0.0, 0.10, 0.85, 1.30]  # t0 + 4 events (seconds)
    out: list[str] = []
    tl = CallTimeline("room-abc", emit=out.append, clock=lambda: seq.pop(0))
    tl.mark("connect")
    tl.mark("user_stopped")
    tl.mark("stt_final", text="నాకు అపాయింట్మెంట్ కావాలి")
    tl.mark("agent_speaking")
    assert out[0].startswith("RAWLAT id=") and " t=0.0 dt=0.0 ev=connect" in out[0]
    assert " t=100.0 dt=100.0 ev=user_stopped" in out[1]
    assert " t=850.0 dt=750.0 ev=stt_final" in out[2]  # 750ms STT gap visible
    assert "text=నాకు_అపాయింట్మెంట్_కావాలి" in out[2]  # spaces collapsed
    assert " dt=450.0 ev=agent_speaking" in out[3]
    print("ok")
