"""organizations.gstin — clinic's GSTIN printed on payment invoices so B2B
clinics can claim input credit (FIXLOG #342). Additive only.
"""
import sqlalchemy as sa
from alembic import op

revision = "dd27_org_gstin"
down_revision = "cc26_ticket_phone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("gstin", sa.String(15), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "gstin")
