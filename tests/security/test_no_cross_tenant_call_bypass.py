"""No call reaches, or appears to come from, the wrong clinic.

Vinay 2026-08-14: "configure setup so good that no call from one clinic/number
gets bypassed by another."

"Bypass" has two directions and they fail differently:

  INBOUND   a patient dials clinic A's DID and reaches clinic B's agent —
            B's doctors, B's slots, B's patient records. DPDP breach.
  OUTBOUND  clinic A's reminder arrives showing clinic B's number. That is
            FIXLOG #518, and it happened.

Same rule both ways: resolve to exactly ONE clinic, or refuse the call. Never
guess, never default, never fall back to a platform identity. Most tests here
assert a REFUSAL, because the safe behaviour of an ambiguous call is not to
happen at all.

These also prove the SHARED-TRUNK model is safe. Per-customer trunks are a
LiveKit anti-pattern — trunks are long-lived cached objects and one per clinic
degrades reliability at scale. Because the caller ID is now stated per call
(`sip_number`) instead of inherited from the trunk, a single outbound trunk
carrying every DID still gives each clinic only its own identity.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schema import Branch, Organization

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _one_shared_outbound_trunk(monkeypatch):
    import backend.services.telephony as telephony

    monkeypatch.setattr(telephony.settings, "outbound_trunk_id", "ST_shared")


# ── database-level invariant ──────────────────────────────────────────────

async def test_postgres_allows_one_branch_per_did(db: AsyncSession):
    """The last line of defence is the database, not application code."""
    from sqlalchemy import text

    rows = (
        await db.execute(
            text(
                "select indexdef from pg_indexes "
                "where tablename='branches' and indexname='uq_branches_did_number'"
            )
        )
    ).scalars().all()
    assert rows, "the one-branch-per-DID unique index is gone"
    assert "UNIQUE" in rows[0].upper()
    assert "did_number" in rows[0]


async def test_a_second_branch_cannot_claim_the_same_did(db: AsyncSession):
    """Proven against the real database, not by reading the index definition."""
    from sqlalchemy import func, select
    from sqlalchemy.exc import IntegrityError

    did = f"+9180{uuid.uuid4().int % 100000000:08d}"
    await _branch(db, did=did)
    await db.commit()

    with pytest.raises(IntegrityError):
        await _branch(db, did=did)
        await db.commit()
    await db.rollback()

    owners = (
        await db.execute(
            select(func.count()).select_from(Branch).where(Branch.did_number == did)
        )
    ).scalar_one()
    assert owners == 1, "a DID ended up owned by more than one clinic"


# ── INBOUND ───────────────────────────────────────────────────────────────

def _agent_source() -> str:
    from pathlib import Path

    return Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")


def test_inbound_refuses_an_unknown_or_duplicate_did():
    """One check covers a DID belonging to no clinic AND one claimed by two."""
    src = _agent_source()
    assert "if len(branches) != 1:" in src, "the exactly-one-tenant check is gone"
    block = src.split("if len(branches) != 1:", 1)[1][:600]
    assert "did_resolution_failed" in block
    assert "_end_call_with_notice" in block, "an ambiguous call must END, not continue"


def test_inbound_refuses_the_platform_fallback_once_a_second_clinic_exists():
    """A missing SIP attribute must never route to the default DID's clinic."""
    src = _agent_source()
    assert "if did_from_fallback:" in src
    block = src.split("if did_from_fallback:", 1)[1][:700]
    assert "total_branches != 1" in block
    assert "did_fallback_refused" in block
    assert "ctx.shutdown()" in block


def test_inbound_matching_is_did_format_agnostic():
    """A format difference must fail the MATCH, not silently widen it."""
    from backend.services.validators import normalize_did

    canonical = "+918046733493"
    for spelling in ("+918046733493", "918046733493", "08046733493", "+91 80 4673 3493"):
        assert normalize_did(spelling) == canonical, spelling


# ── OUTBOUND fixtures ─────────────────────────────────────────────────────

async def _org(db: AsyncSession) -> Organization:
    org = Organization(
        id=uuid.uuid4(), name="C", plan="solo", status="active",
        owner_phone=f"+9198{uuid.uuid4().int % 100000000:08d}",
        owner_email=f"{uuid.uuid4().hex[:10]}@example.com",
    )
    db.add(org)
    await db.flush()
    return org


async def _branch(db: AsyncSession, *, did: str | None = None,
                  trunk: str | None = "ST_valid") -> Branch:
    org = await _org(db)
    branch = Branch(
        id=uuid.uuid4(), org_id=org.id, name="Main", timezone="Asia/Kolkata",
        whatsapp_number=f"+9188{uuid.uuid4().int % 100000000:08d}",
        did_number=did, outbound_trunk_id=trunk, status="active",
    )
    db.add(branch)
    await db.flush()
    return branch


class _FakeTrunk:
    def __init__(self, trunk_id, numbers):
        self.sip_trunk_id = trunk_id
        self.numbers = numbers


class _FakeSip:
    def __init__(self, trunks):
        self._trunks = trunks

    async def list_outbound_trunk(self, _request):
        class _Res:
            pass

        res = _Res()
        res.items = self._trunks
        return res


async def _validate(branch, *, supplied_trunk=None, trunks=None):
    from agent.livekit_minimal.agent import _validated_outbound_trunk

    meta = {
        "branch_id": str(branch.id),
        "outbound_trunk_id": supplied_trunk if supplied_trunk is not None
        else "ST_shared",
    }
    inventory = trunks if trunks is not None else [
        _FakeTrunk("ST_shared", [branch.did_number or ""])
    ]
    return await _validated_outbound_trunk(meta, _FakeSip(inventory))


