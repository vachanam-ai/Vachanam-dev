"""An operational runbook must name the stack that actually exists.

Neon was purged on 2026-07-31 and replaced by Supabase Postgres. The runbooks
were not updated, so on 2026-08-12 the breach-response procedure still said:

    "Go to Neon dashboard > your project > Connection Details"
    "Check if you have Neon point-in-time recovery (PITR) available"
    "Neon (database) | Neon Support | neon.tech support portal"

Those are the instructions someone follows while credentials are leaking and
the clock on a 72-hour DPDP notification is running. Pointing them at a vendor
the project left costs the one thing an incident has none of: time.

Runbooks are prose, so nothing else in the suite reads them. This does.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RUNBOOKS = sorted(Path("docs/runbooks").glob("*.md"))

# Vendors the project has left. A runbook naming one is stale by definition.
# Value = what it was replaced by, so the failure tells you the fix.
RETIRED = {
    "neon": "Supabase Postgres (ap-south-1 Mumbai)",
    "pipecat": "LiveKit Agents",
}

# The one legitimate reason to write a retired name: warning people off it.
_ALLOWED_CONTEXT = re.compile(
    r"purged|do not reintroduce|must not be reintroduced|retired|replaced by"
    r"|migrated to|no longer",
    re.IGNORECASE,
)


def test_there_are_runbooks_to_check():
    """A glob that matches nothing would make every test below vacuously pass."""
    assert RUNBOOKS, "docs/runbooks/*.md matched no files"


@pytest.mark.parametrize("path", RUNBOOKS, ids=lambda p: p.name)
def test_runbook_names_no_retired_vendor(path: Path):
    offenders = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if _ALLOWED_CONTEXT.search(line):
            continue  # a line explicitly marking the thing as gone
        for retired, replacement in RETIRED.items():
            if re.search(rf"\b{retired}\b", line, re.IGNORECASE):
                offenders.append(f"{path}:{lineno} names '{retired}' → use {replacement}\n    {line.strip()[:110]}")
    assert not offenders, (
        "runbook points at a vendor this project no longer uses:\n  "
        + "\n  ".join(offenders)
    )


def test_the_guard_detects_a_stale_reference():
    """Negative control — a check that cannot fail is decoration."""
    sample = "Go to Neon dashboard > your project > Connection Details"
    assert not _ALLOWED_CONTEXT.search(sample)
    assert re.search(r"\bneon\b", sample, re.IGNORECASE)


def test_the_allowed_context_really_exempts_a_warning():
    """The deploy runbook's own warning line must not trip the guard."""
    sample = "Neon was PURGED on 2026-07-31 and must not be reintroduced."
    assert _ALLOWED_CONTEXT.search(sample)


def test_breach_runbook_still_has_a_database_recovery_step():
    """Renaming the vendor must not have deleted the procedure itself."""
    text = (Path("docs/runbooks/breach-response.md")).read_text(encoding="utf-8")
    assert "Supabase" in text, "breach runbook names no database vendor at all"
    assert "Backups" in text or "backup" in text
    assert "supabase.com/dashboard/support" in text, "no vendor escalation contact"
