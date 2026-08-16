"""Durable WhatsApp patient notifications with event-level idempotency."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import backend.database as _db_module
from backend.models.schema import Branch, Organization, WhatsAppDelivery
from backend.services import wa_service
from backend.services.wa_lifecycle import is_connected

logger = structlog.get_logger()

BACKOFF_SECONDS = (5, 30, 300, 1800, 21600, 86400, 86400, 86400, 86400)
MAX_ATTEMPTS = 10
BATCH = 50


async def _connected(branch_id) -> bool:
    async with _db_module.AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(Branch, Organization.plan)
                .join(Organization, Organization.id == Branch.org_id)
                .where(Branch.id == branch_id)
            )
        ).first()
    return bool(row and wa_service.wa_enabled(row[0], row[1]))


async def _cancel_if_disconnected(db, task: WhatsAppDelivery, *, lock: bool) -> bool:
    """Make disconnect terminal for work that has not reached the provider.

    The locked form serializes a failed provider attempt with disconnect. If
    the retry decision wins first, disconnect subsequently cancels the pending
    row; if disconnect wins first, this transaction observes it and never
    schedules a retry.
    """
    statement = select(Branch).where(Branch.id == task.branch_id)
    if lock:
        statement = statement.with_for_update()
    branch = (await db.execute(statement)).scalar_one_or_none()
    if branch is not None and is_connected(branch):
        return False

    task.status = "cancelled"
    task.next_attempt_at = datetime.now(timezone.utc)
    task.last_error = "branch disconnected before delivery completed"
    await db.commit()
    logger.info(
        "wa_delivery_cancelled_disconnected",
        branch_id=str(task.branch_id),
        purpose=task.purpose,
        event_key=task.event_key,
    )
    return True


async def enqueue(
    branch_id,
    recipient_phone: str,
    purpose: str,
    values: list[str],
    *,
    event_key: str,
    buttons: list[dict] | None = None,
    send_now: bool = True,
    accept_when_queued: bool = False,
) -> bool:
    """Persist one clinic event, then attempt it immediately.

    A disconnected/non-entitled clinic produces no row. A connected clinic's
    notification survives process restarts and retries. The branch/event
    unique key makes webhook replays and duplicate tool calls harmless.
    """
    if branch_id is None or not recipient_phone or not event_key:
        return False
    if not await _connected(branch_id):
        return False

    task_id = None
    async with _db_module.AsyncSessionLocal() as db:
        existing = (
            await db.execute(
                select(WhatsAppDelivery).where(
                    WhatsAppDelivery.branch_id == branch_id,
                    WhatsAppDelivery.event_key == event_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.status == "sent":
                return True
            task_id = existing.id
        else:
            task = WhatsAppDelivery(
                branch_id=branch_id,
                event_key=event_key[:160],
                purpose=purpose,
                recipient_phone=recipient_phone,
                values_json=[str(v) for v in values],
                buttons_json=buttons or [],
            )
            db.add(task)
            try:
                await db.commit()
                task_id = task.id
            except IntegrityError:
                await db.rollback()
                task_id = (
                    await db.execute(
                        select(WhatsAppDelivery.id).where(
                            WhatsAppDelivery.branch_id == branch_id,
                            WhatsAppDelivery.event_key == event_key,
                        )
                    )
                ).scalar_one()

    try:
        from backend.jobs import wake_gate

        await wake_gate.clear_next_at("wa_notifications")
    except Exception as exc:  # noqa: BLE001
        logger.debug("wa_delivery_gate_clear_failed", error=str(exc)[:120])
    if not send_now:
        return True
    delivered = await deliver(task_id)
    # Reminder/follow-up schedulers need to know whether responsibility was
    # durably handed to the retrying outbox, not whether Meta answered on this
    # exact millisecond. Confirmations keep the historical immediate-send bool.
    return bool(task_id) if accept_when_queued else delivered


async def deliver(task_id) -> bool:
    """Attempt one pending task; never raises into the booking mutation."""
    from backend.services.meta_service import send_purpose

    async with _db_module.AsyncSessionLocal() as db:
        # Lock the row while claiming it. enqueue() and the scheduled worker
        # can race on the same event; without this lock both sessions could
        # read "pending" and send the same patient message twice.
        task = (
            await db.execute(
                select(WhatsAppDelivery)
                .where(WhatsAppDelivery.id == task_id)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if task is None:
            return False
        if task.status == "sent":
            return True
        if task.status in {"in_progress", "failed_permanent", "cancelled"}:
            return False
        task.status = "in_progress"
        await db.commit()

        # Disconnect is a hard lifecycle boundary. A row may have been
        # claimed just before the owner disconnected, so re-check after claim
        # and before handing any patient data to Meta.
        if await _cancel_if_disconnected(db, task, lock=False):
            return False

        ok = await send_purpose(
            task.branch_id,
            task.recipient_phone,
            task.purpose,
            list(task.values_json or []),
            list(task.buttons_json or []),
        )
        if ok:
            task.status = "sent"
            task.sent_at = datetime.now(timezone.utc)
            task.last_error = None
            await db.commit()
            logger.info(
                "wa_delivery_sent",
                branch_id=str(task.branch_id),
                purpose=task.purpose,
                event_key=task.event_key,
            )
            return True

        # The provider call can overlap a disconnect. Lock the branch while
        # deciding whether a retry is legal; this prevents failed work from
        # being resurrected after the clinic disconnects and reconnects.
        if await _cancel_if_disconnected(db, task, lock=True):
            return False

        task.attempts += 1
        task.last_error = "provider send returned false"
        if task.attempts >= MAX_ATTEMPTS:
            task.status = "failed_permanent"
        else:
            delay = BACKOFF_SECONDS[min(task.attempts - 1, len(BACKOFF_SECONDS) - 1)]
            task.status = "pending"
            task.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        await db.commit()
        logger.warning(
            "wa_delivery_retry_scheduled",
            branch_id=str(task.branch_id),
            purpose=task.purpose,
            attempt=task.attempts,
            status=task.status,
        )
        if task.status == "failed_permanent":
            try:
                from backend.services.admin_alert import alert_admin

                await alert_admin(
                    "whatsapp_delivery_failed_permanent",
                    branch_id=task.branch_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "wa_delivery_failure_alert_failed", error=str(exc)[:120]
                )
        return False


async def _next_pending_epoch(db) -> float | None:
    value = (
        await db.execute(
            select(WhatsAppDelivery.next_attempt_at)
            .where(WhatsAppDelivery.status == "pending")
            .order_by(WhatsAppDelivery.next_attempt_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    return value.timestamp() if value else None


async def run_wa_delivery_queue() -> None:
    """Retry transient failures and recover tasks stranded by a process exit."""
    from backend.jobs import wake_gate

    if not await wake_gate.should_run_scheduled("wa_notifications"):
        return

    async with _db_module.AsyncSessionLocal() as db:
        stale_before = datetime.now(timezone.utc) - timedelta(minutes=5)
        stale = (
            await db.execute(
                select(WhatsAppDelivery).where(
                    WhatsAppDelivery.status == "in_progress",
                    WhatsAppDelivery.updated_at < stale_before,
                )
            )
        ).scalars().all()
        for task in stale:
            task.status = "pending"
            task.next_attempt_at = datetime.now(timezone.utc)
        if stale:
            await db.commit()

        ids = (
            await db.execute(
                select(WhatsAppDelivery.id)
                .where(
                    WhatsAppDelivery.status == "pending",
                    WhatsAppDelivery.next_attempt_at <= datetime.now(timezone.utc),
                )
                .order_by(WhatsAppDelivery.next_attempt_at)
                .limit(BATCH)
            )
        ).scalars().all()

    for task_id in ids:
        await deliver(task_id)

    async with _db_module.AsyncSessionLocal() as db:
        await wake_gate.set_next_at(
            "wa_notifications", await _next_pending_epoch(db)
        )
