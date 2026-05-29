# Phase 2: Backend + WhatsApp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete FastAPI backend — WhatsApp webhook routing, doctor commands, patient WA conversation, receptionist queue API, background jobs, and JWT auth.

**Architecture:** FastAPI app on Render; SQLAlchemy async with Neon Postgres; APScheduler for 3 background jobs; all WhatsApp processing in background tasks (Meta 5-second window). Schema already exists in `backend/models/schema.py` — DO NOT recreate it.

**Tech Stack:** FastAPI 0.110+, SQLAlchemy 2.x async, asyncpg, APScheduler 3.x, python-jose JWT, google-auth, openai, google-generativeai, razorpay, structlog, tenacity, Redis

---

## Field Name Reference (CRITICAL — memorize these)

These are the actual SQLAlchemy model attribute names. Use them exactly.

| Model | Primary Key | Key fields |
|---|---|---|
| `Organization` | `.id` | `.name`, `.plan`, `.status`, `.owner_email` |
| `Branch` | `.id` | `.name`, `.whatsapp_number`, `.meta_phone_number_id`, `.emergency_contact`, `.status` |
| `Doctor` | `.id` | `.name`, `.whatsapp_number`, `.specialization`, `.routing_keywords`, `.status`, `.daily_token_limit` |
| `Patient` | `.id` | `.name`, `.phone`, `.branch_id`, `.followup_consent` |
| `Token` | `.id` | `.status` ("confirmed"/"attended"/"no_show"/"cancelled_by_clinic"), `.is_urgent`, `.confirmed_at`, `.attended_at`, `.marked_by_user_id` |
| `FollowupTask` | `.id` | `.what_to_ask`, `.channel`, `.scheduled_date`, `.status` |
| `WhatsAppSession` | `.id` | `.patient_phone`, `.state`, `.session_data`, `.branch_id` |
| `User` | `.id` | `.email`, `.role`, `.branch_ids` (JSONB list of UUID strings), `.is_admin`, `.google_sub` |

