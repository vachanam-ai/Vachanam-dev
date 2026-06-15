"""branches Vobiz sub-account columns — per-clinic telephony isolation.

Adds per-branch Vobiz sub-account credentials + a per-clinic LiveKit outbound
trunk so each clinic gets its own concurrency/channel pool, CDRs and billing
instead of sharing one global Vobiz account. All nullable — existing branches
keep using the global account (backend/services/telephony.py falls back).

The SIP password column holds a Fernet token (encrypted at rest), never plaintext.

Revision ID: m9subacct2026
Revises: l8lang2026
Create Date: 2026-06-15
"""
import sqlalchemy as sa
from alembic import op

revision = "m9subacct2026"
down_revision = "l8lang2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("vobiz_subaccount_id", sa.String(128), nullable=True))
    op.add_column("branches", sa.Column("vobiz_sip_username", sa.String(128), nullable=True))
    op.add_column("branches", sa.Column("vobiz_sip_password_enc", sa.Text(), nullable=True))
    op.add_column("branches", sa.Column("vobiz_sip_domain", sa.String(255), nullable=True))
    op.add_column("branches", sa.Column("outbound_trunk_id", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("branches", "outbound_trunk_id")
    op.drop_column("branches", "vobiz_sip_domain")
    op.drop_column("branches", "vobiz_sip_password_enc")
    op.drop_column("branches", "vobiz_sip_username")
    op.drop_column("branches", "vobiz_subaccount_id")
