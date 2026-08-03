"""WA MVP1 Task 10 — clinic-authored WhatsApp templates.

Templates live PER WABA at Meta, not our DB, so RULE 1 branch scoping has to
be enforced explicitly at the route (assert_branch_access) rather than via a
WHERE clause. Validation (name shape, sequential placeholders, example
coverage) must reject BEFORE any Graph call — each maps to a real Meta 400
we would otherwise surface as an opaque error. The four system templates
(booking_confirm/appt_reminder/rating_ask/leave_rebook) are wired into the
live send paths and can never be deleted here.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.config import settings
from backend.models.schema import AuditLog, Branch, Organization
from backend.services import wa_template_admin
from backend.services.crypto import encrypt_secret

pytestmark = pytest.mark.asyncio
_ALGO = "HS256"


@pytest_asyncio.fixture
async def client(redis, db):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _jwt(*, role: str, org_id: str | None, branch_ids: list[str]) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()), "email": f"{role}@wa-tpl.test", "role": role,
            "org_id": org_id, "branch_ids": branch_ids, "is_admin": False,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret, algorithm=_ALGO,
    )


def _owner_jwt(org_id: str, branch_id: str) -> str:
    return _jwt(role="org_admin", org_id=org_id, branch_ids=[branch_id])


def _receptionist_jwt(org_id: str, branch_id: str) -> str:
    return _jwt(role="receptionist", org_id=org_id, branch_ids=[branch_id])


async def _clinic(db, **branch_kwargs) -> tuple[Organization, Branch]:
    org = Organization(
        name="WA Tpl Org", owner_phone="+919000700099",
        owner_email=f"wa-tpl-{uuid.uuid4().hex[:6]}@test.com", plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="WA Tpl Branch",
        whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}", status="active",
        **branch_kwargs,
    )
    db.add(branch)
    await db.commit()
    return org, branch


async def _connected_clinic(db) -> tuple[Organization, Branch]:
    return await _clinic(
        db, wa_waba_id=f"WABA{uuid.uuid4().hex[:8]}",
        wa_token_enc=encrypt_secret("CLINIC_TOKEN"), wa_status="connected",
    )


# ── list ─────────────────────────────────────────────────────────────────

async def test_templates_are_listed_from_the_branch_own_waba(client, db, monkeypatch):
    org, branch = await _connected_clinic(db)
    owner = _owner_jwt(str(org.id), str(branch.id))

    async def fake_get(url, token):
        assert token == "CLINIC_TOKEN"
        assert branch.wa_waba_id in url
        return {
            "data": [
                {"name": "booking_confirm", "language": "en", "status": "APPROVED",
                 "category": "UTILITY", "components": []},
            ]
        }
    monkeypatch.setattr(wa_template_admin, "_get", fake_get)

    r = await client.get(f"/branches/{branch.id}/whatsapp/templates", headers=_auth(owner))
    assert r.status_code == 200, r.text
    assert {t["name"] for t in r.json()} == {"booking_confirm"}


async def test_unconnected_branch_lists_no_templates_not_an_error(client, db):
    org, branch = await _clinic(db)  # no wa_waba_id / wa_token_enc
    owner = _owner_jwt(str(org.id), str(branch.id))

    r = await client.get(f"/branches/{branch.id}/whatsapp/templates", headers=_auth(owner))
    assert r.status_code == 200
    assert r.json() == []


async def test_a_clinic_cannot_read_another_clinics_templates(client, db):
    """RULE 1 — branch scoping is not optional because the data lives at Meta."""
    org, _branch = await _connected_clinic(db)
    _other_org, other_branch = await _connected_clinic(db)
    owner = _owner_jwt(str(org.id), str(_branch.id))

    r = await client.get(f"/branches/{other_branch.id}/whatsapp/templates", headers=_auth(owner))
    assert r.status_code in (403, 404)


# ── create: validation before Meta ──────────────────────────────────────

async def test_template_name_is_validated_before_meta_sees_it(client, db):
    org, branch = await _clinic(db)  # deliberately NOT connected
    owner = _owner_jwt(str(org.id), str(branch.id))

    r = await client.post(
        f"/branches/{branch.id}/whatsapp/templates",
        json={"name": "Booking Confirm!", "category": "UTILITY", "body": "hi"},
        headers=_auth(owner),
    )
    assert r.status_code == 422, r.text
    assert "lowercase" in r.text.lower()


async def test_body_placeholders_must_be_sequential_from_one(client, db):
    org, branch = await _clinic(db)
    owner = _owner_jwt(str(org.id), str(branch.id))

    r = await client.post(
        f"/branches/{branch.id}/whatsapp/templates",
        json={"name": "x", "category": "UTILITY", "body": "Hi {{1}} on {{3}}",
              "examples": ["Ravi", "Monday"]},
        headers=_auth(owner),
    )
    assert r.status_code == 422, r.text
    assert "sequential" in r.text.lower()


async def test_every_placeholder_needs_an_example(client, db):
    org, branch = await _clinic(db)
    owner = _owner_jwt(str(org.id), str(branch.id))

    r = await client.post(
        f"/branches/{branch.id}/whatsapp/templates",
        json={"name": "x", "category": "UTILITY", "body": "Hi {{1}}", "examples": []},
        headers=_auth(owner),
    )
    assert r.status_code == 422, r.text


async def test_a_blank_example_still_counts_as_missing(client, db):
    org, branch = await _clinic(db)
    owner = _owner_jwt(str(org.id), str(branch.id))

    r = await client.post(
        f"/branches/{branch.id}/whatsapp/templates",
        json={"name": "x", "category": "UTILITY", "body": "Hi {{1}}", "examples": ["  "]},
        headers=_auth(owner),
    )
    assert r.status_code == 422, r.text


async def test_category_defaults_to_utility(client, db, monkeypatch):
    org, branch = await _connected_clinic(db)
    owner = _owner_jwt(str(org.id), str(branch.id))

    seen = {}

    async def fake_post(url, token, payload):
        seen["payload"] = payload
        return httpx.Response(200, json={"id": "123", "status": "PENDING"})
    monkeypatch.setattr(wa_template_admin, "_post", fake_post)

    r = await client.post(
        f"/branches/{branch.id}/whatsapp/templates",
        json={"name": "diwali_offer", "body": "Namaste {{1}}, happy Diwali!",
              "examples": ["Ravi"]},
        headers=_auth(owner),
    )
    assert r.status_code == 201, r.text
    assert seen["payload"]["category"] == "UTILITY"
    assert seen["payload"]["components"][0]["example"]["body_text"] == [["Ravi"]]


async def test_receptionist_cannot_create_templates(client, db):
    org, branch = await _connected_clinic(db)
    staff = _receptionist_jwt(str(org.id), str(branch.id))

    r = await client.post(
        f"/branches/{branch.id}/whatsapp/templates",
        json={"name": "diwali_offer", "category": "UTILITY", "body": "hi"},
        headers=_auth(staff),
    )
    assert r.status_code == 403


async def test_create_when_not_connected_is_a_clean_422(client, db):
    org, branch = await _clinic(db)  # not connected
    owner = _owner_jwt(str(org.id), str(branch.id))

    r = await client.post(
        f"/branches/{branch.id}/whatsapp/templates",
        json={"name": "diwali_offer", "category": "UTILITY", "body": "Happy Diwali!"},
        headers=_auth(owner),
    )
    assert r.status_code == 422
    assert "connect" in r.text.lower()


async def test_successful_create_is_audited(client, db, monkeypatch):
    org, branch = await _connected_clinic(db)
    owner = _owner_jwt(str(org.id), str(branch.id))

    async def fake_post(url, token, payload):
        return httpx.Response(200, json={"id": "123", "status": "PENDING"})
    monkeypatch.setattr(wa_template_admin, "_post", fake_post)

    r = await client.post(
        f"/branches/{branch.id}/whatsapp/templates",
        json={"name": "diwali_offer", "category": "UTILITY", "body": "Happy Diwali!"},
        headers=_auth(owner),
    )
    assert r.status_code == 201, r.text

    row = (
        await db.execute(
            select(AuditLog).where(AuditLog.action == "branch.wa_template_created")
        )
    ).scalars().first()
    assert row is not None
    assert str(row.branch_id) == str(branch.id)
    assert row.success is True


async def test_meta_rejection_is_surfaced_as_a_readable_message(client, db, monkeypatch):
    org, branch = await _connected_clinic(db)
    owner = _owner_jwt(str(org.id), str(branch.id))

    async def fake_post(url, token, payload):
        return httpx.Response(
            400, json={"error": {"message": "Template text is too similar to an existing one"}},
        )
    monkeypatch.setattr(wa_template_admin, "_post", fake_post)

    r = await client.post(
        f"/branches/{branch.id}/whatsapp/templates",
        json={"name": "diwali_offer", "category": "UTILITY", "body": "Happy Diwali!"},
        headers=_auth(owner),
    )
    assert r.status_code == 422
    assert "too similar" in r.text.lower()
    assert "graph.facebook.com" not in r.text  # never a raw Graph payload


# ── delete ───────────────────────────────────────────────────────────────

async def test_the_four_system_templates_cannot_be_deleted(client, db):
    org, branch = await _connected_clinic(db)
    owner = _owner_jwt(str(org.id), str(branch.id))

    for name in ("booking_confirm", "appt_reminder", "rating_ask", "leave_rebook"):
        r = await client.delete(
            f"/branches/{branch.id}/whatsapp/templates/{name}", headers=_auth(owner),
        )
        assert r.status_code == 409, (name, r.text)


async def test_receptionist_cannot_delete_templates(client, db):
    org, branch = await _connected_clinic(db)
    staff = _receptionist_jwt(str(org.id), str(branch.id))

    r = await client.delete(
        f"/branches/{branch.id}/whatsapp/templates/diwali_offer", headers=_auth(staff),
    )
    assert r.status_code == 403


async def test_owner_can_delete_a_custom_template(client, db, monkeypatch):
    org, branch = await _connected_clinic(db)
    owner = _owner_jwt(str(org.id), str(branch.id))

    async def fake_delete(url, token):
        assert "diwali_offer" in url
        return httpx.Response(200, json={"success": True})
    monkeypatch.setattr(wa_template_admin, "_delete", fake_delete)

    r = await client.delete(
        f"/branches/{branch.id}/whatsapp/templates/diwali_offer", headers=_auth(owner),
    )
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True
