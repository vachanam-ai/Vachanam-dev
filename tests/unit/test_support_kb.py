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
