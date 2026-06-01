"""Branch-level access control.

Enforces multi-tenant isolation at the middleware layer. The WHERE branch_id
clause in queries is the final tripwire — branch_guard is the friendlier
front-line that returns 403 early instead of silently returning empty data.

Per CLAUDE.md Rule 1: every multi-tenant query MUST filter by branch_id.
Per security spec Section 7 A01: branch_guard rejects URL-tampering attempts
before any DB query runs.
"""
import structlog
from fastapi import HTTPException

from backend.middleware.auth_middleware import CurrentUser

logger = structlog.get_logger()


def assert_branch_access(current_user: CurrentUser, branch_id: str) -> None:
    """Raise 403 if current_user cannot access the given branch.

    Rules:
      - super_admin role bypasses (Vinay's admin views span all branches)
      - is_admin=True (platform admin) bypasses for the same reason
      - All other roles must have branch_id in their JWT branch_ids list

    Logs every denial with user_id + attempted branch_id for audit forensics.
    """
    if current_user.role == "super_admin" or current_user.is_admin:
        return

    if branch_id not in (current_user.branch_ids or []):
        logger.warning(
            "branch_access_denied",
            user_id=current_user.user_id,
            email=current_user.email,
            attempted_branch_id=branch_id,
            allowed_branch_ids=current_user.branch_ids,
        )
        raise HTTPException(status_code=403, detail="No access to this branch")
