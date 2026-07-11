"""Autonomous health watchdog (FIXLOG #306) — the agent that replaces a human
watching dashboards.

Every 60s (Redis-only — never wakes Neon, #299 discipline):
  * agent-plane liveness  — the Fly agent writes `watchdog:hb:agent` every 60s;
    a stale/missing key means the voice plane is down. REMEDIATION: restart the
    Fly machine via the Machines API (FLY_API_TOKEN), 10-min cooldown so a
    genuinely broken deploy can't be flap-restarted forever.
  * redis liveness        — the checks themselves prove it; failure is tracked
    in process memory (Redis can't store its own obituary).
  * api memory            — /proc RSS. >WARN_MB opens a warning incident;
    >CRIT_MB triggers a CLEAN self-restart (os._exit) so Render reboots us
    between requests instead of OOM-killing us mid-request (#305 history).

Hourly (piggybacks the existing maintenance wake — zero extra Neon wakes):
  * db probe              — SELECT 1.
  * calendar queue        — pending backlog / oldest-age; REMEDIATION: run the
    requeue job immediately, then re-measure.

Every state TRANSITION (ok→down, down→ok) writes an audit row
(action="watchdog.<component>.<opened|resolved>") and sends ONE email via
Resend — change-triggered, never periodic, so it cannot spam.

State lives in Redis (`watchdog:state:{component}`) so the owner dashboard
reads it in O(1) without touching Postgres.
"""
import json
import os
import time

import httpx
import structlog

from backend.config import settings
from backend.memstat import process_mem_mb
from backend.redis_client import drop as _drop_redis
from backend.redis_client import get_redis

logger = structlog.get_logger()

_STATE_KEY = "watchdog:state:{comp}"
_AGENT_HB_KEY = "watchdog:hb:agent"
_FLY_COOLDOWN_KEY = "watchdog:fly_restart_cooldown"

AGENT_STALE_SECONDS = 180      # 3 missed 60s heartbeats = down
FLY_RESTART_COOLDOWN = 600     # never auto-restart the agent more than 1/10min
MEM_WARN_MB = 400
MEM_CRIT_MB = 480              # Render kills at 512 — restart cleanly before it
MIN_UPTIME_FOR_SELF_RESTART = 600  # never self-restart inside boot (loop guard)

_process_started = time.monotonic()
# Redis-down state must live OUTSIDE Redis. Module-level is fine: one API process.
_redis_down_since: float | None = None
_redis_down_notified = False


# ── notify ───────────────────────────────────────────────────────────────────

async def _email_alert(subject: str, body: str) -> None:
    """One alert email via Resend (same channel as OTP). Best-effort — an
    unreachable mailer must never break the watchdog itself."""
    if not settings.resend_api_key:
        logger.warning("watchdog_email_skipped_no_resend", subject=subject)
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.resend_from,
                    "to": [settings.alert_email],
                    "subject": f"[Vachanam watchdog] {subject}",
                    "text": body,
                },
            )
            if r.status_code >= 300:
                logger.error("watchdog_email_failed", status=r.status_code, body=r.text[:160])
    except Exception as e:  # noqa: BLE001
        logger.error("watchdog_email_error", error=str(e)[:160])


