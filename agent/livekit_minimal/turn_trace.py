"""Correlated per-turn latency trace (plan 2026-07-21 Phase 1, Task 1.1).

Joins the separate lat_eou / lat_llm / lat_tts signals into ONE summary dict
per caller turn, so the unattributed portion of the perceived turn gap
(TTFA review F1/F2) becomes measurable. Pure Python — no LiveKit imports,
injectable clock, emission via callback — so it is unit-testable in isolation.

Emission model: LLM/TTS metrics arrive AFTER first playout (LiveKit emits them
at stream end), so a turn is flushed complete on the NEXT turn's speech end or
an explicit flush(), never eagerly at playout. total_ms still measures
speech end -> playout start.

Privacy (hard constraint 9): the summary carries ONLY numeric stages and short
tags from SUMMARY_ALLOWED_KEYS. No transcripts, phones, names, or tool args.
The session field is a truncated hash of the room name, never the name itself.
"""
from __future__ import annotations

import hashlib
import time
from typing import Callable

# The complete legal field set of a summary line. The privacy test pins
# emitted keys to this allowlist — extend deliberately, never with free text.
SUMMARY_ALLOWED_KEYS = frozenset({
    "session", "turn", "kind", "language", "provider", "cache_hit",
    "total_ms", "stt_finalize_ms", "commit_ms", "eou_delay_ms",
    "transcription_delay_ms", "llm_ttft_ms", "llm_runs", "safety_buffer_ms",
    "tts_ttfb_ms", "tool", "tool_ms", "unaccounted_ms",
})


def _ms(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else round((b - a) * 1000, 1)


class TurnLatencyTrace:
    """One instance per call session. Not thread-safe; the agent event loop is
    single-threaded, which is exactly where every mark_* runs."""

    def __init__(self, session_id: str,
                 emit: Callable[[dict], None],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._session = hashlib.sha256(session_id.encode()).hexdigest()[:8]
        self._emit = emit
        self._clock = clock
        self._seq = 0
        self._ctx: dict = {}
        self._turn: dict | None = None
        self._speech_ids: set[str] = set()
        self._stale_ids: set[str] = set()

    # ── context tags (set once per call / language handoff) ─────────────────
    def set_context(self, language: str | None = None,
                    provider: str | None = None,
                    cache_hit: bool | None = None) -> None:
        if language is not None:
            self._ctx["language"] = language
        if provider is not None:
            self._ctx["provider"] = provider
        if cache_hit is not None:
            self._ctx["cache_hit"] = cache_hit

    # ── marks ───────────────────────────────────────────────────────────────
    def mark_speech_end(self) -> None:
        self.flush()
        self._speech_ids = set()
        self._turn = {"t_speech_end": self._clock(), "llm_runs": 0}

    def mark_final_transcript(self) -> None:
        if self._turn is not None:
            self._turn["t_final_transcript"] = self._clock()

    def mark_turn_committed(self, eou_delay: float | None = None,
                            transcription_delay: float | None = None) -> None:
        if self._turn is None:
            return
        self._turn["t_committed"] = self._clock()
        self._turn["eou_delay"] = eou_delay
        self._turn["transcription_delay"] = transcription_delay

    def mark_llm_run(self, speech_id: str, ttft: float) -> None:
        if self._turn is None or speech_id in self._stale_ids:
            return
        self._speech_ids.add(speech_id)
        self._turn["llm_runs"] += 1
        self._turn["ttft"] = ttft  # last run = the one that played

    def mark_guard_first_in(self) -> None:
        if self._turn is not None and "t_guard_in" not in self._turn:
            self._turn["t_guard_in"] = self._clock()

    def mark_guard_first_out(self) -> None:
        if self._turn is not None and "t_guard_out" not in self._turn:
            self._turn["t_guard_out"] = self._clock()

    def mark_tts(self, speech_id: str, ttfb: float) -> None:
        if self._turn is None or speech_id in self._stale_ids:
            return
        self._speech_ids.add(speech_id)
        self._turn["ttfb"] = ttfb

    def mark_tool(self, name: str, duration: float | None = None) -> None:
        if self._turn is not None:
            self._turn["tool"] = name
            if duration is not None:
                self._turn["tool_s"] = duration

    def mark_playout_start(self) -> None:
        if self._turn is not None and "t_playout" not in self._turn:
            self._turn["t_playout"] = self._clock()

    # ── flush ───────────────────────────────────────────────────────────────
    def flush(self) -> None:
        t = self._turn
        self._turn = None
        if t is None or "t_playout" not in t:
            return  # no user turn reached playout — nothing to report
        # seq assigned at EMISSION: an abandoned candidate (echo flap, caller
        # noise with no agent reply) must not consume a turn number.
        self._seq += 1
        self._stale_ids |= self._speech_ids
        total = _ms(t["t_speech_end"], t["t_playout"])
        stt_final = _ms(t["t_speech_end"], t.get("t_final_transcript"))
        commit = _ms(t.get("t_final_transcript"), t.get("t_committed"))
        guard = _ms(t.get("t_guard_in"), t.get("t_guard_out"))
        ttft_ms = None if "ttft" not in t else round(t["ttft"] * 1000, 1)
        ttfb_ms = None if "ttfb" not in t else round(t["ttfb"] * 1000, 1)
        known = sum(v for v in (stt_final, commit, ttft_ms, guard, ttfb_ms)
                    if v is not None)
        summary = {
            "session": self._session,
            "turn": self._seq,
            "kind": "tool" if "tool" in t else "chat",
            **self._ctx,
            "total_ms": total,
            "stt_finalize_ms": stt_final,
            "commit_ms": commit,
            "eou_delay_ms": None if t.get("eou_delay") is None
            else round(t["eou_delay"] * 1000, 1),
            "transcription_delay_ms": None if t.get("transcription_delay") is None
            else round(t["transcription_delay"] * 1000, 1),
            "llm_ttft_ms": ttft_ms,
            "llm_runs": t["llm_runs"],
            "safety_buffer_ms": guard,
            "tts_ttfb_ms": ttfb_ms,
            "unaccounted_ms": None if total is None
            else round(total - known, 1),
        }
        if "tool" in t:
            summary["tool"] = t["tool"]
            if "tool_s" in t:
                summary["tool_ms"] = round(t["tool_s"] * 1000, 1)
        self._emit(summary)



def format_summary_line(summary: dict) -> str:
    """`voice_turn_latency k=v ...` — single line, space-separated, no PII."""
    parts = ["voice_turn_latency"]
    for k, v in summary.items():
        parts.append(f"{k}={'null' if v is None else v}")
    return " ".join(parts)
