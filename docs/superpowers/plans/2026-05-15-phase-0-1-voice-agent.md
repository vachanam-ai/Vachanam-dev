# Vachanam Phase 0+1: Environment & Voice Agent Core

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up local dev environment with all 9 DB tables migrated, then build a working Telugu voice agent that books appointments with atomic token assignment, Google Calendar events, and WhatsApp confirmations.

**Architecture:** LiveKit Agents 1.4.x hosts the voice agent; Sarvam Saaras v3 → STT, Sarvam Bulbul v3 → TTS, Gemini 2.5 Flash (primary) / GPT-4o mini (fallback) drives conversation. Redis INCR handles atomic token/slot booking — DECR only as rollback. Calendar creation must succeed for booking to succeed; WhatsApp is fire-and-forget. Full code reference in `PHASE_0_ENVIRONMENT.md` and `PHASE_1_VOICE_AGENT.md`.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x async + asyncpg, Alembic, LiveKit Agents 1.4.x, livekit-plugins-sarvam, livekit-plugins-google, Upstash Redis (redis-py async), Neon Postgres, docker-compose (local dev), pytest + pytest-asyncio, structlog, tenacity.

---

## File Map

### Phase 0 — Environment
| File | Purpose |
|---|---|
| `docker-compose.yml` | Local Postgres + Redis |
| `.env.example` | All 25 env vars documented, empty values |
| `.env` | Your actual secrets — **NEVER commit** |
| `backend/__init__.py` | Package marker |
| `backend/config.py` | Pydantic BaseSettings, reads all 25 env vars |
| `backend/database.py` | SQLAlchemy async engine + session factory |
| `backend/models/__init__.py` | Package marker |
| `backend/models/schema.py` | All 9 ORM models |
| `alembic.ini` | Alembic config pointing to backend/models |
| `alembic/env.py` | Async migration runner |
| `alembic/versions/001_initial_schema.py` | Single migration: all 9 tables |

### Phase 1 — Voice Agent
| File | Purpose |
|---|---|
| `agent/__init__.py` | Package marker |
| `agent/requirements.txt` | Agent Python dependencies |
| `agent/services/__init__.py` | Package marker |
| `agent/services/tts_sanitizer.py` | Strip markdown/symbols before TTS |
| `agent/services/emergency.py` | MVP: keyword detect → give emergency_contact |
| `agent/session_state.py` | Per-call state dataclass |
| `agent/prompts/__init__.py` | Package marker |
| `agent/prompts/system_prompt.py` | Telugu system prompt builder |
| `agent/tools/__init__.py` | Package marker |
| `agent/tools/booking_tools.py` | 4 LLM function tools |
| `agent/agent.py` | LiveKit entrypoint, 4-min Solo cap |
| `tests/__init__.py` | Package marker |
| `tests/conftest.py` | Pytest fixtures (async DB session, Redis) |
| `tests/unit/__init__.py` | Package marker |
| `tests/unit/test_tts_sanitizer.py` | 11 sanitizer tests |
| `tests/unit/test_emergency.py` | 12 emergency MVP tests |
| `tests/integration/__init__.py` | Package marker |
| `tests/integration/test_booking_flow.py` | End-to-end voice booking simulation |
| `tests/edge_cases/__init__.py` | Package marker |
| `tests/edge_cases/test_concurrent_tokens.py` | 5 simultaneous callers, no duplicate tokens |

---

## Task 1: Project Directory Scaffold

**Files:** Creates all directories and `__init__.py` files per `CLAUDE.md` structure.

- [ ] **Step 1: Create directory tree**

```powershell
cd C:\Users\vinay\OneDrive\Desktop\SAAS\VACHANAM
New-Item -ItemType Directory -Force -Path `
  agent/prompts, agent/services, agent/tools, `
  backend/models, backend/routers, backend/services, backend/middleware, backend/jobs, `
  frontend/src/api, frontend/src/hooks, frontend/src/pages, frontend/src/components, `
  frontend/public, infra, `
  tests/unit, tests/integration, tests/edge_cases, `
  alembic/versions, `
  docs/superpowers/plans
```

- [ ] **Step 2: Create all `__init__.py` files**

```powershell
$packages = @(
  "agent/__init__.py", "agent/prompts/__init__.py",
  "agent/services/__init__.py", "agent/tools/__init__.py",
  "backend/__init__.py", "backend/models/__init__.py",
  "backend/routers/__init__.py", "backend/services/__init__.py",
  "backend/middleware/__init__.py", "backend/jobs/__init__.py",
  "tests/__init__.py", "tests/unit/__init__.py",
  "tests/integration/__init__.py", "tests/edge_cases/__init__.py"
)
foreach ($f in $packages) { New-Item -ItemType File -Force -Path $f }
```

- [ ] **Step 3: Create `.gitignore`**

```
.env
google-service-account.json
__pycache__/
*.pyc
.pytest_cache/
.venv/
node_modules/
dist/
```

- [ ] **Step 4: Commit scaffold**

```bash
git init
git add .
git commit -m "feat: project scaffold — directory structure and package markers"
```

---

## Task 2: Docker Compose (Local Dev)

**Files:** Create `docker-compose.yml`

- [ ] **Step 1: Write `docker-compose.yml`**

```yaml
version: "3.9"
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: vachanam
      POSTGRES_PASSWORD: localdev123
      POSTGRES_DB: vachanam_dev
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres_data:
```

- [ ] **Step 2: Start services and verify**

```bash
docker-compose up -d
docker-compose ps
# Expected: postgres and redis both show "Up"
```

- [ ] **Step 3: Test Postgres connection**

```bash
docker exec -it vachanam-postgres-1 psql -U vachanam -d vachanam_dev -c "\l"
# Expected: lists vachanam_dev database
```

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: docker-compose for local postgres and redis"
```

---

## Task 3: Environment Variables

**Files:** Create `.env.example` and `.env`

- [ ] **Step 1: Create `.env.example`**

```bash
# ── AI ────────────────────────────────────────────────────────────────
SARVAM_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=

# ── LiveKit ───────────────────────────────────────────────────────────
LIVEKIT_URL=wss://vachanam-agent.fly.dev
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=

# ── Telephony (Vobiz) ─────────────────────────────────────────────────
VOBIZ_API_KEY=
VOBIZ_API_SECRET=
VOBIZ_WEBHOOK_SECRET=
VOBIZ_PARTNER_AUTH_ID=
VOBIZ_PARTNER_AUTH_TOKEN=

# ── Telephony backup (Twilio) ─────────────────────────────────────────
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=

# ── WhatsApp (Meta Cloud API) ─────────────────────────────────────────
META_ACCESS_TOKEN=
META_PHONE_NUMBER_ID=
META_WABA_ID=
META_WEBHOOK_VERIFY_TOKEN=
META_APP_SECRET=

# ── Google ────────────────────────────────────────────────────────────
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_APPLICATION_CREDENTIALS=./google-service-account.json
GOOGLE_CALENDAR_SERVICE_EMAIL=

# ── Database ──────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://vachanam:localdev123@localhost:5432/vachanam_dev

# ── Redis ─────────────────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379

# ── Auth ──────────────────────────────────────────────────────────────
JWT_SECRET=
JWT_EXPIRE_HOURS=24

# ── Payment ───────────────────────────────────────────────────────────
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=
RAZORPAY_PLAN_SOLO_ID=
RAZORPAY_PLAN_CLINIC_ID=
RAZORPAY_PLAN_MULTI_ID=

# ── App config ────────────────────────────────────────────────────────
APP_ENV=development
BASE_URL=http://localhost:8000
FRONTEND_URL=http://localhost:3000
ADMIN_PHONE=+919XXXXXXXXX
LOG_LEVEL=debug
```