async def _audit(component: str, event: str, detail: str, action_taken: str | None) -> None:
    """History row for the dashboard feed. Audit write failure is swallowed
    (audit_service contract) — the Redis state is the source of NOW-truth."""
    try:
        from backend.services.audit_service import write_audit_row

        await write_audit_row(
            action=f"watchdog.{component}.{event}",
            resource_type="health",
            resource_id=None,
            branch_id=None,
            metadata={"detail": detail[:300], "action_taken": action_taken},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("watchdog_audit_failed", error=str(e)[:120])


# ── state machine ────────────────────────────────────────────────────────────

async def _transition(component: str, ok: bool, detail: str, action_taken: str | None = None) -> None:
    """Record component state; on CHANGE → audit row + one email. Stored state:
    {status, since, detail, action}. Change-triggered alerts cannot spam."""
    r = get_redis()
    key = _STATE_KEY.format(comp=component)
    try:
        raw = await r.get(key)
        prev = json.loads(raw)["status"] if raw else "ok"
    except Exception:  # noqa: BLE001 — unreadable state = assume ok, still write
        prev = "ok"
    status = "ok" if ok else "down"
    if status != prev:
        logger.warning("watchdog_transition", component=component, frm=prev, to=status,
                       detail=detail, action=action_taken)
        event = "resolved" if ok else "opened"
        await _audit(component, event, detail, action_taken)
        verb = "RECOVERED" if ok else "DOWN"
        await _email_alert(
            f"{component} {verb}",
            f"Component: {component}\nStatus: {verb}\nDetail: {detail}\n"
            f"Automatic action: {action_taken or 'none needed'}\n"
            f"Board: dashboard → Monitoring",
        )
    if status != prev or not ok:
        # rewrite `since` only on transition; refresh detail while down
        since = time.time() if status != prev else json.loads(raw).get("since", time.time())
        await r.set(key, json.dumps({
            "status": status, "since": since, "detail": detail[:300],
            "action": action_taken,
        }))
    elif raw is None:
        await r.set(key, json.dumps({"status": "ok", "since": time.time(),
                                     "detail": detail[:300], "action": None}))


# ── remediations ─────────────────────────────────────────────────────────────

async def _restart_fly_agent() -> str:
    """Restart the voice-agent machine via Fly Machines API. Returns a human
    description of what happened (goes into the incident + email)."""
    if not settings.fly_api_token:
        return "restart skipped: FLY_API_TOKEN not configured"
    r = get_redis()
    try:
        if await r.exists(_FLY_COOLDOWN_KEY):
            return "restart skipped: cooldown active (restarted <10min ago)"
        await r.set(_FLY_COOLDOWN_KEY, "1", ex=FLY_RESTART_COOLDOWN)
    except Exception:  # noqa: BLE001 — no cooldown readable ⇒ still act, once
        pass
    app = settings.fly_agent_app
    hdrs = {"Authorization": f"Bearer {settings.fly_api_token}"}
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            machines = (await c.get(
                f"https://api.machines.dev/v1/apps/{app}/machines", headers=hdrs
            )).json()
            restarted = []
            for m in machines:
                # standbys stay stopped by design — only kick started/failed workers
                if m.get("state") in ("started", "stopped") and not m.get("config", {}).get("standby"):
                    resp = await c.post(
                        f"https://api.machines.dev/v1/apps/{app}/machines/{m['id']}/restart",
                        headers=hdrs,
                    )
                    restarted.append(f"{m['id']}:{resp.status_code}")
            return f"fly restart issued → {', '.join(restarted) or 'no machines found'}"
    except Exception as e:  # noqa: BLE001
        return f"fly restart FAILED: {str(e)[:120]}"


# ── the 60s tick (Redis-only) ────────────────────────────────────────────────

async def run_watchdog_tick() -> None:
    global _redis_down_since, _redis_down_notified

    # 1) Redis itself
    try:
        r = get_redis()
        await r.ping()
        if _redis_down_since is not None:
            await _transition("redis", True,
                              f"reachable again after {int(time.time() - _redis_down_since)}s")
            _redis_down_since = None
            _redis_down_notified = False
    except Exception as e:  # noqa: BLE001
        _drop_redis()
        if _redis_down_since is None:
            _redis_down_since = time.time()
        if not _redis_down_notified:
            _redis_down_notified = True
            logger.error("watchdog_redis_down", error=str(e)[:160])
            await _email_alert(
                "redis DOWN",
                f"Upstash unreachable: {str(e)[:200]}\n"
                "Impact: wake-gates fail open (more Neon wakes), token locking degraded.\n"
                "Automatic action: none possible from here — check Upstash status.",
            )
        return  # everything below needs Redis

    # 2) voice agent heartbeat
    try:
        hb = await r.get(_AGENT_HB_KEY)
        age = (time.time() - float(hb)) if hb else None
        if hb is None or age > AGENT_STALE_SECONDS:
            detail = ("no heartbeat ever seen (agent not writing yet, or down)"
                      if hb is None else f"heartbeat {int(age)}s stale")
            action = await _restart_fly_agent()
            await _transition("agent", False, detail, action)
        else:
            await _transition("agent", True, f"heartbeat {int(age)}s ago")
    except Exception as e:  # noqa: BLE001
        logger.warning("watchdog_agent_check_failed", error=str(e)[:120])

    # 3) own memory
    mem = process_mem_mb()
    if mem:
        rss = mem["rss"]
        if rss >= MEM_CRIT_MB and (time.monotonic() - _process_started) > MIN_UPTIME_FOR_SELF_RESTART:
            await _transition("api_memory", False, f"rss {rss}MB ≥ {MEM_CRIT_MB}MB",
                              "clean self-restart (beat the 512MB OOM-kill)")
            logger.critical("watchdog_self_restart", rss_mb=rss)
            os._exit(1)  # Render restarts the service; clean exit > mid-request OOM kill
        elif rss >= MEM_WARN_MB:
            await _transition("api_memory", False, f"rss {rss}MB ≥ warn {MEM_WARN_MB}MB")
        else:
            await _transition("api_memory", True, f"rss {rss}MB")


# ── hourly deep checks (piggyback the maintenance wake — Neon already awake) ─

async def run_watchdog_deep() -> None:
    import backend.database as _db_module

    # 1) Postgres probe
    try:
        from sqlalchemy import text

        async with _db_module.AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        await _transition("database", True, "SELECT 1 ok")
    except Exception as e:  # noqa: BLE001
        await _transition("database", False, f"probe failed: {str(e)[:160]}",
                          "callers degrade gracefully (#298); check Neon console")
        return  # backlog check needs the DB

    # 2) calendar queue backlog — remediate by requeueing stale tasks NOW
    try:
        from sqlalchemy import func, select

        from backend.models.schema import CalendarWriteTask

        async with _db_module.AsyncSessionLocal() as db:
            pending = (await db.execute(
                select(func.count()).select_from(CalendarWriteTask)
                .where(CalendarWriteTask.status.in_(("pending", "in_progress")))
            )).scalar_one()
        if pending > 20:
            from backend.jobs.calendar_writer import requeue_stale_in_progress

            await requeue_stale_in_progress()
            await _transition("calendar_queue", False,
                              f"{pending} tasks queued", "ran requeue_stale_in_progress")
        else:
            await _transition("calendar_queue", True, f"{pending} tasks queued")
    except Exception as e:  # noqa: BLE001
        logger.warning("watchdog_calendar_check_failed", error=str(e)[:120])


# ── board read (owner dashboard) ─────────────────────────────────────────────

COMPONENTS = ("agent", "redis", "database", "api_memory", "calendar_queue")


async def board_state() -> dict:
    """Current component states for the dashboard. Redis-only, O(components)."""
    out: dict = {"components": {}, "mem_mb": process_mem_mb()}
    if _redis_down_since is not None:
        out["components"]["redis"] = {"status": "down", "since": _redis_down_since,
                                      "detail": "unreachable from API", "action": None}
    try:
        r = get_redis()
        for comp in COMPONENTS:
            raw = await r.get(_STATE_KEY.format(comp=comp))
            if raw:
                out["components"][comp] = json.loads(raw)
        hb = await r.get(_AGENT_HB_KEY)
        if hb:
            out["agent_heartbeat_age_s"] = int(time.time() - float(hb))
        # A healthy Redis never writes its own state key (only recovery does) —
        # but answering these reads IS the health proof. Synthesize the card.
        if "redis" not in out["components"]:
            out["components"]["redis"] = {"status": "ok", "since": None,
                                          "detail": "answering reads", "action": None}
    except Exception as e:  # noqa: BLE001
        out["error"] = f"redis unreachable: {str(e)[:120]}"
    return out
