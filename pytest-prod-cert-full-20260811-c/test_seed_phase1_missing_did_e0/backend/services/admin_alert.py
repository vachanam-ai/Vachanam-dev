"""Admin alert helper — minimal CRITICAL log + audit row.

Real email/SMS delivery is deferred to TD (tech-debt entry to add on first
paying clinic). This module only logs and writes an audit row so the event
is traceable without blocking the worker.

See docs/superpowers/specs/2026-06-08-calendar-and-receptionist-pwa-design.md §6.8.
"""
import structlog

from backend.services.audit_service import write_audit_row

logger = structlog.get_logger()


async def alert_admin(event: str, branch_id: object, token_id: object = None) -> None:
    """Log CRITICAL + write AuditLog row for a permanent-failure admin alert.

    Args:
        event:     Dot-notation event name, e.g. "calendar_write_failed_permanent".
        branch_id: UUID of the affected branch (any str/UUID-ish type accepted).
        token_id:  UUID of the affected token (optional).

    Audit failure is never re-raised (write_audit_row swallows DB errors per spec §8.5).
    """
    branch_str = str(branch_id) if branch_id is not None else None
    token_str = str(token_id) if token_id is not None else None

    logger.critical(
        "admin_alert",
        event=event,
        branch_id=branch_str,
        token_id=token_str,
    )

    await write_audit_row(
        action=f"admin.alert.{event}",
        resource_type="calendar_write_task",
        resource_id=token_str,
        branch_id=None,  # plain UUID would need import; log has it; skip FK risk
        metadata={"token_id": token_str} if token_str else None,
    )