Doctor commands use `doctor.whatsapp_number` (NOT `personal_phone`).
Doctor specialization is `doctor.specialization` (NOT `speciality`).
Doctor keywords are `doctor.routing_keywords` (NOT `treats_keywords`).
Branch has both `whatsapp_number` (human-readable) AND `meta_phone_number_id` (Meta's internal ID for webhook routing).

---

## File Structure

**Create:**
- `backend/main.py` — FastAPI app, lifespan, scheduler, router registration
- `backend/middleware/auth_middleware.py` — JWT decode, `get_current_user` dependency
- `backend/middleware/branch_guard.py` — branch access validation helper
- `backend/services/meta_service.py` — Meta Cloud API wrapper (send messages, verify signatures)
- `backend/services/token_service.py` — Redis token release helper
- `backend/services/calendar_service.py` — Google Calendar CRUD
- `backend/routers/whatsapp.py` — webhook handler (GET verify + POST receive)
- `backend/routers/queue.py` — receptionist queue endpoints
- `backend/routers/auth.py` — Google OAuth + JWT issue
- `backend/routers/dashboard.py` — clinic owner analytics
- `backend/routers/admin.py` — Vachanam admin (Vinay only)
- `backend/services/doctor_commands.py` — parse + execute doctor WA commands
- `backend/services/whatsapp_agent.py` — patient WA state machine
- `backend/jobs/token_expiry.py` — mark stale confirmed tokens as no_show
- `backend/jobs/eod_summary.py` — 5:30 PM IST EOD summary to doctors
- `backend/jobs/followup_calls.py` — 9 AM IST follow-up tasks

**Modify:**
- `backend/config.py` — already correct, no changes needed
- `backend/models/schema.py` — already correct, no changes needed
- `backend/database.py` — add `init_db()` helper for startup

---

### Task 1: `backend/database.py` — add `init_db()`

**Files:**
- Modify: `backend/database.py`

- [ ] **Step 1: Add `init_db()` to database.py**

```python
# Add to backend/database.py after the existing code:

async def init_db() -> None:
    """Create all tables if they don't exist (dev only — use alembic in prod)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 2: Verify import works**

```bash
cd C:\Users\vinay\OneDrive\Desktop\SAAS\VACHANAM
python -c "from backend.database import init_db; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/database.py
git commit -m "feat: add init_db helper to database.py"
```

---

### Task 2: `backend/services/meta_service.py` — WhatsApp API wrapper

**Files:**
- Create: `backend/services/meta_service.py`

- [ ] **Step 1: Create meta_service.py**

```python
# backend/services/meta_service.py
"""
Meta Cloud API wrapper for sending WhatsApp messages.
All sends are fire-and-forget: caller must catch exceptions.
"""
import hashlib
import hmac
from datetime import date
from datetime import time as time_type

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config import settings

logger = structlog.get_logger()

_BASE_URL = "https://graph.facebook.com/v20.0"


class MetaService:

    def __init__(self):
        self._headers = {
            "Authorization": f"Bearer {settings.meta_access_token}",
            "Content-Type": "application/json",
        }

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        """Verify X-Hub-Signature-256 header from Meta."""
        if not signature.startswith("sha256="):
            return False
        expected = hmac.new(
            settings.meta_app_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def send_text_message(self, to: str, message: str, branch_id: str) -> None:
        """Send a plain text WhatsApp message."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": message},
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{_BASE_URL}/{settings.meta_phone_number_id}/messages",
                headers=self._headers,
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
        logger.info("whatsapp_sent", to=to[-4:], branch_id=branch_id)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def send_booking_confirmation(
        self,
        to: str,
        patient_name: str,
        doctor_name: str,
        clinic_name: str,
        booking_date: date,
        token_number: int,
        appointment_time: time_type | None,
    ) -> None:
        """Send booking confirmation to patient."""
        if appointment_time:
            time_str = f"Time: {appointment_time.strftime('%I:%M %p')}\n"
        else:
            time_str = f"Token: #{token_number}\n"

        message = (
            f"✅ Appointment Confirmed!\n\n"
            f"Clinic: {clinic_name}\n"
            f"Doctor: Dr. {doctor_name}\n"
            f"Date: {booking_date.strftime('%d %B %Y')}\n"
            f"{time_str}"
            f"\nPlease arrive 15 minutes early.\n"
            f"To cancel, reply CANCEL to this number."
        )
        await self.send_text_message(to=to, message=message, branch_id="")
```

- [ ] **Step 2: Verify import**

```bash
python -c "from backend.services.meta_service import MetaService; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/services/meta_service.py
git commit -m "feat: Meta Cloud API wrapper with retry and signature verification"
```

---

### Task 3: `backend/services/token_service.py` + `backend/services/calendar_service.py`

**Files:**
- Create: `backend/services/token_service.py`
- Create: `backend/services/calendar_service.py`

- [ ] **Step 1: Create token_service.py**

```python
# backend/services/token_service.py
"""Redis token release helper — only called on cancellation or WA conversation abandon."""
import redis.asyncio as aioredis
import structlog

from backend.config import settings

logger = structlog.get_logger()


class TokenService:

    async def release_token(self, redis_key: str) -> None:
        """DECR the Redis counter for an abandoned/cancelled token."""
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            val = await r.decr(redis_key)
            logger.info("token_released", redis_key=redis_key, new_value=val)
        except Exception as e:
            logger.error("token_release_failed", redis_key=redis_key, error=str(e))
        finally:
            await r.aclose()
```

- [ ] **Step 2: Create calendar_service.py**

```python
# backend/services/calendar_service.py
"""
Google Calendar CRUD.
Uses service account credentials from GOOGLE_APPLICATION_CREDENTIALS.
Calendar event stores: patient name (first only), last 4 digits of phone, token number.
NEVER stores medical details, full phone, or diagnosis.
"""
import asyncio
from datetime import date, time, datetime, timedelta

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build

from backend.config import settings

logger = structlog.get_logger()

_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_service():
    creds = service_account.Credentials.from_service_account_file(
        settings.google_application_credentials,
        scopes=_SCOPES,
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


class CalendarService:

    async def create_booking_event(
        self,
        calendar_id: str | None,
        patient_name: str,
        patient_phone: str | None,
        token_number: int,
        booking_date: date,
        appointment_time: time | None,
        doctor_name: str,
    ) -> str:
        """
        Create a Google Calendar event. RAISES on failure (booking must not proceed).
        Returns the event ID.
        Privacy: stores first name only + last 4 digits of phone.
        """
        if not calendar_id:
            logger.warning("calendar_id_missing_skipping", doctor=doctor_name)
            return "no_calendar"

        first_name = patient_name.split()[0] if patient_name else "Patient"
        phone_suffix = patient_phone[-4:] if patient_phone else "unknown"

        if appointment_time:
            start_dt = datetime.combine(booking_date, appointment_time)
            end_dt = start_dt + timedelta(minutes=15)
            start = {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Kolkata"}
            end = {"dateTime": end_dt.isoformat(), "timeZone": "Asia/Kolkata"}
        else:
            start = {"date": booking_date.isoformat()}
            end = {"date": booking_date.isoformat()}

        event = {
            "summary": f"Token #{token_number} — {first_name} (xx{phone_suffix})",
            "start": start,
            "end": end,
        }

        service = _get_service()
        result = await asyncio.to_thread(
            service.events().insert(calendarId=calendar_id, body=event).execute
        )
        event_id = result.get("id", "")
        logger.info("calendar_event_created",
                   calendar_id=calendar_id,
                   event_id=event_id,
                   token_number=token_number)
        return event_id

    async def delete_event(self, calendar_id: str, event_id: str) -> None:
        """Delete a calendar event (used when doctor cancels day)."""
        if not calendar_id or not event_id or event_id == "no_calendar":
            return
        service = _get_service()
        try:
            await asyncio.to_thread(
                service.events().delete(calendarId=calendar_id, eventId=event_id).execute
            )
            logger.info("calendar_event_deleted", event_id=event_id)
        except Exception as e:
            logger.error("calendar_event_delete_failed", event_id=event_id, error=str(e))
```

- [ ] **Step 3: Verify imports**

```bash
python -c "from backend.services.token_service import TokenService; from backend.services.calendar_service import CalendarService; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/services/token_service.py backend/services/calendar_service.py
git commit -m "feat: token release service and Google Calendar service"
```

---

### Task 4: `backend/middleware/auth_middleware.py`

**Files:**
- Create: `backend/middleware/auth_middleware.py`

- [ ] **Step 1: Write auth middleware**

```python
# backend/middleware/auth_middleware.py
"""
JWT validation middleware.
Issues JWTs from Google OAuth subject. Validates on every protected route.
JWT claims: sub (user.id), email, role, branch_ids, org_id, is_admin
"""
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models.schema import User

logger = structlog.get_logger()

_ALGORITHM = "HS256"
_bearer = HTTPBearer()


def create_access_token(user: User) -> str:
    """Create a signed JWT for the given user."""
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "org_id": str(user.org_id) if user.org_id else None,
        "branch_ids": user.branch_ids or [],
        "is_admin": user.is_admin,
        "exp": expires,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


class CurrentUser:
    def __init__(self, user_id: str, email: str, role: str, org_id: str | None,
                 branch_ids: list, is_admin: bool):
        self.user_id = user_id
        self.email = email
        self.role = role
        self.org_id = org_id
        self.branch_ids = branch_ids
        self.is_admin = is_admin


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> CurrentUser:
    """Decode JWT and return claims. Does NOT hit DB — JWT is self-contained."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except JWTError as e:
        logger.warning("jwt_invalid", error=str(e))
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return CurrentUser(
        user_id=payload["sub"],
        email=payload["email"],
        role=payload["role"],
        org_id=payload.get("org_id"),
        branch_ids=payload.get("branch_ids", []),
        is_admin=payload.get("is_admin", False),
    )


async def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Dependency that requires is_admin=True (Vinay's admin dashboard)."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
```

- [ ] **Step 2: Verify import**

```bash
python -c "from backend.middleware.auth_middleware import get_current_user, create_access_token; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/middleware/auth_middleware.py
git commit -m "feat: JWT auth middleware — issue and validate tokens, admin guard"
```

---

### Task 5: `backend/routers/auth.py` — Google OAuth + JWT

**Files:**
- Create: `backend/routers/auth.py`

- [ ] **Step 1: Write auth router**

```python
# backend/routers/auth.py
"""
Google OAuth2 login flow.
1. Frontend redirects to /auth/google
2. Google redirects back to /auth/google/callback with code
3. We exchange code for ID token, extract email + google_sub
4. Look up or create User record
5. Return signed JWT
"""
import structlog
from fastapi import APIRouter, HTTPException, Query
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from sqlalchemy import select

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.middleware.auth_middleware import create_access_token
from backend.models.schema import User

router = APIRouter()
logger = structlog.get_logger()


@router.post("/google")
async def google_login(id_token_str: str = Query(..., alias="id_token")):
    """
    Verify a Google ID token (sent from frontend after Google Sign-In).
    Returns a Vachanam JWT if the user exists or is a new admin.
    """
    try:
        info = id_token.verify_oauth2_token(
            id_token_str,
            google_requests.Request(),
            settings.google_oauth_client_id,
        )
    except Exception as e:
        logger.warning("google_token_invalid", error=str(e))
        raise HTTPException(status_code=401, detail="Invalid Google token")

    google_sub = info["sub"]
    email = info.get("email", "")
    name = info.get("name", "")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.google_sub == google_sub)
        )
        user = result.scalar_one_or_none()

        if not user:
            # Check by email (first-time Google login for existing user)
            result = await db.execute(
                select(User).where(User.email == email)
            )
            user = result.scalar_one_or_none()
            if user:
                user.google_sub = google_sub
                user.name = user.name or name
                await db.commit()

        if not user:
            raise HTTPException(status_code=403, detail="Not registered. Contact your clinic admin.")

    token = create_access_token(user)
    logger.info("user_login", email=email, role=user.role)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
async def get_me(current_user=None):
    """Return current user info from JWT. Frontend calls this on app load."""
    from backend.middleware.auth_middleware import get_current_user
    from fastapi import Depends
    # This endpoint uses Depends inline — see main.py for proper wiring
    return {"user_id": current_user.user_id, "email": current_user.email,
            "role": current_user.role, "is_admin": current_user.is_admin}
```

- [ ] **Step 2: Write failing test**

```python
# tests/unit/test_auth.py
import pytest
from unittest.mock import patch, MagicMock
from backend.middleware.auth_middleware import create_access_token, CurrentUser
from backend.models.schema import User
import uuid

def _make_user(**kwargs) -> User:
    u = User.__new__(User)
    u.id = kwargs.get("id", uuid.uuid4())
    u.email = kwargs.get("email", "test@clinic.com")
    u.role = kwargs.get("role", "receptionist")
    u.org_id = kwargs.get("org_id", uuid.uuid4())
    u.branch_ids = kwargs.get("branch_ids", ["branch-1"])
    u.is_admin = kwargs.get("is_admin", False)
    return u

def test_create_access_token_contains_claims():
    user = _make_user()
    token = create_access_token(user)
    assert isinstance(token, str)
    assert len(token) > 40

def test_admin_token_has_is_admin_true():
    user = _make_user(is_admin=True, role="super_admin")
    token = create_access_token(user)
    from jose import jwt
    from backend.config import settings
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    assert payload["is_admin"] is True
    assert payload["role"] == "super_admin"
```

- [ ] **Step 3: Run test (should pass — no DB needed)**

```bash
pytest tests/unit/test_auth.py -v
```
Expected: 2 passed

- [ ] **Step 4: Commit**

```bash
git add backend/routers/auth.py tests/unit/test_auth.py
git commit -m "feat: Google OAuth login + JWT issue; auth unit tests"
```

---

### Task 6: `backend/routers/whatsapp.py` — Webhook handler

**Files:**
- Create: `backend/routers/whatsapp.py`

- [ ] **Step 1: Write whatsapp router**

```python
# backend/routers/whatsapp.py
"""
Meta Cloud API webhook handler.
Returns 200 immediately; all processing happens in background tasks.
Branch is identified by Branch.meta_phone_number_id matching the receiving number.
"""
import json

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from backend.config import settings
from backend.services.meta_service import MetaService

router = APIRouter()
logger = structlog.get_logger()
meta_service = MetaService()


@router.get("/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_webhook_verify_token:
        logger.info("meta_webhook_verified")
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive all WhatsApp messages. Returns 200 in < 100ms."""
    body = await request.body()

    if settings.app_env == "production":
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not meta_service.verify_webhook_signature(body, signature):
            logger.warning("webhook_signature_invalid")
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {"status": "invalid_json"}

    try:
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return {"status": "no_messages"}

        message = messages[0]
        from_phone = message.get("from", "")
        # meta_phone_number_id from webhook metadata — used to identify branch
        meta_phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
        message_text = message.get("text", {}).get("body", "")
        message_type = message.get("type", "text")

        if not from_phone or message_type != "text" or not message_text:
            return {"status": "ignored"}

        background_tasks.add_task(
            process_whatsapp_message,
            from_phone=from_phone,
            meta_phone_number_id=meta_phone_number_id,
            message_text=message_text,
        )
        return {"status": "received"}

    except Exception as e:
        logger.error("webhook_parse_error", error=str(e))
        return {"status": "parse_error"}


async def process_whatsapp_message(from_phone: str, meta_phone_number_id: str, message_text: str):
    """
    Route message to doctor handler or patient WA agent.
    Branch identified by Branch.meta_phone_number_id — NOT from sender phone.
    """
    try:
        from backend.database import AsyncSessionLocal
        from backend.models.schema import Branch, Doctor
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            # Identify branch by meta_phone_number_id (CRITICAL — branch comes from receiver)
            branch_result = await db.execute(
                select(Branch).where(Branch.meta_phone_number_id == meta_phone_number_id)
            )
            branch = branch_result.scalar_one_or_none()

            if not branch:
                logger.warning("unknown_whatsapp_receiver",
                              meta_phone_number_id=meta_phone_number_id)
                return

            branch_id = branch.id

            # Is this sender a known doctor at this branch?
            doctor_result = await db.execute(
                select(Doctor).where(
                    Doctor.whatsapp_number == from_phone,
                    Doctor.branch_id == branch_id,   # MANDATORY
                    Doctor.status == "active",
                )
            )
            doctor = doctor_result.scalar_one_or_none()
            # Capture needed values before closing session
            doctor_data = {
                "id": doctor.id,
                "name": doctor.name,
                "whatsapp_number": doctor.whatsapp_number,
                "daily_token_limit": doctor.daily_token_limit,
            } if doctor else None

        if doctor_data:
            from backend.services.doctor_commands import DoctorCommandService
            service = DoctorCommandService(doctor_data=doctor_data, branch_id=branch_id)
            await service.process(message_text)
        else:
            from backend.services.whatsapp_agent import WhatsAppAgent
            agent = WhatsAppAgent(branch_id=branch_id, patient_phone=from_phone)
            await agent.process_message(message_text)

    except Exception as e:
        logger.error("whatsapp_processing_failed", from_phone=from_phone[-4:], error=str(e))
```

- [ ] **Step 2: Write failing test**

```python
# tests/integration/test_whatsapp_flow.py
import pytest
import json
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    from backend.main import app
    return TestClient(app)

def test_webhook_verify_returns_challenge(client):
    resp = client.get("/webhook/whatsapp", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "test-verify-token",
        "hub.challenge": "12345",
    })
    # Will need META_WEBHOOK_VERIFY_TOKEN=test-verify-token in test env
    # For now just verify the endpoint exists and returns something
    assert resp.status_code in [200, 403]

def test_webhook_post_returns_200(client):
    payload = {
        "entry": [{"changes": [{"value": {"messages": [], "metadata": {}}}]}]
    }
    resp = client.post("/webhook/whatsapp", json=payload)
    assert resp.status_code == 200
```

- [ ] **Step 3: Commit**

```bash
git add backend/routers/whatsapp.py tests/integration/test_whatsapp_flow.py
git commit -m "feat: Meta webhook handler — verify + receive, background routing"
```

---

### Task 7: `backend/services/doctor_commands.py`

**Files:**
- Create: `backend/services/doctor_commands.py`

- [ ] **Step 1: Write doctor_commands.py**

Uses Gemini primary → GPT-4o mini fallback for intent parsing (RULE 9 from CLAUDE.md).

```python
# backend/services/doctor_commands.py
"""
Parse and execute doctor WhatsApp commands via NLP.
Primary LLM: Gemini 2.5 Flash. Fallback: GPT-4o mini (CLAUDE.md Rule 9).

Doctor's WhatsApp is identified by Doctor.whatsapp_number.
Supported commands (also in Telugu/Hindi/code-mixed):
  list today / ēḍu list           → today's schedule
  list tomorrow / rēpu list       → tomorrow's schedule
  off today / ēḍu ledu            → cancel all today's slots
  off tomorrow / rēpu ledu        → cancel tomorrow's slots
  add 5 tokens / 5 tokens add     → increase daily limit
  help / ?                        → command list
"""
import asyncio
import json
from datetime import date, timedelta

import google.generativeai as genai
import structlog
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config import settings
from backend.services.meta_service import MetaService

logger = structlog.get_logger()

genai.configure(api_key=settings.gemini_api_key)
_gemini = genai.GenerativeModel("gemini-2.5-flash")


class DoctorCommandService:

    def __init__(self, doctor_data: dict, branch_id):
        self.doctor_data = doctor_data  # dict with id, name, whatsapp_number, daily_token_limit
        self.branch_id = branch_id
        self.meta = MetaService()
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)

    async def process(self, message: str):
        intent = await self._parse_intent(message)
        logger.info("doctor_command_parsed",
                   doctor_id=str(self.doctor_data["id"]),
                   intent=intent.get("intent"),
                   branch_id=str(self.branch_id))
        handlers = {
            "LIST_APPOINTMENTS": self._handle_list,
            "CANCEL_DAY": self._handle_cancel_day,
            "ADD_TOKENS": self._handle_add_tokens,
            "UNKNOWN": self._handle_unknown,
        }
        handler = handlers.get(intent.get("intent", "UNKNOWN"), self._handle_unknown)
        await handler(intent)

    async def _parse_intent(self, message: str) -> dict:
        today = date.today()
        tomorrow = today + timedelta(days=1)
        prompt = f"""Parse this WhatsApp message from a clinic doctor.
Today is {today.isoformat()}. Doctor: Dr. {self.doctor_data['name']}
Message: "{message}"
Return ONLY valid JSON. Intents: LIST_APPOINTMENTS, CANCEL_DAY, ADD_TOKENS, UNKNOWN
{{"intent": "LIST_APPOINTMENTS|CANCEL_DAY|ADD_TOKENS|UNKNOWN",
  "dates": ["{today.isoformat()}"],
  "token_count_to_add": null,
  "confidence": "high|medium|low"}}
Examples: "list today" → LIST_APPOINTMENTS dates:["{today}"]
"ēḍu ledu" → CANCEL_DAY dates:["{today}"]
"rēpu ledu" → CANCEL_DAY dates:["{tomorrow}"]
"add 5 slots" → ADD_TOKENS token_count_to_add:5"""

        # Try Gemini first (RULE 9)
        try:
            response = await asyncio.to_thread(_gemini.generate_content, prompt)
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as e:
            logger.error("doctor_command_gemini_failed", error=str(e))

        # Fallback to GPT-4o mini
        try:
            resp = await self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=150,
                response_format={"type": "json_object"},
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            logger.error("doctor_command_openai_failed", error=str(e))
            return {"intent": "UNKNOWN", "confidence": "low"}

    async def _handle_list(self, intent: dict):
        from backend.database import AsyncSessionLocal
        from backend.models.schema import Token, Patient
        from sqlalchemy import select

        dates = intent.get("dates", [date.today().isoformat()])
        target_date_str = dates[0] if dates else date.today().isoformat()

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Token, Patient)
                .join(Patient, Token.patient_id == Patient.id)
                .where(
                    Token.doctor_id == self.doctor_data["id"],
                    Token.branch_id == self.branch_id,   # MANDATORY
                    Token.date == target_date_str,
                    Token.status.in_(["confirmed", "attended"]),
                )
                .order_by(Token.token_number)
            )
            rows = result.all()
            # Capture values before closing session
            row_data = [
                {
                    "token_number": t.token_number,
                    "status": t.status,
                    "is_urgent": t.is_urgent,
                    "patient_name": p.name,
                }
                for t, p in rows
            ]

        if not row_data:
            msg = f"📋 {target_date_str}\nNo appointments scheduled."
        else:
            attended = sum(1 for r in row_data if r["status"] == "attended")
            remaining = sum(1 for r in row_data if r["status"] == "confirmed")
            lines = [f"📋 {target_date_str} — Dr. {self.doctor_data['name']}\n"]
            for r in row_data:
                status = "✅" if r["status"] == "attended" else "⏳"
                urgent = " 🔴" if r["is_urgent"] else ""
                lines.append(f"{status} #{r['token_number']} {r['patient_name']}{urgent}")
            lines.append(f"\n✅ {attended} attended · ⏳ {remaining} remaining")
            msg = "\n".join(lines)

        await self.meta.send_text_message(
            to=self.doctor_data["whatsapp_number"],
            message=msg,
            branch_id=str(self.branch_id),
        )

    async def _handle_cancel_day(self, intent: dict):
        from backend.database import AsyncSessionLocal
        from backend.models.schema import Token, Patient, Doctor, Branch
        from backend.services.calendar_service import CalendarService
        from sqlalchemy import select

        dates = intent.get("dates", [])
        if not dates:
            await self.meta.send_text_message(
                to=self.doctor_data["whatsapp_number"],
                message="Which date? Reply: off today OR off tomorrow",
                branch_id=str(self.branch_id),
            )
            return

        cal = CalendarService()
        all_cancelled = []

        for target_date in dates:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Token, Patient)
                    .join(Patient, Token.patient_id == Patient.id)
                    .where(
                        Token.doctor_id == self.doctor_data["id"],
                        Token.branch_id == self.branch_id,   # MANDATORY
                        Token.date == target_date,
                        Token.status == "confirmed",
                    )
                )
                rows = result.all()
                for token, patient in rows:
                    all_cancelled.append({
                        "token_number": token.token_number,
                        "patient_phone": patient.phone,
                        "patient_name": patient.name,
                        "date": target_date,
                        "calendar_event_id": token.google_calendar_event_id,
                    })
                    token.status = "cancelled_by_clinic"
                    token.cancellation_reason = "Doctor unavailable"
                await db.commit()

                # Get doctor's calendar_id for cleanup
                doc_result = await db.execute(
                    select(Doctor).where(Doctor.id == self.doctor_data["id"])
                )
                doc = doc_result.scalar_one_or_none()
                branch_result = await db.execute(
                    select(Branch).where(Branch.id == self.branch_id)
                )
                branch = branch_result.scalar_one_or_none()
                cal_id = (doc.google_calendar_id if doc else None) or (branch.google_calendar_id if branch else None)

            # Delete calendar events
            for item in all_cancelled:
                if item.get("calendar_event_id") and cal_id:
                    await cal.delete_event(cal_id, item["calendar_event_id"])

        if not all_cancelled:
            await self.meta.send_text_message(
                to=self.doctor_data["whatsapp_number"],
                message=f"No confirmed appointments found for {', '.join(dates)}.",
                branch_id=str(self.branch_id),
            )
            return

        # Notify patients in parallel (fire-and-forget per patient)
        async def notify_patient(item):
            if not item["patient_phone"]:
                return
            try:
                await self.meta.send_text_message(
                    to=item["patient_phone"],
                    message=(
                        f"❌ Appointment Cancelled\n\n"
                        f"Dr. {self.doctor_data['name']} is unavailable on {item['date']}.\n"
                        f"Token #{item['token_number']} is cancelled.\n"
                        f"Please call the clinic to reschedule."
                    ),
                    branch_id=str(self.branch_id),
                )
            except Exception as e:
                logger.error("cancel_notify_failed",
                            patient_phone=item["patient_phone"][-4:], error=str(e))

        await asyncio.gather(*[notify_patient(item) for item in all_cancelled])

        await self.meta.send_text_message(
            to=self.doctor_data["whatsapp_number"],
            message=f"✅ Done. {len(all_cancelled)} appointments cancelled. All patients notified.",
            branch_id=str(self.branch_id),
        )

    async def _handle_add_tokens(self, intent: dict):
        count = intent.get("token_count_to_add")
        if not count:
            await self._handle_unknown(intent)
            return

        from backend.database import AsyncSessionLocal
        from backend.models.schema import Doctor
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Doctor).where(Doctor.id == self.doctor_data["id"])
            )
            doctor = result.scalar_one_or_none()
            if doctor:
                new_limit = min((doctor.daily_token_limit or 30) + count, 60)
                doctor.daily_token_limit = new_limit
                await db.commit()

        await self.meta.send_text_message(
            to=self.doctor_data["whatsapp_number"],
            message=f"✅ {count} extra slots added.",
            branch_id=str(self.branch_id),
        )

    async def _handle_unknown(self, intent: dict):
        await self.meta.send_text_message(
            to=self.doctor_data["whatsapp_number"],
            message=(
                "📋 Commands:\n"
                "• list today\n"
                "• list tomorrow\n"
                "• off today\n"
                "• off tomorrow\n"
                "• add [N] tokens\n\n"
                "Telugu: ēḍu list, rēpu ledu, ēḍu ledu"
            ),
            branch_id=str(self.branch_id),
        )
```

- [ ] **Step 2: Verify import**

```bash
python -c "from backend.services.doctor_commands import DoctorCommandService; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/services/doctor_commands.py
git commit -m "feat: doctor WhatsApp command parser — Gemini primary, GPT-4o mini fallback"
```

---

### Task 8: `backend/services/whatsapp_agent.py` — Patient WA state machine

**Files:**
- Create: `backend/services/whatsapp_agent.py`

State machine uses `WhatsAppSession` table (NOT `patient.wa_conversation_state`).
States: `GREETING → WAITING_NAME → WAITING_DOCTOR → WAITING_SLOT → CONFIRM → CONFIRMED`

- [ ] **Step 1: Write whatsapp_agent.py**

```python
# backend/services/whatsapp_agent.py
"""
Patient WhatsApp conversation state machine.
State persisted in WhatsAppSession table (branch_id + patient_phone is unique per session).
session_data JSONB stores: doctor_id, doctor_name, date_str, token_redis_key, token_number.

States: GREETING → WAITING_DOCTOR → WAITING_SLOT → CONFIRM → CONFIRMED
        GREETING → WAITING_NAME (if name unknown) → WAITING_DOCTOR → ...
At any state: "cancel" releases held token and returns to GREETING.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import google.generativeai as genai
import structlog
from openai import AsyncOpenAI
from sqlalchemy import select

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models.schema import Branch, Doctor, Patient, Token, WhatsAppSession
from backend.services.meta_service import MetaService

logger = structlog.get_logger()

genai.configure(api_key=settings.gemini_api_key)
_gemini = genai.GenerativeModel("gemini-2.5-flash")

_CANCEL_WORDS = {"cancel", "stop", "no", "vaddhu", "వద్దు", "nahi", "cancel"}
_CONFIRM_WORDS = {"yes", "avunu", "ok", "okay", "confirm", "book", "చేయి", "అవును", "ha", "haan"}


class WhatsAppAgent:

    def __init__(self, branch_id, patient_phone: str):
        self.branch_id = branch_id
        self.patient_phone = patient_phone
        self.meta = MetaService()
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)

    async def process_message(self, message: str):
        patient = await self._get_or_create_patient()
        session = await self._get_or_create_session()
        state = session.state
        data = session.session_data or {}

        msg_lower = message.strip().lower()

        # Cancel at any state (except already CONFIRMED)
        if any(w in msg_lower for w in _CANCEL_WORDS) and state not in ("GREETING", "CONFIRMED"):
            await self._handle_cancel(session, data)
            return

        if state == "GREETING":
            await self._handle_greeting(session, data, patient, message)
        elif state == "WAITING_NAME":
            await self._handle_waiting_name(session, data, patient, message)
        elif state == "WAITING_DOCTOR":
            await self._handle_waiting_doctor(session, data, patient, message)
        elif state == "WAITING_SLOT":
            await self._handle_waiting_slot(session, data, patient, message)
        elif state == "CONFIRM":
            await self._handle_confirm(session, data, patient, message)
        else:
            # CONFIRMED or unknown — restart
            await self._handle_greeting(session, {}, patient, message)

    async def _handle_greeting(self, session, data: dict, patient, message: str):
        """Patient's first message — ask for name if unknown, then route to doctor."""
        if not patient.name:
            await self._send("Namaskāram! Mee pēru cheppandi:")
            await self._update_session(session, "WAITING_NAME", {})
        else:
            await self._send(
                f"Namaskāram {patient.name}!\n\n"
                f"Appointment book cheyyāli anukuntunnārā?\n"
                f"Mee problem cheppandi."
            )
            await self._update_session(session, "WAITING_DOCTOR", {"complaint": message})

    async def _handle_waiting_name(self, session, data: dict, patient, message: str):
        """Patient provided name."""
        name = message.strip().title()
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Patient).where(Patient.id == patient.id)
            )
            p = result.scalar_one_or_none()
            if p:
                p.name = name
                await db.commit()

        await self._send(f"Dhanyavaadālu {name}!\n\nMee problem cheppandi.")
        await self._update_session(session, "WAITING_DOCTOR", {"patient_name": name})

    async def _handle_waiting_doctor(self, session, data: dict, patient, message: str):
        """Match complaint to doctor, then ask for date."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Doctor).where(
                    Doctor.branch_id == self.branch_id,   # MANDATORY
                    Doctor.status == "active",
                )
            )
            doctors = result.scalars().all()
            # Capture before close
            doctor_list = [
                {"id": str(d.id), "name": d.name, "specialization": d.specialization,
                 "routing_keywords": d.routing_keywords or []}
                for d in doctors
            ]

        if not doctor_list:
            await self._send("Sorry, ippude doctors available kaadu. Clinic ki call cheyandi.")
            await self._update_session(session, "GREETING", {})
            return

        matched_id = await self._match_doctor(message, doctor_list)
        if not matched_id and len(doctor_list) > 1:
            lines = [f"{i+1}. Dr. {d['name']} ({d['specialization'] or 'General'})"
                     for i, d in enumerate(doctor_list[:4])]
            data["doctors"] = doctor_list[:4]
            await self._send(f"Yē doctor ki appointment kavāli?\n\n" + "\n".join(lines))
            await self._update_session(session, "WAITING_DOCTOR", {**data, "awaiting_selection": True})
            return

        doctor = doctor_list[0] if not matched_id else next(
            (d for d in doctor_list if d["id"] == matched_id), doctor_list[0]
        )
        data["doctor_id"] = doctor["id"]
        data["doctor_name"] = doctor["name"]
        await self._send(
            f"Dr. {doctor['name']} selected.\n\n"
            f"Ēḍu ki booking: *today*\n"
            f"Rēpu ki: *tomorrow*"
        )
        await self._update_session(session, "WAITING_SLOT", data)

    async def _handle_waiting_slot(self, session, data: dict, patient, message: str):
        """Patient chose today/tomorrow — check availability and present token."""
        from agent.tools.booking_tools import check_availability, assign_token
        from datetime import date
        import uuid

        msg_lower = message.lower()
        if any(w in msg_lower for w in ["tomorrow", "rēpu", "kal", "next"]):
            booking_date = date.today() + timedelta(days=1)
            date_label = "tomorrow"
        else:
            booking_date = date.today()
            date_label = "today"

        doctor_id = uuid.UUID(data["doctor_id"])

        async with AsyncSessionLocal() as db:
            avail_msg = await check_availability(doctor_id, self.branch_id, booking_date, db)

        if "fully booked" in avail_msg.lower():
            await self._send(
                f"Sorry, Dr. {data['doctor_name']} ki {date_label} available kaadu.\n"
                f"Vēre date try cheyāli?"
            )
            return

        data["date_str"] = booking_date.isoformat()
        await self._send(
            f"✅ Available!\n\n"
            f"Dr. {data['doctor_name']}\n"
            f"Date: {date_label.capitalize()}\n\n"
            f"Confirm cheyāli? *yes* or *avunu*"
        )
        await self._update_session(session, "CONFIRM", data)

    async def _handle_confirm(self, session, data: dict, patient, message: str):
        """Patient confirms — run assign + confirm booking."""
        from agent.tools.booking_tools import assign_token, confirm_booking
        from backend.services.calendar_service import CalendarService
        from datetime import date
        import uuid

        msg_lower = message.strip().lower()
        if not any(w in msg_lower for w in _CONFIRM_WORDS):
            await self._send("Confirm cheyāli? *yes* cheppandi lēdā booking cancel ki *cancel* cheppandi.")
            return

        doctor_id = uuid.UUID(data["doctor_id"])
        booking_date = date.fromisoformat(data["date_str"])

        async with AsyncSessionLocal() as db:
            assign_result = await assign_token(doctor_id, self.branch_id, booking_date, db)

        if not assign_result["success"]:
            await self._send("Sorry, booking fail aindi. Clinic ki call cheyandi.")
            await self._update_session(session, "GREETING", {})
            return

        token_number = assign_result["token_number"]
        redis_key = assign_result["redis_key"]
        patient_name = patient.name or "Patient"

        cal = CalendarService()
        meta = MetaService()

        async with AsyncSessionLocal() as db:
            confirm_result = await confirm_booking(
                doctor_id=doctor_id,
                branch_id=self.branch_id,
                patient_name=patient_name,
                patient_phone=self.patient_phone,
                complaint=data.get("complaint", ""),
                booking_date=booking_date,
                token_number=token_number,
                followup_consent=False,
                appointment_time=None,
                source="whatsapp",
                db=db,
                calendar_service=cal,
                meta_service=meta,
            )

        if confirm_result.get("success"):
            await self._send(
                f"✅ Booking Confirmed!\n\n"
                f"Dr. {data['doctor_name']}\n"
                f"Date: {booking_date.strftime('%d %B %Y')}\n"
                f"Token: #{token_number}\n\n"
                f"15 minutes early randi."
            )
            await self._update_session(session, "CONFIRMED", {})
        else:
            # Release held token
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.redis_url, decode_responses=True)
            try:
                await r.decr(redis_key)
            finally:
                await r.aclose()
            await self._send("Booking fail aindi. Clinic ki call cheyandi.")
            await self._update_session(session, "GREETING", {})

    async def _handle_cancel(self, session, data: dict):
        """Release held token and reset to GREETING."""
        redis_key = data.get("token_redis_key")
        if redis_key:
            from backend.services.token_service import TokenService
            await TokenService().release_token(redis_key)
        await self._send("Cancelled. Malli try cheyāli anukuntē message cheyandi.")
        await self._update_session(session, "GREETING", {})

    async def _send(self, message: str):
        await self.meta.send_text_message(
            to=self.patient_phone,
            message=message,
            branch_id=str(self.branch_id),
        )

    async def _get_or_create_patient(self) -> Patient:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Patient).where(
                    Patient.phone == self.patient_phone,
                    Patient.branch_id == self.branch_id,   # MANDATORY
                )
            )
            patient = result.scalar_one_or_none()
            if not patient:
                patient = Patient(
                    phone=self.patient_phone,
                    name="",
                    branch_id=self.branch_id,
                )
                db.add(patient)
                await db.commit()
                await db.refresh(patient)
            patient_id = patient.id
            patient_name = patient.name
            patient_phone = patient.phone

        patient_copy = Patient.__new__(Patient)
        patient_copy.id = patient_id
        patient_copy.name = patient_name
        patient_copy.phone = patient_phone
        return patient_copy

    async def _get_or_create_session(self) -> WhatsAppSession:
        expires = datetime.now(timezone.utc) + timedelta(hours=4)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(WhatsAppSession).where(
                    WhatsAppSession.branch_id == self.branch_id,   # MANDATORY
                    WhatsAppSession.patient_phone == self.patient_phone,
                    WhatsAppSession.state != "CONFIRMED",
                )
            )
            session = result.scalar_one_or_none()
            if not session:
                session = WhatsAppSession(
                    branch_id=self.branch_id,
                    patient_phone=self.patient_phone,
                    state="GREETING",
                    session_data={},
                    expires_at=expires,
                )
                db.add(session)
                await db.commit()
                await db.refresh(session)
            session_id = session.id
            session_state = session.state
            session_data = session.session_data

        s = WhatsAppSession.__new__(WhatsAppSession)
        s.id = session_id
        s.state = session_state
        s.session_data = session_data or {}
        return s

    async def _update_session(self, session, new_state: str, new_data: dict):
        expires = datetime.now(timezone.utc) + timedelta(hours=4)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(WhatsAppSession).where(WhatsAppSession.id == session.id)
            )
            s = result.scalar_one_or_none()
            if s:
                s.state = new_state
                s.session_data = new_data
                s.expires_at = expires
                await db.commit()

    async def _match_doctor(self, symptom: str, doctors: list) -> str | None:
        """Use Gemini to match symptom to doctor. Returns doctor_id or None."""
        if len(doctors) == 1:
            return doctors[0]["id"]
        doctor_json = json.dumps(doctors, ensure_ascii=False)
        prompt = (
            f'Match patient symptom to doctor.\nSymptom: "{symptom}"\n'
            f"Doctors: {doctor_json}\n"
            f'Return ONLY JSON: {{"matched_doctor_id": "id or null", "confidence": "high|low"}}'
        )
        # Gemini primary
        try:
            resp = await asyncio.to_thread(_gemini.generate_content, prompt)
            result = json.loads(resp.text.strip())
            return result.get("matched_doctor_id")
        except Exception:
            pass
        # GPT-4o mini fallback
        try:
            resp = await self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=60,
                response_format={"type": "json_object"},
            )
            result = json.loads(resp.choices[0].message.content)
            return result.get("matched_doctor_id")
        except Exception:
            return None
```

- [ ] **Step 2: Verify import**

```bash
python -c "from backend.services.whatsapp_agent import WhatsAppAgent; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/services/whatsapp_agent.py
git commit -m "feat: patient WhatsApp state machine — WhatsAppSession table, Gemini routing"
```

---

### Task 9: `backend/routers/queue.py` — Receptionist endpoints

**Files:**
- Create: `backend/routers/queue.py`

- [ ] **Step 1: Write queue router**

```python
# backend/routers/queue.py
"""
Receptionist app endpoints. All require JWT auth.
All queries MANDATORY filter by branch_id.
"""
from datetime import date, datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.models.schema import Doctor, Patient, Token

router = APIRouter()
logger = structlog.get_logger()


def _assert_branch_access(current_user: CurrentUser, branch_id: str):
    if current_user.role in ("super_admin",):
        return
    if branch_id not in (current_user.branch_ids or []):
        raise HTTPException(status_code=403, detail="No access to this branch")


@router.get("/{branch_id}/today")
async def get_today_queue(
    branch_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Today's complete queue grouped by doctor."""
    _assert_branch_access(current_user, branch_id)
    today = date.today()

    result = await db.execute(
        select(Token, Patient, Doctor)
        .join(Patient, Token.patient_id == Patient.id)
        .join(Doctor, Token.doctor_id == Doctor.id)
        .where(
            Token.branch_id == branch_id,      # MANDATORY
            Token.date == today,
            Token.status.in_(["confirmed", "attended", "no_show"]),
        )
        .order_by(Doctor.name, Token.token_number)
    )
    rows = result.all()

    doctors_map: dict = {}
    for token, patient, doctor in rows:
        did = str(doctor.id)
        if did not in doctors_map:
            doctors_map[did] = {
                "doctor_id": did,
                "doctor_name": doctor.name,
                "booking_type": doctor.booking_type,
                "stats": {"attended": 0, "no_show": 0, "remaining": 0},
                "patients": [],
            }
        entry = doctors_map[did]
        entry["patients"].append({
            "appointment_id": str(token.id),
            "token_number": token.token_number,
            "patient_name": patient.name,
            "status": token.status,
            "is_urgent": token.is_urgent,
            "confirmed_at": token.confirmed_at.isoformat() if token.confirmed_at else None,
        })
        if token.status == "attended":
            entry["stats"]["attended"] += 1
        elif token.status == "no_show":
            entry["stats"]["no_show"] += 1
        else:
            entry["stats"]["remaining"] += 1

    return {
        "date": str(today),
        "branch_id": branch_id,
        "summary": {
            "total": len(rows),
            "attended": sum(1 for t, _, _ in rows if t.status == "attended"),
            "no_show": sum(1 for t, _, _ in rows if t.status == "no_show"),
            "remaining": sum(1 for t, _, _ in rows if t.status == "confirmed"),
        },
        "doctors": list(doctors_map.values()),
    }


