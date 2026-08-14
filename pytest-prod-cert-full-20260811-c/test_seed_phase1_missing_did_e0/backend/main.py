"""Vachanam FastAPI application entrypoint.

Wires together:
- Routers: auth (Google OAuth + JWT), queue (receptionist), payments (Razorpay)
- Middleware stack (outermost-first):
    1. SecurityHeadersMiddleware — CSP, HSTS, X-Frame, etc. on EVERY response
    2. CORSMiddleware — exact-origin allowlist (no wildcard)
- Static: mounts /static and serves landing page mirror at /
- Lifespan: structlog config, scheduler/Calendar/jobs (Phase 6 will add)
- Health: /health for UptimeRobot + Render + Fly probes

Phase 4.5 adds: SecurityHeadersMiddleware, fastapi-limiter rate_limit, audit_log
decorator on sensitive routes. Phase 6 adds: APScheduler in lifespan.

Middleware ordering note: Starlette wraps middleware in reverse registration
order (last-added = outermost). We add SecurityHeadersMiddleware AFTER
CORSMiddleware so it executes FIRST (outermost), ensuring every response —
including CORS preflight 204s — carries the security headers.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from agent.logging_config import configure_structlog
from backend.config import settings
from backend.memstat import process_mem_mb
from backend.jobs.calendar_writer import run_calendar_writer
from backend.middleware.rate_limit import close_rate_limiter, init_rate_limiter
from backend.middleware.security_headers import SecurityHeadersMiddleware

# Gap 3: configure structlog JSON output before any logger.info() call.
# Must be at module level (not inside lifespan) so the very first logger
# reference — including any that fire during FastAPI app construction —
# already uses JSON. log_level read from settings here (no chicken-egg:
# pydantic-settings loads env vars synchronously before this line runs).
configure_structlog(log_level=settings.log_level)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App startup + shutdown.

    Rate-limiter note: fastapi-limiter (pyrate-limiter backend) requires one
    Redis connection shared across workers. We initialize it here and close
    on shutdown. Each uvicorn worker runs its own lifespan independently —
    no cross-loop binding issues because the Redis client is created inside
    the running event loop (not at module import time).

    APScheduler: AsyncIOScheduler runs in-process on the same event loop.
    Jobs are registered here so they share the app's loop (required for
    async job functions). replace_existing=True allows hot-reload in dev.
    """
    logger.info("vachanam_starting", env=settings.app_env, base_url=settings.base_url)
    await init_rate_limiter()

    # NEON WARM-KEEPER — UNCONDITIONAL, per-instance (#435; ungated 2026-07-26).
    # A SELECT 1 every 240s (< Neon's 5-min scale-to-zero) keeps the SAME compute
    # warm so the first call after idle skips the ~2-4s cold wake. It runs on
    # EVERY instance, NOT only the scheduler leader: during a rolling Render
    # redeploy the new instance is not leader yet (it retries every 60s while the
    # old one drains), and that no-leader gap let Neon suspend → the next call
    # paid the cold wake (Vinay live 2026-07-26, ~5s first reply). Ungated, a
    # fresh instance warms Neon immediately at boot and every 240s regardless of
    # leadership. Cost is unchanged — #435 already authorized 24/7 compute; a
    # brief two-instance overlap during a deploy just pings the same compute
    # twice. (The agent-side keepalive stays REMOVED — #299 outage.)
    async def _neon_warm_loop() -> None:
        from sqlalchemy import text as _text

        from backend.database import AsyncSessionLocal as _SL

        while True:
            try:
                async with _SL() as _s:
                    await _s.execute(_text("SELECT 1"))
            except Exception as e:  # noqa: BLE001 — a warm-ping failure is harmless
                logger.warning("neon_warm_ping_failed", error=str(e)[:120])
            await asyncio.sleep(240)

    neon_warm_task = asyncio.create_task(_neon_warm_loop())

    def _build_scheduler():
        from backend.jobs.cascade_rebook_caller import run_cascade_rebook_calls
        from backend.jobs.data_retention import run_data_retention
        from backend.jobs.maintenance import run_hourly_maintenance
        from backend.jobs.next_visit_followup_caller import run_next_visit_followups
        from backend.jobs.pre_appt_reminder import run_pre_appt_reminders
        from backend.jobs.trial_pause import run_pending_plan_changes, run_trial_pause
        from backend.services.wa_delivery import run_wa_delivery_queue
        from backend.jobs.job_lease import leased_job

        scheduler = AsyncIOScheduler()
        immediate_jobs = {
            "calendar_writer",
            "pre_appt_reminder",
            "wa_delivery_queue",
            "cascade_rebook_caller",
            "next_visit_followups",
            "question_callbacks",
            "self_keepalive",
            "hourly_maintenance",
            "watchdog_tick",
        }

        def _add_job(function, trigger, *, id: str, replace_existing: bool = True):
            options = {
                "id": id,
                "replace_existing": replace_existing,
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 3600,
            }
            if id in immediate_jobs:
                options["next_run_time"] = datetime.now(timezone.utc)
            return scheduler.add_job(leased_job(id, function), trigger, **options)
        # #299: calendar_writer / pre_appt_reminders / cascade_rebook keep their
        # fast ticks, but each now answers "is there work?" from Redis
        # (backend/jobs/wake_gate.py) and touches Postgres only when there is.
        # Neon's compute stays awake 5 min after ANY query, so an unconditional
        # 30s poll pinned it on 24/7 (~$19/mo at 0.25 CU with zero calls) and
        # exhausted the plan on 2026-07-09.
        # 60s, not 30s: each tick is now a Redis GET, and this is only the RETRY
        # queue — a booking's calendar event is written inline at confirm_booking
        # (RULE 4). Halving the tick halves the Upstash command spend for no
        # loss: a failed write still retries within a minute.
        _add_job(
            run_calendar_writer, IntervalTrigger(seconds=60),
            id="calendar_writer", replace_existing=True,
        )
        _add_job(
            run_pre_appt_reminders, IntervalTrigger(seconds=60),
            id="pre_appt_reminder", replace_existing=True,
        )
        _add_job(
            run_wa_delivery_queue, IntervalTrigger(seconds=60),
            id="wa_delivery_queue", replace_existing=True,
        )
        _add_job(
            run_cascade_rebook_calls, IntervalTrigger(seconds=60),
            id="cascade_rebook_caller", replace_existing=True,
        )
        # M2: dispatch treatment follow-up calls (next_visit_book at/after 09:00
        # on the scheduled day; doctor_advice ASAP). Calling hours 09:00-20:00 IST.
        # 5 min, not 15: a 15-min first-fire lost the race with Render free
        # tier's ~15-min idle sleep — on a quiet afternoon the job NEVER fired
        # and a doctor_advice task sat pending for hours (prod 2026-07-03).
        _add_job(
            run_next_visit_followups, IntervalTrigger(minutes=5),
            id="next_visit_followups", replace_existing=True,
        )
        # 2026-08-02: call a patient back with the doctor's answer to the
        # question the AI could not answer. Same 5-min tick + wake gate: idle
        # clinics cost one Redis GET, not a Postgres wake.
        from backend.jobs.question_callback_caller import run_question_callbacks

        _add_job(
            run_question_callbacks, IntervalTrigger(minutes=5),
            id="question_callbacks", replace_existing=True,
        )
        # WA T8: evening rating asks (19:00 IST, cron). Cheap when idle: the
        # branch query filters on wa_phone_number_id IS NOT NULL — zero linked
        # branches = one indexed read a day.
        from apscheduler.triggers.cron import CronTrigger

        from backend.jobs.wa_rating_ask import run_wa_rating_ask

        _add_job(
            run_wa_rating_ask,
            CronTrigger(hour=19, minute=0, timezone="Asia/Kolkata"),
            id="wa_rating_ask", replace_existing=True,
        )
        # SELF KEEP-ALIVE: ping our own PUBLIC url so Render's idle detector
        # sees traffic and never sleeps the instance (its in-process scheduler
        # dies with it — missed reminders/follow-ups). Render sets
        # RENDER_EXTERNAL_URL automatically; absent locally → job not added.
        # The external GitHub-cron ping stays as the cold-start waker, but its
        # schedules get throttled by hours, so we can't rely on it alone.
        _self_url = os.getenv("RENDER_EXTERNAL_URL")
        if _self_url:
            async def _self_ping() -> None:
                import httpx

                try:
                    async with httpx.AsyncClient(timeout=15) as hc:
                        await hc.get(f"{_self_url.rstrip('/')}/health")
                except Exception as e:  # noqa: BLE001 — keep-alive must never crash
                    logger.warning("self_ping_failed", error=str(e)[:120])

            _add_job(
                _self_ping, IntervalTrigger(minutes=5),
                id="self_keepalive", replace_existing=True,
            )
        # H5: pause expired trials once a day.
        _add_job(
            run_trial_pause, IntervalTrigger(hours=6),
            id="trial_pause", replace_existing=True,
        )
        # Day-12 payment nudge: one email when a trial has <2 days left.
        from backend.jobs.trial_pause import run_trial_nudge

        _add_job(
            run_trial_nudge, IntervalTrigger(hours=6),
            id="trial_nudge", replace_existing=True,
        )
        # Anniversary-billing renewal loop (#340): renewal email when a paid
        # cycle ends within 3 days; pause 3 days after an unpaid cycle end.
        from backend.jobs.trial_pause import run_billing_renewal

        _add_job(
            run_billing_renewal, IntervalTrigger(hours=6),
            id="billing_renewal", replace_existing=True,
        )
        # Apply clinic-scheduled plan changes whose effective date (the current
        # cycle's end date) has arrived.
        _add_job(
            run_pending_plan_changes, IntervalTrigger(hours=6),
            id="pending_plan_changes", replace_existing=True,
        )
        # DPDP s.8(7): erase patient PII past the retention window (daily).
        _add_job(
            run_data_retention, IntervalTrigger(hours=24),
            id="data_retention", replace_existing=True,
        )
        # #299 ONE HOURLY POSTGRES WAKE for everything unconditional:
        # requeue_stale_in_progress (was 5 min), finalize_stale_calls (was
        # 30 min), call_scoring (was 1 h) and vobiz_cdr_sync (was 3 min — on its
        # own enough to pin Neon's compute on permanently). Neon keeps compute
        # running 5 min after ANY query, so what costs money is the NUMBER of
        # distinct wakes, not the frequency: four staggered jobs burned ~20 min
        # of compute per hour, one shared tick burns ~5.
        _add_job(
            run_hourly_maintenance, IntervalTrigger(hours=1),
            id="hourly_maintenance", replace_existing=True,
        )
        # #306 autonomous watchdog: 60s Redis-only tick (agent heartbeat,
        # redis, own memory) with auto-remediation (Fly restart / clean
        # self-restart) + change-triggered email. Deep checks (DB probe,
        # calendar backlog) ride the hourly maintenance wake — zero extra
        # Neon wakes.
        from backend.watchdog import run_watchdog_tick

        _add_job(
            run_watchdog_tick, IntervalTrigger(seconds=60),
            id="watchdog_tick", replace_existing=True,
        )
        # (Neon warm-keeper moved OUT of the leader scheduler 2026-07-26 — it now
        # runs unconditionally per-instance in the lifespan startup above, so a
        # rolling Render redeploy's no-leader window can no longer let Neon
        # suspend. See _neon_warm_loop.)
        scheduler.start()
        return scheduler

    # Every process schedules every job. Renewable per-job Redis leases decide
    # which process executes each tick. This remains correct behind Supavisor;
    # a crashed process cannot strand leadership inside a pooled DB session.
    scheduler = _build_scheduler()
    logger.info("scheduler_started_with_distributed_job_leases")

    yield

    neon_warm_task.cancel()
    scheduler.shutdown(wait=False)
    await close_rate_limiter()
    logger.info("vachanam_shutdown")


