"""seed_phase1.py — Phase 1 first-call seed.

Seeds the minimum rows required for the voice agent to handle a real call:
  - 1 Organization (plan=clinic, status=trial)
  - 1 Branch (did_number from VOBIZ_DID_NUMBER env var)
  - 1 Doctor (is_default_doctor=True, booking_type=token)

Idempotent: exits 0 immediately if a Branch with did_number already exists.

Usage:
    python scripts/seed_phase1.py

Env vars required (read from .env in repo root):
    VOBIZ_DID_NUMBER  — E.164 DID, e.g. +914066XXXXXX
    ADMIN_PHONE       — Vinay's WhatsApp; used as emergency_contact placeholder
    DATABASE_URL      — sqlalchemy+asyncpg URL (set in .env)

Sensitive data: DID and phone numbers are masked to last 4 digits in all log output.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add repo root to sys.path so `python scripts/seed_phase1.py` works the same
# as `python -m scripts.seed_phase1` (both resolve backend.* imports correctly).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Load .env from repo root before importing backend modules
from dotenv import load_dotenv

load_dotenv(_REPO_ROOT / ".env")

# Validate required env vars before touching DB
_VOBIZ_DID_NUMBER = os.getenv("VOBIZ_DID_NUMBER", "")
if not _VOBIZ_DID_NUMBER:
    print(
        "ERROR: VOBIZ_DID_NUMBER is not set. "
        "Add it to .env before running seed_phase1.py.",
        file=sys.stderr,
    )
    sys.exit(1)

_ADMIN_PHONE = os.getenv("ADMIN_PHONE", "")
if not _ADMIN_PHONE:
    print(
        "ERROR: ADMIN_PHONE is not set. "
        "Add it to .env before running seed_phase1.py.",
        file=sys.stderr,
    )
    sys.exit(1)


# Import backend modules AFTER .env is loaded so settings reads the right values
import uuid
from datetime import time as dt_time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import AsyncSessionLocal
from backend.models.schema import Branch, Doctor, Organization


def _mask(phone: str) -> str:
    """Return last 4 digits of a phone number for safe log output."""
    return f"...{phone[-4:]}" if len(phone) >= 4 else "****"


async def _seed(
    session: AsyncSession,
    *,
    did_number: str | None = None,
    admin_phone: str | None = None,
    owner_email: str | None = None,
) -> None:
    """Insert Org → Branch → Doctor if Branch does not already exist.

    Parameters
    ----------
    session:      AsyncSession to use.
    did_number:   Override _VOBIZ_DID_NUMBER (for test injection).
    admin_phone:  Override _ADMIN_PHONE (for test injection).
    owner_email:  Override owner_email for Organization (for test isolation).
                  Defaults to "test@vachanam-phase1.internal".
    """
    _did = did_number if did_number is not None else _VOBIZ_DID_NUMBER
    _admin = admin_phone if admin_phone is not None else _ADMIN_PHONE
    _email = owner_email if owner_email is not None else "test@vachanam-phase1.internal"

    # Idempotency check: branch identified by did_number
    result = await session.execute(
        select(Branch).where(Branch.did_number == _did)
    )
    existing_branch = result.scalar_one_or_none()

    if existing_branch is not None:
        print(
            f"already seeded, skipping  "
            f"(branch.did_number={_mask(_did)}, "
            f"branch.id={existing_branch.id})"
        )
        return

    now_utc = datetime.now(tz=timezone.utc)
    trial_ends_at = now_utc + timedelta(days=14)

    # --- Organization ---
    org = Organization(
        id=uuid.uuid4(),
        name="Vachanam Test Clinic",
        owner_phone=_admin,
        owner_email=_email,
        plan="clinic",
        status="trial",
        trial_ends_at=trial_ends_at,
    )
    session.add(org)
    await session.flush()  # get org.id for FK

    # --- Branch ---
    # whatsapp_number uses ADMIN_PHONE as placeholder until WhatsApp wiring (MVP2).
    # google_calendar_id uses "primary" as placeholder for stub CalendarService.
    branch = Branch(
        id=uuid.uuid4(),
        org_id=org.id,
        name="Vachanam",
        address="Test Address Hyderabad 500001",
        city="Hyderabad",
        whatsapp_number=_admin,
        did_number=_did,
        emergency_contact=_admin,
        google_calendar_id="primary",
        timezone="Asia/Kolkata",
        status="active",
    )
    session.add(branch)
    await session.flush()  # get branch.id for FK

    # --- Doctor ---
    # working_hours_start / working_hours_end: schema uses separate Time columns.
    # The dispatch spec requested a JSONB working_hours column but that column does
    # not exist in schema.py — the schema uses Time columns instead. Using 09:00-18:00
    # Mon-Fri range expressed as start/end times.
    doctor = Doctor(
        id=uuid.uuid4(),
        branch_id=branch.id,
        name="Dr. Test Kumar",
        specialization="general",
        is_default_doctor=True,
        booking_type="token",
        daily_token_limit=50,
        working_hours_start=dt_time(9, 0),   # 09:00 IST
        working_hours_end=dt_time(18, 0),    # 18:00 IST
        slot_duration_minutes=15,
        pre_appointment_reminder=False,
        status="active",
    )
    session.add(doctor)
    await session.commit()

    print(
        f"seed_complete  "
        f"org_id={org.id}  "
        f"branch_id={branch.id}  "
        f"doctor_id={doctor.id}  "
        f"did={_mask(_did)}  "
        f"admin={_mask(_admin)}"
    )


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await _seed(session)


if __name__ == "__main__":
    asyncio.run(main())
