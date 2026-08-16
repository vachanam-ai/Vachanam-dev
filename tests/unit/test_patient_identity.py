import pytest

from backend.services.patient_identity import normalize_patient_age, normalize_patient_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("vinay rongala", "vinay rongala"),
        ("\u0c35\u0c3f\u0c28\u0c2f\u0c4d", "Vinay"),
        ("\u0c36\u0c4d\u0c30\u0c40\u0c28\u0c3f\u0c35\u0c3e\u0c38\u0c4d", "Shrinivas"),
        ("\u0c32\u0c15\u0c4d\u0c37\u0c4d\u0c2e\u0c3f", "Lakshmi"),
    ],
)
def test_patient_names_are_stored_in_latin_script(raw, expected):
    assert normalize_patient_name(raw) == expected


@pytest.mark.parametrize("raw", [24, "24", "\u0c68\u0c6a"])
def test_patient_age_is_stored_as_an_integer(raw):
    assert normalize_patient_age(raw) == 24


@pytest.mark.parametrize("raw", [True, "twenty four", -1, 121, "24.5"])
def test_patient_age_is_never_guessed(raw):
    with pytest.raises(ValueError):
        normalize_patient_age(raw)
