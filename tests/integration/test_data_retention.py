"""Proof for the DPDP s.8(7) retention/erasure job + s.5 consent record.

- A patient with no appointment inside the retention window has their PII erased
  (name/phone/age/gender cleared, anonymized_at stamped) while the booking rows
  survive.
- A patient with a RECENT appointment is never touched.
- Demonstrable-notice (consents) rows past the window are pruned.
- The consents table records a per-call notice (DPDP s.5).
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.config import settings
from backend.jobs.data_retention import ERASED_NAME, run_data_retention
from backend.models.schema import (
    Branch,
    CallQuality,
    Consent,
    Doctor,
    Organization,
    Patient,
    Token,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def clinic(db):
    org = Organization(
        name="Ret Org", owner_phone="+919000111222",
        owner_email=f"ret-{uuid.uuid4().hex[:6]}@t.com", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="Ret Branch",
        whatsapp_number=f"+9188{str(uuid.uuid4().int)[:8]}", status="active",
    )
    db.add(branch)
    await db.flush()
    doc = Doctor(
        branch_id=branch.id, name="Dr R", specialization="dentist",
        booking_type="token", status="active",
    )
    db.add(doc)
    await db.commit()
    return {"branch": branch, "doctor": doc}


async def _patient_with_token(db, clinic, *, name, phone, last_token_days_ago, created_days_ago):
    p = Patient(
        branch_id=clinic["branch"].id, name=name, phone=phone, age=30, gender="male",
        created_at=datetime.now(timezone.utc) - timedelta(days=created_days_ago),
    )
    db.add(p)
    await db.flush()
    db.add(Token(
        branch_id=clinic["branch"].id, doctor_id=clinic["doctor"].id, patient_id=p.id,
        date=date.today() - timedelta(days=last_token_days_ago), token_number=1,
        status="attended", source="voice",
    ))
    await db.commit()
    return p


async def test_retention_erases_stale_patient(clinic, db, monkeypatch):
    monkeypatch.setattr(settings, "patient_retention_days", 30, raising=False)
    p = await _patient_with_token(
        db, clinic, name="Old Patient", phone="+919666000111",
        last_token_days_ago=60, created_days_ago=60,
    )
    pid = p.id  # capture before expiry (avoids lazy sync IO after expire_all)
    await run_data_retention()
    db.expire_all()
    row = (await db.execute(select(Patient).where(Patient.id == pid))).scalar_one()
    assert row.name == ERASED_NAME
    assert row.phone is None and row.age is None and row.gender is None
    assert row.anonymized_at is not None
    # the booking row survives (anonymised analytics) — patient_id still resolves
    tok = (await db.execute(select(Token).where(Token.patient_id == pid))).scalar_one()
    assert tok.status == "attended"


async def test_retention_keeps_recent_patient(clinic, db, monkeypatch):
    monkeypatch.setattr(settings, "patient_retention_days", 30, raising=False)
    p = await _patient_with_token(
        db, clinic, name="Recent Patient", phone="+919666000222",
        last_token_days_ago=5, created_days_ago=60,
    )
    pid = p.id  # capture before expiry
    await run_data_retention()
    db.expire_all()
    row = (await db.execute(select(Patient).where(Patient.id == pid))).scalar_one()
    assert row.name == "Recent Patient"  # a recent booking keeps the whole record
    assert row.phone == "+919666000222"
    assert row.anonymized_at is None


async def test_retention_prunes_old_consents(clinic, db, monkeypatch):
    monkeypatch.setattr(settings, "patient_retention_days", 30, raising=False)
    old = Consent(
        branch_id=clinic["branch"].id, patient_phone="+919666000333",
        created_at=datetime.now(timezone.utc) - timedelta(days=60),
    )
    new = Consent(
        branch_id=clinic["branch"].id, patient_phone="+919666000444",
        created_at=datetime.now(timezone.utc) - timedelta(days=5),
    )
    db.add_all([old, new])
    await db.commit()
    old_id, new_id = old.id, new.id
    await run_data_retention()
    db.expire_all()
    remaining = set((await db.execute(select(Consent.id))).scalars().all())
    assert new_id in remaining
    assert old_id not in remaining


async def test_retention_nulls_old_transcript_keeps_outcome_row(clinic, db, monkeypatch):
    """Transcripts are PII on the shorter transcript_retention clock: the text is
    NULLED past the window but the (non-PII) outcome row survives for trends."""
    monkeypatch.setattr(settings, "transcript_retention_days", 30, raising=False)
    old = CallQuality(
        branch_id=clinic["branch"].id, session_id="cq-old", language="te",
        booking_made=True, turns=6, transcript="patient: ... / agent: ...",
        created_at=datetime.now(timezone.utc) - timedelta(days=60),
    )
    recent = CallQuality(
        branch_id=clinic["branch"].id, session_id="cq-new", language="te",
        booking_made=True, turns=4, transcript="patient: hello / agent: hi",
        created_at=datetime.now(timezone.utc) - timedelta(days=5),
    )
    db.add_all([old, recent])
    await db.commit()
    old_id, new_id = old.id, recent.id
    await run_data_retention()
    db.expire_all()
    old_row = (await db.execute(select(CallQuality).where(CallQuality.id == old_id))).scalar_one()
    new_row = (await db.execute(select(CallQuality).where(CallQuality.id == new_id))).scalar_one()
    # outcome row kept, only the PII text dropped
    assert old_row.transcript is None
    assert old_row.booking_made is True and old_row.turns == 6
    # recent transcript untouched
    assert new_row.transcript == "patient: hello / agent: hi"


async def test_consent_row_records_notice(clinic, db):
    """consents stores a demonstrable-notice record (DPDP s.5)."""
    c = Consent(
        branch_id=clinic["branch"].id, session_id="sess-1",
        patient_phone="+919666000555", consent_type="data_processing",
        notice_version="1.0", method="verbal",
    )
    db.add(c)
    await db.commit()
    got = (await db.execute(select(Consent).where(Consent.session_id == "sess-1"))).scalar_one()
    assert got.consent_type == "data_processing" and got.method == "verbal"
    assert got.branch_id == clinic["branch"].id
