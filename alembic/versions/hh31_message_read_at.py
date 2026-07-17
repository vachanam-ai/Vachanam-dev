"""patient_messages.read_at — seen-in-treatment-thread marker (Vinay
2026-07-17: a treating patient's message must surface inside their treatment
thread with a WhatsApp-style unread highlight; opening the thread marks it
read). NULL = unread. Additive nullable column — no existing rows change.
"""
import sqlalchemy as sa
from alembic import op

revision = "hh31_message_read_at"
down_revision = "gg30_plan_lite"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patient_messages",
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("patient_messages", "read_at")
