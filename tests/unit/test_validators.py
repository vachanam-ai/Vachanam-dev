"""Input validators — Indian phone, email, password strength.

Uses Vinay's real sample data (8096007554) to confirm valid input passes and a
wide spread of garbage is rejected. These are pure functions — no DB/Redis.
"""
import pytest

from backend.services.validators import (
    normalize_email,
    normalize_indian_phone,
    validate_password,
)


# ── Phone ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("8096007554", "+918096007554"),       # Vinay's real number
        ("08096007554", "+918096007554"),       # leading 0
        ("918096007554", "+918096007554"),       # 91 prefix
        ("+918096007554", "+918096007554"),       # E.164
        ("+91 80960 07554", "+918096007554"),     # spaces
        ("80960-07554", "+918096007554"),         # hyphen
        ("9999999999", "+919999999999"),          # starts 9
        ("6000000000", "+916000000000"),          # starts 6
    ],
)
def test_valid_indian_phones_normalize(raw, expected):
    assert normalize_indian_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",                  # empty
        "123",               # too short
        "12345",             # too short
        "1234567890",        # 10 digits but starts 1 (not a mobile)
        "5096007554",        # starts 5 (invalid)
        "80960075540",       # 11 digits
        "809600755",         # 9 digits
        "abcdefghij",        # letters
        "8096a07554",        # mixed
        "+1 5096007554",     # non-India
        "0000000000",        # starts 0
    ],
)
def test_invalid_phones_rejected(raw):
    with pytest.raises(ValueError):
        normalize_indian_phone(raw)


# ── Email ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("vinayrongala2002@gmail.com", "vinayrongala2002@gmail.com"),
        ("  Vinay@Clinic.IN ", "vinay@clinic.in"),
        ("apple@example.com", "apple@example.com"),  # valid format — accepted
    ],
)
def test_valid_emails(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "notanemail", "a@b", "a@@b.com", "a b@c.com", "x@y..com", "@nope.com", "nope@"],
)
def test_invalid_emails_rejected(raw):
    with pytest.raises(ValueError):
        normalize_email(raw)


# ── Password ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pw", ["Clinic2024", "srinivas7", "Dental@99", "abcd1234x"])
def test_strong_passwords_pass(pw):
    validate_password(pw)  # no raise


@pytest.mark.parametrize(
    "pw",
    [
        "",              # empty
        "short1",        # < 8
        "1234567890",    # all numbers (the one Vinay flagged)
        "00000000",      # all numbers + common
        "password",      # no digit + common
        "abcdefgh",      # no digit
        "12345678",      # common all-numeric
        "qwerty123",     # common
    ],
)
def test_weak_passwords_rejected(pw):
    with pytest.raises(ValueError):
        validate_password(pw)