- [ ] **Step 2: Copy to `.env` and fill in real values**

```bash
cp .env.example .env
# Now fill in: SARVAM_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY
# Generate JWT_SECRET:
python -c "import secrets; print(secrets.token_hex(32))"
# DATABASE_URL and REDIS_URL already set for local dev
# Leave Vobiz/Twilio/Meta/Razorpay empty for now — Phase 1 tests mock them
```

- [ ] **Step 3: Commit only `.env.example`**

```bash
git add .env.example
git commit -m "feat: env.example with all 25 required variables documented"
```

---

## Task 4: Backend Config (Pydantic Settings)

**Files:** Create `backend/config.py`

- [ ] **Step 1: Install dependencies**

```bash
pip install pydantic-settings python-dotenv
```

- [ ] **Step 2: Write `backend/config.py`**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI
    sarvam_api_key: str
    openai_api_key: str
    gemini_api_key: str

    # LiveKit
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str

    # Telephony
    vobiz_api_key: str = ""
    vobiz_api_secret: str = ""
    vobiz_webhook_secret: str = ""
    vobiz_partner_auth_id: str = ""
    vobiz_partner_auth_token: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""

    # WhatsApp
    meta_access_token: str = ""
    meta_phone_number_id: str = ""
    meta_waba_id: str = ""
    meta_webhook_verify_token: str = ""
    meta_app_secret: str = ""

    # Google
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_application_credentials: str = "./google-service-account.json"
    google_calendar_service_email: str = ""

    # Database
    database_url: str

    # Redis
    redis_url: str

    # Auth
    jwt_secret: str
    jwt_expire_hours: int = 24

    # Payment
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_plan_solo_id: str = ""
    razorpay_plan_clinic_id: str = ""
    razorpay_plan_multi_id: str = ""

    # App
    app_env: str = "development"
    base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    admin_phone: str = ""
    log_level: str = "debug"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Step 3: Verify it loads**

```bash
python -c "from backend.config import settings; print(settings.app_env)"
# Expected: development
```

- [ ] **Step 4: Commit**

```bash
git add backend/config.py
git commit -m "feat: pydantic settings — reads all 25 env vars from .env"
```

---

## Task 5: Database Engine

**Files:** Create `backend/database.py`

- [ ] **Step 1: Install dependencies**

```bash
pip install sqlalchemy asyncpg
```

- [ ] **Step 2: Write `backend/database.py`**

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from backend.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

- [ ] **Step 3: Verify import**

```bash
python -c "from backend.database import engine; print(engine)"
# Expected: <AsyncEngine ...>
```

- [ ] **Step 4: Commit**

```bash
git add backend/database.py
git commit -m "feat: async sqlalchemy engine with session factory"
```

---

## Task 6: Database Schema (All 9 Models)

**Files:** Write `backend/models/schema.py`

- [ ] **Step 1: Install remaining ORM deps**

```bash
pip install alembic
```

- [ ] **Step 2: Write `backend/models/schema.py`**

```python
import uuid
from datetime import datetime, date, time
from sqlalchemy import (
    String, Boolean, Integer, Text, DateTime, Date, Time,
    ForeignKey, Enum, ARRAY, JSON, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    plan: Mapped[str] = mapped_column(Enum("solo", "clinic", "multi", name="plan_type"), nullable=False)
    subscription_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    razorpay_customer_id: Mapped[str | None] = mapped_column(String(255))
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(255))
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        Enum("active", "trial", "paused", "cancelled", name="org_status"),
        default="trial",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    branches: Mapped[list["Branch"]] = relationship(back_populates="organization")
    billing_cycles: Mapped[list["BillingCycle"]] = relationship(back_populates="organization")


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    whatsapp_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    did_number: Mapped[str | None] = mapped_column(String(20))
    vobiz_did_id: Mapped[str | None] = mapped_column(String(255))
    emergency_contact: Mapped[str | None] = mapped_column(String(20))
    google_calendar_id: Mapped[str | None] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata")
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", name="branch_status"),
        default="active",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="branches")
    doctors: Mapped[list["Doctor"]] = relationship(back_populates="branch")
    patients: Mapped[list["Patient"]] = relationship(back_populates="branch")
    tokens: Mapped[list["Token"]] = relationship(back_populates="branch")
    calls: Mapped[list["Call"]] = relationship(back_populates="branch")
    whatsapp_sessions: Mapped[list["WhatsAppSession"]] = relationship(back_populates="branch")


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    specialization: Mapped[str | None] = mapped_column(String(100))
    routing_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    is_default_doctor: Mapped[bool] = mapped_column(Boolean, default=False)
    booking_type: Mapped[str] = mapped_column(
        Enum("token", "appointment", name="booking_type"),
        nullable=False,
    )
    working_hours_start: Mapped[time | None] = mapped_column(Time)
    working_hours_end: Mapped[time | None] = mapped_column(Time)
    slot_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    max_concurrent_per_slot: Mapped[int | None] = mapped_column(Integer)
    pre_appointment_reminder: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_token_limit: Mapped[int | None] = mapped_column(Integer)
    whatsapp_number: Mapped[str | None] = mapped_column(String(20))
    google_calendar_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", name="doctor_status"),
        default="active",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    branch: Mapped["Branch"] = relationship(back_populates="doctors")
    tokens: Mapped[list["Token"]] = relationship(back_populates="doctor")
    followup_tasks: Mapped[list["FollowupTask"]] = relationship(back_populates="doctor")


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    followup_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    branch: Mapped["Branch"] = relationship(back_populates="patients")
    tokens: Mapped[list["Token"]] = relationship(back_populates="patient")
    followup_tasks: Mapped[list["FollowupTask"]] = relationship(back_populates="patient")


class Token(Base):
    __tablename__ = "tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctors.id"), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    token_number: Mapped[int | None] = mapped_column(Integer)
    appointment_time: Mapped[time | None] = mapped_column(Time)
    source: Mapped[str] = mapped_column(
        Enum("voice", "whatsapp", "walk_in", name="booking_source"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Enum("waiting", "attended", "no_show", "cancelled_by_clinic", name="token_status"),
        default="waiting",
        nullable=False,
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    call_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    google_calendar_event_id: Mapped[str | None] = mapped_column(String(255))
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    branch: Mapped["Branch"] = relationship(back_populates="tokens")
    doctor: Mapped["Doctor"] = relationship(back_populates="tokens")
    patient: Mapped["Patient"] = relationship(back_populates="tokens")


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("doctors.id"))
    token_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tokens.id"))
    caller_phone: Mapped[str | None] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(
        Enum("inbound", "outbound", name="call_direction"),
        nullable=False,
    )
    call_type: Mapped[str] = mapped_column(
        Enum("inbound_booking", "followup", "cancellation_notify", name="call_type"),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    livekit_room_id: Mapped[str | None] = mapped_column(String(255))
    vobiz_call_id: Mapped[str | None] = mapped_column(String(255))
    outcome: Mapped[str | None] = mapped_column(
        Enum(
            "booked", "no_slot", "emergency", "dropped", "followup_completed",
            "cancellation_rebooked", "cancellation_declined", "cancellation_unreachable",
            name="call_outcome",
        )
    )

    branch: Mapped["Branch"] = relationship(back_populates="calls")


class FollowupTask(Base):
    __tablename__ = "followup_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctors.id"), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False)
    requested_by_doctor_whatsapp: Mapped[str | None] = mapped_column(String(20))
    topic: Mapped[str | None] = mapped_column(Text)
    specific_question: Mapped[str | None] = mapped_column(Text)
    response_summary: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(
        Enum("pending", "in_progress", "completed", "unreachable", name="followup_status"),
        default="pending",
        nullable=False,
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    branch: Mapped["Branch"] = relationship()
    doctor: Mapped["Doctor"] = relationship(back_populates="followup_tasks")
    patient: Mapped["Patient"] = relationship(back_populates="followup_tasks")


class BillingCycle(Base):
    __tablename__ = "billing_cycles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    cycle_start: Mapped[date] = mapped_column(Date, nullable=False)
    cycle_end: Mapped[date] = mapped_column(Date, nullable=False)
    plan: Mapped[str] = mapped_column(String(20), nullable=False)
    base_amount: Mapped[int] = mapped_column(Integer, nullable=False)  # paise
    included_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    minutes_used: Mapped[int] = mapped_column(Integer, default=0)
    overage_minutes: Mapped[int] = mapped_column(Integer, default=0)
    overage_rate: Mapped[int] = mapped_column(Integer, default=0)  # paise per minute
    overage_amount: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        Enum("open", "invoiced", "paid", "failed", name="billing_status"),
        default="open",
        nullable=False,
    )
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(255))
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="billing_cycles")


class WhatsAppSession(Base):
    __tablename__ = "whatsapp_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), nullable=False)
    patient_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[str] = mapped_column(
        Enum(
            "GREETING", "WAITING_NAME", "WAITING_DOCTOR", "WAITING_SLOT",
            "CONFIRM", "CONFIRMED", "CANCELLATION_REBOOK",
            name="wa_session_state",
        ),
        default="GREETING",
        nullable=False,
    )
    session_data: Mapped[dict | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    branch: Mapped["Branch"] = relationship(back_populates="whatsapp_sessions")
```

