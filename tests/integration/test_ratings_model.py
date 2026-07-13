"""WA T2 (spec 2026-07-13): ratings table constraints — one rating per token,
score bounded 1-5 at the DB (RULE-9-adjacent: score only, no text column at
all), branch CASCADE."""
import uuid
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from backend.models.schema import Branch, Doctor, Organization, Patient, Rating, Token


async def _branch(db):
    org = Organization(
        name="RatOrg", owner_phone="+919000700001",
        owner_email=f"rat-{uuid.uuid4().hex[:6]}@test.com", plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name="RatBranch",
        whatsapp_number=f"+9177{str(uuid.uuid4().int)[:8]}", status="active",
    )
    db.add(b)
    await db.commit()
    return b


@pytest.mark.asyncio
async def test_rating_score_bounds(db):
    b = await _branch(db)
    bid = b.id  # captured pre-rollback (expired ORM attrs can't lazy-load async)
    db.add(Rating(branch_id=bid, score=6))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
    db.add(Rating(branch_id=bid, score=5))
    await db.commit()  # 5 is fine


@pytest.mark.asyncio
async def test_rating_unique_per_token(db):
    b = await _branch(db)
    doc = Doctor(branch_id=b.id, name="Dr R", booking_type="token")
    pat = Patient(branch_id=b.id, name="P", phone="+919000700002")
    db.add_all([doc, pat])
    await db.flush()
    token = Token(
        branch_id=b.id, doctor_id=doc.id, patient_id=pat.id,
        date=date.today(), token_number=1, source="voice", status="attended",
    )
    db.add(token)
    await db.commit()

    db.add(Rating(branch_id=b.id, token_id=token.id, score=4))
    await db.commit()
    db.add(Rating(branch_id=b.id, token_id=token.id, score=2))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


@pytest.mark.asyncio
async def test_branch_wa_phone_number_id_unique(db):
    b1 = await _branch(db)
    b2 = await _branch(db)
    b1.wa_phone_number_id = "1234567890"
    await db.commit()
    b2.wa_phone_number_id = "1234567890"
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
