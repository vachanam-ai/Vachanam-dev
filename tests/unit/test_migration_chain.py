"""Structural guards for the fresh-database Alembic and ZAP gates."""

import importlib.util
import inspect
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_phase45_revision_is_delta_not_second_initial_schema():
    path = (
        ROOT
        / "alembic"
        / "versions"
        / "8559268c0c44_phase45_audit_log_ondelete_fk_indexes.py"
    )
    spec = importlib.util.spec_from_file_location("phase45_revision", path)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    source = inspect.getsource(revision.upgrade)

    assert source.count("op.create_table(") == 1
    assert '"audit_log"' in source
    assert '"organizations"' not in source
    assert len(revision._FOREIGN_KEYS) == 15


def test_ci_runs_real_fresh_database_upgrade():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "Alembic fresh-database upgrade" in workflow
    assert "alembic upgrade head" in workflow
    assert "KNOWN-broken" not in workflow


def test_zap_missing_report_is_a_failure():
    workflow = (ROOT / ".github" / "workflows" / "zap-baseline.yml").read_text()
    missing_report_branch = workflow.split("ZAP report not found", maxsplit=1)[1]

    assert "ghcr.io/zaproxy/zaproxy:stable" in workflow
    assert "softwaresecurityproject/zap-stable" not in workflow
    assert "chmod 777 zap" in workflow
    assert "exit 1" in missing_report_branch
