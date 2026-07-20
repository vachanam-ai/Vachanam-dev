"""#432 per-clinic doctor + timings cache (Vinay 2026-07-20).

"clinic number is lagging like anything... cache clinic doctors and their
timings per every clinic registers. so details about them will be true and
accurate all the time."

The roster is read on the call's critical path (it builds the system prompt
before the agent can speak) and, with Neon scale-to-zero (#299), that read
often paid a multi-second cold wake. Cached in Redis it is ~1-5ms.

ACCURACY is the hard requirement here: a stale roster would make the agent
quote wrong hours. So every doctor write must drop the key.
"""
import uuid
from datetime import time

import pytest

from backend.models.schema import Branch, Doctor, Organization
from backend.services import clinic_cache

pytestmark = pytest.mark.asyncio


async def _branch(db, tag):
    org = Organization(name=f"CC {tag}", owner_phone="+919000000000",
                       owner_email=f"cc-{tag}-{uuid.uuid4().hex[:6]}@t.in",
                       plan="clinic", status="active")
    db.add(org)
    await db.flush()
    br = Branch(org_id=org.id, name=f"B {tag}",
                whatsapp_number=f"+9111{uuid.uuid4().hex[:8]}", status="active")
    db.add(br)
    await db.flush()
    return br


async def _doctor(db, br, name, start=time(9, 0), end=time(17, 0), status="active"):
    doc = Doctor(branch_id=br.id, name=name, specialization="dental",
                 routing_keywords=["tooth"], booking_type="appointment",
                 working_hours_start=start, working_hours_end=end,
                 slot_duration_minutes=15, max_concurrent_per_slot=1,
                 available_weekdays=[0, 1, 2, 3, 4, 5], status=status)
    db.add(doc)
    await db.flush()
    return doc


async def test_miss_then_hit_returns_same_roster(db, redis):
    br = await _branch(db, "hit")
    await _doctor(db, br, "Dr. Cache", start=time(9, 0), end=time(23, 0))
    await db.commit()

    await clinic_cache.invalidate(br.id)
    first = await clinic_cache.load_doctors(br.id, db)      # miss → DB → fill
    assert await clinic_cache.get_doctors(br.id) is not None  # now cached
    second = await clinic_cache.load_doctors(br.id, db)     # hit
    assert first == second
    assert first[0]["name"] == "Dr. Cache"
    # timings survive the round trip in the shape DoctorContext wants
    assert first[0]["working_hours_start"] == "09:00"
    assert first[0]["working_hours_end"] == "23:00"
    assert first[0]["available_weekdays"] == [0, 1, 2, 3, 4, 5]


async def test_only_active_doctors_are_cached(db, redis):
    br = await _branch(db, "active")
    await _doctor(db, br, "Dr. On")
    await _doctor(db, br, "Dr. Gone", status="inactive")
    await db.commit()

    await clinic_cache.invalidate(br.id)
    names = [d["name"] for d in await clinic_cache.load_doctors(br.id, db)]
    assert names == ["Dr. On"]


async def test_invalidate_forces_fresh_timings(db, redis):
    """The accuracy requirement: after a timing change the next call must see
    the NEW hours, never the cached old ones."""
    br = await _branch(db, "fresh")
    doc = await _doctor(db, br, "Dr. Hours", end=time(17, 0))
    await db.commit()

    cached = await clinic_cache.load_doctors(br.id, db)
    assert cached[0]["working_hours_end"] == "17:00"

    doc.working_hours_end = time(23, 0)          # clinic extends the day
    await db.commit()
    # Without invalidation the cache would still say 17:00 …
    assert (await clinic_cache.get_doctors(br.id))[0]["working_hours_end"] == "17:00"
    # … the write path calls this, and the next read is correct.
    await clinic_cache.invalidate(br.id)
    assert (await clinic_cache.load_doctors(br.id, db))[0]["working_hours_end"] == "23:00"


async def test_warm_refreshes_in_one_step(db, redis):
    br = await _branch(db, "warm")
    doc = await _doctor(db, br, "Dr. Warm", end=time(17, 0))
    await db.commit()
    await clinic_cache.load_doctors(br.id, db)

    doc.working_hours_end = time(21, 0)
    await db.commit()
    refreshed = await clinic_cache.warm(br.id, db)
    assert refreshed[0]["working_hours_end"] == "21:00"
    assert (await clinic_cache.get_doctors(br.id))[0]["working_hours_end"] == "21:00"


async def test_rule1_two_clinics_never_share_a_roster(db, redis):
    a = await _branch(db, "iso-a")
    b = await _branch(db, "iso-b")
    await _doctor(db, a, "Dr. Alpha")
    await _doctor(db, b, "Dr. Beta")
    await db.commit()

    ra = await clinic_cache.load_doctors(a.id, db)
    rb = await clinic_cache.load_doctors(b.id, db)
    assert [d["name"] for d in ra] == ["Dr. Alpha"]
    assert [d["name"] for d in rb] == ["Dr. Beta"]
    # invalidating one clinic must not touch the other's cache
    await clinic_cache.invalidate(a.id)
    assert await clinic_cache.get_doctors(a.id) is None
    assert await clinic_cache.get_doctors(b.id) is not None


async def test_cache_failure_falls_back_to_db(db, redis, monkeypatch):
    """RULE 8: the cache is an accelerator. If Redis is down the call still
    gets a correct roster from the DB."""
    br = await _branch(db, "down")
    await _doctor(db, br, "Dr. Resilient")
    await db.commit()

    async def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(clinic_cache, "_redis", _boom)
    rows = await clinic_cache.load_doctors(br.id, db)
    assert [d["name"] for d in rows] == ["Dr. Resilient"]


async def test_every_doctor_write_endpoint_invalidates():
    """Source guard: all four doctor mutations must drop the cached roster —
    a missed one silently serves stale hours on live calls."""
    import inspect

    import backend.routers.doctors as mod

    for fn in ("create_doctor", "update_doctor", "soft_delete_doctor",
               "stop_walkins_today"):
        src = inspect.getsource(getattr(mod, fn))
        assert "invalidate_clinic_cache(branch_uuid)" in src, fn
