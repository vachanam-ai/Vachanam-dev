from pathlib import Path


def test_c26_is_head_after_b25():
    src = Path(
        "alembic/versions/c26preflang2026_patient_preferred_language.py"
    ).read_text(encoding="utf-8")
    assert 'revision = "c26preflang2026"' in src
    assert 'down_revision = "b25clinicq2026"' in src
    assert "preferred_language" in src


def test_no_other_migration_points_past_b25():
    versions = Path("alembic/versions")
    claimants = [
        f.name for f in versions.glob("*.py")
        if 'down_revision = "b25clinicq2026"' in f.read_text(encoding="utf-8")
    ]
    assert claimants == ["c26preflang2026_patient_preferred_language.py"]
