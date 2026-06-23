"""De-id gate must reject identifying data before it reaches the example bank
(DPDP RULE 1 / RULE 9). Clean placeholder lines must pass.
"""
import pytest

from backend.services.deidentify import (
    DeidentificationError,
    assert_deidentified,
    find_pii,
    scrub,
)

PII_SAMPLES = [
    "+919876543210",
    "9876543210",
    "call me on 98765 43210",
    "phone 98765-43210",
    "patient age 45 years",
    "వయసు 60",
    "reach x@clinic.in",
    "OTP is 123456",
]

CLEAN_SAMPLES = [
    "నమస్తే అండి, {clinic} నుంచి మాట్లాడుతున్నాను. చెప్పండి, మీకు నేను ఎలా సహాయం చేయగలను?",
    "ఓకే అండి, నేను డాక్టర్ గారితో {name} గారి ప్రాబ్లం గురించి చెబుతాను. మీకు మళ్ళీ కాల్ చేస్తాను.",
    "రేపు ఉదయం {time} కి, లేదా మధ్యాహ్నం {time} కి స్లాట్ అవైలబుల్ గా ఉంది అండి.",
    "ఈ రోజు {time} కి డాక్టర్ {doctor} గారితో మీకు అపాయింట్‌మెంట్ ఉంది అండి.",  # has "10:30"-style? no — placeholder
]


@pytest.mark.parametrize("s", PII_SAMPLES)
def test_pii_rejected(s):
    assert find_pii(s), f"should have flagged PII in: {s}"
    with pytest.raises(DeidentificationError):
        assert_deidentified(s)


@pytest.mark.parametrize("s", CLEAN_SAMPLES)
def test_clean_passes(s):
    assert find_pii(s) == []
    assert_deidentified(s)  # no raise


def test_scrub_replaces_identifiers():
    out = scrub("call 9876543210 or x@y.com, age 45 years, id 999999")
    # after scrub, the gate must pass
    assert_deidentified(out)
    assert "{phone}" in out and "{email}" in out


def test_literal_time_digits_pass():
    # A spoken time like 10:30 is not PII (no 5-digit run) — must not be rejected.
    assert find_pii("మీటింగ్ 10:30 కి") == []
