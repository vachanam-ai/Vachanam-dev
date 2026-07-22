"""Voice turn-latency report (plan 2026-07-21, Task 1.2).

Feed it exported agent logs (Fly logs, or the structlog file) — it keeps the
`voice_turn_latency` summary lines emitted by TurnLatencyTrace and prints
p50/p95/p99 by cohort:

    python scripts/analyze_voice_latency.py fly.log [more.log ...]
    fly logs -a vachanam-agent | python scripts/analyze_voice_latency.py -

Rules (plan Phase 1): `null` stays None — never a fake zero; if the p50 of
unaccounted_ms exceeds 100ms the report says instrumentation is incomplete
and TUNING PAUSES until the missing buffer is found.
"""
from __future__ import annotations

import re
import sys
from statistics import median

_KV = re.compile(r"(\w+)=(\S+)")
_STAGES = (
    "total_ms", "from_last_word_ms", "vad_hangover_ms", "speak_dur_ms",
    "stt_finalize_ms", "commit_ms", "llm_ttft_ms", "tts_synth_ms",
    "safety_buffer_ms", "tts_ttfb_ms", "playout_gap_ms", "tool_ms",
    "unaccounted_ms",
)


def parse_line(line: str) -> dict | None:
    if "voice_turn_latency" not in line:
        return None
    row: dict = {}
    for k, v in _KV.findall(line.split("voice_turn_latency", 1)[1]):
        if v == "null":
            row[k] = None
        elif v in ("True", "False"):
            row[k] = v == "True"
        else:
            try:
                row[k] = int(v) if re.fullmatch(r"-?\d+", v) else float(v)
            except ValueError:
                row[k] = v
    return row or None


def _pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def _stats(rows: list[dict], field: str) -> str:
    vals = [r[field] for r in rows if r.get(field) is not None]
    if not vals:
        return f"  {field:22} n=0"
    return (f"  {field:22} n={len(vals):<4} p50={_pct(vals, 50):>8.1f} "
            f"p95={_pct(vals, 95):>8.1f} p99={_pct(vals, 99):>8.1f}")


def _cohorts(rows: list[dict]):
    yield "ALL", rows
    for kind in sorted({r.get("kind") for r in rows if r.get("kind")}):
        yield f"kind={kind}", [r for r in rows if r.get("kind") == kind]
    yield "first-turn", [r for r in rows if r.get("turn") == 1]
    yield "later-turn", [r for r in rows if isinstance(r.get("turn"), int) and r["turn"] > 1]
    for hit in (True, False):
        sub = [r for r in rows if r.get("cache_hit") is hit]
        if sub:
            yield f"cache_hit={hit}", sub
    for lang in sorted({r.get("language") for r in rows if r.get("language")}):
        yield f"language={lang}", [r for r in rows if r.get("language") == lang]
    multi = [r for r in rows if isinstance(r.get("llm_runs"), int) and r["llm_runs"] > 1]
    if multi:
        yield "llm_runs>1 (preemptive wasted)", multi


def render_report(rows: list[dict]) -> str:
    rows = [r for r in rows if r]
    if not rows:
        return "no voice_turn_latency lines found"
    out = [f"voice turn latency — {len(rows)} turns"]
    for name, sub in _cohorts(rows):
        if not sub:
            continue
        out.append(f"\n[{name}] ({len(sub)} turns)")
        out.extend(_stats(sub, f) for f in _STAGES)
    unacc = [r["unaccounted_ms"] for r in rows if r.get("unaccounted_ms") is not None]
    if unacc and median(unacc) > 100:
        out.append(
            f"\nWARNING: unaccounted_ms p50={median(unacc):.0f}ms > 100ms — "
            "instrumentation incomplete; find the missing buffer BEFORE tuning "
            "any provider knob (plan Phase 1 gate)."
        )
    return "\n".join(out)


def _redis_lines() -> list[str]:
    """Read the durable mirror (agent RPUSHes every summary to `lat:turns`,
    7-day expiry) — survives Fly's minutes-long log rotation."""
    import asyncio

    async def _fetch() -> list[str]:
        from backend.redis_client import get_redis

        r = await get_redis()
        return [
            x if isinstance(x, str) else x.decode()
            for x in await r.lrange("lat:turns", 0, -1)
        ]

    return asyncio.run(_fetch())


def main() -> None:
    args = sys.argv[1:]
    rows: list[dict] = []
    if args and args[0] == "--redis":
        rows = [r for r in (parse_line(ln) for ln in _redis_lines()) if r]
    else:
        for p in args or ["-"]:
            fh = sys.stdin if p == "-" else open(p, encoding="utf-8", errors="replace")
            with fh if p != "-" else fh:
                rows.extend(r for r in (parse_line(ln) for ln in fh) if r)
    print(render_report(rows))


if __name__ == "__main__":
    main()
