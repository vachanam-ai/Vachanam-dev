"""Fault-tolerance primitives + chaos injection for external dependencies.

One entry point — `guard(name, coro_factory, timeout=..., ...)` — wraps ANY
async external call (HTTP, SDK, DB probe) with, in order:

  1. chaos injection      — opt-in latency / failure for that named dependency,
                            so we can SEE how the system behaves when Resend is
                            slow or Fly is down, without waiting for it to break
                            in prod. HARD-OFF unless settings.chaos_enabled.
  2. circuit breaker      — after N consecutive failures the breaker OPENS and
                            calls short-circuit instantly (fallback / raise) for
                            reset_after seconds, so a dead dependency stops
                            eating request threads. Then HALF-OPEN probes once.
  3. per-attempt timeout  — asyncio.wait_for; a hung socket can't hang us.
  4. retry with backoff   — optional, exponential.
  5. metrics              — total / ok / failed / timeout / rejected + latency,
                            surfaced on /admin/resilience for the health board.

State is in-process (per API worker). ponytail: fine for the single Render
process; if we scale to N workers, move breaker+metrics to Redis (keys already
namespaced by `name`). Chaos config is process-local by design — a drill is
driven against one process.

RULE 8: `guard(..., fallback=X)` returns X instead of raising when a dependency
is down/timed-out/circuit-open, so a best-effort caller degrades cleanly.
"""
from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass, field

import structlog

from backend.config import settings

logger = structlog.get_logger()

_UNSET = object()


class CircuitOpenError(RuntimeError):
    """Raised by guard() when the breaker is open and no fallback was given."""


class ChaosInjectedError(RuntimeError):
    """A failure deliberately injected by the chaos harness (never in prod)."""


# ── circuit breaker ───────────────────────────────────────────────────────────

FAIL_THRESHOLD = 5      # consecutive failures before the breaker opens
RESET_AFTER = 30.0      # seconds open before a half-open probe is allowed


@dataclass
class _Breaker:
    failures: int = 0
    opened_at: float | None = None  # monotonic ts when it tripped, else None

    def is_open(self) -> bool:
        """Open = reject. After RESET_AFTER we allow ONE half-open probe through
        (opened_at cleared so the next call runs; success closes, failure re-opens)."""
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at >= RESET_AFTER:
            self.opened_at = None  # half-open: let the next call probe
            return False
        return True

    def on_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def on_failure(self) -> None:
        self.failures += 1
        if self.failures >= FAIL_THRESHOLD and self.opened_at is None:
            self.opened_at = time.monotonic()

    def state(self) -> str:
        if self.opened_at is None:
            return "half_open" if self.failures else "closed"
        return "open"


# ── metrics ───────────────────────────────────────────────────────────────────

@dataclass
class _Metric:
    total: int = 0
    ok: int = 0
    failed: int = 0
    timeout: int = 0
    rejected_open: int = 0
    _latency: deque = field(default_factory=lambda: deque(maxlen=100))

    def snapshot(self) -> dict:
        lat = sorted(self._latency)
        avg = round(sum(lat) / len(lat), 1) if lat else 0.0
        p95 = round(lat[int(len(lat) * 0.95) - 1], 1) if lat else 0.0
        bad = self.failed + self.timeout
        served = self.ok + bad  # rejected_open never reached the dependency
        return {
            "total": self.total, "ok": self.ok, "failed": self.failed,
            "timeout": self.timeout, "rejected_open": self.rejected_open,
            "error_rate": round(bad / served, 3) if served else 0.0,
            "latency_ms_avg": avg, "latency_ms_p95": p95,
        }


_breakers: dict[str, _Breaker] = {}
_metrics: dict[str, _Metric] = {}
# chaos: name -> {"fail_rate": 0..1, "latency_ms": int, "until": monotonic|None}
_chaos: dict[str, dict] = {}


def _breaker(name: str) -> _Breaker:
    return _breakers.setdefault(name, _Breaker())


def _metric(name: str) -> _Metric:
    return _metrics.setdefault(name, _Metric())


