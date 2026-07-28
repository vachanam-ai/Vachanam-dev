"""Align historical timestamp nullability and support-message indexing.

Revision ID: kk34_schema_alignment
Revises: jj33_doctor_schedules
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "kk34_schema_alignment"
down_revision: str | Sequence[str] | None = "jj33_doctor_schedules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NON_NULL_TIMESTAMPS = (
    ("call_quality", "created_at"),
    ("clinic_questions", "created_at"),
    ("consents", "created_at"),
    ("treatment_notes", "created_at"),
    ("treatment_notes", "updated_at"),
)


def upgrade() -> None:
    # Historical migrations declared these nullable even though every writer and
    # ORM model treats them as required. Backfill defensively before tightening.
    for table, column in _NON_NULL_TIMESTAMPS:
        op.execute(sa.text(f'UPDATE "{table}" SET "{column}" = now() WHERE "{column}" IS NULL'))
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            existing_server_default=sa.text("now()"),
            nullable=False,
        )

    # The model always requested this FK lookup index, but aa24 created only the
    # compound (ticket_id, created_at) index. Keep both query shapes explicit.
    op.create_index(
        "ix_support_messages_ticket_id",
        "support_messages",
        ["ticket_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_support_messages_ticket_id", table_name="support_messages")
    for table, column in reversed(_NON_NULL_TIMESTAMPS):
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            existing_server_default=sa.text("now()"),
            nullable=True,
        )