- [ ] **Step 3: Verify models import cleanly**

```bash
python -c "from backend.models.schema import Organization, Branch, Doctor, Patient, Token, Call, FollowupTask, BillingCycle, WhatsAppSession; print('All 9 models OK')"
# Expected: All 9 models OK
```

- [ ] **Step 4: Commit**

```bash
git add backend/models/schema.py
git commit -m "feat: all 9 sqlalchemy ORM models"
```

---

## Task 7: Alembic Migrations

**Files:** `alembic.ini`, `alembic/env.py`, `alembic/versions/001_initial_schema.py`

- [ ] **Step 1: Initialize Alembic**

```bash
alembic init alembic
```

- [ ] **Step 2: Replace `alembic/env.py` with async version**

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from backend.config import settings
from backend.database import Base
from backend.models import schema  # noqa: F401 — registers all models

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Generate migration**

```bash
alembic revision --autogenerate -m "initial_schema"
# Expected: creates alembic/versions/xxxx_initial_schema.py
```

- [ ] **Step 4: Run migration**

```bash
alembic upgrade head
# Expected: each CREATE TABLE prints, no errors
```

- [ ] **Step 5: Verify tables exist**

```bash
docker exec -it vachanam-postgres-1 psql -U vachanam -d vachanam_dev -c "\dt"
# Expected: 9 tables listed (organizations, branches, doctors, patients, tokens, calls, followup_tasks, billing_cycles, whatsapp_sessions)
```

- [ ] **Step 6: Commit**

```bash
git add alembic.ini alembic/
git commit -m "feat: alembic async migrations — all 9 tables"
```

---

## Task 8: Agent Requirements

**Files:** Create `agent/requirements.txt`

- [ ] **Step 1: Write `agent/requirements.txt`**

```
livekit-agents[sarvam,google,openai]>=1.4.0
structlog>=24.0.0
tenacity>=8.2.0
redis>=5.0.0
httpx>=0.27.0
pydantic-settings>=2.0.0
google-auth>=2.0.0
google-api-python-client>=2.0.0
python-dotenv>=1.0.0
```

- [ ] **Step 2: Install in a virtual environment**

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r agent/requirements.txt
pip install pytest pytest-asyncio
```

- [ ] **Step 3: Verify LiveKit import**

```bash
python -c "import livekit.agents; print('LiveKit agents OK')"
# Expected: LiveKit agents OK
```

- [ ] **Step 4: Commit**

```bash
git add agent/requirements.txt
git commit -m "feat: agent python dependencies"
```

---

## Task 9: TTS Sanitizer Tests (Write First)

**Files:** Create `tests/unit/test_tts_sanitizer.py`

- [ ] **Step 1: Write `tests/unit/test_tts_sanitizer.py`** (all 11 tests)

```python
import pytest
from agent.services.tts_sanitizer import sanitize_for_tts


def test_bold_markdown_stripped():
    assert sanitize_for_tts("**Token number** is ready") == "Token number is ready"


def test_italic_markdown_stripped():
    assert sanitize_for_tts("*urgent* appointment") == "urgent appointment"


def test_hash_number_converted():
    # #8 should become just "8" (spoken naturally)
    result = sanitize_for_tts("Token #8 confirmed")
    assert result == "Token 8 confirmed"


def test_markdown_header_stripped():
    assert sanitize_for_tts("## Welcome to Vachanam") == "Welcome to Vachanam"


def test_dash_bullet_stripped():
    result = sanitize_for_tts("- Morning slot\n- Evening slot")
    assert "#" not in result
    assert "-" not in result


def test_asterisk_bullet_stripped():
    result = sanitize_for_tts("* Token 1\n* Token 2")
    assert result.strip().startswith("Token")


def test_multiple_spaces_collapsed():
    result = sanitize_for_tts("Hello   world")
    assert "  " not in result


def test_emoji_stripped():
    result = sanitize_for_tts("Booking confirmed ✅")
    assert "✅" not in result


def test_numbered_list_dot_stripped():
    # "8. Next patient" — the "8." should become "8"
    result = sanitize_for_tts("8. Next patient please")
    assert "8." not in result


def test_clean_text_unchanged():
    text = "Your token number is 5. Doctor will see you soon."
    result = sanitize_for_tts(text)
    assert result == text


def test_combined_markdown():
    result = sanitize_for_tts("**Token #3** confirmed! ✅\n- See you at 10:30")
    assert "**" not in result
    assert "#" not in result
    assert "✅" not in result
```

- [ ] **Step 2: Run tests to confirm they all fail**

```bash
pytest tests/unit/test_tts_sanitizer.py -v
# Expected: 11 FAILED (ImportError — module doesn't exist yet)
```

- [ ] **Step 3: Commit tests**

```bash
git add tests/unit/test_tts_sanitizer.py
git commit -m "test: tts_sanitizer — 11 failing tests (TDD)"
```

---

## Task 10: TTS Sanitizer Implementation

**Files:** Create `agent/services/tts_sanitizer.py`

- [ ] **Step 1: Write `agent/services/tts_sanitizer.py`**

```python
import re
import unicodedata


