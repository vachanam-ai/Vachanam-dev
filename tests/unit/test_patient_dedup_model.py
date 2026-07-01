from backend.models.schema import Patient


def test_patient_has_is_primary_column():
    col = Patient.__table__.columns["is_primary"]
    assert col.nullable is False


def test_patient_has_partial_unique_index():
    idx = {i.name: i for i in Patient.__table__.indexes}
    assert "uq_patient_branch_phone_name" in idx
    target = idx["uq_patient_branch_phone_name"]
    assert target.unique is True
