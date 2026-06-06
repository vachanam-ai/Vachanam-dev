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
    users: Mapped[list["User"]] = relationship(back_populates="organization")


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # RESTRICT: org must be explicitly cleared before a branch can be deleted (DPDP data-lifecycle)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    # whatsapp_number: human-readable phone (+91XXXXXXXXXX) used in messages
    whatsapp_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    # meta_phone_number_id: Meta's internal numeric ID — used to identify receiving branch in webhook
    meta_phone_number_id: Mapped[str | None] = mapped_column(String(50), unique=True)
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
    # RESTRICT: patients/tokens must be deleted before a branch can be removed
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
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
    # whatsapp_number: doctor's personal WhatsApp for receiving commands and EOD summaries
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
    # RESTRICT: patient rows carry PII; must be explicitly deleted before branch removal (DPDP)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
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
    # RESTRICT: explicit deletion path for booking records (audit trail)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    token_number: Mapped[int | None] = mapped_column(Integer)
    appointment_time: Mapped[time | None] = mapped_column(Time)
    source: Mapped[str] = mapped_column(
        Enum("voice", "whatsapp", "walk_in", name="booking_source"),
        nullable=False,
    )
    # Status lifecycle: confirmed → attended | no_show | cancelled_by_clinic
    status: Mapped[str] = mapped_column(
        Enum("confirmed", "attended", "no_show", "cancelled_by_clinic", name="token_status"),
        default="confirmed",
        nullable=False,
    )
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    call_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    google_calendar_event_id: Mapped[str | None] = mapped_column(String(255))
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # marked_by_user_id: UUID of User who marked attendance (plain UUID, no FK to avoid circular deps)
    marked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
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
    # RESTRICT: call records reference branches; explicit deletion required
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # RESTRICT (conservative): nullable FK — doctor may be deleted later but call record must be retained
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("doctors.id", ondelete="RESTRICT"), index=True
    )
    # RESTRICT: token link; caller must explicitly handle before token deletion
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tokens.id", ondelete="RESTRICT"), index=True
    )
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
    session_id: Mapped[str | None] = mapped_column("livekit_room_id", String(255))
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
    # RESTRICT: followup tasks reference live patient + doctor data; explicit deletion
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requested_by_doctor_whatsapp: Mapped[str | None] = mapped_column(String(20))
    topic: Mapped[str | None] = mapped_column(Text)
    # what_to_ask: the specific question/instruction to relay to the patient
    what_to_ask: Mapped[str | None] = mapped_column(Text)
    # channel: how to reach the patient
    channel: Mapped[str] = mapped_column(
        Enum("whatsapp", "voice", "both", name="followup_channel"),
        default="whatsapp",
        nullable=False,
    )
    response_summary: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(
        Enum("pending", "in_progress", "completed", "unreachable", name="followup_status"),
        default="pending",
        nullable=False,
    )
    # scheduled_date: which day to run the follow-up (compared to date.today() in job)
    scheduled_date: Mapped[date | None] = mapped_column(Date)
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
    # RESTRICT: billing records must not be silently removed when org is deleted (financial audit trail)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    cycle_start: Mapped[date] = mapped_column(Date, nullable=False)
    cycle_end: Mapped[date] = mapped_column(Date, nullable=False)
    plan: Mapped[str] = mapped_column(String(20), nullable=False)
    base_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    included_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    minutes_used: Mapped[int] = mapped_column(Integer, default=0)
    overage_minutes: Mapped[int] = mapped_column(Integer, default=0)
    overage_rate: Mapped[int] = mapped_column(Integer, default=0)
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
    # CASCADE: session has no independent meaning without its branch; safe to cascade delete
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True
    )
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
    # session_data: stores context between messages (doctor_id, date_str, token_redis_key, etc.)
    session_data: Mapped[dict | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    branch: Mapped["Branch"] = relationship(back_populates="whatsapp_sessions")


class User(Base):
    """Clinic staff: owners, receptionists. Also used for Vachanam platform admin (is_admin=True)."""
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # RESTRICT: user org membership must be explicitly unlinked before org deletion
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(
        Enum("super_admin", "org_admin", "receptionist", name="user_role"),
        nullable=False,
    )
    # branch_ids: JSONB list of branch UUID strings this user can access
    branch_ids: Mapped[list | None] = mapped_column(JSONB)
    # google_sub: Google OAuth subject ID (from JWT "sub" claim) for login matching
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    # is_admin: Vachanam platform admin (Vinay only) — gives access to AdminDashboard
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization | None"] = relationship(back_populates="users")


class AuditLog(Base):
    """Append-only security audit trail. No FKs by design — rows survive user/branch deletion.

    DPDP classification: pseudonymous (user_id + branch_id are UUIDs; action strings contain no PII).
    PII note: ip_address is pseudonymous (links to a person only with ISP records); user_agent is
    aggregate (browser metadata). metadata_json must NOT store patient name/phone — only IDs.

    Append-only enforcement: vachanam_app DB role is granted only INSERT + SELECT on this table.
    UPDATE and DELETE are withheld. Set up in Phase 10 prod DB init script (devops-engineer).
    """
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # timestamp: indexed for chronological queries and retention scans
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    # user_id, branch_id, org_id: plain UUIDs — intentionally no FK constraints.
    # Audit rows survive deletion of the referenced user/branch/org.
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    # action: dot-notation event name e.g. "user.login.success", "token.attend"
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    # ip_address: supports IPv4 (max 15 chars) and IPv6 (max 45 chars)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    # metadata_json: structured context — branch_ids, error codes, etc. Never raw PII.
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
    # success: false = failure events (login failures, access denials, signature mismatches)
    # server_default="true" ensures DB-level default; default=True kept for ORM inserts
    success: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, index=True)
