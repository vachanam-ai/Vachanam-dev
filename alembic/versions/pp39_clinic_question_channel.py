"""clinic_questions.channel — answer on the channel the patient chose

Vinay 2026-08-04: "questions asked in whatsapp should get whatsapp reply after
getting confirmation from clinic. not call. because, those people whatsapp
clinic because they don't want to talk."

Every existing row was taken by the voice agent, so backfilling "voice" is
exactly right and the callback job's behaviour is unchanged for them.

Revision ID: pp39_clinic_question_channel
Revises: oo38_addon_purchases
"""
import sqlalchemy as sa
from alembic import op

revision = "pp39_clinic_question_channel"
down_revision = "oo38_addon_purchases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default so the column is NOT NULL from the first instant without a
    # separate backfill pass, and so rows written by a not-yet-deployed API
    # instance during the rollout still land valid.
    op.add_column(
        "clinic_questions",
        sa.Column(
            "channel", sa.String(length=12),
            nullable=False, server_default="voice",
        ),
    )


def downgrade() -> None:
    op.drop_column("clinic_questions", "channel")
