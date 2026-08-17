"""Persist caller language before a patient record exists.

Revision ID: kkkk57_caller_lang
Revises: jjjj56_founding_unlimited_trial
"""
import sqlalchemy as sa
from alembic import op


revision = "kkkk57_caller_lang"
down_revision = "jjjj56_founding_unlimited_trial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "caller_preferences",
        sa.Column("branch_id", sa.UUID(), nullable=False),
        sa.Column("phone_last10", sa.String(length=10), nullable=False),
        sa.Column("preferred_language", sa.String(length=8), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"], ["branches.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("branch_id", "phone_last10"),
    )
    # Preserve every mapping learned before this table existed.  A primary
    # family member wins, matching get_preferred_language's established rule.
    op.execute(
        sa.text(
            """
            INSERT INTO caller_preferences
                (branch_id, phone_last10, preferred_language)
            SELECT DISTINCT ON (branch_id, phone_last10)
                branch_id, phone_last10, preferred_language
            FROM (
                SELECT branch_id,
                       right(regexp_replace(phone, '\\D', '', 'g'), 10) AS phone_last10,
                       preferred_language,
                       is_primary,
                       created_at
                FROM patients
                WHERE preferred_language IS NOT NULL
                  AND length(regexp_replace(phone, '\\D', '', 'g')) >= 10
            ) mapped
            ORDER BY branch_id, phone_last10, is_primary DESC, created_at ASC
            ON CONFLICT (branch_id, phone_last10) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_table("caller_preferences")
