"""End-to-end proof for tenant-safe, consent-gated Soniox voice cloning."""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.config import settings
from backend.models.schema import Branch, BranchVoice, Organization, User
from backend.services import soniox_voice

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _bypass_rate_limit(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_BYPASS_IPS", "testclient")


@pytest_asyncio.fixture
async def client(redis, db):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _clinic(db, suffix: str):
    org = Organization(
        name=f"Voice Org {suffix}", owner_phone=f"+91900000{suffix:0>4}",
        owner_email=f"voice-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
        plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name=f"Voice Clinic {suffix}",
        whatsapp_number=f"+9188{str(uuid.uuid4().int)[:8]}", status="active",
        language="te",
    )
    user = User(
        org_id=org.id, email=f"owner-{suffix}-{uuid.uuid4().hex[:6]}@test.com",
        name=f"Owner {suffix}", role="org_admin", branch_ids=[str(branch.id)],
        is_admin=False,
    )
    db.add_all([branch, user])
    await db.commit()
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(user.id), "email": user.email, "role": "org_admin",
            "org_id": str(org.id), "branch_ids": [str(branch.id)], "is_admin": False,
            "iat": int(now.timestamp()), "exp": int((now + timedelta(hours=8)).timestamp()),
            "jti": str(uuid.uuid4()), "tv": 0,
        },
        settings.jwt_secret, algorithm="HS256",
    )
    return branch, {"Authorization": f"Bearer {token}"}


def _provider_voice(provider_id: str, provider_name: str):
    return {
        "id": provider_id, "name": provider_name, "filename": "sample.webm",
        "created_at": "2026-08-10T10:00:00Z",
        "models": [{"model": "tts-rt-v1", "status": "ready", "error_type": None, "error_message": None}],
    }


async def test_clone_is_consent_gated_tenant_isolated_and_drives_calls(
    db, client, monkeypatch
):
    branch_a, auth_a = await _clinic(db, "1")
    branch_b, auth_b = await _clinic(db, "2")
    branch_a_id = branch_a.id
    branch_b_id = branch_b.id
    provider_id = str(uuid.uuid4())
    provider_items = []
    deleted = []

    async def create(**kwargs):
        voice = _provider_voice(provider_id, kwargs["provider_name"])
        provider_items.append(voice)
        return voice

    async def list_all():
        # The provider inventory is project-wide; the API must still return
        # only rows locally owned by the requesting branch.
        return provider_items + [_provider_voice(str(uuid.uuid4()), "other-customer")]

    async def preview(**kwargs):
        assert kwargs["provider_voice_id"] == provider_id
        return b"ID3-test-audio", "audio/mpeg"

    async def remove(voice_id):
        deleted.append(voice_id)

    monkeypatch.setattr(soniox_voice, "create_provider_voice", create)
    monkeypatch.setattr(soniox_voice, "list_provider_voices", list_all)
    monkeypatch.setattr(soniox_voice, "preview_voice", preview)
    monkeypatch.setattr(soniox_voice, "delete_provider_voice", remove)

    denied = await client.post(
        f"/branches/{branch_a_id}/voice-clones", headers=auth_a,
        data={"name": "Clinic voice", "consent_confirmed": "false"},
        files={"file": ("sample.webm", b"audio", "audio/webm")},
    )
    assert denied.status_code == 422
    assert provider_items == []

    created = await client.post(
        f"/branches/{branch_a_id}/voice-clones", headers=auth_a,
        data={"name": "Clinic voice", "consent_confirmed": "true"},
        files={"file": ("sample.webm", b"clean-audio", "audio/webm")},
    )
    assert created.status_code == 201, created.text
    clone = created.json()
    assert clone["status"] == "ready"
    assert clone["voice_id"] == provider_id

    own = await client.get(f"/branches/{branch_a_id}/voice-clones", headers=auth_a)
    foreign = await client.get(f"/branches/{branch_b_id}/voice-clones", headers=auth_b)
    assert [item["name"] for item in own.json()["voices"]] == ["Clinic voice"]
    assert foreign.json()["voices"] == []

    leak_attempt = await client.post(
        f"/branches/{branch_b_id}/voice-clones/{clone['id']}/preview", headers=auth_b
    )
    assert leak_attempt.status_code == 404
    cross_activate = await client.patch(
        f"/branches/{branch_b_id}/voice", headers=auth_b, json={"tts_voice": provider_id}
    )
    assert cross_activate.status_code == 422

    activated = await client.post(
        f"/branches/{branch_a_id}/voice-clones/{clone['id']}/activate", headers=auth_a
    )
    assert activated.status_code == 200
    db.expire_all()
    assert (await db.get(Branch, branch_a_id)).tts_voice == provider_id

    sample = await client.post(
        f"/branches/{branch_a_id}/voice-clones/{clone['id']}/preview", headers=auth_a
    )
    assert sample.status_code == 200
    assert sample.content == b"ID3-test-audio"
    assert sample.headers["cache-control"] == "private, no-store"

    removed = await client.delete(
        f"/branches/{branch_a_id}/voice-clones/{clone['id']}", headers=auth_a
    )
    assert removed.status_code == 200
    assert deleted == [provider_id]
    db.expire_all()
    assert (await db.get(Branch, branch_a_id)).tts_voice == settings.soniox_tts_default_voice
    assert (
        await db.execute(select(BranchVoice).where(BranchVoice.branch_id == branch_a_id))
    ).scalar_one_or_none() is None


async def test_clone_rejects_oversized_audio_before_provider(db, client, monkeypatch):
    branch, auth = await _clinic(db, "3")
    called = False

    async def create(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(soniox_voice, "create_provider_voice", create)
    response = await client.post(
        f"/branches/{branch.id}/voice-clones", headers=auth,
        data={"name": "Too long", "consent_confirmed": "true"},
        files={"file": ("huge.wav", b"x" * (soniox_voice.MAX_CLIP_BYTES + 1), "audio/wav")},
    )
    assert response.status_code == 413
    assert called is False
