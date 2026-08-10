"""Branch-owned Soniox cloned voices with consent provenance.

Revision ID: ww46_branch_voice_clones
Revises: vv45_razorpay_autopay
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ww46_branch_voice_clones"
down_revision = "vv45_razorpay_autopay"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "branch_voices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_voice_id", sa.String(length=64), nullable=True),
        sa.Column("provider_name", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="uploading", nullable=False),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("consent_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consent_text", sa.String(length=255), nullable=False),
        sa.Column("consent_recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "name", name="uq_branch_voice_name"),
        sa.UniqueConstraint("provider_name"),
        sa.UniqueConstraint("provider_voice_id"),
    )
    op.create_index("ix_branch_voices_branch_id", "branch_voices", ["branch_id"])
    # Voice cloning was previously removed and legacy provider IDs are not
    # valid Soniox UUIDs. Start from a known-safe catalog voice; new clone UUIDs
    # can only be written after a ready branch_voices mapping exists.
    op.execute(
        """
        UPDATE branches
        SET tts_voice = 'Priya'
        WHERE tts_voice IS NOT NULL
          AND tts_voice NOT IN (
            'Maya','Daniel','Noah','Nina','Emma','Jack','Adrian','Claire',
            'Grace','Owen','Mina','Kenji','Rafael','Mateo','Lucia','Sofia',
            'Oliver','Arthur','Isla','Victoria','Cooper','Mason','Ruby','Elise',
            'Arjun','Rohan','Priya','Meera'
          )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_branch_voices_branch_id", table_name="branch_voices")
    op.drop_table("branch_voices")
