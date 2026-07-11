"""support tickets + messages (additive, deploy-gated)

Revision ID: aa24_support_tables
Revises: c26preflang2026
Create Date: 2026-07-11

Additive only — creates two new tables + their enum types. Safe to apply to
prod on top of the current head. DEPLOY-GATED: apply only on Vinay's confirm.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "aa24_support_tables"
down_revision = "c26preflang2026"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "support_tickets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("category", sa.Enum("billing", "technical", "onboarding",
                                       "feature_request", "sales_demo", "other",
                                       name="support_category"), nullable=False),
        sa.Column("status", sa.Enum("ai_resolved", "open", "pending", "resolved",
                                    "closed", name="support_status"), nullable=False),
        sa.Column("priority", sa.Enum("low", "normal", "high", "urgent",
                                      name="support_priority"), nullable=False),
        sa.Column("sla_due_at", sa.DateTime(timezone=True)),
        sa.Column("first_responded_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("csat_score", sa.Integer),
        sa.Column("csat_comment", sa.Text),
        sa.Column("source", sa.Enum("in_app", "public_chat", "public_form", "email",
                                    name="support_source"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_support_tickets_org_id", "support_tickets", ["org_id"])
    op.create_index("ix_support_tickets_status_sla", "support_tickets",
                    ["status", "sla_due_at"])

    op.create_table(
        "support_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ticket_id", UUID(as_uuid=True),
                  sa.ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender", sa.Enum("user", "staff", "bot", "system",
                                    name="support_sender"), nullable=False),
        sa.Column("sender_user_id", UUID(as_uuid=True)),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_support_messages_ticket_created", "support_messages",
                    ["ticket_id", "created_at"])


def downgrade():
    op.drop_table("support_messages")
    op.drop_table("support_tickets")
    for enum_name in ("support_sender", "support_source", "support_priority",
                      "support_status", "support_category"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
