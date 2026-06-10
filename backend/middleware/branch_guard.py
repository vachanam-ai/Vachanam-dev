"""Branch-level access control.

Enforces multi-tenant isolation at the middleware layer. The WHERE branch_id
clause in queries is the final tripwire — branch_guard is the friendlier
front-line that returns 403 early instead of silently returning empty data.

Per CLAUDE.md Rule 1: every multi-tenant query MUST filter by branch_id.
Per security spec Section 7 A01: branch_guard rejects URL-tampering attempts
before any DB query runs.

DPDP Act 2023 boundary (sub-spec A §5.4):
  - super_admin (Vinay) is Vachanam's platform admin — a Data Processor role.
    He MUST NOT access clinic PII routes. Only /admin/* aggregate routes allowed.
  - org_admin auto-inherits all branches where branch.org_id == user.org_id,
    without requiring branch_ids JSONB to be populated.
  - receptionist + doctor roles still require explicit branch_id in branch_ids.
"""
import uuid

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.middleware.auth_middleware import CurrentUser
from backend.models.schema import Branch

logger = structlog.get_logger()


async def assert_branch_access(
    current_user: CurrentUser, branch_id: str, db: AsyncSession
) -> None:
    """Raise 403 if current_user cannot access the given branch.

    Rules (sub-spec A §5.4, DPDP boundary):
      1. super_admin → 403 always. Platform admin cannot access clinic PII.
         Vinay must use /admin endpoints for aggregate views only.
      2. org_admin → auto-inherits all branches in own org. Checks
         branch.org_id == user.org_id via DB lookup. No branch_ids needed.
      3. receptionist + doctor → must have branch_id in JWT branch_ids list.

    Logs every denial with user_id + attempted branch_id for audit forensics.
    """
    # Rule 1: super_admin locked OUT of clinic PII routes (DPDP boundary)
    if current_user.role == "super_admin" or current_user.is_admin:
        logger.warning(
            "super_admin_clinic_access_blocked",
            user_id=current_user.user_id,
            attempted_branch_id=branch_id,
        )
        raise HTTPException(
            status_code=403,
            detail="Platform admin cannot access clinic PII; use /admin endpoints",
        )

    # Validate branch_id format
    try:
        branch_uuid = uuid.UUID(branch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch_id format")

    # Rule 2: org_admin auto-inherits all branches in own org
    if current_user.role == "org_admin":
        result = await db.execute(
            select(Branch.org_id).where(Branch.id == branch_uuid)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Branch not found")
        branch_org_id = str(row)
        if branch_org_id != current_user.org_id:
            logger.warning(
                "branch_access_denied_org_mismatch",
                user_id=current_user.user_id,
                user_org_id=current_user.org_id,
                branch_org_id=branch_org_id,
                attempted_branch_id=branch_id,
            )
            raise HTTPException(
                status_code=403, detail="Branch not in your organization"
            )
        return  # org_admin auto-inherits — no branch_ids check needed

    # Rule 3: receptionist + doctor — explicit branch_ids list
    if branch_id not in (current_user.branch_ids or []):
        logger.warning(
            "branch_access_denied",
            user_id=current_user.user_id,
            email=current_user.email,
            role=current_user.role,
            attempted_branch_id=branch_id,
            allowed_branch_ids=current_user.branch_ids,
        )
        raise HTTPException(status_code=403, detail="No access to this branch")
