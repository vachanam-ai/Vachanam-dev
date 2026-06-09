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

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_calendar_writer,
        IntervalTrigger(seconds=30),
        id="calendar_writer",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("scheduler_started", jobs=["calendar_writer"])

    yield

    scheduler.shutdown(wait=False)
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
from backend.routers import auth as auth_router
from backend.routers import legal as legal_router
from backend.routers import payments as payments_router
from backend.routers import queue as queue_router

app.include_router(auth_router.router, prefix="/auth", tags=["auth"])
app.include_router(queue_router.router, prefix="/queue", tags=["queue"])
app.include_router(payments_router.router, prefix="/api", tags=["payments"])
app.include_router(admin_router.router, prefix="/admin", tags=["admin"])
# Legal pages — public, no auth, no prefix (routes are /privacy /terms /dpa)
app.include_router(legal_router.router, tags=["legal"])

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
