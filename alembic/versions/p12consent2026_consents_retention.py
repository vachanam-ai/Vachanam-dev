"""consents table (DPDP s.5 demonstrable notice) + patients.anonymized_at
(DPDP s.8(7) retention erasure).

Revision ID: p12consent2026
Revises: o11clonedvoices2026
Create Date: 2026-06-16
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "p12consent2026"
down_revision = "o11clonedvoices2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(64)),
        sa.Column("patient_phone", sa.String(20)),
        sa.Column(
            "consent_type",
            sa.Enum("data_processing", "followup", "recording", name="consent_type"),
            nullable=False,
            server_default="data_processing",
        ),
        sa.Column("notice_version", sa.String(10), nullable=False, server_default="1.0"),
        sa.Column(
            "method",
            sa.Enum("verbal", "written", "whatsapp", name="consent_method"),
            nullable=False,
            server_default="verbal",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_consents_branch_id", "consents", ["branch_id"])
    op.create_index("ix_consents_branch_phone", "consents", ["branch_id", "patient_phone"])
    op.add_column(
        "patients",
        sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("patients", "anonymized_at")
    op.drop_index("ix_consents_branch_phone", table_name="consents")
    op.drop_index("ix_consents_branch_id", table_name="consents")
    op.drop_table("consents")
    sa.Enum(name="consent_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="consent_method").drop(op.get_bind(), checkfirst=True)
