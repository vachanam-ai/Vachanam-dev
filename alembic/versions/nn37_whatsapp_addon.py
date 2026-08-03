"""Add the Rs1,499 WhatsApp add-on flag to branches.

Spec: docs/superpowers/specs/2026-08-02-whatsapp-pricing-design.md §1.

Found in production 2026-08-03: a real clinic on the `solo` plan messaged the
pilot number and every message was dropped with `wa_skipped_plan`. That is
correct billing behaviour (WhatsApp is bundled into clinic/multi/wa only) and
the wrong product behaviour — the add-on is how a Lite/Starter clinic pays for
WhatsApp without upgrading to Clinic at +Rs4,000/mo.

Per-BRANCH rather than per-org because WhatsApp is provisioned per NUMBER:
each branch holds its own WhatsApp Business Account and its own Meta billing
relationship, so an org with three branches genuinely needs three numbers and
three add-ons.

Additive and defaulted false, so existing rows keep exactly today's behaviour
and this is safe to apply ahead of the deploy.
"""
import sqlalchemy as sa
from alembic import op

revision = "nn37_whatsapp_addon"
down_revision = "mm36_wa_plan_and_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "branches",
        sa.Column(
            "whatsapp_addon",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("branches", "whatsapp_addon")
