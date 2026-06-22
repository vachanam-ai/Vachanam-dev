import uuid
from datetime import datetime, date, time
from sqlalchemy import (
    String, Boolean, Integer, Text, DateTime, Date, Time,
    ForeignKey, Enum, ARRAY, JSON, func, text, false, Index, UniqueConstraint
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
    # Super-admin kill switch: when True and the month's voice minutes reach
    # the plan's included bucket, the agent answers with a one-line "service
    # unavailable" and hangs up. Default False — overage billing is normal.
    hard_block_on_exhaust: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
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
    # clinic_phone: the clinic's existing patient-facing number (forwards to the DID)
    clinic_phone: Mapped[str | None] = mapped_column(String(20))
    vobiz_did_id: Mapped[str | None] = mapped_column(String(255))
    # Per-clinic Vobiz SUB-ACCOUNT (concurrency isolation: each clinic gets its
    # own channel pool + CDRs + billing instead of sharing one global account).
    # When vobiz_subaccount_id is set, the agent/outbound jobs use these creds +
    # outbound_trunk_id instead of the global settings.vobiz_*. The SIP password
    # is encrypted at rest (DPDP/RULE 9) — never store it plaintext; use
    # backend/services/crypto.py. All nullable → existing single-account branches
    # keep working unchanged (telephony.py falls back to the global account).
    vobiz_subaccount_id: Mapped[str | None] = mapped_column(String(128))
    vobiz_sip_username: Mapped[str | None] = mapped_column(String(128))
    vobiz_sip_password_enc: Mapped[str | None] = mapped_column(Text)  # Fernet token
    vobiz_sip_domain: Mapped[str | None] = mapped_column(String(255))
    outbound_trunk_id: Mapped[str | None] = mapped_column(String(255))  # per-clinic LiveKit outbound trunk
    emergency_contact: Mapped[str | None] = mapped_column(String(20))
    google_calendar_id: Mapped[str | None] = mapped_column(String(255))
    # smallest.ai Waves voice_id for this clinic's agent (clinic-selectable; can
    # be a cloned voice). NULL → the agent uses the language's default smallest
    # voice (agent/i18n). Nullable + widened from the old Sarvam-speaker column
    # (TTS provider switched Sarvam Bulbul → smallest.ai 2026-06-15).
    tts_voice: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Cloned smallest.ai voices registered to this clinic: list of
    # {"voice_id","name","language"}. A clinic clones a voice in the smallest.ai
    # dashboard, then registers the returned voice_id here so it shows in the
    # Settings voice picker for that language and can be selected as tts_voice.
    # Tenant-scoped (RULE 1) — a clinic only ever sees its own clones.
    cloned_voices: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    # Spoken language for this clinic's voice agent (clinic-selectable). Drives
    # the Sarvam STT/TTS language codes AND the per-language spoken lines +
    # system-prompt directive. Short code (te/hi/ta/kn/ml/mr/bn/or); see
    # agent/i18n/languages.py. Default Telugu — the launch market.
    language: Mapped[str] = mapped_column(String(8), default="te", server_default="te", nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata")
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", name="branch_status"),
        default="active",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # No two clinics may share a DID — the voice agent resolves tenant identity
    # from the dialed number. Partial unique (NULL DIDs allowed for un-provisioned
    # branches). Matches alembic e1diduniq2026.
    __table_args__ = (
        Index(
            "uq_branches_did_number",
            "did_number",
            unique=True,
            postgresql_where=text("did_number IS NOT NULL"),
        ),
    )

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

    # --- Sub-spec A additions (migration fd4a95d354fa) ---
    # available_weekdays: ISO int array 0-6 (0=Mon). All listed days share working_hours range.
    # DPDP: aggregate metadata — no PII.
    available_weekdays: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[0,1,2,3,4,5,6]'::jsonb")
    )
    # post_treatment_followup: auto-set TRUE for booking_type='appointment' at creation.
    post_treatment_followup: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    # walkins_closed_today_date: receptionist sets to CURRENT_DATE to stop walk-ins.
    # Auto-clears next day via date comparison in preflight check.
    walkins_closed_today_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # calendar_event_id_recurring: token-doctor only — Google Cal recurring clinic-hours event ID.
    calendar_event_id_recurring: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # user_id: links Doctor row to User account for doctor-role login.
    # SET NULL on user deletion — preserves the Doctor row.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    # invited_email: org_admin enters doctor's Google email. Cleared after first sign-in.
    invited_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    branch: Mapped["Branch"] = relationship(back_populates="doctors")
    tokens: Mapped[list["Token"]] = relationship(back_populates="doctor")
    followup_tasks: Mapped[list["FollowupTask"]] = relationship(back_populates="doctor")
    unavailabilities: Mapped[list["DoctorUnavailability"]] = relationship(back_populates="doctor")


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # RESTRICT: patient rows carry PII; must be explicitly deleted before branch removal (DPDP)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    # Family bookings: caller != patient, several patients can share one phone.
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    followup_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # DPDP s.8(7) retention: set by the data_retention job when this patient's PII
    # is erased (name/phone/age/gender cleared) after the retention window. NULL =
    # still live. The booking rows survive (anonymised) for aggregate analytics.
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    branch: Mapped["Branch"] = relationship(back_populates="patients")
    tokens: Mapped[list["Token"]] = relationship(back_populates="patient")
    followup_tasks: Mapped[list["FollowupTask"]] = relationship(back_populates="patient")


class Consent(Base):
    """DPDP s.5 demonstrable-notice record. One row per call where the data-
    processing disclosure (the AI-assistant greeting) was spoken to the caller,
    so we can prove to the Data Protection Board that notice was served. Tenant-
    scoped (branch_id). No medical data — only that notice was given, to which
    number, and which notice version."""
    __tablename__ = "consents"
    __table_args__ = (Index("ix_consents_branch_phone", "branch_id", "patient_phone"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    session_id: Mapped[str | None] = mapped_column(String(64))
    patient_phone: Mapped[str | None] = mapped_column(String(20))
    consent_type: Mapped[str] = mapped_column(
        Enum("data_processing", "followup", "recording", name="consent_type"),
        default="data_processing", nullable=False,
    )
    notice_version: Mapped[str] = mapped_column(String(10), default="1.0", nullable=False)
    method: Mapped[str] = mapped_column(
        Enum("verbal", "written", "whatsapp", name="consent_method"),
        default="verbal", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Token(Base):
    __tablename__ = "tokens"
    # Compound indexes for "today's queue" and "doctor X's tokens today" query patterns (TD-018).
    # Partial unique index (migration i5tokuniq2026): race-proof token-doctor
    # queue numbers — a concurrent double-book the TOCTOU re-count races past is
    # rejected at the DB (bug-bounty T1). Defined here so create_all (tests)
    # builds it too. Slot doctors are excluded (per-slot number + max_concurrent).
    __table_args__ = (
        Index("ix_tokens_branch_date", "branch_id", "date"),
        Index("ix_tokens_branch_doctor_date", "branch_id", "doctor_id", "date"),
        Index(
            "uq_token_number_confirmed",
            "branch_id", "doctor_id", "date", "token_number",
            unique=True,
            postgresql_where=text("status = 'confirmed' AND appointment_time IS NULL"),
        ),
    )

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
    # (clinic cascade / doctor leave) | cancelled_by_patient (self-cancel on call)
    status: Mapped[str] = mapped_column(
        Enum(
            "confirmed", "attended", "no_show",
            "cancelled_by_clinic", "cancelled_by_patient",
            name="token_status",
        ),
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

    # --- Sub-spec A additions (migration fd4a95d354fa) ---
    # cancelled_by_user_id: UUID of User who triggered cascade cancellation (plain UUID, no FK).
    # Plain UUID pattern consistent with marked_by_user_id — survives user deletion.
    # DPDP: pseudonymous (UUID only, no name/phone).
    cancelled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # emergency_reason: required when walk-in bypasses daily cap via is_urgent=true.
    # DPDP: sensitive — describes patient's stated urgency reason. Stored only here, not in audit log.
    emergency_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

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


class CallLog(Base):
    """One row per voice call — analytics + minute metering.

    Rule 9: caller stored as LAST-4 only; no names, no recordings.
    Written by the voice agent at call end (and on failed outbound dials).
    """
    __tablename__ = "call_logs"
    __table_args__ = (
        Index("ix_call_logs_branch_started", "branch_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    call_type: Mapped[str] = mapped_column(String(20), nullable=False)  # inbound|reminder|cascade_rebook|outbound
    caller_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    answered: Mapped[bool] = mapped_column(Boolean, default=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    booking_made: Mapped[bool] = mapped_column(Boolean, default=False)
    # Telephony provider's call UUID (Vobiz). The CDR sync job is the
    # AUTHORITATIVE source of minutes — independent of the agent process, so a
    # dropped/crashed/locally-run call is still billed. Unique → idempotent
    # upsert across repeated syncs. NULL for agent-written rows.
    provider_call_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)


class CallQuality(Base):
    """One agent-written record per voice call — the foundation of monitoring
    (answer rate, booking conversion, abandonment, failure breakdown per clinic)
    AND the feedback loop (eval corpus for LLM-as-judge + human review).

    Written at call end REGARDLESS of agent_call_log_enabled, so it exists even
    when Vobiz CDR is the billing writer (CallLog stays billing-only). Keyed by
    session_id + branch_id; loosely linked to the metering row via call_log_id.

    Two data classes, two retention rules:
      - OUTCOME fields (language, duration, booking_made, fail_reason, turns, ...)
        are NON-PII aggregates — kept long-term for trend analysis.
      - `transcript` can hold the caller's spoken name/age/health complaint, so it
        is PII (text only — NOT audio; RULE 9 keeps prod recording-free). Captured
        only when settings.transcript_capture_enabled, phone digits MASKED before
        storage, tenant-scoped (RULE 1), and NULLED by the data_retention job after
        settings.transcript_retention_days while the outcome row survives."""
    __tablename__ = "call_quality"
    __table_args__ = (Index("ix_call_quality_branch_created", "branch_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Soft link to the billing row; nullable + SET NULL so the quality record
    # survives independently (CDR may write/replace its CallLog separately).
    call_log_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_logs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    call_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    turns: Mapped[int] = mapped_column(Integer, default=0)  # patient conversation turns
    booking_made: Mapped[bool] = mapped_column(Boolean, default=False)
    booking_abandoned: Mapped[bool] = mapped_column(Boolean, default=False)  # held a slot, never confirmed
    transfer_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    fail_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)  # None on a booked call
    # Role-tagged, phone-masked conversation text ("patient: ... / agent: ...").
    # NULL when capture is disabled or after the transcript-retention prune.
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── LLM-as-judge (feedback loop, written by the call_scoring job) ──────────
    # DERIVED, non-PII: an automated quality read of the transcript. These survive
    # the transcript prune (they hold no patient data) so trends outlive the text.
    judge_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # overall 1-5
    judge_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)     # issue-tag vocab
    judge_summary: Mapped[str | None] = mapped_column(Text, nullable=True)   # 1-line, PII-FREE, INTERNAL only
    judged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


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

    # --- Sub-spec A additions (migration fd4a95d354fa) ---
    # task_type: app-side enum (VARCHAR not DB ENUM) for zero-DDL growth.
    # Values: 'post_appt_check' | 'pre_appt_reminder' | 'cascade_rebook'
    task_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="post_appt_check"
    )
    # token_id: back-reference to the original Token. Nullable for free-floating follow-ups.
    # RESTRICT: Token cannot be deleted while a FollowupTask references it.
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tokens.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # --- Sub-spec M2 (treatment progress + follow-up loop) additions (migration s16followupthread2026) ---
    # treatment_note_id: links this follow-up into a treatment thread. Nullable for
    # free-floating follow-ups (reminders/cascade-rebook). RESTRICT: a TreatmentNote
    # cannot be deleted while a FollowupTask references it.
    treatment_note_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("treatment_notes.id", ondelete="RESTRICT"),
        nullable=True, index=True)
    # created_by_user_id: doctor/staff who scheduled this follow-up. SET NULL on user
    # deletion so the thread survives. task_type (VARCHAR) now also carries
    # 'next_visit_book' | 'doctor_advice' — no DB enum change.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    branch: Mapped["Branch"] = relationship()
    doctor: Mapped["Doctor"] = relationship(back_populates="followup_tasks")
    patient: Mapped["Patient"] = relationship(back_populates="followup_tasks")


class TreatmentNote(Base):
    """Treatment progress notes: one row per patient visit. Tracks what was done
    (steps_performed), what comes next (next_steps), when to follow up (next_reporting_date),
    and whether this is a final visit (is_final). Links back to the Token that triggered
    this visit (nullable — some notes may be created offline)."""
    __tablename__ = "treatment_notes"
    __table_args__ = (
        Index("ix_treatment_notes_branch_patient_date", "branch_id", "patient_id", "visit_date"),
        Index("ix_treatment_notes_branch_doctor", "branch_id", "doctor_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # RESTRICT: treatment notes reference live patient/doctor/branch; explicit deletion required (DPDP)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Optional back-reference to the Token that triggered this visit
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tokens.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    visit_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Treatment performed during the visit
    steps_performed: Mapped[str | None] = mapped_column(Text)
    # Instructions for ongoing care or follow-up actions
    next_steps: Mapped[str | None] = mapped_column(Text)
    # Date when the patient should return for follow-up
    next_reporting_date: Mapped[date | None] = mapped_column(Date)
    # Indicates if this is the final visit in a treatment cycle
    is_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # User (doctor/staff) who created this note; SET NULL if user deleted
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    branch: Mapped["Branch"] = relationship()
    doctor: Mapped["Doctor"] = relationship()
    patient: Mapped["Patient"] = relationship()


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
        # 'doctor' added via ALTER TYPE in migration fd4a95d354fa (sub-spec A).
        # create_constraint=False prevents Alembic autogenerate from re-creating
        # the enum type (it already exists in the DB from the initial migration).
        Enum("super_admin", "org_admin", "receptionist", "doctor", name="user_role", create_constraint=False),
        nullable=False,
    )
    # branch_ids: JSONB list of branch UUID strings this user can access
    branch_ids: Mapped[list | None] = mapped_column(JSONB)
    # google_sub: Google OAuth subject ID (from JWT "sub" claim) for login matching
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    # is_admin: Vachanam platform admin (Vinay only) — gives access to AdminDashboard
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # password_hash: bcrypt hash for email+password login (None for Google-only users)
    password_hash: Mapped[str | None] = mapped_column(String(255))
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


class DoctorUnavailability(Base):
    """Date-specific doctor absence override.

    A DoctorUnavailability row marks one doctor as absent on one specific date.
    The UNIQUE(doctor_id, date) constraint prevents double-entries.

    When inserted via POST /availability, the cascade flow:
      1. INSERT INTO doctor_unavailability (one row per date, ON CONFLICT DO NOTHING)
      2. Bulk cancel confirmed tokens for that doctor+date
      3. Enqueue FollowupTask(task_type='cascade_rebook') for each cancelled token

    DPDP classification: pseudonymous — doctor_id is UUID (no name/phone).
    created_by_user_id is a plain UUID (no FK) — audit trail survives user deletion.

    Added: migration fd4a95d354fa (sub-spec A, 2026-06-09).
    """
    __tablename__ = "doctor_unavailability"
    __table_args__ = (
        UniqueConstraint("doctor_id", "date", name="uq_doctor_unavailability_doctor_date"),
        Index("ix_doctor_unavailability_branch_date", "branch_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # branch_id: first non-PK column (Rule 1 — every multi-tenant table scoped to branch)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("doctors.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # created_by_user_id: plain UUID (no FK) — matches Token.marked_by_user_id pattern.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    doctor: Mapped["Doctor"] = relationship(back_populates="unavailabilities")


class CalendarWriteTask(Base):
    """Async Google Calendar write queue.

    Used for the token-doctor path (no per-patient Cal events), and as
    fallback for slot-doctor when the synchronous inline write exhausts its
    retry budget (3 attempts: 0s, 2s, 5s).

    Worker: backend/jobs/calendar_writer.py — APScheduler every 30s.
    Backoff: 5s, 30s, 5min, 60min → failed_permanent after 5 total attempts.

    DPDP classification: pseudonymous — payload_json stores patient_first_name
    + last-4 digits of phone only (no full phone). Compliant with PII denylist.

    branch_id is the first non-PK column (Rule 1).

    Added: migration fd4a95d354fa (sub-spec A, 2026-06-09).
    """
    __tablename__ = "calendar_write_tasks"
    # Worker poll index: WHERE status='pending' AND next_attempt_at <= NOW()
    __table_args__ = (
        Index("ix_calendar_tasks_status_next", "status", "next_attempt_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # branch_id: first non-PK column (Rule 1)
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tokens.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # operation: 'create' | 'update' | 'delete'
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    # payload_json: JSONB (Rule 8 — never plain JSON).
    # Contents: {calendar_id, patient_first_name, patient_phone_last4, appointment_dt, duration_minutes, doctor_name}
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # google_event_id: populated after successful create; reused for update/delete.
    google_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # status: 'pending' | 'in_progress' | 'done' | 'failed_permanent'
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # next_attempt_at: worker polls WHERE status='pending' AND next_attempt_at <= NOW()
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
