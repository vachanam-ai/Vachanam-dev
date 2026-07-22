"""Print the RAW per-call timeline, newest call last.

    python sandbox/raw-latency/analyze_raw.py            # from Redis lat:raw
    fly logs -a vachanam-speed | python .../analyze_raw.py -   # from a log stream

Groups RAWLAT lines by call id and prints each event in time order with its
`dt` gap. A trailing per-call summary flags the biggest gaps — that's the
latency. No stats magic; the timeline speaks for itself.
"""
from __future__ import annotations

import re
import sys

_LINE = re.compile(r"RAWLAT id=(\w+) t=([\d.]+) dt=([\d.]+) ev=(\S+)(.*)")


def _rows(lines):
    for ln in lines:
        m = _LINE.search(ln)
        if m:
            yield m.group(1), float(m.group(2)), float(m.group(3)), m.group(4), m.group(5).strip()


def _redis_lines() -> list[str]:
    import asyncio

    async def _fetch():
        from backend.redis_client import get_redis
        r = await get_redis()
        return [x if isinstance(x, str) else x.decode()
                for x in await r.lrange("lat:raw", 0, -1)]

    return asyncio.run(_fetch())


def render(rows) -> str:
    calls: dict[str, list] = {}
    for cid, t, dt, ev, rest in rows:
        calls.setdefault(cid, []).append((t, dt, ev, rest))
    if not calls:
        return "no RAWLAT lines found"
    out = []
    for cid, evs in calls.items():
        out.append(f"\n=== call {cid} - {len(evs)} events, {evs[-1][0]:.0f}ms total ===")
        for t, dt, ev, rest in evs:
            flag = "  <<<" if dt >= 400 else ""
            out.append(f"  t={t:>8.1f}  +{dt:>7.1f}  {ev:<20} {rest}{flag}")
        gaps = sorted(((dt, ev) for _, dt, ev, _ in evs), reverse=True)[:3]
        out.append("  biggest gaps: " + ", ".join(f"{ev} +{dt:.0f}ms" for dt, ev in gaps))
    return "\n".join(out)


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "-":
        rows = list(_rows(sys.stdin))
    else:
        rows = list(_rows(_redis_lines()))
    print(render(rows))


if __name__ == "__main__":
    main()
