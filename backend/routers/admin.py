"""Admin-only router — Phase 4.5 Task 9.

Provides a minimal /admin/ping health check gated by require_admin (is_admin=True
JWT claim). This is a placeholder skeleton for the Phase 8 admin dashboard routes
(spec §8.1 admin.view_* actions). Only Vachanam's own admin (Vinay) reaches these
routes.

Per CLAUDE.md Rule 7: structlog JSON on every significant event.
Per backend-engineer.md: no module-level singletons; all auth via dependency injection.
"""
import structlog
from fastapi import APIRouter, Depends, Request

from backend.middleware.auth_middleware import CurrentUser, require_admin
from backend.middleware.rate_limit import default_limit

logger = structlog.get_logger()

router = APIRouter()


@router.get("/ping")
async def admin_ping(
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    _rate_limit: None = Depends(default_limit),
) -> dict:
    """Admin liveness check. Returns 200 only when is_admin=True JWT is presented.

    Non-admin JWT → 403 (require_admin raises before this handler runs).
    No JWT → 401 (get_current_user raises before require_admin).
    Expired JWT → 401 (get_current_user raises before require_admin).

    Placeholder for Phase 8 admin dashboard routes. The response shape is
    intentionally minimal — just proves the require_admin dependency works.
    """
    logger.info(
        "admin_ping",
        user_id=current_user.user_id,
        email=current_user.email,
    )
    return {"status": "ok", "admin_user_id": current_user.user_id}
