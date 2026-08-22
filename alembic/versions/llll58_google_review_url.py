"""Store each clinic's Google review link.

Revision ID: llll58_google_review_url
Revises: kkkk57_caller_lang
"""
import sqlalchemy as sa
from alembic import op


revision = "llll58_google_review_url"
down_revision = "kkkk57_caller_lang"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("google_review_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("branches", "google_review_url")