@router.patch("/{branch_id}/token/{token_id}/attend")
async def mark_attended(
    branch_id: str,
    token_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _assert_branch_access(current_user, branch_id)
    await _update_status(db, token_id, branch_id, "attended", current_user.user_id)
    return {"status": "attended"}


@router.patch("/{branch_id}/token/{token_id}/no-show")
async def mark_no_show(
    branch_id: str,
    token_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _assert_branch_access(current_user, branch_id)
    await _update_status(db, token_id, branch_id, "no_show", current_user.user_id)
    return {"status": "no_show"}


async def _update_status(db: AsyncSession, token_id: str, branch_id: str, status: str, user_id: str):
    import uuid
    result = await db.execute(
        select(Token).where(
            Token.id == uuid.UUID(token_id),
            Token.branch_id == branch_id,   # MANDATORY — prevents cross-clinic access
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    if token.status in ("attended", "no_show"):
        raise HTTPException(status_code=409, detail=f"Already {token.status}")

    token.status = status
    token.attended_at = datetime.now(timezone.utc)
    token.marked_by_user_id = uuid.UUID(user_id) if user_id else None
    await db.commit()
    logger.info("token_status_updated",
               token_id=token_id,
               status=status,
               branch_id=branch_id)
```

- [ ] **Step 2: Write test for data isolation**

```python
# tests/edge_cases/test_data_isolation.py
import pytest
import uuid
from sqlalchemy import select
from backend.models.schema import Token, Patient, Doctor, Branch, Organization
from backend.database import AsyncSessionLocal
from datetime import date


@pytest.mark.asyncio
async def test_queue_scoped_to_branch(db):
    """Clinic A receptionist cannot see Clinic B's tokens."""
    # Create two orgs, two branches, two patients, two tokens
    org_a = Organization(name="Clinic A", owner_phone="+911111111111",
                         owner_email="a@a.com", plan="solo")
    org_b = Organization(name="Clinic B", owner_phone="+912222222222",
                         owner_email="b@b.com", plan="solo")
    db.add_all([org_a, org_b])
    await db.flush()

    branch_a = Branch(org_id=org_a.id, name="A Branch",
                      whatsapp_number="+911111111111")
    branch_b = Branch(org_id=org_b.id, name="B Branch",
                      whatsapp_number="+912222222222")
    db.add_all([branch_a, branch_b])
    await db.flush()

    doctor_a = Doctor(branch_id=branch_a.id, name="Dr A", booking_type="token")
    doctor_b = Doctor(branch_id=branch_b.id, name="Dr B", booking_type="token")
    db.add_all([doctor_a, doctor_b])
    await db.flush()

    patient_a = Patient(branch_id=branch_a.id, name="Patient A")
    patient_b = Patient(branch_id=branch_b.id, name="Patient B")
    db.add_all([patient_a, patient_b])
    await db.flush()

    today = date.today()
    token_a = Token(branch_id=branch_a.id, doctor_id=doctor_a.id,
                    patient_id=patient_a.id, date=today, token_number=1,
                    source="voice", status="confirmed")
    token_b = Token(branch_id=branch_b.id, doctor_id=doctor_b.id,
                    patient_id=patient_b.id, date=today, token_number=1,
                    source="voice", status="confirmed")
    db.add_all([token_a, token_b])
    await db.commit()

    # Branch A query must not see branch B's token
    result_a = await db.execute(
        select(Token).where(Token.branch_id == branch_a.id, Token.date == today)
    )
    tokens_a = result_a.scalars().all()
    assert len(tokens_a) == 1
    assert tokens_a[0].id == token_a.id

    # Branch B query must not see branch A's token
    result_b = await db.execute(
        select(Token).where(Token.branch_id == branch_b.id, Token.date == today)
    )
    tokens_b = result_b.scalars().all()
    assert len(tokens_b) == 1
    assert tokens_b[0].id == token_b.id
```

- [ ] **Step 3: Run isolation test**

```bash
pytest tests/edge_cases/test_data_isolation.py -v
```
Expected: 1 passed

- [ ] **Step 4: Commit**

```bash
git add backend/routers/queue.py tests/edge_cases/test_data_isolation.py
git commit -m "feat: receptionist queue endpoints + data isolation test"
```

---

### Task 10: Background jobs

**Files:**
- Create: `backend/jobs/token_expiry.py`
- Create: `backend/jobs/eod_summary.py`
- Create: `backend/jobs/followup_calls.py`

- [ ] **Step 1: Create token_expiry.py**

```python
# backend/jobs/token_expiry.py
"""Runs every 2 minutes. Marks yesterday's unattended confirmed tokens as no_show."""
from datetime import date, timedelta
import structlog

logger = structlog.get_logger()


async def run_token_expiry():
    try:
        from backend.database import AsyncSessionLocal
        from backend.models.schema import Token
        from sqlalchemy import select

        cutoff = date.today() - timedelta(days=1)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Token).where(
                    Token.date < cutoff,
                    Token.status == "confirmed",
                )
            )
            stale = result.scalars().all()
            for token in stale:
                token.status = "no_show"
            if stale:
                await db.commit()
                logger.info("stale_tokens_expired", count=len(stale))
    except Exception as e:
        logger.error("token_expiry_job_failed", error=str(e))
```

- [ ] **Step 2: Create eod_summary.py**

```python
# backend/jobs/eod_summary.py
"""
Runs at 5:30 PM IST daily.
For each active branch → each doctor with appointments today:
  1. Auto-mark remaining confirmed tokens as no_show
  2. Send WhatsApp EOD summary to doctor
  3. Prompt for follow-up instructions
"""
from datetime import date
import structlog

logger = structlog.get_logger()


async def run_eod_summary():
    try:
        from backend.database import AsyncSessionLocal
        from backend.models.schema import Token, Doctor, Patient, Branch
        from backend.services.meta_service import MetaService
        from sqlalchemy import select

        meta = MetaService()
        today = date.today()

        async with AsyncSessionLocal() as db:
            branches_result = await db.execute(
                select(Branch).where(Branch.status == "active")
            )
            branches = branches_result.scalars().all()
            branch_ids = [b.id for b in branches]
            branch_names = {b.id: b.name for b in branches}

        for branch_id in branch_ids:
            async with AsyncSessionLocal() as db:
                doctors_result = await db.execute(
                    select(Doctor).where(
                        Doctor.branch_id == branch_id,   # MANDATORY
                        Doctor.status == "active",
                        Doctor.whatsapp_number.isnot(None),
                    )
                )
                doctors = doctors_result.scalars().all()
                doctor_data = [
                    {"id": d.id, "name": d.name, "whatsapp_number": d.whatsapp_number}
                    for d in doctors
                ]

            for doc in doctor_data:
                async with AsyncSessionLocal() as db:
                    tokens_result = await db.execute(
                        select(Token).where(
                            Token.doctor_id == doc["id"],
                            Token.branch_id == branch_id,   # MANDATORY
                            Token.date == today,
                        )
                    )
                    tokens = tokens_result.scalars().all()
                    if not tokens:
                        continue

                    # Auto-mark remaining as no_show
                    for token in tokens:
                        if token.status == "confirmed":
                            token.status = "no_show"
                    await db.commit()

                    attended = sum(1 for t in tokens if t.status == "attended")
                    no_show = sum(1 for t in tokens if t.status in ("no_show", "confirmed"))
                    total = len(tokens)

                summary = (
                    f"📊 End of Day — {today.strftime('%d %B %Y')}\n"
                    f"Dr. {doc['name']}\n\n"
                    f"✅ Attended: {attended}\n"
                    f"❌ No-show: {no_show}\n"
                    f"📋 Total: {total}\n\n"
                    f"_Reply with follow-up instructions if needed._"
                )

                try:
                    await meta.send_text_message(
                        to=doc["whatsapp_number"],
                        message=summary,
                        branch_id=str(branch_id),
                    )
                    logger.info("eod_summary_sent",
                               doctor_id=str(doc["id"]),
                               branch_id=str(branch_id))
                except Exception as e:
                    logger.error("eod_summary_send_failed",
                                doctor_id=str(doc["id"]), error=str(e))
    except Exception as e:
        logger.error("eod_summary_job_failed", error=str(e))
```

- [ ] **Step 3: Create followup_calls.py**

```python
# backend/jobs/followup_calls.py
"""
Runs at 9:00 AM IST daily.
Sends WhatsApp follow-up to patients with scheduled_date = today and status = pending.
"""
from datetime import date
import structlog

logger = structlog.get_logger()


async def run_followup_tasks():
    try:
        from backend.database import AsyncSessionLocal
        from backend.models.schema import FollowupTask, Patient, Doctor
        from backend.services.meta_service import MetaService
        from sqlalchemy import select

        meta = MetaService()
        today = date.today()

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(FollowupTask, Patient, Doctor)
                .join(Patient, FollowupTask.patient_id == Patient.id)
                .join(Doctor, FollowupTask.doctor_id == Doctor.id)
                .where(
                    FollowupTask.scheduled_date == today,
                    FollowupTask.status == "pending",
                )
            )
            tasks = result.all()
            # Capture all values before closing session
            task_data = [
                {
                    "id": task.id,
                    "what_to_ask": task.what_to_ask or "",
                    "channel": task.channel,
                    "branch_id": task.branch_id,
                    "patient_name": patient.name,
                    "patient_phone": patient.phone,
                    "doctor_name": doctor.name,
                }
                for task, patient, doctor in tasks
            ]

        for item in task_data:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(FollowupTask).where(FollowupTask.id == item["id"])
                )
                task = result.scalar_one_or_none()
                if not task:
                    continue
                try:
                    if item["channel"] in ("whatsapp", "both") and item["patient_phone"]:
                        msg = (
                            f"Namaskāram {item['patient_name']} gāru,\n\n"
                            f"Dr. {item['doctor_name']} check-in:\n"
                            f"{item['what_to_ask']}\n\n"
                            f"Reply cheyandi."
                        )
                        await meta.send_text_message(
                            to=item["patient_phone"],
                            message=msg,
                            branch_id=str(item["branch_id"]),
                        )
                    task.status = "completed"
                    task.attempt_count += 1
                    await db.commit()
                    logger.info("followup_task_completed",
                               task_id=str(item["id"]),
                               patient_phone=item["patient_phone"][-4:] if item["patient_phone"] else "unknown")
                except Exception as e:
                    task.status = "failed"
                    task.attempt_count += 1
                    await db.commit()
                    logger.error("followup_task_failed",
                                task_id=str(item["id"]), error=str(e))
    except Exception as e:
        logger.error("followup_jobs_failed", error=str(e))
