"""patient_messages — caller messages for the doctor/clinic taken by the voice
agent, with callback phone + urgent flag + pending/done state (FIXLOG #349).
Additive only.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "ee28_patient_messages"
down_revision = "dd27_org_gstin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patient_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "branch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("caller_phone", sa.String(20), nullable=True),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("urgent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_patient_messages_branch_id", "patient_messages", ["branch_id"])


def downgrade() -> None:
    op.drop_index("ix_patient_messages_branch_id", table_name="patient_messages")
    op.drop_table("patient_messages")
