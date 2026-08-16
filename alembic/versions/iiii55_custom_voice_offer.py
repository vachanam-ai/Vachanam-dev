"""Limit custom voice access to the first ten organizations.

Revision ID: iiii55_custom_voice_offer
Revises: hhhh54_patient_names_latin
"""
import sqlalchemy as sa
from alembic import op


revision = "iiii55_custom_voice_offer"
down_revision = "hhhh54_patient_names_latin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("custom_voice_member", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "organizations",
        sa.Column("custom_voice_granted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Existing clinics that already own a custom voice must never lose access.
    # The deterministic ten-row cap also leaves at least half of Soniox's
    # twenty-voice project inventory as operational reserve.
    op.execute(
        sa.text(
            """
            WITH existing AS (
                SELECT DISTINCT b.org_id
                FROM branch_voices bv
                JOIN branches b ON b.id = bv.branch_id
                ORDER BY b.org_id
                LIMIT 10
            )
            UPDATE organizations o
            SET custom_voice_member = TRUE,
                custom_voice_granted_at = COALESCE(o.custom_voice_granted_at, NOW())
            FROM existing e
            WHERE o.id = e.org_id
            """
        )
    )


def downgrade() -> None:
    op.drop_column("organizations", "custom_voice_granted_at")
    op.drop_column("organizations", "custom_voice_member")