# ── chaos harness ─────────────────────────────────────────────────────────────

async def _inject_chaos(name: str) -> None:
    """Apply configured latency/failure for `name`. No-op unless chaos_enabled —
    so this is dead weight in prod (one dict lookup) and can never fire there."""
    if not settings.chaos_enabled:
        return
    cfg = _chaos.get(name)
    if not cfg:
        return
    until = cfg.get("until")
    if until is not None and time.monotonic() > until:
        _chaos.pop(name, None)  # expired
        return
    latency = cfg.get("latency_ms", 0)
    if latency:
        await asyncio.sleep(latency / 1000.0)
    if random.random() < cfg.get("fail_rate", 0.0):
        raise ChaosInjectedError(f"chaos: injected failure for '{name}'")


def set_chaos(name: str, *, fail_rate: float = 0.0, latency_ms: int = 0,
              ttl_s: float | None = None) -> dict:
    """Arm chaos for a dependency. Ignored at call time unless chaos_enabled."""
    cfg = {
        "fail_rate": max(0.0, min(1.0, float(fail_rate))),
        "latency_ms": max(0, int(latency_ms)),
        "until": (time.monotonic() + ttl_s) if ttl_s else None,
    }
    _chaos[name] = cfg
    logger.warning("chaos_armed", dependency=name, **{k: v for k, v in cfg.items() if k != "until"})
    return cfg


def clear_chaos(name: str | None = None) -> None:
    if name is None:
        _chaos.clear()
    else:
        _chaos.pop(name, None)


# ── the wrapper ───────────────────────────────────────────────────────────────

async def guard(name: str, coro_factory, *, timeout: float, retries: int = 0,
                backoff: float = 0.2, fallback=_UNSET):
    """Run `coro_factory()` (a zero-arg callable making a FRESH coroutine each
    attempt) under timeout + circuit breaker + metrics, retrying `retries` times.

    On exhaustion: return `fallback` if given, else re-raise the last error.
    Circuit open: return `fallback` if given, else raise CircuitOpenError.
    """
    m, br = _metric(name), _breaker(name)
    m.total += 1
    if br.is_open():
        m.rejected_open += 1
        logger.warning("resilience_circuit_open", dependency=name)
        if fallback is not _UNSET:
            return fallback
        raise CircuitOpenError(f"circuit open for '{name}'")

    async def _attempt():
        # Chaos runs INSIDE the timeout so injected latency competes with it —
        # a "slow dependency" drill must be able to trip the timeout.
        await _inject_chaos(name)
        return await coro_factory()

    attempt = 0
    while True:
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(_attempt(), timeout)
            m.ok += 1
            m._latency.append((time.monotonic() - start) * 1000.0)
            br.on_success()
            return result
        except asyncio.TimeoutError as exc:
            m.timeout += 1
            last = exc
        except Exception as exc:  # noqa: BLE001 — any dependency error counts
            m.failed += 1
            last = exc
        m._latency.append((time.monotonic() - start) * 1000.0)
        br.on_failure()
        attempt += 1
        if attempt > retries:
            logger.warning("resilience_call_failed", dependency=name,
                           error=str(last)[:160], attempts=attempt,
                           circuit=br.state())
            if fallback is not _UNSET:
                return fallback
            raise last
        await asyncio.sleep(backoff * (2 ** (attempt - 1)))


# ── board read (admin) ────────────────────────────────────────────────────────

def board() -> dict:
    """Metrics + breaker states + armed chaos, for /admin/resilience."""
    now = time.monotonic()
    return {
        "chaos_enabled": settings.chaos_enabled,
        "dependencies": {
            name: {
                **_metric(name).snapshot(),
                "circuit": _breaker(name).state(),
                "consecutive_failures": _breaker(name).failures,
            }
            for name in sorted(set(_metrics) | set(_breakers))
        },
        "chaos": {
            name: {
                "fail_rate": c["fail_rate"], "latency_ms": c["latency_ms"],
                "expires_in_s": round(c["until"] - now, 1) if c.get("until") else None,
            }
            for name, c in _chaos.items()
        },
    }
