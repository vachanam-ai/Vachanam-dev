"""A paid add-on must leave a record, not just a boolean.

Vinay 2026-08-03, looking at the ops Operations page after paying ₹1,499:
"whatsapp payment didn't got updated here in super_owner pages."

He was right and it was worse than a UI gap. The ops Payments list reads
billing_cycles, and an add-on deliberately creates no cycle — starting a
billing period nobody bought would corrupt minutes accounting and the renewal
lock. So the money existed only in Razorpay and as a boolean on the branch:
nothing to reconcile, nothing to show an auditor.

addon_purchases is that ledger. The flag is idempotent STATE; the row is MONEY,
and uniqueness on razorpay_payment_id is what stops a webhook replay booking
the same payment twice.
"""
import uuid

import pytest

from backend.models.schema import AddonPurchase, Branch, Organization
from backend.routers.payments import _enable_whatsapp_addon
from backend.services.billing_math import WHATSAPP_ADDON_RUPEES


async def _clinic(db):
    org = Organization(
        name="LedgerOrg", owner_phone="+919000700033",
        owner_email=f"ledger-{uuid.uuid4().hex[:6]}@test.com",
        plan="solo", status="active",
    )
    db.add(org)
    await db.flush()
    br = Branch(
        org_id=org.id, name="LedgerBranch", status="active",
        whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}",
    )
    db.add(br)
    await db.commit()
    return org, br


async def _rows(db, org_id):
    from sqlalchemy import select

    return (
        await db.execute(select(AddonPurchase).where(AddonPurchase.org_id == org_id))
    ).scalars().all()


@pytest.mark.asyncio
async def test_paying_writes_a_ledger_row_with_the_amount(db):
    org, br = await _clinic(db)
    await _enable_whatsapp_addon(
        db, {"branch_id": str(br.id), "org_id": str(org.id)}, "pay_ledger_1"
    )
    rows = await _rows(db, org.id)
    assert len(rows) == 1
    assert rows[0].kind == "whatsapp_addon"
    assert rows[0].amount == WHATSAPP_ADDON_RUPEES
    assert rows[0].branch_id == br.id
    assert rows[0].razorpay_payment_id == "pay_ledger_1"


@pytest.mark.asyncio
async def test_a_webhook_replay_does_not_book_the_money_twice(db):
    """Razorpay redelivers. Two rows for one payment is a reconciliation bug."""
    org, br = await _clinic(db)
    for _ in range(3):
        await _enable_whatsapp_addon(
            db, {"branch_id": str(br.id), "org_id": str(org.id)}, "pay_same"
        )
    assert len(await _rows(db, org.id)) == 1


@pytest.mark.asyncio
async def test_the_row_is_written_even_when_the_flag_was_already_on(db):
    """The flag is state and may already be true — from an earlier manual link,
    say. The money still has to be recorded, or a real payment vanishes."""
    org, br = await _clinic(db)
    br.whatsapp_addon = True
    await db.commit()

    await _enable_whatsapp_addon(
        db, {"branch_id": str(br.id), "org_id": str(org.id)}, "pay_after_manual"
    )
    rows = await _rows(db, org.id)
    assert len(rows) == 1, "a payment against an already-on branch must still be booked"


@pytest.mark.asyncio
async def test_a_forged_cross_org_note_writes_nothing(db):
    """RULE 1: no ledger row, and no flag, for a branch outside the paying org."""
    _org_a, br_a = await _clinic(db)
    org_b, _br_b = await _clinic(db)

    await _enable_whatsapp_addon(
        db, {"branch_id": str(br_a.id), "org_id": str(org_b.id)}, "pay_forged"
    )
    await db.refresh(br_a)
    assert br_a.whatsapp_addon is False
    assert await _rows(db, org_b.id) == []
