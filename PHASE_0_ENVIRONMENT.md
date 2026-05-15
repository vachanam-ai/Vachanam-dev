# PHASE_0_ENVIRONMENT.md — Environment Setup
## Complete this phase before writing any application code.
## Every step is mandatory. Every exit criterion must pass.

---

## WHY THIS PHASE EXISTS

You cannot build on a broken foundation. This phase ensures:
- Local development environment is identical for every machine
- All external accounts are created and keys are in hand
- Database schema is correct before any code touches it
- All 25 environment variables are populated and tested
- One-time regulatory actions are started (GST, Vobiz Partner, Sarvam credits)

**Time estimate:** 1–2 days (Vobiz Partner approval takes 1 business day)
**Cost:** ₹0

---

## STEP 1 — ACCOUNTS TO CREATE

Create all accounts before writing code. Some take days to approve.

### Immediate (create today)

| Service | URL | Purpose | Cost |
|---|---|---|---|
| Sarvam AI | sarvam.ai | STT + TTS API keys | ₹0 (₹1,000 free credits) |
| OpenAI | platform.openai.com | GPT-4o mini API key | Pay-as-you-go |
| Google Cloud | console.cloud.google.com | Calendar API + OAuth | Free |
| Fly.io | fly.io | Voice agent hosting | Pay-as-you-go |
| Render | render.com | Backend API hosting | Free → $7/month |
| Neon | neon.tech | Managed Postgres | Free → $5/month |
| Upstash | upstash.com | Managed Redis | Free |
| Cloudflare | cloudflare.com | Pages hosting | Free |
| GitHub | github.com | Source control | Free |
| UptimeRobot | uptimerobot.com | Health monitoring | Free |

### Requires documents (start immediately, takes days)

| Service | URL | What you need | Time |
|---|---|---|---|
| Meta Business Manager | business.facebook.com | GST number + address proof | 2–4 days |
| Razorpay | razorpay.com | GST number + bank account | After GST |
| Vobiz Partner API | docs.vobiz.ai | Email support@vobiz.ai | 1 business day |
| Twilio (dev backup) | twilio.com | Just Gmail — no documents | Instant |

### Email to send today — Vobiz Partner API

```
To: support@vobiz.ai
Subject: Partner API Access Request — Vachanam AI Voice Agent

Hi,

I am building Vachanam, an AI-powered appointment booking platform
for Indian clinics. I need programmatic control to provision DID
numbers and configure inbound call webhooks for each clinic.

I am requesting access to the Vobiz Partner Program API for:
- Creating sub-accounts per clinic
- Provisioning Indian DID numbers via API
- Configuring inbound WebSocket call webhooks
- Monitoring wallet balances and call volumes

Website: vachanam.in
Use case: B2B SaaS — AI receptionist for Indian clinics
Expected volume: 5 clinics month 1, scaling to 50+

Please let me know the requirements to proceed.

Vinay Rongala
Founder, Vachanam
hello@vachanam.in
+91-XXXXXXXXXX
```

### Apply for Sarvam startup credits

URL: sarvam.ai/startup-program
This gives free STT + TTS credits for 6–12 months.
Without this: margins are 44–57%.
With this: margins jump to 63–72%.
**This is the single highest-impact action you can take right now.**

---

## STEP 2 — ONE-TIME REGULATORY ACTIONS

