"""Merge reminder audit and clinic voice schema heads.

Revision ID: bbb48_merge_reminder_and_voice_heads
Revises: aaa47_reminder_dispatch_audit, ww46_branch_voice_clones
"""


revision = "bbb48_merge_reminder_and_voice_heads"
down_revision = ("aaa47_reminder_dispatch_audit", "ww46_branch_voice_clones")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
