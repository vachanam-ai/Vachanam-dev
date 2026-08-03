"""WA MVP1 Task 8 — templates ship English-only (spec D5)."""
from backend.services.wa_templates import template_lang


def test_template_language_is_always_english():
    """Clinics use English on WhatsApp — one approved copy per template beats
    four half-approved translations, and a te template does not exist on the
    WABA (the send would fail outright)."""
    for lang in ("te", "hi", "ta", "kn", "ml", "mr", "bn", None, "", "en"):
        assert template_lang(lang) == "en"
