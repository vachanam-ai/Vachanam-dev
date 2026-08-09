"""Durable idempotent WhatsApp notification outbox.

Revision ID: uu44_wa_delivery_outbox
Revises: tt43_org_cancellation
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "uu44_wa_delivery_outbox"
down_revision = "tt43_org_cancellation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_key", sa.String(length=160), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("recipient_phone", sa.String(length=20), nullable=False),
        sa.Column("values_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "buttons_json", postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"), nullable=False,
        ),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "event_key", name="uq_wa_delivery_branch_event"),
    )
    op.create_index(
        "ix_whatsapp_deliveries_branch_id", "whatsapp_deliveries", ["branch_id"]
    )
    op.create_index(
        "ix_wa_deliveries_status_next", "whatsapp_deliveries",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_wa_deliveries_status_next", table_name="whatsapp_deliveries")
    op.drop_index("ix_whatsapp_deliveries_branch_id", table_name="whatsapp_deliveries")
    op.drop_table("whatsapp_deliveries")
