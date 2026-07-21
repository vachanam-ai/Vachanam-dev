"""Chat auto-logs one ticket per session (ai_resolved vs open), org-aware."""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
import jwt
from sqlalchemy import select

from backend.config import settings

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app
    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _stub_bot(monkeypatch):
    from backend.services import support_bot

    async def fake(question, history, audience, plan=None):
        if "stuck" in question:
            return {"answer": "not sure, team will follow up", "answered": False}
        return {"answer": "Starter is 5,999.", "answered": True}

    monkeypatch.setattr(support_bot, "answer", fake)


async def test_public_chat_answers_and_logs_ai_resolved(client, db):
    from backend.models.schema import SupportTicket
    r = await client.post("/support/chat", json={"question": "cost of starter?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answered"] is True and "5,999" in body["answer"]
    tid = uuid.UUID(body["ticket_id"])
    row = (await db.execute(select(SupportTicket).where(SupportTicket.id == tid))).scalar_one()
    assert row.status == "ai_resolved"
    assert row.org_id is None  # public


async def test_unanswered_chat_logs_open_ticket(client, db):
    from backend.models.schema import SupportTicket
    r = await client.post("/support/chat", json={"question": "I am stuck, help"})
    tid = uuid.UUID(r.json()["ticket_id"])
    row = (await db.execute(select(SupportTicket).where(SupportTicket.id == tid))).scalar_one()
    assert row.status == "open"


async def test_authed_chat_ticket_carries_org(client, db):
    from backend.models.schema import Organization, SupportTicket
    org = Organization(name="C", owner_phone="", owner_email=f"{uuid.uuid4().hex}@t.com",
                       plan="clinic", status="active")
    db.add(org)
    await db.commit()
    now = datetime.now(timezone.utc)
    tok = jwt.encode({"sub": str(uuid.uuid4()), "email": "o@t.com", "role": "org_admin",
                      "org_id": str(org.id), "branch_ids": [], "is_admin": False,
                      "iat": int(now.timestamp()),
                      "exp": int((now + timedelta(hours=8)).timestamp()),
                      "jti": str(uuid.uuid4())}, settings.jwt_secret, algorithm="HS256")
    r = await client.post("/support/chat", json={"question": "cost?"},
                          headers={"Authorization": f"Bearer {tok}"})
    tid = uuid.UUID(r.json()["ticket_id"])
    row = (await db.execute(select(SupportTicket).where(SupportTicket.id == tid))).scalar_one()
    assert str(row.org_id) == str(org.id)
    assert row.source == "in_app"


async def test_chat_question_length_capped(client):
    r = await client.post("/support/chat", json={"question": "x" * 5000})
    assert r.status_code == 422


async def test_kb_public_subset(client):
    r = await client.get("/support/kb")
    assert r.status_code == 200
    assert "Connecting your phone number" not in r.text  # clinic-only stays out


async def test_authed_chat_works_without_turnstile_token(client, db, monkeypatch):
    """Regression: a logged-in user's client never attaches a Turnstile token —
    with Turnstile ENFORCED, an authed chat must still succeed (Turnstile is
    anonymous-only); an anonymous chat with no token must 403."""
    from backend.config import settings
    from backend.models.schema import Organization
    from backend.routers import support
    monkeypatch.setattr(settings, "turnstile_secret_key", "enforced", raising=False)

    async def token_required(token, _ip):
        return bool(token)

    monkeypatch.setattr(support, "verify_turnstile", token_required)

    org = Organization(name="C", owner_phone="", owner_email=f"{uuid.uuid4().hex}@t.com",
                       plan="clinic", status="active")
    db.add(org)
    await db.commit()
    now = datetime.now(timezone.utc)
    tok = jwt.encode({"sub": str(uuid.uuid4()), "email": "o@t.com", "role": "org_admin",
                      "org_id": str(org.id), "branch_ids": [], "is_admin": False,
                      "iat": int(now.timestamp()),
                      "exp": int((now + timedelta(hours=8)).timestamp()),
                      "jti": str(uuid.uuid4())}, settings.jwt_secret, algorithm="HS256")
    r = await client.post("/support/chat", json={"question": "cost?"},
                          headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200  # authed → Turnstile skipped

    r = await client.post("/support/chat", json={"question": "cost?"})  # anon, no token
    assert r.status_code == 403  # anonymous must pass Turnstile


async def test_team_emailed_once_only_for_new_unanswered_ticket(client, db, monkeypatch):
    """Resend-quota policy: a NEW ticket the AI couldn't answer emails the team
    exactly once; an AI-resolved chat emails nobody."""
    from backend.services import support_email
    calls = []

    async def fake_notify(ticket_id, subject, from_email):
        calls.append(str(ticket_id))

    monkeypatch.setattr(support_email, "notify_new_ticket", fake_notify)

    # answered → ai_resolved → NO email
    r = await client.post("/support/chat", json={"question": "cost of starter?"})
    assert r.json()["answered"] is True
    assert calls == []

    # unanswered → open → exactly ONE email
    r = await client.post("/support/chat", json={"question": "I am stuck, help"})
    tid = r.json()["ticket_id"]
    assert calls == [tid]

    # a follow-up turn in the SAME ticket → still just one email (not new)
    await client.post("/support/chat", json={"question": "still stuck", "ticket_id": tid})
    assert calls == [tid]
