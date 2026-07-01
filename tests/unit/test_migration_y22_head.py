from pathlib import Path


def test_y22_is_head_after_x21():
    src = Path("alembic/versions/y22patientdedup2026_patient_dedup.py").read_text(encoding="utf-8")
    assert 'revision = "y22patientdedup2026"' in src
    assert 'down_revision = "x21welcomeshort2026"' in src


def test_no_other_migration_points_past_x21():
    # y22 must be the new single head — nothing else may claim x21 as parent.
    versions = Path("alembic/versions")
    claimants = [
        f.name for f in versions.glob("*.py")
        if 'down_revision = "x21welcomeshort2026"' in f.read_text(encoding="utf-8")
    ]
    assert claimants == ["y22patientdedup2026_patient_dedup.py"]