def sanitize_for_tts(text: str) -> str:
    """Strip markdown and symbols so text sounds natural when spoken aloud."""
    # Remove markdown bold (**text** or __text__)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)

    # Remove markdown italic (*text* or _text_) — single asterisk/underscore
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)

    # Remove markdown headers (## Heading → Heading)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # Convert Token #8 → Token 8 (hash before digit)
    text = re.sub(r"#(\d+)", r"\1", text)

    # Remove remaining hash symbols
    text = re.sub(r"#", "", text)

    # Remove bullet point dashes at start of line (- item)
    text = re.sub(r"^\s*-\s+", "", text, flags=re.MULTILINE)

    # Remove asterisk bullets at start of line (* item)
    text = re.sub(r"^\s*\*\s+", "", text, flags=re.MULTILINE)

    # Remove numbered list dots ("8. Next" → "8 Next")
    text = re.sub(r"(\d+)\.\s+", r"\1 ", text)

    # Strip emoji and other non-ASCII symbols
    text = "".join(
        ch for ch in text
        if unicodedata.category(ch) not in ("So", "Sm", "Sk", "Sc")
        and (ch.isascii() or "ऀ" <= ch <= "ॿ"  # allow Devanagari
             or "ఀ" <= ch <= "౿")              # allow Telugu
    )

    # Collapse multiple spaces
    text = re.sub(r"  +", " ", text)

    # Strip leading/trailing whitespace per line, then rejoin
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines)
```

- [ ] **Step 2: Run tests — all 11 must pass**

```bash
pytest tests/unit/test_tts_sanitizer.py -v
# Expected: 11 passed
```

- [ ] **Step 3: Commit**

```bash
git add agent/services/tts_sanitizer.py
git commit -m "feat: tts_sanitizer — strips markdown, hashes, emoji before TTS"
```

---

## Task 11: Emergency Detection Tests (Write First — MVP)

**Files:** Create `tests/unit/test_emergency.py`

> **MVP scope:** No TYPE_1/TYPE_2 classification. Tests verify keyword detection only — returns True if emergency keyword found, False otherwise. The actual string shown to patients comes from `branch.emergency_contact`.

- [ ] **Step 1: Write `tests/unit/test_emergency.py`**

```python
import pytest
from agent.services.emergency import is_emergency


def test_heart_attack_english():
    assert is_emergency("I am having a heart attack") is True


def test_chest_pain_english():
    assert is_emergency("severe chest pain right now") is True


def test_unconscious_english():
    assert is_emergency("he is unconscious on the floor") is True


def test_not_breathing():
    assert is_emergency("patient is not breathing") is True


def test_severe_bleeding():
    assert is_emergency("there is severe bleeding") is True


def test_telugu_emergency_keyword():
    # "padipōyāḍu" = collapsed / fell down
    assert is_emergency("padipōyāḍu") is True


def test_routine_headache_not_emergency():
    assert is_emergency("I have a headache since yesterday") is False


def test_routine_fever_not_emergency():
    assert is_emergency("fever for two days") is False


def test_empty_string_not_emergency():
    assert is_emergency("") is False


def test_routine_dental_not_emergency():
    assert is_emergency("my tooth is paining") is False


def test_case_insensitive():
    assert is_emergency("HEART ATTACK") is True


def test_keyword_in_middle_of_sentence():
    assert is_emergency("please help my father is unconscious") is True
```

- [ ] **Step 2: Run tests to confirm they all fail**

```bash
pytest tests/unit/test_emergency.py -v
# Expected: 12 FAILED (ImportError)
```

- [ ] **Step 3: Commit tests**

```bash
git add tests/unit/test_emergency.py
git commit -m "test: emergency MVP — 12 failing tests (TDD)"
```

---

## Task 12: Emergency Detection Implementation (MVP)

**Files:** Create `agent/services/emergency.py`

- [ ] **Step 1: Write `agent/services/emergency.py`**

```python
import structlog

logger = structlog.get_logger()

_EMERGENCY_KEYWORDS: list[str] = [
    # English
    "heart attack", "chest pain", "not breathing", "unconscious",
    "severe bleeding", "collapsed", "choking", "stroke",
    "seizure", "convulsion", "overdose", "fainted",
    # Telugu (romanized)
    "padipōyāḍu", "collapse", "mūrchanam", "guṇḍe noppi",
    "śvāsa", "blood pōtuṃdi",
    # Common transliteration variants
    "heart attak", "harttak", "hartattack",
]

_KEYWORDS_LOWER: list[str] = [k.lower() for k in _EMERGENCY_KEYWORDS]


def is_emergency(text: str) -> bool:
    """
    MVP: Return True if any emergency keyword appears in the text.
    No TYPE_1/TYPE_2 classification — that is a post-MVP feature.
    Caller is responsible for giving branch.emergency_contact if True.
    """
    if not text:
        return False

    text_lower = text.lower()
    for keyword in _KEYWORDS_LOWER:
        if keyword in text_lower:
            logger.warning("emergency_keyword_detected", keyword=keyword)
            return True

    return False
```

- [ ] **Step 2: Run tests — all 12 must pass**

```bash
pytest tests/unit/test_emergency.py -v
# Expected: 12 passed
```

- [ ] **Step 3: Run both test files together**

```bash
pytest tests/unit/ -v
# Expected: 23 passed (11 + 12)
```

- [ ] **Step 4: Commit**

```bash
git add agent/services/emergency.py
git commit -m "feat: emergency MVP — keyword detection only, no TYPE_1/TYPE_2 classification"
```

---

## Task 13: Session State Dataclass

**Files:** Create `agent/session_state.py`

- [ ] **Step 1: Write `agent/session_state.py`**

```python
from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class SessionState:
    """Per-call state. One instance per LiveKit room. Never shared between calls."""

    # Branch and doctor resolved at call start
    branch_id: UUID | None = None
    doctor_id: UUID | None = None
    patient_name: str | None = None
    patient_phone: str | None = None
    complaint: str | None = None

    # Token / slot tracking
    token_held: bool = False
    token_confirmed: bool = False
    token_redis_key: str | None = None
    token_number: int | None = None
    appointment_time: str | None = None  # "HH:MM" for appointment-type

    # Consent and follow-ups
    followup_consent: bool = False

    # Call type and rebook context
    call_type: str = "inbound_booking"  # inbound_booking | followup | cancellation_notify
    is_rebook: bool = False
    cancelled_token_id: UUID | None = None

    # Solo plan 4-minute cap
    elapsed_seconds: int = 0
    plan: str | None = None  # solo | clinic | multi

    # Logging
    livekit_room_id: str | None = None
```

- [ ] **Step 2: Verify it imports**

```bash
python -c "from agent.session_state import SessionState; s = SessionState(); print(s.call_type)"
# Expected: inbound_booking
```

- [ ] **Step 3: Commit**

```bash
git add agent/session_state.py
git commit -m "feat: session_state dataclass — per-call state tracking"
```

---

## Task 14: System Prompt Builder

**Files:** Create `agent/prompts/system_prompt.py`

- [ ] **Step 1: Write `agent/prompts/system_prompt.py`**

```python
from dataclasses import dataclass


@dataclass
class DoctorContext:
    id: str
    name: str
    specialization: str
    routing_keywords: list[str]
    booking_type: str  # token | appointment
    is_default: bool


