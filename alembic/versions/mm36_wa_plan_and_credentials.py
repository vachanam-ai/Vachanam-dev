"""Add the 'wa' (WhatsApp-only) plan and per-branch WhatsApp credentials.

Vinay 2026-08-02: ₹1,499 WhatsApp-only plan — no DID, no voice minutes — plus
the credential columns a clinic-owned WhatsApp Business Account needs, so each
clinic sends on its OWN WABA rather than a shared platform token.

Spec: docs/superpowers/specs/2026-08-02-whatsapp-pricing-design.md

ALTER TYPE ... ADD VALUE cannot run inside a transaction block, so the enum
change commits the surrounding transaction first (same pattern as gg30, which
added 'lite'). IF NOT EXISTS makes it idempotent.

wa_token_enc holds a Fernet-encrypted Meta business token (never plaintext,
never logged, never returned by any API) — same discipline as the Vobiz SIP
password. wa_waba_id is UNIQUE: one WhatsApp Business Account may only ever be
claimed by a single branch (RULE 1 — a second claim must fail loudly rather
than silently route one clinic's patients to another).
"""
import sqlalchemy as sa
from alembic import op

revision = "mm36_wa_plan_and_credentials"
down_revision = "ll35_question_answer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("COMMIT")
    op.execute("ALTER TYPE plan_type ADD VALUE IF NOT EXISTS 'wa'")

    op.add_column("branches", sa.Column("wa_waba_id", sa.String(length=32), nullable=True))
    op.add_column("branches", sa.Column("wa_token_enc", sa.Text(), nullable=True))
    op.add_column("branches", sa.Column("wa_verified_name", sa.String(length=120), nullable=True))
    op.add_column(
        "branches",
        sa.Column(
            "wa_status",
            sa.String(length=16),
            nullable=False,
            server_default="none",  # none | connected | disconnected | error
        ),
    )
    op.add_column(
        "branches",
        sa.Column("wa_connected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_branches_wa_waba_id", "branches", ["wa_waba_id"])


def downgrade() -> None:
    op.drop_constraint("uq_branches_wa_waba_id", "branches", type_="unique")
    op.drop_column("branches", "wa_connected_at")
    op.drop_column("branches", "wa_status")
    op.drop_column("branches", "wa_verified_name")
    op.drop_column("branches", "wa_token_enc")
    op.drop_column("branches", "wa_waba_id")
    # Postgres cannot DROP a value from an enum. A rollback would require
    # recreating the type; not worth it for an additive value. Left in place.
