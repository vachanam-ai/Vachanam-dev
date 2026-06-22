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
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from agent.logging_config import configure_structlog
from backend.config import settings
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

    # LEADER ELECTION (bug-bounty M1): every uvicorn worker / Render instance
    # runs its own lifespan, so without a guard N schedulers fire the SAME tick
    # and double-dispatch reminder/rebook calls and calendar writes. A Postgres
    # session-level advisory lock makes exactly one process the scheduler
    # leader; the lock auto-releases if that process dies (another then wins).
    scheduler = None
    leader_conn = None
    SCHED_LOCK_KEY = 0x7661636861  # "vacha"
    try:
        import backend.database as _db_module

        leader_conn = await _db_module.engine.raw_connection()
        got = await leader_conn.driver_connection.fetchval(
            "SELECT pg_try_advisory_lock($1)", SCHED_LOCK_KEY
        )
    except Exception as e:
        got = False
        logger.warning("scheduler_leader_lock_failed", error=str(e))

    if got:
        from backend.jobs.call_scoring import run_call_scoring
        from backend.jobs.cascade_rebook_caller import run_cascade_rebook_calls
        from backend.jobs.calendar_writer import requeue_stale_in_progress
        from backend.jobs.data_retention import run_data_retention
        from backend.jobs.finalize_stale_calls import run_finalize_stale_calls
        from backend.jobs.next_visit_followup_caller import run_next_visit_followups
        from backend.jobs.pre_appt_reminder import run_pre_appt_reminders
        from backend.jobs.trial_pause import run_trial_pause
        from backend.jobs.vobiz_cdr_sync import run_vobiz_cdr_sync

        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            run_calendar_writer, IntervalTrigger(seconds=30),
            id="calendar_writer", replace_existing=True,
        )
        # M2: requeue tasks stranded in_progress by a crash (every 5 min).
        scheduler.add_job(
            requeue_stale_in_progress, IntervalTrigger(seconds=300),
            id="calendar_requeue_stale", replace_existing=True,
        )
        scheduler.add_job(
            run_pre_appt_reminders, IntervalTrigger(seconds=60),
            id="pre_appt_reminder", replace_existing=True,
        )
        scheduler.add_job(
            run_cascade_rebook_calls, IntervalTrigger(seconds=60),
            id="cascade_rebook_caller", replace_existing=True,
        )
        # M2: dispatch treatment follow-up calls (next_visit_book at/after 09:00
        # on the scheduled day; doctor_advice ASAP). Calling hours 09:00-20:00 IST.
        scheduler.add_job(
            run_next_visit_followups, IntervalTrigger(minutes=15),
            id="next_visit_followups", replace_existing=True,
        )
        # H5: pause expired trials once a day.
        scheduler.add_job(
            run_trial_pause, IntervalTrigger(hours=6),
            id="trial_pause", replace_existing=True,
        )
        # TD-027/F6: reconcile call-metering rows stranded by a crashed worker.
        scheduler.add_job(
            run_finalize_stale_calls, IntervalTrigger(minutes=30),
            id="finalize_stale_calls", replace_existing=True,
        )
        # DPDP s.8(7): erase patient PII past the retention window (daily).
        scheduler.add_job(
            run_data_retention, IntervalTrigger(hours=24),
            id="data_retention", replace_existing=True,
        )
        # Feedback loop: LLM-as-judge scores captured transcripts (hourly batch).
        scheduler.add_job(
            run_call_scoring, IntervalTrigger(hours=1),
            id="call_scoring", replace_existing=True,
        )
        # Authoritative call/minute metering from Vobiz CDRs (agent-independent).
        # Only scheduled when Vobiz creds are present.
        if settings.vobiz_auth_id and settings.vobiz_auth_token:
            scheduler.add_job(
                run_vobiz_cdr_sync, IntervalTrigger(minutes=3),
                id="vobiz_cdr_sync", replace_existing=True,
            )
        scheduler.start()
        logger.info("scheduler_started_as_leader")
    else:
        logger.info("scheduler_skipped_not_leader")

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)
    if leader_conn is not None:
        try:
            # Explicit unlock (T5): closing a pooled connection returns it to
            # the pool with the session-level advisory lock STILL held, so a
            # graceful in-process restart could never elect a new leader.
            # pg_advisory_unlock releases it before the connection goes back.
            if got:
                await leader_conn.driver_connection.fetchval(
                    "SELECT pg_advisory_unlock($1)", SCHED_LOCK_KEY
                )
            await leader_conn.close()
        except Exception as e:
            logger.warning("scheduler_leader_unlock_failed", error=str(e))
    await close_rate_limiter()
    logger.info("vachanam_shutdown")


# In production, suppress Swagger UI + OpenAPI export — attackers can't
# enumerate our API surface. In dev they're available for testing.
_is_prod = settings.app_env == "production"

app = FastAPI(
    title="Vachanam API",
    version="1.0.0",
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
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
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
from backend.routers import doctors as doctors_router
from backend.routers import legal as legal_router
from backend.routers import payments as payments_router
from backend.routers import queue as queue_router
from backend.routers import treatment as treatment_router

app.include_router(auth_router.router, prefix="/auth", tags=["auth"])
app.include_router(queue_router.router, prefix="/queue", tags=["queue"])
app.include_router(payments_router.router, prefix="/api", tags=["payments"])
app.include_router(admin_router.router, prefix="/admin", tags=["admin"])
app.include_router(doctors_router.router, prefix="/doctors", tags=["doctors"])
app.include_router(availability_router.router, prefix="/availability", tags=["availability"])
app.include_router(branches_router.router, prefix="/branches", tags=["branches"])
# Legal pages — public, no auth, no prefix (routes are /privacy /terms /dpa)
app.include_router(legal_router.router, tags=["legal"])
app.include_router(analytics_router.router, tags=["analytics"])
app.include_router(treatment_router.router, prefix="/treatment", tags=["treatment"])

# Landing page (Vachanam marketing mirror + Razorpay test target).
# Static files served from backend/static/ — landing index.html at /,
# everything else under /static/<path>.
_STATIC = Path(__file__).parent / "static"
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False, response_model=None)
async def landing():
    """Serve the Vachanam landing page with canonical Solo/Clinic/Multi pricing."""
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


@app.get("/health", tags=["health"])
async def health() -> dict:
    """Health check for UptimeRobot + Render + Fly probes.

    Returns 200 with env tag. Does NOT touch DB or Redis — health endpoint
    must stay fast and unauthenticated to avoid cascading failures.
    Phase 10 adds: /health/deep that probes DB + Redis on demand.
    """
    return {"status": "ok", "env": settings.app_env, "service": "vachanam-api"}


@app.get("/health/voice-plane", tags=["health"])
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
