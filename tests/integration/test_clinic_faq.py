"""Clinic FAQ: save/roundtrip + agent prompt injection (2026-07-03).

The agent answers clinic-configured FAQs (fees, timings, parking...) on calls
instead of "please confirm at the clinic". Unanswered template rows are
skipped; the injected block is grounded ("never contradict or extend").
"""
import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.middleware.auth_middleware import get_current_user, CurrentUser
from backend.models.schema import Branch, Organization
from agent.prompts.system_prompt import build_system_prompt


def _as_user(branch_id, org_id, role="org_admin"):
    return CurrentUser(
        user_id=str(uuid.uuid4()), email="o@c.com", role=role,
        org_id=str(org_id), branch_ids=[str(branch_id)], is_admin=False,
        jti=str(uuid.uuid4()),
    )


async def _seed(db, wa):
    org_id = uuid.uuid4()
    db.add(Organization(id=org_id, name="Org", owner_phone="+919000099088",
                        owner_email=f"o-{org_id}@c.com", plan="clinic"))
    await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C", whatsapp_number=wa)
    db.add(br)
    await db.commit()
    return org_id, br


@pytest.mark.asyncio
async def test_faq_save_and_roundtrip(db):
    org_id, br = await _seed(db, "+910000000090")
    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            g = await ac.get(f"/branches/{br.id}/faq")
            assert g.status_code == 200
            assert g.json()["faq"] == []
            assert len(g.json()["template"]) >= 10  # researched template served

            body = {"faq": [
                {"q": "What is the consultation fee?", "a": "Rs 300 for Dr Srinivas"},
                {"q": "Is parking available?", "a": "Yes, in front of the clinic"},
                {"q": "  ", "a": "dropped"},              # empty q row dropped
                {"q": "Sunday open?", "a": ""},            # unanswered kept
            ]}
            s = await ac.put(f"/branches/{br.id}/faq", json=body)
            assert s.status_code == 200, s.text
            saved = s.json()["faq"]
            assert len(saved) == 3
            assert saved[0]["a"] == "Rs 300 for Dr Srinivas"

            g2 = await ac.get(f"/branches/{br.id}/faq")
            assert g2.json()["faq"] == saved
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_faq_staff_cannot_save(db):
    org_id, br = await _seed(db, "+910000000091")
    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id, role="receptionist")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            s = await ac.put(f"/branches/{br.id}/faq", json={"faq": []})
            assert s.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_prompt_injects_answered_faq_only():
    prompt = build_system_prompt(
        clinic_name="C", doctors=[], emergency_contact="+911234567890",
        plan="clinic", language="te",
        faq=[
            {"q": "Consultation fee?", "a": "Rs 300"},
            {"q": "Sunday open?", "a": ""},          # unanswered -> skipped
        ],
    )
    assert "CLINIC FAQ" in prompt
    assert "Rs 300" in prompt
    assert "Sunday open?" not in prompt
    # grounding directive present
    assert "Never contradict or extend" in prompt


def test_prompt_no_faq_no_block():
    prompt = build_system_prompt(
        clinic_name="C", doctors=[], emergency_contact="+911234567890",
        plan="clinic", language="te", faq=None,
    )
    assert "CLINIC FAQ" not in prompt
