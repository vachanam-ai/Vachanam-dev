"""subspec_a_schema

Sub-spec A schema: Calendar + Receptionist PWA + RBAC.
See docs/superpowers/specs/2026-06-08-calendar-and-receptionist-pwa-design.md §3.

Revision ID: fd4a95d354fa
Revises: 8559268c0c44
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'fd4a95d354fa'
down_revision: Union[str, Sequence[str], None] = '8559268c0c44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Sub-spec A schema additions. See spec §3 for full rationale.

    Zero-downtime notes:
    - All ADD COLUMN use Postgres 11+ instant-default (server_default) — no table rewrite.
    - New tables are empty at deploy — no backfill needed.
    - ALTER TYPE ADD VALUE is non-blocking but MUST run outside a transaction
      (Postgres rule). We COMMIT the current Alembic transaction first, execute
      the ALTER TYPE, then BEGIN a new transaction for the remaining DDL.
      Alembic does NOT restart its own transaction after our explicit COMMIT,
      so subsequent statements run in auto-commit mode which is fine for DDL
      (each CREATE/ALTER is its own implicit transaction).
    - Existing Doctor rows receive available_weekdays = [0,1,2,3,4,5,6] (all days)
      which preserves today's behaviour exactly.
    """

    # ------------------------------------------------------------------
    # 3.6 user_role enum gains 'doctor' value
    # MUST run FIRST and outside a transaction.
    # Pattern: COMMIT Alembic's open transaction, run ALTER TYPE, re-open.
    # ------------------------------------------------------------------
    op.execute("COMMIT")
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'doctor'")
    op.execute("BEGIN")

    # ------------------------------------------------------------------
    # 3.1 Doctor weekly availability + override + post-treatment-followup
    # All columns nullable or carry server_default — instant DDL on Postgres 11+
    # ------------------------------------------------------------------
    op.add_column(
        "doctors",
        sa.Column(
            "available_weekdays",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[0,1,2,3,4,5,6]'::jsonb"),
            comment="ISO weekday ints 0-6 (0=Mon). All listed days share the same working_hours range.",
        ),
    )
    op.add_column(
        "doctors",
        sa.Column(
            "post_treatment_followup",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Auto-defaults TRUE for booking_type=appointment at doctor creation.",
        ),
    )
    op.add_column(
        "doctors",
        sa.Column(
            "walkins_closed_today_date",
            sa.Date(),
            nullable=True,
            comment="Set to CURRENT_DATE when receptionist stops walk-ins. Auto-clears next day by date comparison.",
        ),
    )
    op.add_column(
        "doctors",
        sa.Column(
            "calendar_event_id_recurring",
            sa.String(255),
            nullable=True,
            comment="Token-doctor only: Google Cal event ID for recurring clinic-hours event.",
        ),
    )
    op.add_column(
        "doctors",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Links Doctor row to User account (doctor-role login). Nullable: exists before first sign-in.",
        ),
    )
    op.add_column(
        "doctors",
        sa.Column(
            "invited_email",
            sa.String(255),
            nullable=True,
            comment="Google email the org_admin types at Doctor creation. Cleared after first sign-in links google_sub.",
        ),
    )
    # FK from doctors.user_id → users.id (SET NULL on user deletion — preserve doctor row)
    op.create_foreign_key(
        "fk_doctors_user_id",
        "doctors",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # UNIQUE: one Doctor row per User account
    op.create_unique_constraint("uq_doctors_user_id", "doctors", ["user_id"])
    # Index the FK so JOIN doctors ON users.id = doctors.user_id uses index
    op.create_index("ix_doctors_user_id", "doctors", ["user_id"])

    # ------------------------------------------------------------------
    # 3.2 doctor_unavailability — date-specific override table
    # branch_id first non-PK column (Rule 1), indexed.
    # UNIQUE(doctor_id, date) — one absence record per doctor per date.
    # created_by_user_id is plain UUID (no FK) — matches Token.marked_by_user_id pattern.
    # ------------------------------------------------------------------
    op.create_table(
        "doctor_unavailability",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "doctor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("doctors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Plain UUID — no FK constraint. Matches Token.marked_by_user_id pattern (survives user deletion).",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "doctor_id",
            "date",
            name="uq_doctor_unavailability_doctor_date",
        ),
    )
    # Compound index for "all unavailable doctors on branch X for date Y" queries
    op.create_index(
        "ix_doctor_unavailability_branch_date",
        "doctor_unavailability",
        ["branch_id", "date"],
    )
    # FK-column indexes (Rule 6: every FK has an index)
    op.create_index(
        "ix_doctor_unavailability_branch_id",
        "doctor_unavailability",
        ["branch_id"],
    )
    op.create_index(
        "ix_doctor_unavailability_doctor_id",
        "doctor_unavailability",
        ["doctor_id"],
    )

    # ------------------------------------------------------------------
    # 3.3 FollowupTask additions — task typing + token back-reference
    # task_type uses VARCHAR(30) with app-side enum (not DB enum) so values
    # can grow without ALTER TYPE migrations.
    # ------------------------------------------------------------------
    op.add_column(
        "followup_tasks",
        sa.Column(
            "task_type",
            sa.String(30),
            nullable=False,
            server_default="post_appt_check",
            comment="App-side enum: post_appt_check | pre_appt_reminder | cascade_rebook",
        ),
    )
    op.add_column(
        "followup_tasks",
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Back-reference to the original Token. Nullable for free-floating follow-ups.",
        ),
    )
    # FK with RESTRICT: a cancelled Token must not silently orphan FollowupTask rows
    op.create_foreign_key(
        "fk_followup_tasks_token_id",
        "followup_tasks",
        "tokens",
        ["token_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    # Index the FK
    op.create_index("ix_followup_tasks_token_id", "followup_tasks", ["token_id"])

    # ------------------------------------------------------------------
    # 3.4 Token additions — cascade audit trail + emergency override reason
    # Both nullable — no backfill needed; existing rows stay valid.
    # ------------------------------------------------------------------
    op.add_column(
        "tokens",
        sa.Column(
            "cancelled_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="UUID of User who triggered cascade cancellation. Plain UUID (no FK) — matches marked_by_user_id pattern.",
        ),
    )
    op.add_column(
        "tokens",
        sa.Column(
            "emergency_reason",
            sa.Text(),
            nullable=True,
            comment="Required when walk-in bypasses daily cap via is_urgent=true.",
        ),
    )

    # ------------------------------------------------------------------
    # 3.5 calendar_write_tasks — async Cal write queue
    # branch_id first non-PK column (Rule 1), indexed.
    # payload_json is JSONB (Rule 8: never plain JSON).
    # status + next_attempt_at compound index for worker poll query.
    # ------------------------------------------------------------------
    op.create_table(
        "calendar_write_tasks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tokens.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "operation",
            sa.String(20),
            nullable=False,
            comment="'create' | 'update' | 'delete'",
        ),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="{calendar_id, patient_first_name, patient_phone_last4, appointment_dt, duration_minutes, doctor_name}",
        ),
        sa.Column(
            "google_event_id",
            sa.String(255),
            nullable=True,
            comment="Populated after successful create; reused for update/delete operations.",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
            comment="'pending' | 'in_progress' | 'done' | 'failed_permanent'",
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    # Worker poll index: WHERE status='pending' AND next_attempt_at <= NOW()
    op.create_index(
        "ix_calendar_tasks_status_next",
        "calendar_write_tasks",
        ["status", "next_attempt_at"],
    )
    # FK-column indexes
    op.create_index(
        "ix_calendar_write_tasks_branch_id",
        "calendar_write_tasks",
        ["branch_id"],
    )
    op.create_index(
        "ix_calendar_write_tasks_token_id",
        "calendar_write_tasks",
        ["token_id"],
    )

    # ------------------------------------------------------------------
    # 3.7 Compound indexes on tokens (TD-018 payback)
    # - ix_tokens_branch_date: "today's queue for this branch" queries
    # - ix_tokens_branch_doctor_date: "doctor X's tokens today" queries
    # ------------------------------------------------------------------
    op.create_index(
        "ix_tokens_branch_date",
        "tokens",
        ["branch_id", "date"],
    )
    op.create_index(
        "ix_tokens_branch_doctor_date",
        "tokens",
        ["branch_id", "doctor_id", "date"],
    )


def downgrade() -> None:
    """Reverse sub-spec A schema additions (dev use only — not trusted for prod).

    NOTE: ALTER TYPE DROP VALUE does not exist in Postgres; the 'doctor' enum
    value cannot be removed via DDL. This is documented and acceptable — unused
    enum values are harmless.
    """
    # 3.7 compound indexes
    op.drop_index("ix_tokens_branch_doctor_date", table_name="tokens")
    op.drop_index("ix_tokens_branch_date", table_name="tokens")

    # 3.5 calendar_write_tasks
    op.drop_index("ix_calendar_write_tasks_token_id", table_name="calendar_write_tasks")
    op.drop_index("ix_calendar_write_tasks_branch_id", table_name="calendar_write_tasks")
    op.drop_index("ix_calendar_tasks_status_next", table_name="calendar_write_tasks")
    op.drop_table("calendar_write_tasks")

    # 3.4 token additions
    op.drop_column("tokens", "emergency_reason")
    op.drop_column("tokens", "cancelled_by_user_id")

    # 3.3 followup_tasks additions
    op.drop_index("ix_followup_tasks_token_id", table_name="followup_tasks")
    op.drop_constraint("fk_followup_tasks_token_id", "followup_tasks", type_="foreignkey")
    op.drop_column("followup_tasks", "token_id")
    op.drop_column("followup_tasks", "task_type")

    # 3.2 doctor_unavailability
    op.drop_index("ix_doctor_unavailability_doctor_id", table_name="doctor_unavailability")
    op.drop_index("ix_doctor_unavailability_branch_id", table_name="doctor_unavailability")
    op.drop_index("ix_doctor_unavailability_branch_date", table_name="doctor_unavailability")
    op.drop_table("doctor_unavailability")

    # 3.1 doctors additions
    op.drop_index("ix_doctors_user_id", table_name="doctors")
    op.drop_constraint("uq_doctors_user_id", "doctors", type_="unique")
    op.drop_constraint("fk_doctors_user_id", "doctors", type_="foreignkey")
    for col in [
        "invited_email",
        "user_id",
        "calendar_event_id_recurring",
        "walkins_closed_today_date",
        "post_treatment_followup",
        "available_weekdays",
    ]:
        op.drop_column("doctors", col)

    # 3.6 NOTE: 'doctor' enum value cannot be removed from user_role in Postgres.
    # This is a known Postgres limitation. The value is unused after downgrade
    # and harmless. Tracked in migration log.