### GST Registration (mandatory for Razorpay, Meta Business)
- URL: gst.gov.in → New Registration
- Business type: Proprietorship (you don't need a Pvt Ltd)
- Trade name: Vachanam
- Documents: Aadhar + PAN + bank account statement
- Cost: ₹0
- Time: 3–5 business days
- **Start this today. Everything else waits on it.**

### Google Service Account Setup
```bash
# In Google Cloud Console:
1. Create project: "vachanam-production"
2. Enable: Google Calendar API
3. Create Service Account: vachanam-calendar@vachanam-production.iam.gserviceaccount.com
4. Create and download JSON key → save as google-service-account.json
5. NEVER commit this file. Add to .gitignore immediately.

# The service account needs these scopes:
# https://www.googleapis.com/auth/calendar
```

### Meta WhatsApp Business Setup
```
1. Create Meta Business Manager account (business.facebook.com)
2. Verify business identity (GST + address proof) → 2–4 days
3. Create WhatsApp Business Account (WABA)
4. Add phone number (get OTP on the number)
5. Create message templates:
   - appointment_confirmation (utility)
   - doctor_notification (utility)
   - followup_check (utility)
6. Get permanent access token from Meta dashboard
7. Configure webhook URL (after backend is deployed):
   https://vachanam-backend.onrender.com/webhook/whatsapp
8. Set webhook verify token (any random string, put in .env)
```

---

## STEP 3 — LOCAL DEVELOPMENT SETUP

### .gitignore (create first)
```
# Secrets — never commit these
.env
*.env
.env.*
!.env.example
google-service-account.json
*.pem
*.key
*.p8

# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.coverage
htmlcov/
*.egg-info/
dist/
build/
venv/
.venv/

# Node
node_modules/
frontend/dist/

# IDE
.vscode/
.idea/
*.swp
*.swo
.DS_Store

# Fly.io local overrides
fly.toml.local

# Logs
*.log
logs/
```

### docker-compose.yml (local development only)
```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: vachanam_dev
      POSTGRES_USER: vachanam
      POSTGRES_PASSWORD: localdev123
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U vachanam -d vachanam_dev"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    command: redis-server --save "" --appendonly no
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  livekit:
    image: livekit/livekit-server:latest
    command: --dev --bind 0.0.0.0
    ports:
      - "7880:7880"
      - "7881:7881"
      - "7882:7882/udp"
    environment:
      - LIVEKIT_KEYS=devkey:devsecret

volumes:
  postgres_data:
```

Run it:
```bash
docker-compose up -d
docker-compose ps
# All three must show as healthy before continuing
```

---

## STEP 4 — PYTHON ENVIRONMENT

```bash
# Must use Python 3.11 exactly
python3.11 --version  # Must show 3.11.x
python3.11 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install --upgrade pip
```

### agent/requirements.txt
```txt
# LiveKit
livekit-agents[openai,sarvam]==1.4.*
livekit-plugins-sarvam

# AI
openai>=1.30.0
google-generativeai>=0.5.0

# Database
sqlalchemy[asyncio]>=2.0.0
asyncpg>=0.29.0
alembic>=1.13.0

# Redis
upstash-redis>=1.0.0

# Google
google-auth>=2.29.0
google-auth-oauthlib>=1.2.0
google-api-python-client>=2.127.0

# HTTP
httpx>=0.27.0
tenacity>=8.3.0

# Config
python-dotenv>=1.0.0
pydantic>=2.7.0
pydantic-settings>=2.2.0

# Logging
structlog>=24.1.0

# Testing
pytest>=8.1.0
pytest-asyncio>=0.23.0
pytest-cov>=5.0.0
ruff>=0.4.0
```

### backend/requirements.txt
```txt
# Web framework
fastapi>=0.110.0
uvicorn[standard]>=0.29.0

# Database
sqlalchemy[asyncio]>=2.0.0
asyncpg>=0.29.0
alembic>=1.13.0

# Redis
upstash-redis>=1.0.0

# Google
google-auth>=2.29.0
google-auth-oauthlib>=1.2.0
google-api-python-client>=2.127.0

# AI (for WhatsApp NLP)
openai>=1.30.0
google-generativeai>=0.5.0

# HTTP
httpx>=0.27.0
tenacity>=8.3.0

# Config
python-dotenv>=1.0.0
pydantic>=2.7.0
pydantic-settings>=2.2.0

# Auth
python-jose[cryptography]>=3.3.0

# Scheduling
apscheduler>=3.10.0

# Payment
razorpay>=1.4.0

# Logging
structlog>=24.1.0

# Testing
pytest>=8.1.0
pytest-asyncio>=0.23.0
pytest-cov>=5.0.0
ruff>=0.4.0
```

Install both:
```bash
pip install -r agent/requirements.txt
pip install -r backend/requirements.txt
```

---

## STEP 5 — BACKEND CONFIG

### backend/config.py
```python
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    # App
    app_env: str = "development"
    base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    log_level: str = "debug"
    admin_phone: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://vachanam:localdev123@localhost:5432/vachanam_dev"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # AI
    sarvam_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # LiveKit
    livekit_url: str = "ws://localhost:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "devsecret"

    # Telephony — Vobiz
    vobiz_api_key: str = ""
    vobiz_api_secret: str = ""
    vobiz_webhook_secret: str = ""
    vobiz_partner_auth_id: str = ""
    vobiz_partner_auth_token: str = ""

    # Telephony — Twilio (backup)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""

    # WhatsApp — Meta Cloud API
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

    # Auth
    jwt_secret: str = "dev-secret-change-in-production"
    jwt_expire_hours: int = 24

    # Payment
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_plan_solo_id: str = ""
    razorpay_plan_clinic_id: str = ""
    razorpay_plan_multi_id: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
```

---

## STEP 6 — DATABASE SETUP

### backend/database.py
```python
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker
)
from sqlalchemy.orm import DeclarativeBase
from backend.config import settings
import structlog

logger = structlog.get_logger()

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("database_initialized")
```

### backend/models/schema.py
```python
import uuid
from datetime import datetime, date
from sqlalchemy import (
    String, Boolean, Integer, Date, DateTime, Text,
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from backend.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Organisation(Base):
    __tablename__ = "organisations"
    org_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_email: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    # solo | clinic | multi
    plan: Mapped[str] = mapped_column(String(20), nullable=False)
    plan_price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_trial: Mapped[bool] = mapped_column(Boolean, default=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    branches: Mapped[list["Branch"]] = relationship("Branch", back_populates="organisation")


class Branch(Base):
    __tablename__ = "branches"
    branch_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organisations.org_id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str] = mapped_column(String(100), default="Hyderabad")
    state: Mapped[str] = mapped_column(String(100), default="Telangana")
    # Telephony
    vobiz_did: Mapped[str | None] = mapped_column(String(20), unique=True)
    vobiz_auth_id: Mapped[str | None] = mapped_column(String(100))
    vobiz_auth_token: Mapped[str | None] = mapped_column(String(200))
    # WhatsApp
    meta_phone_number_id: Mapped[str | None] = mapped_column(String(50))
    # Google
    calendar_ids: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Settings
    primary_language: Mapped[str] = mapped_column(String(10), default="te-IN")
    working_hours_start: Mapped[str] = mapped_column(String(5), default="09:00")
    working_hours_end: Mapped[str] = mapped_column(String(5), default="18:00")
    closed_days: Mapped[list] = mapped_column(JSONB, default=list)
    has_ambulance: Mapped[bool] = mapped_column(Boolean, default=False)
    ambulance_driver_phone: Mapped[str | None] = mapped_column(String(20))
    emergency_fallback_phone: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    organisation: Mapped["Organisation"] = relationship("Organisation", back_populates="branches")
    __table_args__ = (
        Index("idx_branches_org", "org_id"),
        Index("idx_branches_did", "vobiz_did"),
    )


class Doctor(Base):
    __tablename__ = "doctors"
    doctor_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    branch_id: Mapped[str] = mapped_column(String(36), ForeignKey("branches.branch_id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    personal_phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(200))
    speciality: Mapped[str | None] = mapped_column(String(200))
    # booking_type: "token" | "slot"
    booking_type: Mapped[str] = mapped_column(String(10), default="token")
    daily_token_limit: Mapped[int] = mapped_column(Integer, default=30)
    slot_duration_mins: Mapped[int] = mapped_column(Integer, default=15)
    hours_start: Mapped[str] = mapped_column(String(5), default="09:00")
    hours_end: Mapped[str] = mapped_column(String(5), default="17:00")
    working_days: Mapped[list] = mapped_column(JSONB, default=lambda: [0,1,2,3,4,5])
    # Telugu + English symptom keywords this doctor treats
    treats_keywords: Mapped[list] = mapped_column(JSONB, default=list)
    # Google Calendar ID for this doctor's appointments
    calendar_id: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        Index("idx_doctors_branch", "branch_id"),
        Index("idx_doctors_phone", "personal_phone"),
    )


class Patient(Base):
    __tablename__ = "patients"
    patient_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    branch_id: Mapped[str] = mapped_column(String(36), ForeignKey("branches.branch_id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    preferred_language: Mapped[str] = mapped_column(String(10), default="te-IN")
    call_recording_consent: Mapped[bool | None] = mapped_column(Boolean)
    # WhatsApp conversation state: {"state": "IDLE", "context": {...}}
    wa_conversation_state: Mapped[dict] = mapped_column(JSONB, default=lambda: {"state": "IDLE"})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("phone", "branch_id", name="uq_patient_phone_branch"),
        Index("idx_patients_phone", "phone"),
        Index("idx_patients_branch", "branch_id"),
    )


class Token(Base):
    __tablename__ = "tokens"
    token_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    doctor_id: Mapped[str] = mapped_column(String(36), ForeignKey("doctors.doctor_id"), nullable=False)
    branch_id: Mapped[str] = mapped_column(String(36), ForeignKey("branches.branch_id"), nullable=False)
    patient_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("patients.patient_id"))
    date: Mapped[date] = mapped_column(Date, nullable=False)
    token_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # confirmed | attended | no_show | cancelled | expired
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    # voice | whatsapp | walk_in
    booked_via: Mapped[str] = mapped_column(String(20), default="voice")
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    calendar_event_id: Mapped[str | None] = mapped_column(String(200))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    attended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    marked_by_user_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("doctor_id", "branch_id", "date", "token_number", name="uq_token"),
        Index("idx_tokens_doctor_branch_date", "doctor_id", "branch_id", "date"),
        Index("idx_tokens_patient", "patient_id"),
        Index("idx_tokens_status", "status"),
    )


class Slot(Base):
    __tablename__ = "slots"
    slot_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    doctor_id: Mapped[str] = mapped_column(String(36), ForeignKey("doctors.doctor_id"), nullable=False)
    branch_id: Mapped[str] = mapped_column(String(36), ForeignKey("branches.branch_id"), nullable=False)
    patient_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("patients.patient_id"))
    slot_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_mins: Mapped[int] = mapped_column(Integer, default=15)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    booked_via: Mapped[str] = mapped_column(String(20), default="voice")
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    calendar_event_id: Mapped[str | None] = mapped_column(String(200))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    attended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("doctor_id", "branch_id", "slot_datetime", name="uq_slot"),
        Index("idx_slots_doctor_branch", "doctor_id", "branch_id"),
    )


class FollowupTask(Base):
    __tablename__ = "followup_tasks"
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    doctor_id: Mapped[str] = mapped_column(String(36), ForeignKey("doctors.doctor_id"), nullable=False)
    branch_id: Mapped[str] = mapped_column(String(36), ForeignKey("branches.branch_id"), nullable=False)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.patient_id"), nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    # call | whatsapp | both
    channel: Mapped[str] = mapped_column(String(20), default="both")
    what_to_ask: Mapped[str] = mapped_column(Text, nullable=False)
    # pending | completed | failed | skipped
    status: Mapped[str] = mapped_column(String(20), default="pending")
    doctor_instruction: Mapped[str | None] = mapped_column(Text)
    patient_response: Mapped[str | None] = mapped_column(Text)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        Index("idx_followup_date_status", "scheduled_date", "status"),
        Index("idx_followup_branch", "branch_id"),
    )


class UserAccess(Base):
    __tablename__ = "user_access"
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    google_id: Mapped[str | None] = mapped_column(String(200))
    # super_admin | org_admin | branch_manager | receptionist | doctor
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    org_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("organisations.org_id"))
    branch_ids: Mapped[list] = mapped_column(JSONB, default=list)
    doctor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("doctors.doctor_id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("email", "org_id", name="uq_user_email_org"),
        Index("idx_user_access_email", "email"),
    )


class CallLog(Base):
    __tablename__ = "call_logs"
    call_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    branch_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("branches.branch_id"))
    vobiz_call_id: Mapped[str | None] = mapped_column(String(200))
    caller_phone_last4: Mapped[str | None] = mapped_column(String(4))
    patient_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("patients.patient_id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_secs: Mapped[int | None] = mapped_column(Integer)
    # booked | cancelled | transferred | no_action | dropped | emergency
    outcome: Mapped[str | None] = mapped_column(String(50))
    was_emergency: Mapped[bool] = mapped_column(Boolean, default=False)
    # type_1 | type_2 | null
    emergency_type: Mapped[str | None] = mapped_column(String(20))
    recording_consent: Mapped[bool | None] = mapped_column(Boolean)
    error_message: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        Index("idx_call_logs_branch", "branch_id"),
        Index("idx_call_logs_date", "started_at"),
    )


class WhatsappLog(Base):
    __tablename__ = "whatsapp_logs"
    log_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    branch_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("branches.branch_id"))
    direction: Mapped[str | None] = mapped_column(String(10))
    sender_phone_last4: Mapped[str | None] = mapped_column(String(4))
    receiver_phone: Mapped[str | None] = mapped_column(String(20))
    message_preview: Mapped[str | None] = mapped_column(String(100))
    # patient | doctor | unknown
    sender_role: Mapped[str | None] = mapped_column(String(20))
    meta_message_id: Mapped[str | None] = mapped_column(String(200))
    # sent | delivered | read | failed
    status: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
```

---

## STEP 7 — ALEMBIC SETUP

```bash
cd backend
alembic init migrations

# Edit alembic.ini:
# sqlalchemy.url = postgresql+asyncpg://vachanam:localdev123@localhost:5432/vachanam_dev

# Edit migrations/env.py — add after existing imports:
# from backend.models.schema import Base
# target_metadata = Base.metadata
# Also configure async engine setup in env.py (see Alembic async docs)

# Generate first migration
alembic revision --autogenerate -m "initial_schema"

# Apply migration
alembic upgrade head

# Verify (connects to local docker postgres)
docker exec -it $(docker ps -q -f name=postgres) \
  psql -U vachanam -d vachanam_dev -c "\dt"
```

Expected output — all 10 tables:
```
 Schema |       Name        | Type  |
--------+-------------------+-------+
 public | branches          | table |
 public | call_logs         | table |
 public | doctors           | table |
 public | followup_tasks    | table |
 public | organisations     | table |
 public | patients          | table |
 public | slots             | table |
 public | tokens            | table |
 public | user_access       | table |
 public | whatsapp_logs     | table |
```

---

## STEP 8 — FASTAPI SKELETON

### backend/main.py
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from backend.config import settings
from backend.database import init_db

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", env=settings.app_env, version="1.0.0")
    await init_db()
    # Start background job scheduler here in Phase 2
    yield
    logger.info("shutdown")


app = FastAPI(
    title="Vachanam API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "1.0.0",
        "env": settings.app_env
    }
```

Start it:
```bash
uvicorn backend.main:app --reload --port 8000
```

---

## STEP 9 — .env FILE

Create `.env` in project root. Copy from `.env.example` and fill in:
```bash
# Minimum values needed for Phase 0 to pass:
DATABASE_URL=postgresql+asyncpg://vachanam:localdev123@localhost:5432/vachanam_dev
REDIS_URL=redis://localhost:6379
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=devsecret
APP_ENV=development
JWT_SECRET=dev-secret-change-in-production
LOG_LEVEL=debug

# Fill these in when you have the keys:
SARVAM_API_KEY=
OPENAI_API_KEY=
```

---

## STEP 10 — TEST SETUP

### tests/conftest.py
```python
import pytest
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from backend.models.schema import Base

TEST_DATABASE_URL = "postgresql+asyncpg://vachanam:localdev123@localhost:5432/vachanam_dev"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()
```

Run:
```bash
pytest tests/ -v
# Expected: 0 tests collected, 0 failures (empty suite is fine)
```

---

## PHASE 0 EXIT CRITERIA

**Do not proceed to Phase 1 until every item below is confirmed.**

```
INFRASTRUCTURE
□ docker-compose up -d → postgres, redis, livekit all show "healthy"
□ docker-compose ps → all 3 services running, no errors
□ curl http://localhost:8000/health → {"status":"ok","version":"1.0.0","env":"development"}
□ psql -h localhost -U vachanam -d vachanam_dev -c "\dt" → 10 tables listed

DATABASE
□ alembic upgrade head → "Running upgrade -> xxxx, initial_schema"
□ All 10 tables present in local postgres
□ No alembic errors

REDIS
□ redis-cli -h localhost ping → PONG
□ redis-cli -h localhost INCR test:token → returns 1
□ redis-cli -h localhost INCR test:token → returns 2
□ redis-cli -h localhost DEL test:token → cleanup

PYTHON
□ python --version → 3.11.x
□ pip install -r agent/requirements.txt → no errors
□ pip install -r backend/requirements.txt → no errors
□ python -c "import livekit; print(livekit.__version__)" → no error
□ python -c "import sqlalchemy; print(sqlalchemy.__version__)" → no error

API KEYS (test each one)
□ SARVAM_API_KEY — test with curl:
  curl -X POST https://api.sarvam.ai/v1/text-to-speech \
    -H "api-subscription-key: $SARVAM_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"target_language_code":"te-IN","text":"Hello","speaker":"meera"}' \
    → Returns audio bytes (not 401)

□ OPENAI_API_KEY — test with:
  python -c "
  import openai, os
  c = openai.OpenAI(api_key=os.environ['OPENAI_API_KEY'])
  r = c.chat.completions.create(model='gpt-4o-mini',
      messages=[{'role':'user','content':'say ok'}], max_tokens=5)
  print(r.choices[0].message.content)
  "
  → Prints "ok" or similar

□ Google service account — test with:
  python -c "
  from google.oauth2.service_account import Credentials
  from googleapiclient.discovery import build
  creds = Credentials.from_service_account_file(
      'google-service-account.json',
      scopes=['https://www.googleapis.com/auth/calendar'])
  service = build('calendar', 'v3', credentials=creds)
  print('Google Calendar OK')
  "
  → Prints "Google Calendar OK"

TESTS
□ pytest tests/ -v → 0 failures (0 tests collected is acceptable)

REGULATORY
□ GST registration application submitted (gst.gov.in)
□ Vobiz Partner API email sent (support@vobiz.ai)
□ Sarvam startup program applied (sarvam.ai/startup-program)
□ Meta Business Manager account created
```

**ALL items above must be checked. Then and only then: proceed to PHASE_1_VOICE_AGENT.md**
