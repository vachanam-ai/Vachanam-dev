"""Audit logging service.

Provides:
  - PII_DENYLIST: set of key-substring words forbidden in metadata_json.
  - write_audit_row(): async INSERT helper (validates PII, inserts AuditLog).
  - audit(): decorator factory for route handlers; audit failure NEVER blocks
    the user response (spec §8.5).

Per CLAUDE.md Rule 10: structlog JSON on every significant event.
Per security spec §8.4: AuditLog is append-only — no UPDATE or DELETE here.
TD-022 closed: PII denylist enforced on metadata_json keys.
"""
import uuid
from functools import wraps

import structlog
from sqlalchemy import insert

import backend.services.audit_service as _self  # monkeypatch-safe module self-reference
from backend.database import AsyncSessionLocal
from backend.models.schema import AuditLog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# PII denylist — closes TD-022
# ---------------------------------------------------------------------------

PII_DENYLIST: set[str] = {"phone", "name", "email", "address", "complaint", "symptom"}


def _contains_pii_key(metadata: dict | None, action: str) -> str | None:
    """Return the offending key name if metadata contains a PII-denylisted key.

    Matching is substring-based (e.g., "patient_phone" matches "phone").

    Exception per spec §8.2:
      action="user.login.failure" is allowed to include exactly the key "email"
      (attempted credential has forensic value for detecting credential-stuffing).
    """
    if not metadata:
        return None
    for key in metadata.keys():
        key_lower = key.lower()
        for banned in PII_DENYLIST:
            if banned in key_lower:
                # Spec §8.2 exception: login.failure may carry exactly "email"
                if action == "user.login.failure" and banned == "email" and key_lower == "email":
                    continue
                return key
    return None


# ---------------------------------------------------------------------------
# Core write helper
# ---------------------------------------------------------------------------

async def write_audit_row(
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    user_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict | None = None,
    success: bool = True,
) -> None:
    """Insert one AuditLog row.

    Validates metadata keys against PII_DENYLIST FIRST (before any DB write).
    Raises ValueError immediately if a key is forbidden — callers must fix the
    call (this is a programming error, not a runtime transient failure).

    DB errors are caught, logged via structlog.error, and NOT re-raised.
    Rationale: per spec §8.5, audit failure must never block the user's
    request. The caller (route handler or @audit decorator) should not need
    to worry about transient DB unavailability during audit writes.

    Uses a fresh AsyncSessionLocal per call (no module-level session singleton,
    per QUALITY_BAR rule and TD-016/TD-017 guidance).
    """
    # PII denylist enforcement — raises ValueError BEFORE touching the DB
    offending = _contains_pii_key(metadata, action)
    if offending:
        raise ValueError(
            f"PII denylist violation: metadata key '{offending}' is forbidden "
            f"for action='{action}' (contains banned word from PII_DENYLIST)"
        )

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                insert(AuditLog).values(
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    user_id=user_id,
                    branch_id=branch_id,
                    org_id=org_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    metadata_json=metadata,
                    success=success,
                )
            )
            await db.commit()
    except Exception as db_err:
        # DB errors are best-effort — log and continue (spec §8.5)
        logger.error(
            "audit_db_write_failed",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            error=str(db_err),
        )
        return

    logger.info(
        "audit_row_written",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        success=success,
    )


# ---------------------------------------------------------------------------
# @audit decorator
# ---------------------------------------------------------------------------

def audit(action: str, resource_type: str | None = None):
    """Decorator factory for route handlers.

    After the handler executes (or raises), writes an AuditLog row in the
    same async context (inline, not background task). Audit failure is
    caught, logged via structlog.error, and NEVER re-raised — audit failure
    must not block the user response (spec §8.5).

    The decorator reads audit context from request.state (set by the handler
    before returning):
      - request.state.audit_resource_id (str | None)
      - request.state.audit_user_id     (str | uuid.UUID | None)
      - request.state.audit_branch_id   (str | uuid.UUID | None)
      - request.state.audit_success     (bool | None — overrides default)
      - request.state.audit_metadata    (dict | None)

    If the handler raises HTTPException, audit fires with success=False and
    the exception class name in metadata["error"] (no PII risk from class
    names).

    The decorated function MUST accept a `request: Request` keyword argument
    (standard FastAPI pattern) so the decorator can extract ip_address and
    user_agent. If request is absent, those fields will be None.

    Call pattern (monkeypatch-safe):
        Uses `_self.write_audit_row` so test monkeypatching of
        `backend.services.audit_service.write_audit_row` takes effect at
        call time, not at decoration time.
    """
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            # Locate the Request object — it is passed as a keyword arg by FastAPI
            request = kwargs.get("request")
            if request is None:
                for arg in args:
                    if hasattr(arg, "client") and hasattr(arg, "state"):
                        request = arg
                        break

            ip_address: str | None = None
            user_agent: str | None = None
            if request is not None:
                ip_address = request.client.host if request.client else None
                user_agent = request.headers.get("user-agent")

            handler_success = True
            handler_exception: BaseException | None = None
            result = None

            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:
                handler_success = False
                handler_exception = exc
                raise
            finally:
                try:
                    state = getattr(request, "state", None) if request else None

                    # Read audit context set by the handler on request.state
                    resource_id_raw = getattr(state, "audit_resource_id", None) if state else None
                    user_id_raw = getattr(state, "audit_user_id", None) if state else None
                    branch_id_raw = getattr(state, "audit_branch_id", None) if state else None
                    metadata_raw = getattr(state, "audit_metadata", None) if state else None
                    success_override = getattr(state, "audit_success", None) if state else None

                    # Resolve user_id and branch_id to uuid.UUID if they are strings
                    resolved_user_id: uuid.UUID | None = None
                    if user_id_raw is not None:
                        resolved_user_id = (
                            user_id_raw if isinstance(user_id_raw, uuid.UUID)
                            else uuid.UUID(str(user_id_raw))
                        )

                    resolved_branch_id: uuid.UUID | None = None
                    if branch_id_raw is not None:
                        resolved_branch_id = (
                            branch_id_raw if isinstance(branch_id_raw, uuid.UUID)
                            else uuid.UUID(str(branch_id_raw))
                        )

                    metadata = dict(metadata_raw) if metadata_raw else {}

                    # On exception, add error class name to metadata (no PII risk)
                    if handler_exception is not None and "error" not in metadata:
                        metadata["error"] = type(handler_exception).__name__

                    final_success = (
                        success_override if success_override is not None else handler_success
                    )

                    # Use module-level reference so monkeypatching works in tests
                    await _self.write_audit_row(
                        action=action,
                        resource_type=resource_type,
                        resource_id=str(resource_id_raw) if resource_id_raw is not None else None,
                        user_id=resolved_user_id,
                        branch_id=resolved_branch_id,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        metadata=metadata if metadata else None,
                        success=final_success,
                    )
                except Exception as audit_err:
                    # Audit failure must never block the user response (spec §8.5)
                    logger.error(
                        "audit_write_failed",
                        action=action,
                        error=str(audit_err),
                    )

            return result

        return wrapper
    return decorator
