"""Doctor multi-session and date-specific schedules.

Revision ID: jj33_doctor_schedules
Revises: ii32_audit_security
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "jj33_doctor_schedules"
down_revision = "ii32_audit_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "doctors",
        sa.Column("schedule_mode", sa.String(length=20), server_default="recurring", nullable=False),
    )
    op.add_column(
        "doctors",
        sa.Column(
            "recurring_schedule",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_doctors_schedule_mode", "doctors",
        "schedule_mode IN ('recurring', 'date_specific')",
    )
    # Preserve every existing doctor's behavior in the new multi-session shape.
    op.execute(
        """
        UPDATE doctors
        SET recurring_schedule = (
          SELECT COALESCE(
            jsonb_object_agg(
              day::text,
              jsonb_build_array(jsonb_build_object(
                'start', to_char(working_hours_start, 'HH24:MI'),
                'end', to_char(working_hours_end, 'HH24:MI')
              ))
            ), '{}'::jsonb
          )
          FROM jsonb_array_elements_text(available_weekdays) AS day
        )
        WHERE working_hours_start IS NOT NULL AND working_hours_end IS NOT NULL
        """
    )
    # Missing legacy hours carry no safe recurring fact. Preserve those doctors
    # as date-specific/unpublished rather than inventing a default window.
    op.execute(
        """
        UPDATE doctors
        SET schedule_mode = 'date_specific'
        WHERE working_hours_start IS NULL OR working_hours_end IS NULL
        """
    )
    op.create_table(
        "doctor_date_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doctor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "sessions", postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"), nullable=False,
        ),
        sa.Column("token_limit", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doctor_id", "date", name="uq_doctor_date_schedule_doctor_date"),
    )
    op.create_index("ix_doctor_date_schedules_branch_id", "doctor_date_schedules", ["branch_id"])
    op.create_index("ix_doctor_date_schedules_doctor_id", "doctor_date_schedules", ["doctor_id"])
    op.create_index("ix_doctor_date_schedules_branch_date", "doctor_date_schedules", ["branch_id", "date"])


def downgrade() -> None:
    op.drop_index("ix_doctor_date_schedules_branch_date", table_name="doctor_date_schedules")
    op.drop_index("ix_doctor_date_schedules_doctor_id", table_name="doctor_date_schedules")
    op.drop_index("ix_doctor_date_schedules_branch_id", table_name="doctor_date_schedules")
    op.drop_table("doctor_date_schedules")
    op.drop_constraint("ck_doctors_schedule_mode", "doctors", type_="check")
    op.drop_column("doctors", "recurring_schedule")
    op.drop_column("doctors", "schedule_mode")
