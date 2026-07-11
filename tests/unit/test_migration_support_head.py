"""The support migration must exist, define both tables, and be chained."""
import pathlib
import re


def test_support_migration_defines_both_tables():
    versions = pathlib.Path("alembic/versions")
    src = next(p for p in versions.glob("*_support_tables.py")).read_text(encoding="utf-8")
    assert "create_table" in src
    assert "support_tickets" in src and "support_messages" in src
    # down_revision chained to a real prior head, not None
    assert re.search(r"down_revision\s*=\s*['\"]\w+['\"]", src)