# ── OUTBOUND ──────────────────────────────────────────────────────────────

async def test_outbound_presents_this_branchs_own_number(db: AsyncSession):
    did = f"+9180{uuid.uuid4().int % 100000000:08d}"
    branch = await _branch(db, did=did)
    await db.commit()

    trunk_id, caller_id = await _validate(branch)

    assert trunk_id == "ST_shared"
    assert caller_id == did, "the presented caller ID is not this clinic's number"


async def test_outbound_refuses_a_trunk_the_branch_does_not_own(db: AsyncSession):
    """#518: dispatch metadata naming ANOTHER clinic's trunk must not dial."""
    branch = await _branch(db, did=f"+9180{uuid.uuid4().int % 100000000:08d}")
    await db.commit()

    assert await _validate(branch, supplied_trunk="ST_someone_else") == ("", "")


async def test_outbound_refuses_when_the_trunk_cannot_present_our_did(db: AsyncSession):
    branch = await _branch(db, did=f"+9180{uuid.uuid4().int % 100000000:08d}")
    await db.commit()

    assert await _validate(
        branch, trunks=[_FakeTrunk("ST_shared", ["+919999999999"])]
    ) == ("", "")


async def test_outbound_refuses_a_branch_with_no_did(db: AsyncSession):
    """No DID means no provable identity. Dialling anyway would present the
    trunk's default number — how a clinic ends up calling as somebody else."""
    branch = await _branch(db, did=None)
    await db.commit()

    assert await _validate(branch) == ("", "")


async def test_outbound_refuses_an_unknown_branch(db: AsyncSession):
    from agent.livekit_minimal.agent import _validated_outbound_trunk

    meta = {"branch_id": str(uuid.uuid4()), "outbound_trunk_id": "ST_valid"}
    assert await _validated_outbound_trunk(meta, _FakeSip([])) == ("", "")


async def test_outbound_refuses_junk_metadata(db: AsyncSession):
    from agent.livekit_minimal.agent import _validated_outbound_trunk

    for bad in ({}, {"branch_id": "not-a-uuid"}, {"branch_id": None}):
        assert await _validated_outbound_trunk(bad, _FakeSip([])) == ("", "")


async def test_two_clinics_never_share_a_caller_id(db: AsyncSession):
    a = await _branch(db, did=f"+9180{uuid.uuid4().int % 100000000:08d}", trunk="ST_a")
    b = await _branch(db, did=f"+9180{uuid.uuid4().int % 100000000:08d}", trunk="ST_b")
    await db.commit()

    shared = [_FakeTrunk("ST_shared", [a.did_number, b.did_number])]
    _, caller_a = await _validate(a, trunks=shared)
    _, caller_b = await _validate(b, trunks=shared)

    assert caller_a == a.did_number
    assert caller_b == b.did_number
    assert caller_a != caller_b


# ── the shared-trunk model ────────────────────────────────────────────────

async def test_one_shared_trunk_still_gives_each_clinic_its_own_number(db: AsyncSession):
    """THE test for the scale model.

    One outbound trunk carrying every DID, both branches pointing at it. Each
    still presents only its own number, because the caller ID is stated per
    call rather than inherited from the trunk. Without that, both clinics would
    present whatever the trunk defaults to — FIXLOG #518 all over again.
    """
    a = await _branch(db, did=f"+9180{uuid.uuid4().int % 100000000:08d}", trunk="ST_shared")
    b = await _branch(db, did=f"+9180{uuid.uuid4().int % 100000000:08d}", trunk="ST_shared")
    await db.commit()

    shared = [_FakeTrunk("ST_shared", [a.did_number, b.did_number])]

    trunk_a, caller_a = await _validate(a, trunks=shared)
    trunk_b, caller_b = await _validate(b, trunks=shared)

    assert trunk_a == trunk_b == "ST_shared", "both should use the one trunk"
    assert caller_a == a.did_number
    assert caller_b == b.did_number
    assert caller_a != caller_b, "a shared trunk leaked one clinic's caller ID"


async def test_a_shared_trunk_still_refuses_a_branch_with_no_did(db: AsyncSession):
    """On a shared trunk this is the dangerous case: the trunk carries plenty of
    numbers, so 'does the trunk have a number?' is not the question. The branch
    must have ITS OWN."""
    orphan = await _branch(db, did=None, trunk="ST_shared")
    neighbour = await _branch(db, did=f"+9180{uuid.uuid4().int % 100000000:08d}",
                              trunk="ST_shared")
    await db.commit()

    shared = [_FakeTrunk("ST_shared", [neighbour.did_number])]

    assert await _validate(orphan, trunks=shared) == ("", "")


def test_the_dial_actually_states_the_caller_id():
    """A validated caller ID that never reaches the dial proves nothing."""
    src = _agent_source()
    assert "_out_trunk, _out_caller_id = await _validated_outbound_trunk(" in src
    assert "if not _out_trunk or not _out_caller_id:" in src
    dial = src.split("api.CreateSIPParticipantRequest(", 1)[1][:600]
    assert "sip_number=_out_caller_id" in dial, "the dial does not state the caller ID"


def test_sip_number_is_a_real_field_on_the_livekit_request():
    """The whole approach rests on LiveKit accepting a per-call caller ID.
    Pin it, so an SDK upgrade that renames the field fails here and not in
    production with the wrong number on a patient's phone."""
    from livekit import api

    fields = {f.name for f in api.CreateSIPParticipantRequest.DESCRIPTOR.fields}
    assert "sip_number" in fields
