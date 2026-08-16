import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from backend.config import settings
from backend.models.schema import Branch, Organization
from backend.services import wa_connect
from backend.services.crypto import encrypt_secret


@pytest.fixture
async def client(redis):
    from backend.main import app
    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
        yield api


def jwt_for(*, role="org_admin", org_id=None, branch_ids=None, is_admin=False):
    import jwt
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": str(uuid.uuid4()), "email": f"{role}@wa.test", "role": role,
        "org_id": org_id, "branch_ids": branch_ids or [], "is_admin": is_admin,
        "iat": int(now.timestamp()), "exp": int((now + timedelta(hours=2)).timestamp()),
        "jti": str(uuid.uuid4()),
    }, settings.jwt_secret, algorithm="HS256")


def auth(token): return {"Authorization": f"Bearer {token}"}


async def clinic(db, **branch_values):
    org = Organization(
        name="WA Org", owner_phone="+919000700077",
        owner_email=f"wa-{uuid.uuid4().hex[:6]}@test.com", plan="solo", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="WA Clinic",
        whatsapp_number=f"+9177{str(uuid.uuid4().int)[:9]}", status="active",
        whatsapp_addon=True, **branch_values,
    )
    db.add(branch)
    await db.commit()
    return org, branch


BODY = {
    "code": "AUTHORIZATION_CODE_ABCDEFG",
    "waba_id": "123456789",
    "phone_number_id": "987654321",
    "business_id": "111222333",
    "flow_event": "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
}


@pytest.fixture
def fake_connect(monkeypatch):
    calls = []

    async def connect(branch, **values):
        calls.append(values)
        branch.wa_waba_id = values["waba_id"]
        branch.wa_phone_number_id = values["phone_number_id"]
        branch.wa_token_enc = encrypt_secret("BUSINESS_TOKEN")
        branch.wa_verified_name = "Test Clinic"
        branch.wa_status = "connected"
        branch.wa_connected_at = datetime.now(timezone.utc)
        branch.wa_onboarding = {
            "mode": "coexistence", "payment_status": "required",
            "registration_pin_enc": encrypt_secret("123456"), "sync": {},
        }
        return {
            "registered": False,
            "verified_name": "Test Clinic",
            "onboarding": wa_connect.public_onboarding(branch),
        }

    monkeypatch.setattr(wa_connect, "connect_branch", connect)
    return calls


@pytest.mark.asyncio
async def test_owner_connects_with_v4_session_data(db, client, fake_connect):
    org, branch = await clinic(db)
    response = await client.post(
        f"/branches/{branch.id}/whatsapp/connect",
        headers=auth(jwt_for(org_id=str(org.id))), json=BODY,
    )
    assert response.status_code == 201, response.text
    assert fake_connect[0]["flow_event"] == "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING"
    assert fake_connect[0]["business_id"] == "111222333"
    assert response.json()["onboarding"]["payment_status"] == "required"
    assert "registration_pin_enc" not in response.text


@pytest.mark.asyncio
async def test_manual_token_endpoint_is_retired(db, client):
    org, branch = await clinic(db)
    response = await client.post(
        f"/branches/{branch.id}/whatsapp/connect/manual",
        headers=auth(jwt_for(org_id=str(org.id))), json={"access_token": "secret"},
    )
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_connection_status_never_exposes_token_or_pin(db, client, fake_connect):
    org, branch = await clinic(db)
    token = jwt_for(org_id=str(org.id))
    await client.post(f"/branches/{branch.id}/whatsapp/connect", headers=auth(token), json=BODY)
    response = await client.get(f"/branches/{branch.id}/whatsapp/connect", headers=auth(token))
    assert response.status_code == 200
    assert response.json()["connected"] is True
    assert "BUSINESS_TOKEN" not in response.text
    assert "registration_pin_enc" not in response.text


@pytest.mark.asyncio
async def test_invalid_finish_event_is_rejected_before_service(db, client, fake_connect):
    org, branch = await clinic(db)
    response = await client.post(
        f"/branches/{branch.id}/whatsapp/connect",
        headers=auth(jwt_for(org_id=str(org.id))),
        json={**BODY, "flow_event": "FINISH_ONLY_WABA"},
    )
    assert response.status_code == 422 and fake_connect == []


@pytest.mark.asyncio
async def test_receptionist_and_other_org_cannot_connect(db, client, fake_connect):
    org_a, branch_a = await clinic(db)
    org_b, _branch_b = await clinic(db)
    receptionist = jwt_for(
        role="receptionist", org_id=str(org_a.id), branch_ids=[str(branch_a.id)]
    )
    assert (await client.post(
        f"/branches/{branch_a.id}/whatsapp/connect", headers=auth(receptionist), json=BODY,
    )).status_code == 403
    assert (await client.post(
        f"/branches/{branch_a.id}/whatsapp/connect",
        headers=auth(jwt_for(org_id=str(org_b.id))), json=BODY,
    )).status_code == 403
    assert fake_connect == []


@pytest.mark.asyncio
async def test_waba_cannot_be_claimed_by_two_clinics(db, client, fake_connect):
    await clinic(db, wa_waba_id=BODY["waba_id"], wa_status="connected")
    org, branch = await clinic(db)
    response = await client.post(
        f"/branches/{branch.id}/whatsapp/connect",
        headers=auth(jwt_for(org_id=str(org.id))), json=BODY,
    )
    assert response.status_code == 409 and fake_connect == []


@pytest.mark.asyncio
async def test_payment_confirmation_and_sync_retry_are_owner_only(db, client, monkeypatch):
    org, branch = await clinic(
        db, wa_status="connected", wa_waba_id="123", wa_phone_number_id="456",
        wa_token_enc=encrypt_secret("token"),
        wa_onboarding={"mode": "coexistence", "payment_status": "required", "sync": {}},
    )
    owner = auth(jwt_for(org_id=str(org.id)))

    async def retry(row):
        row.wa_onboarding = {**row.wa_onboarding, "sync": {"history": {"status": "requested"}}}
        return wa_connect.public_onboarding(row)
    monkeypatch.setattr(wa_connect, "retry_coexistence_sync", retry)

    payment = await client.post(
        f"/branches/{branch.id}/whatsapp/connect/payment-confirmed", headers=owner,
    )
    assert payment.status_code == 200
    assert payment.json()["onboarding"]["payment_status"] == "confirmed"
    sync = await client.post(f"/branches/{branch.id}/whatsapp/connect/sync", headers=owner)
    assert sync.status_code == 200


@pytest.mark.asyncio
async def test_disconnect_unsubscribes_then_clears_all_local_state(db, client, monkeypatch):
    org, branch = await clinic(
        db, wa_status="connected", wa_waba_id="123", wa_phone_number_id="456",
        wa_token_enc=encrypt_secret("token"), wa_onboarding={"mode": "cloud_api"},
    )
    called = []
    async def unsubscribe(row): called.append(str(row.id)); return True
    monkeypatch.setattr(wa_connect, "unsubscribe_branch", unsubscribe)

    response = await client.delete(
        f"/branches/{branch.id}/whatsapp/connect",
        headers=auth(jwt_for(org_id=str(org.id))),
    )
    assert response.status_code == 200 and response.json()["meta_unsubscribed"] is True
    assert called == [str(branch.id)]
    fresh = (await db.execute(select(Branch).where(Branch.id == branch.id))).scalar_one()
    await db.refresh(fresh)
    assert fresh.wa_status == "disconnected"
    assert fresh.wa_waba_id is None and fresh.wa_token_enc is None
    assert fresh.wa_onboarding is None
