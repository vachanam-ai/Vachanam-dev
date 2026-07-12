"""support_tickets.phone — demo leads carry a callback number (FIXLOG #337).

Additive only; safe on live data.
"""
import sqlalchemy as sa
from alembic import op

revision = "cc26_ticket_phone"
down_revision = "bb25_support_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("support_tickets", sa.Column("phone", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("support_tickets", "phone")