def build_system_prompt(
    clinic_name: str,
    doctors: list[DoctorContext],
    emergency_contact: str,
    plan: str,
    is_rebook: bool = False,
    cancelled_date: str | None = None,
) -> str:
    """Build the Telugu system prompt for a specific clinic's voice agent."""

    doctor_list = "\n".join(
        f"  - {d.name} ({d.specialization}), keywords: {', '.join(d.routing_keywords)}, "
        f"booking: {d.booking_type}, default: {d.is_default}"
        for d in doctors
    )

    rebook_instruction = ""
    if is_rebook:
        rebook_instruction = (
            f"\nThis call is a REBOOKING after a cancellation on {cancelled_date}. "
            "The patient's name and doctor are already known. Go directly to checking "
            "availability — skip name collection and routing."
        )

    cap_instruction = ""
    if plan == "solo":
        cap_instruction = (
            "\nCALL TIME LIMIT: This clinic is on the Solo plan. "
            "At 3 minutes 50 seconds, say 'We are about to wrap up, let me confirm your booking.' "
            "The call ends at exactly 4 minutes."
        )

    return f"""You are Vachanam, an AI appointment booking assistant for {clinic_name}.
You speak Telugu. You also understand Hindi and English mixed with Telugu (code-switching is normal).
You are warm, professional, and efficient. You never give medical advice or diagnoses.

CLINIC DOCTORS:
{doctor_list}

EMERGENCY CONTACT: {emergency_contact}
If the patient mentions ANY emergency (heart attack, chest pain, unconscious, severe bleeding, etc.):
→ Say: "నేను అర్థం చేసుకున్నాను. దయచేసి వెంటనే ఈ నంబర్ కు కాల్ చేయండి: {emergency_contact}"
→ Then continue with booking as urgent priority. Never suggest 108.

BOOKING FLOW:
1. Greet the patient warmly in Telugu
2. Ask their name
3. Ask the reason for their visit (complaint)
4. Route to the correct doctor using the doctors list above
5. Check availability using check_availability tool
6. Assign token/slot using assign_token tool
7. Ask for follow-up consent: "మేము తర్వాత follow-up కాల్ చేయవచ్చా?"
8. Confirm all details with the patient
9. Confirm booking using confirm_booking tool

RULES:
- Never pick a day for the patient — always ask which day they want
- Never make medical recommendations
- If doctor routing confidence is low, ask one clarifying question
- If no match, route to the default doctor
- Always sanitize your responses — no markdown, no bullet points, no asterisks{rebook_instruction}{cap_instruction}
"""
```

- [ ] **Step 2: Verify it builds without error**

```python
# Run in python shell
from agent.prompts.system_prompt import build_system_prompt, DoctorContext
prompt = build_system_prompt(
    clinic_name="Test Clinic",
    doctors=[DoctorContext("1", "Dr. Kumar", "general_physician", ["fever", "cold"], "token", True)],
    emergency_contact="+910000000000",
    plan="clinic",
)
print(prompt[:200])
```

- [ ] **Step 3: Commit**

```bash
git add agent/prompts/system_prompt.py
git commit -m "feat: Telugu system prompt builder with emergency, rebook, and solo-cap variants"
```

---

## Task 15: Booking Tools (4 LLM Function Tools)

**Files:** Create `agent/tools/booking_tools.py`

> These are the tools the LLM can call during a voice conversation. They connect to Redis and the DB.

- [ ] **Step 1: Install Redis client**

```bash
pip install redis
```

- [ ] **Step 2: Write `agent/tools/booking_tools.py`**

```python
import json
from datetime import date, timedelta, datetime, time
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.session_state import SessionState
from backend.config import settings
from backend.models.schema import Doctor, Token, Patient, Branch

logger = structlog.get_logger()

redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)


async def route_to_doctor(
    complaint: str,
    branch_id: UUID,
    db: AsyncSession,
    llm_call,  # callable: async (messages: list) -> str
) -> dict:
    """
    Route patient complaint to the correct doctor.
    Returns: {"doctor_id": str | None, "confidence": "high" | "low" | "none"}
    """
    result = await db.execute(
        select(Doctor).where(
            and_(Doctor.branch_id == branch_id, Doctor.status == "active")
        )
    )
    doctors = result.scalars().all()

    if len(doctors) == 1:
        return {"doctor_id": str(doctors[0].id), "confidence": "high"}

    doctors_json = [
        {
            "id": str(d.id),
            "name": d.name,
            "specialization": d.specialization,
            "routing_keywords": d.routing_keywords or [],
            "is_default": d.is_default_doctor,
        }
        for d in doctors
    ]

    prompt = [
        {
            "role": "user",
            "content": (
                f"Patient complaint: '{complaint}'\n"
                f"Doctors: {json.dumps(doctors_json, ensure_ascii=False)}\n"
                "Return JSON only: {\"doctor_id\": \"<uuid or null>\", \"confidence\": \"high|low|none\"}"
            ),
        }
    ]

    try:
        response = await llm_call(prompt)
        parsed = json.loads(response.strip())
        if parsed.get("confidence") == "none":
            default = next((d for d in doctors if d.is_default_doctor), doctors[0])
            return {"doctor_id": str(default.id), "confidence": "none"}
        return parsed
    except Exception as e:
        logger.error("route_to_doctor_failed", error=str(e))
        default = next((d for d in doctors if d.is_default_doctor), doctors[0])
        return {"doctor_id": str(default.id), "confidence": "none"}


async def check_availability(
    doctor_id: UUID,
    branch_id: UUID,
    booking_date: date,
    db: AsyncSession,
    query_start: time | None = None,
    query_end: time | None = None,
) -> str:
    """
    Returns a human-readable string of available slots/token status.
    For token-type: "Doctor has 5 tokens booked today. You will be token number 6."
    For appointment-type: "Doctor is available from 2 PM to 4 PM and 5 PM to 6 PM."
    """
    result = await db.execute(select(Doctor).where(Doctor.id == doctor_id))
    doctor = result.scalar_one_or_none()
    if not doctor:
        return "Doctor not found."

    if doctor.booking_type == "token":
        redis_key = f"token:{doctor_id}:{branch_id}:{booking_date}"
        current = int(await redis_client.get(redis_key) or 0)
        limit = doctor.daily_token_limit or 50
        if current >= limit:
            next_day = booking_date + timedelta(days=1)
            return f"Doctor is fully booked on {booking_date.strftime('%d %B')}. Next available date is {next_day.strftime('%d %B')}."
        return (
            f"Doctor has {current} patients booked on {booking_date.strftime('%d %B')}. "
            f"You will be token number {current + 1}."
        )

    # Appointment type — compute available ranges
    if not doctor.working_hours_start or not doctor.working_hours_end or not doctor.slot_duration_minutes:
        return "Doctor's schedule is not configured. Please call the clinic directly."

    slots = _generate_slots(
        doctor.working_hours_start,
        doctor.working_hours_end,
        doctor.slot_duration_minutes,
    )
    if query_start and query_end:
        slots = [s for s in slots if query_start <= s < query_end]

    available = []
    for slot in slots:
        key = f"slot:{doctor_id}:{branch_id}:{booking_date}:{slot.strftime('%H%M')}"
        booked = int(await redis_client.get(key) or 0)
        if booked < (doctor.max_concurrent_per_slot or 1):
            available.append(slot)

    if not available:
        return f"Doctor is fully booked on {booking_date.strftime('%d %B')}."

    ranges = _merge_to_ranges(available, doctor.slot_duration_minutes)
    range_strs = [
        f"{start.strftime('%I:%M %p').lstrip('0')} to {end.strftime('%I:%M %p').lstrip('0')}"
        for start, end in ranges
    ]
    return f"Doctor is available {' and '.join(range_strs)} on {booking_date.strftime('%d %B')}."


