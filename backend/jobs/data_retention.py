"""DPDP s.8(7) data-retention / erasure job.

Personal data must not be kept longer than needed for its purpose. Once a
patient has had no appointment for `patient_retention_days` (default 2 years,
matching the privacy policy), their PII is ERASED — name/phone/age/gender
cleared, `anonymized_at` stamped. The booking rows survive (they hold no PII
beyond patient_id) so the clinic keeps aggregate analytics.

Also prunes `consents` rows older than the same window (the demonstrable-notice
record is only useful while the patient's data is live).

Runs daily from the APScheduler leader (see backend/main.py). Idempotent —
already-anonymised patients are skipped via `anonymized_at IS NULL`.

Per CLAUDE.md: Rule 1 (every row keeps branch_id), Rule 9 (PII discipline —
this job REMOVES PII), Rule 10 (structlog on the erasure event, IDs not names).
"""
from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy import select

import backend.database as _db_module
from backend.config import settings
from backend.models.schema import Consent, Patient, Token

logger = structlog.get_logger()

# Name is NOT NULL on patients — use a fixed placeholder rather than NULL.
ERASED_NAME = "[erased]"


async def run_data_retention() -> None:
    days = max(1, int(settings.patient_retention_days))
    now = datetime.now(timezone.utc)
    cutoff_date = date.today() - timedelta(days=days)
    cutoff_dt = now - timedelta(days=days)

    async with _db_module.AsyncSessionLocal() as db:
        # Patients with any appointment on/after the cutoff are still "active" —
        # never erase them. (A single recent booking keeps the whole record.)
        recent = select(Token.patient_id).where(Token.date >= cutoff_date)

        stale = (
            await db.execute(
                select(Patient).where(
                    Patient.anonymized_at.is_(None),
                    Patient.created_at < cutoff_dt,
                    Patient.id.notin_(recent),
                )
            )
        ).scalars().all()

        for p in stale:
            # Capture identifiers for the log BEFORE erasing (Rule 9: ids + last-4).
            last4 = (p.phone or "")[-4:] or "----"
            p.name = ERASED_NAME
            p.phone = None
            p.age = None
            p.gender = None
            p.followup_consent = False
            p.anonymized_at = now
            logger.info(
                "patient_pii_erased",
                patient_id=str(p.id),
                branch_id=str(p.branch_id),
                phone_last4=last4,
            )

        # Prune the demonstrable-notice records past the same window.
        pruned = await db.execute(
            Consent.__table__.delete().where(Consent.created_at < cutoff_dt)
        )

        if stale or pruned.rowcount:
            await db.commit()
            logger.info(
                "data_retention_run",
                patients_erased=len(stale),
                consents_pruned=int(pruned.rowcount or 0),
                retention_days=days,
            )