# In production, suppress Swagger UI + OpenAPI export — attackers can't
# enumerate our API surface. In dev they're available for testing.
_is_prod = settings.app_env == "production"

app = FastAPI(
    title="Vachanam API",
    version="1.2.0",
    description="AI-powered appointment booking for Indian clinics",
    lifespan=lifespan,
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions. Returns 500 instead of propagating.

    Without this, SQLAlchemy / asyncpg errors propagate through
    httpx.ASGITransport(raise_app_exceptions=True) and crash test cases that
    don't set up the DB but still call endpoints which touch it.  In production
    Starlette's ServerErrorMiddleware would handle this, but in tests we need an
    explicit handler to get a JSON 500 back.
    """
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

# CORS — exact origins (wildcard incompatible with allow_credentials=True).
# Production: only the deployed frontend origin. Dev: also localhost dev ports.
_allowed_origins = [settings.frontend_url]
if not _is_prod:
    _allowed_origins.extend(["http://localhost:3000", "http://localhost:5173"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    # PUT was missing until #410 — the browser preflight 400'd and the FAQ
    # save (the app's only PUT) died client-side while tests (no Origin
    # header → CORS not enforced) stayed green.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Turnstile-Token"],
)

# SecurityHeadersMiddleware must be added AFTER CORSMiddleware.
# Starlette wraps in reverse order: last-added = outermost = first to execute.
# This guarantees security headers appear on ALL responses including CORS
# preflight responses that CORSMiddleware short-circuits.
app.add_middleware(SecurityHeadersMiddleware)

# Routers wired in dependency order:
# - auth: no deps, issues JWTs the others need
# - queue: depends on auth middleware
# - payments: independent (Razorpay flow doesn't need our JWT)
# - admin: requires is_admin=True JWT claim (require_admin dependency)
from backend.routers import admin as admin_router
from backend.routers import analytics as analytics_router
from backend.routers import auth as auth_router
from backend.routers import availability as availability_router
from backend.routers import branches as branches_router
from backend.routers import voices as voices_router
from backend.routers import doctors as doctors_router
from backend.routers import legal as legal_router
from backend.routers import patients as patients_router
from backend.routers import payments as payments_router
from backend.routers import queue as queue_router
from backend.routers import support as support_router
from backend.routers import treatment as treatment_router
from backend.routers import whatsapp_webhook as whatsapp_webhook_router

app.include_router(auth_router.router, prefix="/auth", tags=["auth"])
app.include_router(queue_router.router, prefix="/queue", tags=["queue"])
app.include_router(payments_router.router, prefix="/api", tags=["payments"])
app.include_router(admin_router.router, prefix="/admin", tags=["admin"])
app.include_router(doctors_router.router, prefix="/doctors", tags=["doctors"])
app.include_router(availability_router.router, prefix="/availability", tags=["availability"])
app.include_router(branches_router.router, prefix="/branches", tags=["branches"])
app.include_router(voices_router.router, prefix="/branches", tags=["voices"])
# Legal pages — public, no auth, no prefix (routes are /privacy /terms /dpa)
app.include_router(legal_router.router, tags=["legal"])
app.include_router(analytics_router.router, tags=["analytics"])
app.include_router(treatment_router.router, prefix="/treatment", tags=["treatment"])
app.include_router(patients_router.router, prefix="/patients", tags=["patients"])
app.include_router(support_router.router, prefix="/support", tags=["support"])
# WhatsApp webhook — public (Meta calls it); HMAC-verified inside (WA T5).
app.include_router(whatsapp_webhook_router.router)

# Landing page (Vachanam marketing mirror + Razorpay test target).
# Static files served from backend/static/ — landing index.html at /,
# everything else under /static/<path>.
_STATIC = Path(__file__).parent / "static"
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False, response_model=None)
async def landing():
    """Serve the legacy static mirror with canonical Basic/Growth/Scale pricing."""
    index = _STATIC / "index.html"
    if index.exists():
        return FileResponse(index)
    return HTMLResponse("<h1>Vachanam</h1><p>Landing page not found.</p>", status_code=404)


@app.get("/dev/test", response_class=HTMLResponse, include_in_schema=False, response_model=None)
async def dev_razorpay_test():
    """Developer-only Razorpay test page (single button, any amount)."""
    if _is_prod:
        return HTMLResponse("Not found", status_code=404)
    page = _STATIC / "razorpay-test.html"
    if page.exists():
        return FileResponse(page)
    return HTMLResponse("Dev test page not found", status_code=404)


@app.get("/health", tags=["health"], response_model=None)
async def health() -> dict | JSONResponse:
    """Health check for UptimeRobot + Render + Fly probes.

    Returns 200 with env tag. Does NOT touch DB or Redis — health endpoint
    must stay fast and unauthenticated to avoid cascading failures.
    Phase 10 adds: /health/deep that probes DB + Redis on demand.

    `build` is the short commit the instance is actually running (Render sets
    RENDER_GIT_COMMIT). Without it there is no way to tell from outside whether
    a push actually redeployed — which mattered for #299, where the whole cost
    fix lives in this process's schedulers. Short SHA only; the repo is private
    and a 7-char hash reveals nothing exploitable.
    """
    out = {"status": "ok", "env": settings.app_env, "service": "vachanam-api"}
    commit = os.getenv("RENDER_GIT_COMMIT", "")
    if commit:
        out["build"] = commit[:7]
    mem = process_mem_mb()
    if mem is not None:
        # Render free tier OOM-kills at 512MB (reported 2026-07-11). Exposing
        # current + peak RSS here turns every UptimeRobot/keepalive ping into a
        # memory sample, so the growth curve is readable from Render logs and
        # curl without shelling into the box. Zero dependencies (/proc).
        out["mem_mb"] = mem
    # Local and dependency-free: every process owns an APScheduler instance,
    # and each leased wrapper records its latest tick in memory. If those ticks
    # stop while HTTP still responds, Render must restart the process; otherwise
    # patients get a healthy API with dead reminders/follow-ups.
    from backend.jobs.job_lease import local_scheduler_health

    scheduler_health = local_scheduler_health()
    out["scheduler"] = scheduler_health
    if settings.app_env == "production" and not scheduler_health["ok"]:
        out["status"] = "degraded"
        return JSONResponse(status_code=503, content=out)
    return out


async def _diag_guard(request: Request) -> None:
    """SEC #7/#11: the detailed diagnostics below leak recon (live-call volume,
    the exact resolved rate-limit key + CF headers = an oracle for crafting a
    spoofed IP, Redis reachability). Harmless in dev, but in PRODUCTION they
    must require an admin JWT. Non-prod stays open for easy debugging.

    Routes through get_current_user (not a bare jwt.decode) so a LOGGED-OUT or
    password-reset admin token is rejected here too — the inline decode skipped
    the Redis revocation set and the token_version check, so a revoked admin
    bearer kept working on these endpoints until its natural 8h exp."""
    if settings.app_env != "production":
        return
    from fastapi.security import HTTPAuthorizationCredentials

    from backend.middleware.auth_middleware import get_current_user

    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Admin token required")
    user = await get_current_user(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth[7:])
    )
    if not (user.is_admin or user.role == "super_admin"):
        raise HTTPException(status_code=403, detail="Admin only")


@app.get("/health/voice-plane", tags=["health"], dependencies=[Depends(_diag_guard)])
async def health_voice_plane() -> dict:
    """Diagnostic (Vinay 2026-06-22, missing reminders): confirm THIS host can
    dispatch outbound calls. Returns booleans + a reachability probe only — NO
    secret values. If voice_plane_configured is False here, the reminder /
    follow-up jobs no-op every tick. If livekit_reachable is False, create_dispatch
    would throw. ponytail: keep until the reminder path is proven stable, then
    fold into /health/deep."""
    import os as _os

    out = {
        "voice_plane_configured": settings.voice_plane_configured,
        "livekit_url_present": bool(settings.livekit_url or _os.getenv("LIVEKIT_URL")),
        "livekit_key_present": bool(settings.livekit_api_key or _os.getenv("LIVEKIT_API_KEY")),
        "livekit_secret_present": bool(settings.livekit_api_secret or _os.getenv("LIVEKIT_API_SECRET")),
        "outbound_trunk_present": bool(settings.outbound_trunk_id or _os.getenv("OUTBOUND_TRUNK_ID")),
    }
    try:
        from livekit import api as _lk
        _api = _lk.LiveKitAPI()
        try:
            rooms = await _api.room.list_rooms(_lk.ListRoomsRequest())
            out["livekit_reachable"] = True
            out["active_rooms"] = len(rooms.rooms)
        finally:
            await _api.aclose()
    except Exception as e:  # noqa: BLE001 — diagnostic, surface the reason
        out["livekit_reachable"] = False
        out["livekit_error"] = str(e)[:200]
    return out


@app.get("/health/whatsapp", tags=["health"], dependencies=[Depends(_diag_guard)])
async def health_whatsapp(branch_id: str | None = None) -> dict:
    """Diagnostic (Vinay 2026-08-03, "still not working. no one is replying"):
    WHY is a WhatsApp message not answered?

    Every failure mode is a silent structured no-op by design (RULE 4/8), so
    from outside a dead bot looks identical whether the plan gate rejected it,
    the branch was never linked, or no token resolves. This reports which one,
    for a specific branch, as booleans — never a token, never message text.

    can_send False is the answer: whichever of the three flags below is False
    is the reason.
    """
    import uuid as _uuid

    from sqlalchemy import select

    from backend.database import AsyncSessionLocal
    from backend.models.schema import Branch, Organization
    from backend.services.billing_math import whatsapp_enabled
    from backend.services.wa_service import token_for

    out: dict = {
        "platform_token_configured": bool(settings.meta_access_token),
        "webhook_verify_token_configured": bool(
            getattr(settings, "meta_webhook_verify_token", "")
        ),
    }
    if not branch_id:
        out["hint"] = "pass ?branch_id=<uuid> for the per-clinic verdict"
        return out

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(Branch, Organization.plan)
                .join(Organization, Branch.org_id == Organization.id)
                .where(Branch.id == _uuid.UUID(branch_id))
            )
        ).first()
        if row is None:
            return {**out, "branch_found": False}
        branch, plan = row
        addon = bool(getattr(branch, "whatsapp_addon", False))
        linked = bool(getattr(branch, "wa_phone_number_id", None))
        gated_in = whatsapp_enabled(plan or "", addon)
        has_token = bool(token_for(branch))
        return {
            **out,
            "branch_found": True,
            "plan": plan,
            "whatsapp_addon": addon,
            "plan_gate_passes": gated_in,
            "branch_linked": linked,
            "uses_clinic_token": bool(getattr(branch, "wa_token_enc", None)),
            "token_resolves": has_token,
            "wa_status": getattr(branch, "wa_status", None),
            # The exact condition wa_enabled() applies before every send.
            "can_send": bool(has_token and linked and gated_in),
        }


@app.get("/health/ratelimit", tags=["health"], dependencies=[Depends(_diag_guard)])
async def health_ratelimit(request: Request) -> dict:
    """Diagnostic: what client IP + rate-limit key does THIS request resolve to,
    and what is trusted_proxy_hops? If the key VARIES across repeated requests
    from one client, the limiter can never accumulate a count (no 429) — an
    IP-resolution problem behind Cloudflare/Render, not a limiter bug. No secrets."""
    from backend.middleware.rate_limit import client_ip, user_or_ip_key

    return {
        "trusted_proxy_hops": getattr(settings, "trusted_proxy_hops", 0),
        "resolved_client_ip": client_ip(request),
        "rate_limit_key": await user_or_ip_key(request),
        "xff_present": bool(request.headers.get("x-forwarded-for")),
        "xff_len": len((request.headers.get("x-forwarded-for") or "").split(",")) if request.headers.get("x-forwarded-for") else 0,
        "cf_connecting_ip": request.headers.get("cf-connecting-ip"),
        "true_client_ip": request.headers.get("true-client-ip"),
    }


@app.get("/health/redis", tags=["health"], dependencies=[Depends(_diag_guard)])
async def health_redis() -> dict:
    """Diagnostic: can THIS host reach Redis? Uses the rate-limiter's OWN client
    and does a ping + set/get/del round-trip. Booleans + error class only, no
    secrets. If redis_ok is False in prod, the rate limiter / IP blocklist / OTP
    are silently failing OPEN and atomic token locking is degraded — a Redis
    connectivity problem, not a code one."""
    out: dict = {"redis_ok": False}
    try:
        from backend.middleware.rate_limit import _get_rate_limit_redis

        r = await _get_rate_limit_redis()
        await r.set("health:redis:probe", "1", ex=10)
        v = await r.get("health:redis:probe")
        await r.delete("health:redis:probe")
        out["ping"] = True
        out["roundtrip_ok"] = v in ("1", b"1")
        out["redis_ok"] = out["roundtrip_ok"]
    except Exception as e:  # noqa: BLE001 — diagnostic
        out["error_class"] = type(e).__name__
        out["error"] = str(e)[:160]
    return out
