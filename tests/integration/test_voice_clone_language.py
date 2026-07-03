"""Voice cloning must send smallest.ai the ISO language CODE (prod 2026-07-03).

The router used the full language name ("telugu") — smallest's
/waves/v1/voice-cloning now 400s on names: 'Invalid language. Supported: en,
hi, mr, kn, ta, ... te, pt, pa, or'. The clone must go out with the branch's
ISO code (e.g. "te").
"""
import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.middleware.auth_middleware import get_current_user, CurrentUser
from backend.models.schema import Branch, Organization
from backend.services import smallest_voice


def _as_user(branch_id, org_id):
    return CurrentUser(
        user_id=str(uuid.uuid4()), email="o@c.com", role="org_admin",
        org_id=str(org_id), branch_ids=[str(branch_id)], is_admin=False,
        jti=str(uuid.uuid4()),
    )


@pytest.mark.asyncio
async def test_clone_sends_iso_code_not_language_name(db, monkeypatch):
    org_id = uuid.uuid4()
    db.add(Organization(id=org_id, name="Org", owner_phone="+919000099077",
                        owner_email=f"o-{org_id}@c.com", plan="clinic"))
    await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C",
                whatsapp_number="+910000000077", language="te")
    db.add(br)
    await db.commit()

    seen = {}

    def fake_clone(display_name, filename, audio_bytes, language="en", tag=None):
        seen["language"] = language
        return "voice_test123"

    monkeypatch.setattr(smallest_voice, "clone_voice", fake_clone)

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(
                f"/branches/{br.id}/voice-clone",
                data={"display_name": "sreelekha"},
                files={"file": ("sample.wav", b"RIFF0000WAVE", "audio/wav")},
            )
        assert r.status_code == 200, r.text
        assert seen["language"] == "te", (
            f"must send the ISO code, got {seen['language']!r}"
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_clone_explicit_language_choice_wins(db, monkeypatch):
    """The clinic can clone a sample spoken in a DIFFERENT language than the
    agent's (e.g. a Tamil sample for a te clinic) — the chosen code is sent."""
    org_id = uuid.uuid4()
    db.add(Organization(id=org_id, name="Org", owner_phone="+919000099078",
                        owner_email=f"o-{org_id}@c.com", plan="clinic"))
    await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C",
                whatsapp_number="+910000000078", language="te")
    db.add(br)
    await db.commit()

    seen = {}

    def fake_clone(display_name, filename, audio_bytes, language="en", tag=None):
        seen["language"] = language
        return "voice_test456"

    monkeypatch.setattr(smallest_voice, "clone_voice", fake_clone)
    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(
                f"/branches/{br.id}/voice-clone",
                data={"display_name": "sreelekha", "language": "ta"},
                files={"file": ("sample.wav", b"RIFF0000WAVE", "audio/wav")},
            )
            assert r.status_code == 200, r.text
            assert seen["language"] == "ta"

            bad = await ac.post(
                f"/branches/{br.id}/voice-clone",
                data={"display_name": "x", "language": "xx"},
                files={"file": ("sample.wav", b"RIFF0000WAVE", "audio/wav")},
            )
            assert bad.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_clone_registers_named_voice_visible_cross_language(db, monkeypatch):
    """An upload-clone must REGISTER the voice (name + language) so it shows in
    the picker — and a ta-sample clone must still be visible in the te picker
    (prod 2026-07-03: 'sreelekha speaking but shown nowhere')."""
    org_id = uuid.uuid4()
    db.add(Organization(id=org_id, name="Org", owner_phone="+919000099079",
                        owner_email=f"o-{org_id}@c.com", plan="clinic"))
    await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C",
                whatsapp_number="+910000000079", language="te")
    db.add(br)
    await db.commit()

    monkeypatch.setattr(
        smallest_voice, "clone_voice", lambda *a, **k: "voice_sree789"
    )
    monkeypatch.setattr(smallest_voice, "list_voices", lambda lang: [])

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(
                f"/branches/{br.id}/voice-clone",
                data={"display_name": "sreelekha", "language": "ta"},
                files={"file": ("sample.wav", b"RIFF0000WAVE", "audio/wav")},
            )
            assert r.status_code == 200, r.text

            v = await ac.get(f"/branches/{br.id}/voices", params={"language": "te"})
            assert v.status_code == 200, v.text
            entries = [x for x in v.json()["voices"] if x.get("cloned")]
            assert any(
                e["voice_id"] == "voice_sree789" and e["display_name"] == "sreelekha"
                for e in entries
            ), f"cloned voice not named/visible in the te picker: {entries}"
            assert v.json()["current"] == "voice_sree789"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
