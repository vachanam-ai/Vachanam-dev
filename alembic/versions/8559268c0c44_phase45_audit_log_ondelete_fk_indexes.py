"""Add the audit log, FK delete rules, and FK indexes.

Revision ID: 8559268c0c44
Revises: ffcf1134aa8f
Create Date: 2026-06-02 21:23:22.955703

This revision originally contained a mistaken second copy of the complete
initial schema.  Production was stamped past it before later additive
migrations were applied, so correcting the revision is safe for existing
databases and makes a new ``alembic upgrade head`` produce the same effective
schema production has always expected.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8559268c0c44"
down_revision: str | Sequence[str] | None = "ffcf1134aa8f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, local column, referenced table, referenced column, ON DELETE rule)
_FOREIGN_KEYS = (
    ("billing_cycles", "org_id", "organizations", "id", "RESTRICT"),
    ("branches", "org_id", "organizations", "id", "RESTRICT"),
    ("users", "org_id", "organizations", "id", "RESTRICT"),
    ("doctors", "branch_id", "branches", "id", "RESTRICT"),
    ("patients", "branch_id", "branches", "id", "RESTRICT"),
    ("whatsapp_sessions", "branch_id", "branches", "id", "CASCADE"),
    ("followup_tasks", "branch_id", "branches", "id", "RESTRICT"),
    ("followup_tasks", "doctor_id", "doctors", "id", "RESTRICT"),
    ("followup_tasks", "patient_id", "patients", "id", "RESTRICT"),
    ("tokens", "branch_id", "branches", "id", "RESTRICT"),
    ("tokens", "doctor_id", "doctors", "id", "RESTRICT"),
    ("tokens", "patient_id", "patients", "id", "RESTRICT"),
    ("calls", "branch_id", "branches", "id", "RESTRICT"),
    ("calls", "doctor_id", "doctors", "id", "RESTRICT"),
    ("calls", "token_id", "tokens", "id", "RESTRICT"),
)


def _replace_foreign_key(
    table: str,
    column: str,
    referred_table: str,
    referred_column: str,
    *,
    ondelete: str | None,
) -> None:
    name = f"{table}_{column}_fkey"
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(
        name,
        table,
        referred_table,
        [column],
        [referred_column],
        ondelete=ondelete,
    )


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("branch_id", sa.UUID(), nullable=True),
        sa.Column("org_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=True),
        sa.Column("resource_id", sa.String(length=100), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "success",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "action",
        "branch_id",
        "org_id",
        "success",
        "timestamp",
        "user_id",
    ):
        op.create_index(
            op.f(f"ix_audit_log_{column}"),
            "audit_log",
            [column],
            unique=False,
        )

    for table, column, ref_table, ref_column, ondelete in _FOREIGN_KEYS:
        _replace_foreign_key(
            table,
            column,
            ref_table,
            ref_column,
            ondelete=ondelete,
        )
        op.create_index(
            op.f(f"ix_{table}_{column}"),
            table,
            [column],
            unique=False,
        )


def downgrade() -> None:
    for table, column, ref_table, ref_column, _ondelete in reversed(_FOREIGN_KEYS):
        op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)
        _replace_foreign_key(
            table,
            column,
            ref_table,
            ref_column,
            ondelete=None,
        )

    for column in reversed(
        ("action", "branch_id", "org_id", "success", "timestamp", "user_id")
    ):
        op.drop_index(op.f(f"ix_audit_log_{column}"), table_name="audit_log")
    op.drop_table("audit_log")