async def assign_token(
    doctor_id: UUID,
    branch_id: UUID,
    booking_date: date,
    db: AsyncSession,
    appointment_time: time | None = None,
) -> dict:
    """
    Atomically assign a token or slot using Redis INCR.
    Returns: {"success": True, "token_number": int, "redis_key": str}
          or {"success": False, "reason": "full"}
    RULE: DECR is the ONLY rollback. Never use it as a primary operation.
    """
    result = await db.execute(select(Doctor).where(Doctor.id == doctor_id))
    doctor = result.scalar_one_or_none()
    if not doctor:
        return {"success": False, "reason": "doctor_not_found"}

    if doctor.booking_type == "token":
        redis_key = f"token:{doctor_id}:{branch_id}:{booking_date}"
        # Midnight of booking_date + 2h buffer
        midnight = datetime.combine(booking_date + timedelta(days=1), time(0, 0))
        ttl_seconds = int((midnight - datetime.now()).total_seconds()) + 7200

        token_number = await redis_client.incr(redis_key)
        await redis_client.expire(redis_key, max(ttl_seconds, 7200))

        limit = doctor.daily_token_limit or 50
        if token_number > limit:
            await redis_client.decr(redis_key)  # rollback
            return {"success": False, "reason": "full"}

        logger.info("token_assigned", doctor_id=str(doctor_id), token=token_number, date=str(booking_date))
        return {"success": True, "token_number": token_number, "redis_key": redis_key}

    else:  # appointment type
        if not appointment_time:
            return {"success": False, "reason": "appointment_time_required"}

        slot_key = f"slot:{doctor_id}:{branch_id}:{booking_date}:{appointment_time.strftime('%H%M')}"
        slot_dt = datetime.combine(booking_date, appointment_time)
        ttl_seconds = int((slot_dt - datetime.now()).total_seconds()) + 7200

        slot_count = await redis_client.incr(slot_key)
        await redis_client.expire(slot_key, max(ttl_seconds, 7200))

        max_per_slot = doctor.max_concurrent_per_slot or 1
        if slot_count > max_per_slot:
            await redis_client.decr(slot_key)  # rollback
            return {"success": False, "reason": "full"}

        logger.info("slot_assigned", doctor_id=str(doctor_id), time=str(appointment_time), date=str(booking_date))
        return {
            "success": True,
            "token_number": slot_count,
            "redis_key": slot_key,
            "appointment_time": appointment_time.strftime("%H:%M"),
        }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
async def confirm_booking(
    doctor_id: UUID,
    branch_id: UUID,
    patient_name: str,
    patient_phone: str | None,
    complaint: str,
    booking_date: date,
    token_number: int,
    followup_consent: bool,
    appointment_time: time | None,
    source: str,
    db: AsyncSession,
    calendar_service,   # CalendarService instance (injected)
    meta_service,       # MetaService instance (injected)
) -> dict:
    """
    Persist booking to DB, create Calendar event (must succeed), send WhatsApp (fire-and-forget).
    Returns: {"success": True, "token_id": str} or {"success": False, "reason": str}
    RULE 4: Calendar first, WhatsApp second — never reverse.
    """
    # 1. Find or create patient
    result = await db.execute(
        select(Patient).where(
            and_(Patient.branch_id == branch_id, Patient.phone == patient_phone)
        )
    )
    patient = result.scalar_one_or_none()
    if not patient:
        patient = Patient(
            branch_id=branch_id,
            name=patient_name,
            phone=patient_phone,
            followup_consent=followup_consent,
        )
        db.add(patient)
        await db.flush()
    else:
        patient.followup_consent = followup_consent

    # 2. Create token record
    token = Token(
        branch_id=branch_id,
        doctor_id=doctor_id,
        patient_id=patient.id,
        date=booking_date,
        token_number=token_number,
        appointment_time=appointment_time,
        source=source,
        status="waiting",
    )
    db.add(token)
    await db.flush()

    # 3. Google Calendar (MUST succeed — raises if fails)
    result = await db.execute(select(Doctor).where(Doctor.id == doctor_id))
    doctor = result.scalar_one()
    result = await db.execute(select(Branch).where(Branch.id == branch_id))
    branch = result.scalar_one()

    event_id = await calendar_service.create_booking_event(
        calendar_id=doctor.google_calendar_id or branch.google_calendar_id,
        patient_name=patient_name,
        patient_phone=patient_phone[-4:] if patient_phone else "unknown",
        token_number=token_number,
        booking_date=booking_date,
        appointment_time=appointment_time,
        doctor_name=doctor.name,
    )
    token.google_calendar_event_id = event_id

    await db.commit()

    logger.info(
        "booking_confirmed",
        branch_id=str(branch_id),
        doctor_id=str(doctor_id),
        token_number=token_number,
        patient_phone=patient_phone[-4:] if patient_phone else "None",
        via=source,
    )

    # 4. WhatsApp (fire-and-forget — never fails booking)
    if patient_phone:
        try:
            await meta_service.send_booking_confirmation(
                to=patient_phone,
                patient_name=patient_name,
                doctor_name=doctor.name,
                clinic_name=branch.name,
                booking_date=booking_date,
                token_number=token_number,
                appointment_time=appointment_time,
            )
        except Exception as e:
            logger.error("whatsapp_confirmation_failed", error=str(e), token_id=str(token.id))

    return {"success": True, "token_id": str(token.id)}


def _generate_slots(start: time, end: time, duration_minutes: int) -> list[time]:
    slots = []
    current = datetime.combine(date.today(), start)
    end_dt = datetime.combine(date.today(), end)
    delta = timedelta(minutes=duration_minutes)
    while current < end_dt:
        slots.append(current.time())
        current += delta
    return slots


def _merge_to_ranges(slots: list[time], duration_minutes: int) -> list[tuple[time, time]]:
    if not slots:
        return []
    ranges = []
    start = prev = slots[0]
    delta = timedelta(minutes=duration_minutes)
    for slot in slots[1:]:
        prev_dt = datetime.combine(date.today(), prev)
        slot_dt = datetime.combine(date.today(), slot)
        if slot_dt == prev_dt + delta:
            prev = slot
        else:
            prev_end = (datetime.combine(date.today(), prev) + delta).time()
            ranges.append((start, prev_end))
            start = prev = slot
    prev_end = (datetime.combine(date.today(), prev) + delta).time()
    ranges.append((start, prev_end))
    return ranges
```

- [ ] **Step 3: Verify it imports**

```bash
python -c "from agent.tools.booking_tools import assign_token, check_availability, confirm_booking, route_to_doctor; print('4 tools OK')"
# Expected: 4 tools OK
```

- [ ] **Step 4: Commit**

```bash
git add agent/tools/booking_tools.py
git commit -m "feat: 4 LLM booking tools — route, check, assign (Redis INCR), confirm (calendar+WA)"
```

---

## Task 16: Voice Agent Entrypoint

**Files:** Create `agent/agent.py`

- [ ] **Step 1: Write `agent/agent.py`**

```python
import asyncio
from datetime import datetime

import structlog
from livekit import agents
from livekit.agents import AgentSession, Agent, RoomInputOptions
from livekit.plugins import sarvam, google, openai as lk_openai

from agent.session_state import SessionState
from agent.services.tts_sanitizer import sanitize_for_tts
from agent.services.emergency import is_emergency
from agent.prompts.system_prompt import build_system_prompt, DoctorContext
from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models.schema import Branch, Doctor
from sqlalchemy import select, and_

logger = structlog.get_logger()

SOLO_CAP_SECONDS = 240  # 4 minutes


