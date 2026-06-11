"""Shared input validators — Indian phone, password strength, email.

Used by auth (register/login/OTP) and any endpoint taking phone/password.
Pure functions; raise ValueError with a user-safe message on failure.
"""
import re

# Indian mobile: 10 digits starting 6-9, optionally prefixed +91 / 91 / 0.
_PHONE_STRIP = re.compile(r"[\s\-()]")
_INDIAN_MOBILE = re.compile(r"^[6-9]\d{9}$")

# Top passwords we refuse outright (covers the obvious sequential/keyboard ones).
_COMMON_PASSWORDS = {
    "12345678", "123456789", "1234567890", "password", "password1",
    "qwerty123", "11111111", "00000000", "abcd1234", "admin123",
    "iloveyou", "welcome1", "letmein1",
}


def normalize_indian_phone(raw: str) -> str:
    """Return E.164 +91XXXXXXXXXX for a valid Indian mobile, else raise.

    Accepts: 8096007554, 08096007554, 918096007554, +91 80960 07554, etc.
    """
    if not raw:
        raise ValueError("Phone number is required")
    cleaned = _PHONE_STRIP.sub("", raw.strip())
    if cleaned.startswith("+91"):
        cleaned = cleaned[3:]
    elif cleaned.startswith("91") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    elif cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = cleaned[1:]
    if not _INDIAN_MOBILE.match(cleaned):
        raise ValueError(
            "Enter a valid 10-digit Indian mobile number (starts with 6, 7, 8, or 9)"
        )
    return f"+91{cleaned}"


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(raw: str) -> str:
    """Lowercase + trim a syntactically valid email, else raise."""
    if not raw:
        raise ValueError("Email is required")
    email = raw.strip().lower()
    if not _EMAIL_RE.match(email) or ".." in email:
        raise ValueError("Enter a valid email address")
    return email


def validate_password(password: str) -> None:
    """Enforce a sane minimum: 8+ chars, at least one letter and one digit,
    not all-numeric, not a known-common password. Raises ValueError on failure."""
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if password.lower() in _COMMON_PASSWORDS:
        raise ValueError("That password is too common — choose something less guessable")
    if not re.search(r"[A-Za-z]", password):
        raise ValueError("Password must include at least one letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must include at least one number")
    if password.isdigit():
        raise ValueError("Password cannot be only numbers")
