"""KB loads, parses front-matter, and filters by audience (no clinic leak)."""


def test_kb_audience_filtering():
    from backend.services import support_kb

    pub = support_kb.kb_text("public")
    clin = support_kb.kb_text("clinic")
    assert pub and clin
    # connect-did.md is audience: clinic — must NOT appear in the public subset
    assert "Connecting your phone number" not in pub
    assert "Connecting your phone number" in clin


def test_kb_entries_have_frontmatter():
    from backend.services import support_kb

    entries = support_kb.load_kb()
    assert entries
    for e in entries:
        assert e["title"]
        assert e["audience"] in ("public", "clinic", "both")


# ── #327: single end-to-end knowledge document for the chatbot ────────────────

def test_knowledge_doc_loaded_and_comprehensive():
    from backend.services import support_kb
    k = support_kb.knowledge_text()
    assert len(k) > 5000  # end-to-end, not a stub
    for fact in ("5,999", "9,999", "17,999", "300", "follow-up", "DPDP",
                 "token", "Google Calendar", "support@vachanam.in"):
        assert fact in k, f"knowledge doc missing key fact: {fact}"


def test_knowledge_doc_names_no_stack_vendors():
    """Stack confidentiality (#321) applies to the bot's grounding doc too —
    the bot must never be ABLE to reveal a vendor name."""
    from backend.services import support_kb
    k = support_kb.knowledge_text()
    for vendor in ("Soniox", "Sarvam", "Gemini", "smallest", "LiveKit",
                   "Vobiz", "Neon", "Upstash", "Fly.io", "Resend"):
        assert vendor not in k, f"vendor leaked into bot knowledge: {vendor}"


def test_knowledge_doc_not_an_article():
    from backend.services import support_kb
    titles = [e["title"] for e in support_kb.load_kb()]
    assert not any("KNOWLEDGE" in t.upper() for t in titles)