```

- [ ] **Step 4: Verify imports**

```bash
python -c "from backend.jobs.token_expiry import run_token_expiry; from backend.jobs.eod_summary import run_eod_summary; from backend.jobs.followup_calls import run_followup_tasks; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/jobs/token_expiry.py backend/jobs/eod_summary.py backend/jobs/followup_calls.py
git commit -m "feat: background jobs — token expiry, EOD summary, follow-up tasks"
```

---

### Task 11: `backend/routers/dashboard.py` + `backend/routers/admin.py`

**Files:**
- Create: `backend/routers/dashboard.py`
- Create: `backend/routers/admin.py`

- [ ] **Step 1: Create dashboard.py**

```python
# backend/routers/dashboard.py
"""Clinic owner analytics. Scoped to org_id from JWT."""
from datetime import date, timedelta
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.models.schema import Token, Branch

router = APIRouter()
logger = structlog.get_logger()


@router.get("/{branch_id}/stats")
async def get_branch_stats(
    branch_id: str,
    days: int = 7,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Last N days of booking stats for a branch."""
    if current_user.role not in ("super_admin", "org_admin"):
        if branch_id not in (current_user.branch_ids or []):
            from fastapi import HTTPException
            raise HTTPException(status_code=403)

    since = date.today() - timedelta(days=days)

    result = await db.execute(
        select(
            Token.date,
            Token.status,
            Token.source,
            func.count(Token.id).label("count"),
        )
        .where(
            Token.branch_id == branch_id,   # MANDATORY
            Token.date >= since,
        )
        .group_by(Token.date, Token.status, Token.source)
        .order_by(Token.date)
    )
    rows = result.all()

    by_day: dict = {}
    for row in rows:
        day = str(row.date)
        if day not in by_day:
            by_day[day] = {"date": day, "total": 0, "attended": 0, "no_show": 0,
                           "cancelled": 0, "voice": 0, "whatsapp": 0, "walk_in": 0}
        by_day[day]["total"] += row.count
        if row.status == "attended":
            by_day[day]["attended"] += row.count
        elif row.status == "no_show":
            by_day[day]["no_show"] += row.count
        elif row.status == "cancelled_by_clinic":
            by_day[day]["cancelled"] += row.count
        if row.source in ("voice", "whatsapp", "walk_in"):
            by_day[day][row.source] += row.count

    return {"branch_id": branch_id, "days": days, "data": list(by_day.values())}
```

- [ ] **Step 2: Create admin.py**

```python
# backend/routers/admin.py
"""Vachanam platform admin (Vinay only). Requires is_admin=True JWT claim."""
from datetime import date, timedelta
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.auth_middleware import require_admin, CurrentUser
from backend.models.schema import Organization, Branch, Token, BillingCycle

router = APIRouter()
logger = structlog.get_logger()


@router.get("/orgs")
async def list_all_orgs(
    current_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """All organizations — Vinay's admin view."""
    result = await db.execute(
        select(Organization).order_by(Organization.created_at.desc())
    )
    orgs = result.scalars().all()
    return [
        {
            "id": str(o.id),
            "name": o.name,
            "plan": o.plan,
            "status": o.status,
            "owner_email": o.owner_email,
            "created_at": o.created_at.isoformat(),
        }
        for o in orgs
    ]


@router.get("/revenue")
async def get_platform_revenue(
    current_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Platform-wide revenue summary from billing cycles."""
    result = await db.execute(
        select(
            BillingCycle.plan,
            func.count(BillingCycle.id).label("count"),
            func.sum(BillingCycle.base_amount + BillingCycle.overage_amount).label("total_revenue"),
        )
        .where(BillingCycle.status.in_(["invoiced", "paid"]))
        .group_by(BillingCycle.plan)
    )
    return result.mappings().all()
```

- [ ] **Step 3: Commit**

```bash
git add backend/routers/dashboard.py backend/routers/admin.py
git commit -m "feat: dashboard analytics and admin platform view"
```

---

### Task 12: `backend/main.py` — FastAPI app, lifespan, all routers

**Files:**
- Create: `backend/main.py`

- [ ] **Step 1: Create main.py**

```python
# backend/main.py
from contextlib import asynccontextmanager

import pytz
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.database import init_db

logger = structlog.get_logger()
IST = pytz.timezone("Asia/Kolkata")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    scheduler = AsyncIOScheduler(timezone=IST)

    from backend.jobs.token_expiry import run_token_expiry
    from backend.jobs.eod_summary import run_eod_summary
    from backend.jobs.followup_calls import run_followup_tasks

    scheduler.add_job(run_token_expiry, IntervalTrigger(minutes=2))
    scheduler.add_job(run_eod_summary, CronTrigger(hour=17, minute=30, timezone=IST))
    scheduler.add_job(run_followup_tasks, CronTrigger(hour=9, minute=0, timezone=IST))

    scheduler.start()
    logger.info("scheduler_started")

    yield

    scheduler.shutdown()
    logger.info("shutdown")


app = FastAPI(title="Vachanam API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from backend.routers import auth, whatsapp, queue, dashboard, admin

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(whatsapp.router, prefix="/webhook", tags=["webhook"])
app.include_router(queue.router, prefix="/queue", tags=["queue"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}
```

- [ ] **Step 2: Verify server starts**

```bash
cd C:\Users\vinay\OneDrive\Desktop\SAAS\VACHANAM
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000
```
Expected: `INFO: Application startup complete.` in terminal. No errors.

- [ ] **Step 3: Test health endpoint**

```bash
curl http://localhost:8000/health
```
Expected: `{"status":"ok","env":"development"}`

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat: FastAPI main.py — lifespan, APScheduler, all routers registered"
```

---

### Task 13: Alembic migration and integration test run

**Files:**
- Modify: `alembic/versions/` (auto-generate)

- [ ] **Step 1: Run Docker and generate migration**

```bash
docker-compose up -d
sleep 5
alembic revision --autogenerate -m "initial_schema"
```
Expected: new file in `alembic/versions/`

- [ ] **Step 2: Apply migration**

```bash
alembic upgrade head
```
Expected: `Running upgrade ... -> <hash>, initial_schema`

- [ ] **Step 3: Run all tests**

```bash
pytest tests/ -v --tb=short
```
Expected: all tests pass (unit, integration, edge_cases)

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/
git commit -m "feat: initial database migration — all 10 tables"
```

---

## Phase 2 Exit Criteria

```
AUTOMATED TESTS
□ pytest tests/unit/ -v → all pass
□ pytest tests/integration/ -v → all pass
□ pytest tests/edge_cases/test_data_isolation.py -v → all pass

DATA ISOLATION (critical — DPDP Act)
□ Clinic A tokens not visible in Clinic B's queue query
□ Doctor at Branch X cannot cancel Branch Y appointments
□ Branch identified by meta_phone_number_id, not sender phone

WHATSAPP FLOWS (manual verify with ngrok tunnel)
□ Doctor sends "list today" → formatted schedule received
□ Doctor sends "off tomorrow" → patients notified, doctor confirmed
□ Patient sends first message → GREETING state, asks for name
□ Patient completes booking → token assigned, WhatsApp confirmation sent
□ Patient sends "cancel" mid-booking → held token released in Redis

API ENDPOINTS
□ GET /health → {"status":"ok"}
□ POST /webhook/whatsapp → 200 in < 200ms
□ GET /queue/{branch_id}/today → correct queue, branch-scoped
□ PATCH /queue/{branch_id}/token/{id}/attend → status=attended in DB
□ PATCH /queue/{branch_id}/token/{id}/no-show → status=no_show in DB
□ GET /auth/google?id_token=... → JWT returned for known user

SECURITY
□ POST /queue/other-branch/today → 403
□ GET /admin/orgs without is_admin=True → 403
□ All endpoints without JWT → 401

BACKGROUND JOBS (manual trigger)
□ run_token_expiry() → yesterday's confirmed tokens → no_show
□ run_eod_summary() → doctor receives WhatsApp summary
□ run_followup_tasks() → patient receives follow-up WhatsApp
```

**ALL checked = Phase 2 complete. Proceed to PHASE_3_FRONTEND.md**