class VachananAgent(Agent):
    def __init__(self, state: SessionState) -> None:
        super().__init__(instructions="")  # overridden in on_enter
        self.state = state

    async def on_enter(self) -> None:
        """Fires when agent joins the room. Load clinic context and greet."""
        async with AsyncSessionLocal() as db:
            # Resolve branch from room metadata (set by Vobiz webhook)
            branch_result = await db.execute(
                select(Branch).where(Branch.id == self.state.branch_id)
            )
            branch = branch_result.scalar_one_or_none()
            if not branch:
                await self.session.say(
                    sanitize_for_tts("క్షమించండి, ఈ నంబర్ కు కనెక్ట్ కాలేదు. దయచేసి మళ్ళీ ప్రయత్నించండి.")
                )
                await self.session.disconnect()
                return

            doctor_result = await db.execute(
                select(Doctor).where(
                    and_(Doctor.branch_id == branch.id, Doctor.status == "active")
                )
            )
            doctors = doctor_result.scalars().all()

            doctor_contexts = [
                DoctorContext(
                    id=str(d.id),
                    name=d.name,
                    specialization=d.specialization or "",
                    routing_keywords=d.routing_keywords or [],
                    booking_type=d.booking_type,
                    is_default=d.is_default_doctor,
                )
                for d in doctors
            ]

            self.instructions = build_system_prompt(
                clinic_name=branch.name,
                doctors=doctor_contexts,
                emergency_contact=branch.emergency_contact or branch.whatsapp_number,
                plan=self.state.plan or "clinic",
                is_rebook=self.state.is_rebook,
            )

        greeting = sanitize_for_tts(
            f"నమస్కారం! మీరు {branch.name} కు కాల్ చేశారు. నేను మీకు అపాయింట్‌మెంట్ బుక్ చేయడంలో సహాయం చేస్తాను. మీ పేరు చెప్పగలరా?"
        )
        await self.session.say(greeting)

        logger.info("call_started", branch_id=str(self.state.branch_id), plan=self.state.plan)

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        """Check for emergency keywords in every user utterance."""
        if new_message and is_emergency(new_message.content):
            async with AsyncSessionLocal() as db:
                branch_result = await db.execute(
                    select(Branch).where(Branch.id == self.state.branch_id)
                )
                branch = branch_result.scalar_one_or_none()
                contact = branch.emergency_contact if branch else "the clinic"

            msg = sanitize_for_tts(
                f"నేను అర్థం చేసుకున్నాను. దయచేసి వెంటనే ఈ నంబర్ కు కాల్ చేయండి: {contact}"
            )
            await self.session.say(msg)
            # Continue booking — emergency contact given, do not disconnect

        # Solo plan 4-minute cap
        if self.state.plan == "solo":
            self.state.elapsed_seconds = int(
                (datetime.now() - self._call_start).total_seconds()
            )
            if self.state.elapsed_seconds >= SOLO_CAP_SECONDS - 10:
                await self.session.say(
                    sanitize_for_tts("మేము ముగించబోతున్నాం. మీ బుకింగ్ confirm చేస్తున్నాను.")
                )
            if self.state.elapsed_seconds >= SOLO_CAP_SECONDS:
                logger.info("solo_cap_reached", elapsed=self.state.elapsed_seconds)
                await self.session.disconnect()


async def _llm_with_fallback(messages: list) -> str:
    """Gemini 2.5 Flash primary, GPT-4o mini fallback."""
    try:
        client = google.LLM(model="gemini-2.5-flash", api_key=settings.gemini_api_key)
        # Direct API call for non-streaming use (routing tool)
        import google.generativeai as genai
        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(messages[-1]["content"])
        return response.text
    except Exception as e:
        logger.error("gemini_failed_switching_to_openai", error=str(e))
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.1,
            )
            return resp.choices[0].message.content
        except Exception as e2:
            logger.critical("both_llms_failed", error=str(e2))
            return '{"doctor_id": null, "confidence": "none"}'


async def entrypoint(ctx: agents.JobContext) -> None:
    state = SessionState()
    state.livekit_room_id = ctx.room.name

    # Parse branch_id from room metadata (set by Vobiz webhook handler)
    import json
    metadata = {}
    if ctx.room.metadata:
        try:
            metadata = json.loads(ctx.room.metadata)
        except Exception:
            pass

    from uuid import UUID
    state.branch_id = UUID(metadata.get("branch_id", "")) if metadata.get("branch_id") else None
    state.plan = metadata.get("plan", "clinic")
    state.call_type = metadata.get("call_type", "inbound_booking")
    state.is_rebook = metadata.get("is_rebook", False)
    state._call_start = datetime.now()

    await ctx.connect()

    stt = sarvam.STT(
        api_key=settings.sarvam_api_key,
        model="saaras:v3",
        language="te-IN",
    )
    tts = sarvam.TTS(
        api_key=settings.sarvam_api_key,
        model="bulbul:v3",
        language="te-IN",
    )
    llm = google.LLM(
        model="gemini-2.5-flash",
        api_key=settings.gemini_api_key,
        temperature=0.3,
    )

    session = AgentSession(stt=stt, tts=tts, llm=llm)
    agent = VachananAgent(state=state)

    @session.on("disconnected")
    async def on_disconnect():
        if state.token_held and not state.token_confirmed:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.redis_url)
            await r.decr(state.token_redis_key)
            logger.warning(
                "token_released_on_disconnect",
                token=state.token_number,
                branch_id=str(state.branch_id),
            )

    await session.start(
        room=ctx.room,
        agent=agent,
        room_input_options=RoomInputOptions(),
    )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
```

- [ ] **Step 2: Verify it imports**

```bash
python -c "from agent.agent import entrypoint; print('Agent entrypoint OK')"
# Expected: Agent entrypoint OK
```

- [ ] **Step 3: Commit**

```bash
git add agent/agent.py
git commit -m "feat: livekit voice agent — Gemini LLM, Sarvam STT/TTS, emergency detect, Solo 4-min cap, token rollback on disconnect"
```

---

## Task 17: Integration Test — Full Booking Flow

**Files:** Create `tests/conftest.py` and `tests/integration/test_booking_flow.py`

- [ ] **Step 1: Write `tests/conftest.py`**

```python
import asyncio
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from backend.models.schema import Base
from backend.config import settings


TEST_DB_URL = settings.database_url  # uses local docker DB


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def redis():
    r = aioredis.from_url("redis://localhost:6379", decode_responses=True)
    yield r
    await r.flushdb()  # clean up after each test
    await r.aclose()
```

- [ ] **Step 2: Write `tests/integration/test_booking_flow.py`**

```python
import pytest
import pytest_asyncio
from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy import select

from backend.models.schema import Organization, Branch, Doctor, Patient, Token
from agent.tools.booking_tools import check_availability, assign_token


