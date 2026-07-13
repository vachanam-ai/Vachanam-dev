"""WhatsApp MVP2 (spec 2026-07-13): branches.wa_phone_number_id (Coexistence-
linked clinic number, RULE 5 inbound branch resolution) + ratings table
(post-visit 1-5 WhatsApp rating, one per token, score only — RULE 9).
Additive only.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "ff29_whatsapp_ratings"
down_revision = "ee28_patient_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "branches",
        sa.Column("wa_phone_number_id", sa.String(32), nullable=True),
    )
    op.create_unique_constraint(
        "uq_branches_wa_phone_number_id", "branches", ["wa_phone_number_id"]
    )

    op.create_table(
        "ratings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "branch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "token_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tokens.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column(
            "patient_id",
            UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_ratings_score_1_5"),
    )
    op.create_index("ix_ratings_branch_id", "ratings", ["branch_id"])


def downgrade() -> None:
    op.drop_index("ix_ratings_branch_id", table_name="ratings")
    op.drop_table("ratings")
    op.drop_constraint("uq_branches_wa_phone_number_id", "branches")
    op.drop_column("branches", "wa_phone_number_id")
