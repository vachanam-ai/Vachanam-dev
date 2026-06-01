"""Vachanam FastAPI application entrypoint.

Wires together:
- Routers: auth (Google OAuth + JWT), queue (receptionist), payments (Razorpay)
- Middleware: CORS (locked to frontend_url + localhost dev ports)
- Static: mounts /static and serves landing page mirror at /
- Lifespan: structlog config, scheduler/Calendar/jobs (Phase 6 will add)
- Health: /health for UptimeRobot + Render + Fly probes

Phase 4.5 adds: SecurityHeadersMiddleware, slowapi rate_limit, audit_log
decorator on sensitive routes. Phase 6 adds: APScheduler in lifespan.
"""
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App startup + shutdown. Phase 6 will register APScheduler here."""
    logger.info("vachanam_starting", env=settings.app_env, base_url=settings.base_url)
    yield
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

# Routers wired in dependency order:
# - auth: no deps, issues JWTs the others need
# - queue: depends on auth middleware
# - payments: independent (Razorpay flow doesn't need our JWT)
from backend.routers import auth as auth_router
from backend.routers import payments as payments_router
from backend.routers import queue as queue_router

app.include_router(auth_router.router, prefix="/auth", tags=["auth"])
app.include_router(queue_router.router, prefix="/queue", tags=["queue"])
app.include_router(payments_router.router, prefix="/api", tags=["payments"])

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
    Phase 10 adds: /health/deep that probes DB + Redis + LiveKit on demand.
    """
    return {"status": "ok", "env": settings.app_env, "service": "vachanam-api"}
