"""initial_schema

Revision ID: 2fe8f201bc31
Revises:
Create Date: 2026-05-15 22:27:43.650406

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '2fe8f201bc31'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all 9 tables for Vachanam initial schema."""

    # --- ENUM TYPES ---
    plan_type = postgresql.ENUM(
        "solo", "clinic", "multi",
        name="plan_type", create_type=True,
    )
    org_status = postgresql.ENUM(
        "active", "trial", "paused", "cancelled",
        name="org_status", create_type=True,
    )
    branch_status = postgresql.ENUM(
        "active", "inactive",
        name="branch_status", create_type=True,
    )
    booking_type = postgresql.ENUM(
        "token", "appointment",
        name="booking_type", create_type=True,
    )
    doctor_status = postgresql.ENUM(
        "active", "inactive",
        name="doctor_status", create_type=True,
    )
    booking_source = postgresql.ENUM(
        "voice", "whatsapp", "walk_in",
        name="booking_source", create_type=True,
    )
    token_status = postgresql.ENUM(
        "waiting", "attended", "no_show", "cancelled_by_clinic",
        name="token_status", create_type=True,
    )
    call_direction = postgresql.ENUM(
        "inbound", "outbound",
        name="call_direction", create_type=True,
    )
    call_type_enum = postgresql.ENUM(
        "inbound_booking", "followup", "cancellation_notify",
        name="call_type", create_type=True,
    )
    call_outcome = postgresql.ENUM(
        "booked", "no_slot", "emergency", "dropped", "followup_completed",
        "cancellation_rebooked", "cancellation_declined", "cancellation_unreachable",
        name="call_outcome", create_type=True,
    )
    followup_status = postgresql.ENUM(
        "pending", "in_progress", "completed", "unreachable",
        name="followup_status", create_type=True,
    )
    billing_status = postgresql.ENUM(
        "open", "invoiced", "paid", "failed",
        name="billing_status", create_type=True,
    )
    wa_session_state = postgresql.ENUM(
        "GREETING", "WAITING_NAME", "WAITING_DOCTOR", "WAITING_SLOT",
        "CONFIRM", "CONFIRMED", "CANCELLATION_REBOOK",
        name="wa_session_state", create_type=True,
    )

    # Create all enum types
    for enum_type in [
        plan_type, org_status, branch_status, booking_type, doctor_status,
        booking_source, token_status, call_direction, call_type_enum,
        call_outcome, followup_status, billing_status, wa_session_state,
    ]:
        enum_type.create(op.get_bind(), checkfirst=True)

    # --- TABLE 1: organizations ---
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner_phone", sa.String(20), nullable=False),
        sa.Column("owner_email", sa.String(255), nullable=False, unique=True),
        sa.Column("plan", sa.Enum("solo", "clinic", "multi", name="plan_type"), nullable=False),
        sa.Column("subscription_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("razorpay_customer_id", sa.String(255), nullable=True),
        sa.Column("razorpay_subscription_id", sa.String(255), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "trial", "paused", "cancelled", name="org_status"),
            nullable=False,
            server_default="trial",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- TABLE 2: branches ---
    op.create_table(
        "branches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("address", sa.Text, nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("whatsapp_number", sa.String(20), nullable=False, unique=True),
        sa.Column("did_number", sa.String(20), nullable=True),
        sa.Column("vobiz_did_id", sa.String(255), nullable=True),
        sa.Column("emergency_contact", sa.String(20), nullable=True),
        sa.Column("google_calendar_id", sa.String(255), nullable=True),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="Asia/Kolkata"),
        sa.Column(
            "status",
            sa.Enum("active", "inactive", name="branch_status"),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- TABLE 3: doctors ---
    op.create_table(
        "doctors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("specialization", sa.String(100), nullable=True),
        sa.Column("routing_keywords", sa.ARRAY(sa.Text), nullable=True),
        sa.Column("is_default_doctor", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "booking_type",
            sa.Enum("token", "appointment", name="booking_type"),
            nullable=False,
        ),
        sa.Column("working_hours_start", sa.Time, nullable=True),
        sa.Column("working_hours_end", sa.Time, nullable=True),
        sa.Column("slot_duration_minutes", sa.Integer, nullable=True),
        sa.Column("max_concurrent_per_slot", sa.Integer, nullable=True),
        sa.Column("pre_appointment_reminder", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("daily_token_limit", sa.Integer, nullable=True),
        sa.Column("whatsapp_number", sa.String(20), nullable=True),
        sa.Column("google_calendar_id", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "inactive", name="doctor_status"),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- TABLE 4: patients ---
    op.create_table(
        "patients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("followup_consent", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- TABLE 5: tokens ---
    op.create_table(
        "tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "doctor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("doctors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("token_number", sa.Integer, nullable=True),
        sa.Column("appointment_time", sa.Time, nullable=True),
        sa.Column(
            "source",
            sa.Enum("voice", "whatsapp", "walk_in", name="booking_source"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("waiting", "attended", "no_show", "cancelled_by_clinic", name="token_status"),
            nullable=False,
            server_default="waiting",
        ),
        sa.Column("cancellation_reason", sa.Text, nullable=True),
        sa.Column("call_duration_seconds", sa.Integer, nullable=True),
        sa.Column("google_calendar_event_id", sa.String(255), nullable=True),
        sa.Column("reminder_sent", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- TABLE 6: calls ---
    op.create_table(
        "calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "doctor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("doctors.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("caller_phone", sa.String(20), nullable=True),
        sa.Column(
            "direction",
            sa.Enum("inbound", "outbound", name="call_direction"),
            nullable=False,
        ),
        sa.Column(
            "call_type",
            sa.Enum("inbound_booking", "followup", "cancellation_notify", name="call_type"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer, nullable=True),
        sa.Column("livekit_room_id", sa.String(255), nullable=True),
        sa.Column("vobiz_call_id", sa.String(255), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(
                "booked", "no_slot", "emergency", "dropped", "followup_completed",
                "cancellation_rebooked", "cancellation_declined", "cancellation_unreachable",
                name="call_outcome",
            ),
            nullable=True,
        ),
    )

    # --- TABLE 7: followup_tasks ---
    op.create_table(
        "followup_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "doctor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("doctors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("requested_by_doctor_whatsapp", sa.String(20), nullable=True),
        sa.Column("topic", sa.Text, nullable=True),
        sa.Column("specific_question", sa.Text, nullable=True),
        sa.Column("response_summary", sa.Text, nullable=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column(
            "status",
            sa.Enum("pending", "in_progress", "completed", "unreachable", name="followup_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- TABLE 8: billing_cycles ---
    op.create_table(
        "billing_cycles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cycle_start", sa.Date, nullable=False),
        sa.Column("cycle_end", sa.Date, nullable=False),
        sa.Column("plan", sa.String(20), nullable=False),
        sa.Column("base_amount", sa.Integer, nullable=False),
        sa.Column("included_minutes", sa.Integer, nullable=False),
        sa.Column("minutes_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("overage_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("overage_rate", sa.Integer, nullable=False, server_default="0"),
        sa.Column("overage_amount", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.Enum("open", "invoiced", "paid", "failed", name="billing_status"),
            nullable=False,
            server_default="open",
        ),
        sa.Column("razorpay_payment_id", sa.String(255), nullable=True),
        sa.Column("invoice_number", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- TABLE 9: whatsapp_sessions ---
    op.create_table(
        "whatsapp_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("patient_phone", sa.String(20), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "GREETING", "WAITING_NAME", "WAITING_DOCTOR", "WAITING_SLOT",
                "CONFIRM", "CONFIRMED", "CANCELLATION_REBOOK",
                name="wa_session_state",
            ),
            nullable=False,
            server_default="GREETING",
        ),
        sa.Column("session_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- INDEXES for common query patterns ---
    # tokens: receptionist queue lookup (branch + date, always branch-scoped per Rule 1)
    op.create_index("ix_tokens_branch_date", "tokens", ["branch_id", "date"])
    op.create_index("ix_tokens_branch_doctor_date", "tokens", ["branch_id", "doctor_id", "date"])

    # patients: phone lookup for repeat callers (branch-scoped)
    op.create_index("ix_patients_branch_phone", "patients", ["branch_id", "phone"])

    # whatsapp_sessions: incoming message lookup (branch + patient phone)
    op.create_index(
        "ix_whatsapp_sessions_branch_phone",
        "whatsapp_sessions",
        ["branch_id", "patient_phone"],
    )

    # calls: analytics queries by branch + date range
    op.create_index("ix_calls_branch_started_at", "calls", ["branch_id", "started_at"])

    # followup_tasks: scheduler pickup (branch + status + scheduled_at)
    op.create_index(
        "ix_followup_tasks_branch_status",
        "followup_tasks",
        ["branch_id", "status", "scheduled_at"],
    )

    # billing_cycles: monthly billing queries by org
    op.create_index("ix_billing_cycles_org_start", "billing_cycles", ["org_id", "cycle_start"])


def downgrade() -> None:
    """Drop all 9 tables and enum types."""

    # Drop indexes first
    op.drop_index("ix_billing_cycles_org_start", table_name="billing_cycles")
    op.drop_index("ix_followup_tasks_branch_status", table_name="followup_tasks")
    op.drop_index("ix_calls_branch_started_at", table_name="calls")
    op.drop_index("ix_whatsapp_sessions_branch_phone", table_name="whatsapp_sessions")
    op.drop_index("ix_patients_branch_phone", table_name="patients")
    op.drop_index("ix_tokens_branch_doctor_date", table_name="tokens")
    op.drop_index("ix_tokens_branch_date", table_name="tokens")

    # Drop tables in reverse dependency order
    op.drop_table("whatsapp_sessions")
    op.drop_table("billing_cycles")
    op.drop_table("followup_tasks")
    op.drop_table("calls")
    op.drop_table("tokens")
    op.drop_table("patients")
    op.drop_table("doctors")
    op.drop_table("branches")
    op.drop_table("organizations")

    # Drop enum types
    bind = op.get_bind()
    for enum_name in [
        "wa_session_state", "billing_status", "followup_status",
        "call_outcome", "call_type", "call_direction",
        "token_status", "booking_source", "doctor_status",
        "booking_type", "branch_status", "org_status", "plan_type",
    ]:
        postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
