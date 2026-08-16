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


async def test_clinic_can_keep_only_one_custom_voice(db, client, monkeypatch):
    branch, auth = await _clinic(db, "4")
    created_names = []

    async def create(**kwargs):
        created_names.append(kwargs["provider_name"])
        return _provider_voice(str(uuid.uuid4()), kwargs["provider_name"])

    monkeypatch.setattr(soniox_voice, "create_provider_voice", create)

    first = await client.post(
        f"/branches/{branch.id}/voice-clones", headers=auth,
        data={"name": "Reception voice", "consent_confirmed": "true"},
        files={"file": ("sample.webm", b"clean-audio", "audio/webm")},
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        f"/branches/{branch.id}/voice-clones", headers=auth,
        data={"name": "Replacement voice", "consent_confirmed": "true"},
        files={"file": ("replacement.webm", b"clean-audio", "audio/webm")},
    )
    assert second.status_code == 409
    assert "already has a custom voice" in second.json()["detail"]
    assert len(created_names) == 1

async def test_browser_recording_codec_mime_is_normalized(db, client, monkeypatch):
    branch, auth = await _clinic(db, "5")
    received = {}

    async def create(**kwargs):
        received.update(kwargs)
        return _provider_voice(str(uuid.uuid4()), kwargs["provider_name"])

    monkeypatch.setattr(soniox_voice, "create_provider_voice", create)
    response = await client.post(
        f"/branches/{branch.id}/voice-clones",
        headers=auth,
        data={"name": "Browser recording", "consent_confirmed": "true"},
        files={
            "file": (
                "recording.webm",
                b"webm-opus-audio",
                "audio/webm;codecs=opus",
            )
        },
    )

    assert response.status_code == 201, response.text
    assert received["content_type"] == "audio/webm"
    assert received["audio"] == b"webm-opus-audio"


async def test_existing_soniox_voice_id_is_verified_and_tenant_owned(
    db, client, monkeypatch
):
    branch_a, auth_a = await _clinic(db, "6")
    branch_b, auth_b = await _clinic(db, "7")
    provider_id = str(uuid.uuid4())
    provider = _provider_voice(provider_id, "existing-provider-voice")

    async def list_all():
        return [provider]

    monkeypatch.setattr(soniox_voice, "list_provider_voices", list_all)

    missing_consent = await client.post(
        f"/branches/{branch_a.id}/voice-clones/import",
        headers=auth_a,
        json={
            "name": "Imported voice",
            "voice_id": provider_id,
            "consent_confirmed": False,
        },
    )
    assert missing_consent.status_code == 422

    missing_provider = await client.post(
        f"/branches/{branch_a.id}/voice-clones/import",
        headers=auth_a,
        json={
            "name": "Imported voice",
            "voice_id": str(uuid.uuid4()),
            "consent_confirmed": True,
        },
    )
    assert missing_provider.status_code == 404

    connected = await client.post(
        f"/branches/{branch_a.id}/voice-clones/import",
        headers=auth_a,
        json={
            "name": "Imported voice",
            "voice_id": provider_id,
            "consent_confirmed": True,
        },
    )
    assert connected.status_code == 201, connected.text
    assert connected.json()["voice_id"] == provider_id
    assert connected.json()["status"] == "ready"

    cross_tenant = await client.post(
        f"/branches/{branch_b.id}/voice-clones/import",
        headers=auth_b,
        json={
            "name": "Stolen voice",
            "voice_id": provider_id,
            "consent_confirmed": True,
        },
    )
    assert cross_tenant.status_code == 409
    assert "already connected" in cross_tenant.json()["detail"]

    own = await client.get(f"/branches/{branch_a.id}/voice-clones", headers=auth_a)
    foreign = await client.get(f"/branches/{branch_b.id}/voice-clones", headers=auth_b)
    assert [item["voice_id"] for item in own.json()["voices"]] == [provider_id]
    assert foreign.json()["voices"] == []


async def test_first_ten_clinics_claim_permanent_custom_voice_access(
    db, client, monkeypatch
):
    # Nine existing members leave exactly one launch slot. Merely creating an
    # org/branch does not claim it.
    for index in range(9):
        await _clinic(db, f"launch-{index}")
    orgs = (await db.execute(select(Organization).where(Organization.name.like("Voice Org launch-%")))).scalars().all()
    for org in orgs:
        org.custom_voice_member = True
        org.custom_voice_granted_at = datetime.now(timezone.utc)
    await db.commit()

    tenth, tenth_auth = await _clinic(db, "tenth")
    eleventh, eleventh_auth = await _clinic(db, "eleventh")
    provider_calls = []

    async def create(**kwargs):
        provider_calls.append(kwargs["provider_name"])
        return _provider_voice(str(uuid.uuid4()), kwargs["provider_name"])

    monkeypatch.setattr(soniox_voice, "create_provider_voice", create)
    tenth_response = await client.post(
        f"/branches/{tenth.id}/voice-clones", headers=tenth_auth,
        data={"name": "Tenth clinic voice", "consent_confirmed": "true"},
        files={"file": ("sample.webm", b"clean-audio", "audio/webm")},
    )
    assert tenth_response.status_code == 201, tenth_response.text

    denied = await client.post(
        f"/branches/{eleventh.id}/voice-clones", headers=eleventh_auth,
        data={"name": "Eleventh clinic voice", "consent_confirmed": "true"},
        files={"file": ("sample.webm", b"clean-audio", "audio/webm")},
    )
    assert denied.status_code == 409
    assert "first-10 custom voice offer is full" in denied.json()["detail"]
    assert len(provider_calls) == 1

    tenth_org = await db.get(Organization, tenth.org_id)
    assert tenth_org.custom_voice_member is True
    availability = await client.get(f"/branches/{eleventh.id}/voice-clones", headers=eleventh_auth)
    assert availability.status_code == 200
    assert availability.json()["custom_voice_available"] is False
    assert availability.json()["custom_voice_slots_left"] == 0


async def test_provider_configuration_failure_does_not_consume_launch_slot(
    db, client, monkeypatch
):
    branch, auth = await _clinic(db, "config")
    org_id = branch.org_id

    async def fail(**_kwargs):
        raise soniox_voice.SonioxVoiceError(
            503, "not_configured", "Voice cloning is not configured"
        )

    monkeypatch.setattr(soniox_voice, "create_provider_voice", fail)
    response = await client.post(
        f"/branches/{branch.id}/voice-clones", headers=auth,
        data={"name": "Retry later", "consent_confirmed": "true"},
        files={"file": ("sample.webm", b"clean-audio", "audio/webm")},
    )
    assert response.status_code == 503
    db.expire_all()
    org = await db.get(Organization, org_id)
    assert org.custom_voice_member is False
    assert org.custom_voice_granted_at is None