@pytest_asyncio.fixture
async def seeded_clinic(db):
    """Create a minimal clinic: org → branch → doctor (token type, limit 20)."""
    org = Organization(
        name="Test Clinic",
        owner_phone="+919999999999",
        owner_email="test@testclinic.com",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()

    branch = Branch(
        org_id=org.id,
        name="Test Clinic Branch",
        whatsapp_number="+911111111111",
        did_number="+912222222222",
        emergency_contact="+913333333333",
        status="active",
    )
    db.add(branch)
    await db.flush()

    doctor = Doctor(
        branch_id=branch.id,
        name="Dr. Test",
        specialization="general_physician",
        routing_keywords=["fever", "cold", "headache"],
        is_default_doctor=True,
        booking_type="token",
        daily_token_limit=20,
        status="active",
    )
    db.add(doctor)
    await db.commit()
    return {"org": org, "branch": branch, "doctor": doctor}


@pytest.mark.asyncio
async def test_check_availability_returns_speech_string(seeded_clinic, db, redis):
    branch = seeded_clinic["branch"]
    doctor = seeded_clinic["doctor"]
    today = date.today()

    result = await check_availability(doctor.id, branch.id, today, db)

    assert "token" in result.lower() or "available" in result.lower()
    assert str(today.day) in result or "0" in result


@pytest.mark.asyncio
async def test_assign_token_returns_sequential_numbers(seeded_clinic, db, redis):
    branch = seeded_clinic["branch"]
    doctor = seeded_clinic["doctor"]
    today = date.today() + timedelta(days=1)  # tomorrow to avoid test pollution

    result1 = await assign_token(doctor.id, branch.id, today, db)
    result2 = await assign_token(doctor.id, branch.id, today, db)

    assert result1["success"] is True
    assert result2["success"] is True
    assert result2["token_number"] == result1["token_number"] + 1


@pytest.mark.asyncio
async def test_assign_token_respects_daily_limit(seeded_clinic, db, redis):
    branch = seeded_clinic["branch"]
    doctor = seeded_clinic["doctor"]
    today = date.today() + timedelta(days=2)

    # Fill up the queue (limit=20)
    for _ in range(20):
        await assign_token(doctor.id, branch.id, today, db)

    # 21st should fail
    result = await assign_token(doctor.id, branch.id, today, db)
    assert result["success"] is False
    assert result["reason"] == "full"


@pytest.mark.asyncio
async def test_token_rollback_on_full(seeded_clinic, db, redis):
    """After a 'full' rejection, the Redis counter must not have incremented."""
    import redis.asyncio as aioredis
    branch = seeded_clinic["branch"]
    doctor = seeded_clinic["doctor"]
    today = date.today() + timedelta(days=3)

    for _ in range(20):
        await assign_token(doctor.id, branch.id, today, db)

    r = aioredis.from_url("redis://localhost:6379", decode_responses=True)
    counter_before = int(await r.get(f"token:{doctor.id}:{branch.id}:{today}") or 0)

    await assign_token(doctor.id, branch.id, today, db)  # 21st — should fail + DECR

    counter_after = int(await r.get(f"token:{doctor.id}:{branch.id}:{today}") or 0)
    assert counter_after == counter_before  # DECR rolled it back
    await r.aclose()
```

- [ ] **Step 3: Run integration tests**

```bash
pytest tests/integration/test_booking_flow.py -v
# Expected: 4 passed
# If failing: check docker-compose is up (docker-compose ps)
```

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/integration/test_booking_flow.py
git commit -m "test: integration — booking flow with token assignment, limit enforcement, and DECR rollback"
```

---

## Task 18: Edge Case — 5 Concurrent Callers

**Files:** Create `tests/edge_cases/test_concurrent_tokens.py`

> This is the most critical correctness test. 5 callers must never get the same token number.

- [ ] **Step 1: Write `tests/edge_cases/test_concurrent_tokens.py`**

```python
import asyncio
import pytest
import pytest_asyncio
from datetime import date, timedelta
from uuid import uuid4

from backend.models.schema import Organization, Branch, Doctor
from agent.tools.booking_tools import assign_token


@pytest_asyncio.fixture
async def concurrent_clinic(db):
    org = Organization(
        name="Concurrent Test Clinic",
        owner_phone="+919988776655",
        owner_email="concurrent@test.com",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()

    branch = Branch(
        org_id=org.id,
        name="Concurrent Branch",
        whatsapp_number="+911234567890",
        status="active",
    )
    db.add(branch)
    await db.flush()

    doctor = Doctor(
        branch_id=branch.id,
        name="Dr. Concurrent",
        specialization="general_physician",
        is_default_doctor=True,
        booking_type="token",
        daily_token_limit=50,
        status="active",
    )
    db.add(doctor)
    await db.commit()
    return {"branch": branch, "doctor": doctor}


@pytest.mark.asyncio
async def test_five_concurrent_callers_get_unique_tokens(concurrent_clinic, db):
    """
    5 callers attempt to book simultaneously.
    CRITICAL: All successful bookings must have unique token numbers.
    No token number may appear twice.
    """
    branch = concurrent_clinic["branch"]
    doctor = concurrent_clinic["doctor"]
    booking_date = date.today() + timedelta(days=5)

    async def book_one_caller() -> dict:
        return await assign_token(doctor.id, branch.id, booking_date, db)

    results = await asyncio.gather(*[book_one_caller() for _ in range(5)])

    successful = [r for r in results if r["success"]]
    token_numbers = [r["token_number"] for r in successful]

    assert len(successful) == 5, f"Expected 5 successes, got {len(successful)}"
    assert len(set(token_numbers)) == 5, (
        f"Duplicate tokens found! Numbers: {sorted(token_numbers)}"
    )
    assert sorted(token_numbers) == list(range(1, 6)), (
        f"Expected sequential 1-5, got {sorted(token_numbers)}"
    )


@pytest.mark.asyncio
async def test_concurrent_callers_at_limit_boundary(concurrent_clinic, db):
    """
    49 tokens pre-booked. Then 3 callers arrive simultaneously.
    Exactly 1 should succeed (gets token 50). 2 should get 'full'.
    Counter after: must be exactly 50 (rollbacks applied for the 2 failures).
    """
    import redis.asyncio as aioredis
    branch = concurrent_clinic["branch"]
    doctor = concurrent_clinic["doctor"]
    booking_date = date.today() + timedelta(days=6)

    # Pre-fill 49 tokens
    for _ in range(49):
        result = await assign_token(doctor.id, branch.id, booking_date, db)
        assert result["success"] is True

    # 3 callers race for the last token
    results = await asyncio.gather(*[
        assign_token(doctor.id, branch.id, booking_date, db)
        for _ in range(3)
    ])

    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]

    assert len(successes) == 1, f"Expected 1 success at limit, got {len(successes)}"
    assert len(failures) == 2
    assert successes[0]["token_number"] == 50

    # Verify Redis counter is exactly 50 (not 51 or 52 — rollbacks worked)
    r = aioredis.from_url("redis://localhost:6379", decode_responses=True)
    counter = int(await r.get(f"token:{doctor.id}:{branch.id}:{booking_date}") or 0)
    assert counter == 50, f"Expected Redis counter=50 after rollbacks, got {counter}"
    await r.aclose()
```

- [ ] **Step 2: Run edge case tests**

```bash
pytest tests/edge_cases/test_concurrent_tokens.py -v
# Expected: 2 passed
# These are the most critical correctness tests in the entire codebase
```

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v
# Expected: 27 passed (11 + 12 + 4 + 2 + conftest fixtures)
```

- [ ] **Step 4: Commit**

```bash
git add tests/edge_cases/test_concurrent_tokens.py
git commit -m "test: concurrent token assignment — 5 simultaneous callers get unique sequential tokens"
```

---

## Phase 0+1 Exit Criteria

Before moving to Phase 2, every item below must be checked:

```
Phase 0:
□ docker-compose up runs cleanly — postgres and redis both show "Up"
□ alembic upgrade head completes with 0 errors
□ \dt in psql shows all 9 tables
□ python -c "from backend.config import settings; print(settings.app_env)" prints "development"

Phase 1:
□ pytest tests/unit/ -v → 23 passed (11 tts + 12 emergency)
□ pytest tests/integration/ -v → 4 passed
□ pytest tests/edge_cases/ -v → 2 passed
□ pytest tests/ -v → 27 passed, 0 failed
□ python -c "from agent.agent import entrypoint; print('OK')" → no ImportError
□ python agent/agent.py --help shows LiveKit CLI options (requires LIVEKIT_URL set)
```

---

*Plans for Phases 2–5 will be created at the start of each phase.*
*Reference: `PHASE_2_BACKEND.md`, `PHASE_3_FRONTEND.md`, `PHASE_4_ONBOARDING.md`, `PHASE_5_PRODUCTION.md`*
