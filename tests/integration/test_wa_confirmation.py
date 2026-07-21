"""WA T4: booking-confirmation bridge — linked+gated branch sends one
template with correct params/buttons; unlinked/solo sends nothing; a wa
failure never raises into the booking path (RULE 4)."""
import uuid
from datetime import date, time

import pytest

from backend.models.schema import Branch, Organization
from backend.services import wa_service
from backend.services.meta_service import MetaService


async def _org_branch(db, plan="clinic", linked=True):
    org = Organization(
        name="WaOrg", owner_phone="+919000700010",
        owner_email=f"wa-{uuid.uuid4().hex[:6]}@test.com", plan=plan,
        status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name="WaBranch", address="12 MG Road, Hyd",
        whatsapp_number=f"+9166{str(uuid.uuid4().int)[:8]}", status="active",
        wa_phone_number_id=str(uuid.uuid4().int)[:12] if linked else None,
    )
    db.add(b)
    await db.commit()
    return b


@pytest.fixture
def wa_capture(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "meta_access_token", "tok", raising=False)
    monkeypatch.setattr(wa_service.settings, "meta_access_token", "tok", raising=False)
    sent = []

    async def _fake_send(branch, to, template, lang, params, buttons=None, plan=None):
        sent.append({
            "branch": str(branch.id), "to": to, "template": template,
            "lang": lang, "params": params, "buttons": buttons,
        })
        return True

    monkeypatch.setattr(wa_service, "send_template", _fake_send)
    # meta_service imports wa_service as a module — same object, patch sticks.
    return sent


@pytest.mark.asyncio
async def test_confirmation_sends_template(db, wa_capture):
    b = await _org_branch(db)
    bid, tid = b.id, str(uuid.uuid4())
    await MetaService().send_booking_confirmation(
        to="+919000000042", patient_name="Ravi", doctor_name="Dr S",
        clinic_name="WaBranch", booking_date=date(2026, 7, 15),
        token_number=None, appointment_time=time(18, 0),
        branch_id=bid, token_id=tid, patient_lang="te",
    )
    assert len(wa_capture) == 1
    s = wa_capture[0]
    assert s["template"] == "booking_confirm" and s["lang"] == "te"
    assert s["params"][0] == "WaBranch" and s["params"][1] == "Dr S"
    assert "15 July" in s["params"][2] and "6:00 PM" in s["params"][2]
    assert "maps.google.com" in s["params"][3]
    assert s["buttons"][0]["id"] == f"rs:{tid}"
    assert s["buttons"][1]["id"] == f"cx:{tid}"


@pytest.mark.asyncio
async def test_solo_plan_and_unlinked_send_nothing(db, wa_capture):
    solo = await _org_branch(db, plan="solo")
    unlinked = await _org_branch(db, linked=False)
    for b in (solo, unlinked):
        await MetaService().send_booking_confirmation(
            to="+919000000042", patient_name="R", doctor_name="D",
            clinic_name="C", booking_date=date(2026, 7, 15),
            token_number=3, appointment_time=None,
            branch_id=b.id, token_id=str(uuid.uuid4()),
        )
    assert wa_capture == []


@pytest.mark.asyncio
async def test_unknown_language_falls_back_to_en(db, wa_capture):
    b = await _org_branch(db)
    await MetaService().send_booking_confirmation(
        to="+919000000042", patient_name="R", doctor_name="D",
        clinic_name="C", booking_date=date(2026, 7, 15),
        token_number=3, appointment_time=None,
        branch_id=b.id, token_id=str(uuid.uuid4()), patient_lang="bn",
    )
    assert wa_capture[0]["lang"] == "en"  # bn template not registered day 1


@pytest.mark.asyncio
async def test_send_failure_never_raises(db, monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "meta_access_token", "tok", raising=False)

    async def _boom(*a, **k):
        raise RuntimeError("meta down")

    monkeypatch.setattr(wa_service, "send_template", _boom)
    b = await _org_branch(db)
    # must not raise (RULE 4)
    await MetaService().send_booking_confirmation(
        to="+919000000042", patient_name="R", doctor_name="D",
        clinic_name="C", booking_date=date(2026, 7, 15),
        token_number=3, appointment_time=None,
        branch_id=b.id, token_id=str(uuid.uuid4()),
    )
