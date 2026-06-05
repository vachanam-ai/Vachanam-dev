"""Test: no real secrets committed anywhere in git history.

Phase 4.5 Task 16a — scans `git log --all -p` output for known secret
prefixes / patterns.  Any match that is NOT in the allowlist fails the test
immediately with the offending line quoted.

Patterns checked (per spec section 12.1):
  1. rzp_live_           — Razorpay live-mode key prefix
  2. sk-proj-            — OpenAI live key prefix
  3. AIza[A-Za-z0-9_-]{35} — Google API key (39-char canonical form)
  4. JWT_SECRET=<non-empty-value> — real secret assigned in committed file
  5. META_ACCESS_TOKEN=<non-empty-value>
  6. RAZORPAY_KEY_SECRET=<non-empty-value>

Allowlist policy (mirrors .gitleaks.toml):
  - Documentation / spec files that MENTION the pattern as a scan target
    (e.g., "scan for rzp_live_") are allowlisted — they contain the string
    as an example, not an actual secret.
  - CI test stubs prefixed with test- or rzp_test_ are allowlisted.
  - The well-known dev placeholder `dev-secret-change-in-production` in
    Phase 0 docs is allowlisted (not a real secret).
  - The Razorpay *test-mode* key secret `clEoihnt7Q2OMTCZGJNvrSow` that
    was mentioned in CHANGELOG docs (paired with `rzp_test_` prefix key)
    is allowlisted — test-mode secrets are not production credentials.

Per tester.md rule 9: this test runs against real git history via
subprocess, not a mock.  No fakeredis, no SQLite, no mock git.

Per tester.md rule 5: no hardcoded credentials, URLs, or phone numbers
(the patterns below are detection signatures, not credentials).
"""

import re
import subprocess
from pathlib import Path


# ── Allowlisted strings ─────────────────────────────────────────────────
# Each entry is a substring or regex that, if present on the same line as
# a pattern match, makes that line safe.  Mirrors .gitleaks.toml allowlist
# plus documentation-context allowlists.

# Lines that mention the pattern as a *scan target* in docs / specs / configs
_DOC_CONTEXT_ALLOWLIST = [
    # .gitleaks.toml entries that list patterns as regex examples
    r"'''rzp_live_'''",
    r"'''sk-proj-'''",
    r"AIza\[A-Za-z0-9",           # regex pattern written as a gitleaks rule
    # Spec / CLAUDE.md lines that say "scan for rzp_live_" or similar
    r"grep.*rzp_live",
    r"grep.*sk-proj",
    r"grep.*AIza",
    # Doc lines discussing what patterns to check (this test file itself)
    r"test_secrets_not_in_repo",
    # Commit messages that list pattern names as a summary of what was scanned
    r"secret patterns \(",
    # CI yml line that runs gitleaks or mentions pattern in a grep
    r"gitleaks",
    # Markdown / spec discussion lines about live keys
    r"rzp_live_\*",               # "rzp_live_*" as glob in prose
    r"`rzp_live_\*`",             # backtick-quoted variant
    r"rzp_live_\*`",              # partial backtick variant
    # Phase docs discussing Razorpay activation steps
    r"Live Razorpay",
    r"live mode requires",
    r"live `rzp_live",
]

# Known safe JWT_SECRET values (dev placeholders, CI test stubs)
_SAFE_JWT_SECRETS = [
    "dev-secret-change-in-production",
    "ci-test-jwt-secret-not-real-do-not-use-in-prod",
]

# Known safe RAZORPAY_KEY_SECRET values (test-mode secrets, mentioned in docs)
_SAFE_RAZORPAY_SECRETS = [
    "clEoihnt7Q2OMTCZGJNvrSow",   # test-mode secret paired with rzp_test_ key
    "test-razorpay-secret",        # CI stub
]

# Known safe META_ACCESS_TOKEN values
_SAFE_META_TOKENS = [
    "test-meta-token",             # CI stub
]

# Placeholder-only values that appear in docs as "VAR=..." or "VAR=xxx"
_PLACEHOLDER_RE = re.compile(r"^[.x]+$", re.IGNORECASE)


def _is_doc_context(line: str) -> bool:
    """Return True if the line is documentation / config that MENTIONS the
    pattern as a scan target rather than containing an actual secret."""
    for pattern in _DOC_CONTEXT_ALLOWLIST:
        if re.search(pattern, line, re.IGNORECASE):
            return True
    return False


def _get_git_log_diff() -> str:
    """Run git log --all -p and return stdout as a string.

    Uses the repo root (two levels up from this file) as cwd so the test
    works regardless of the pytest invocation directory.

    IMPORTANT: excludes diffs from this test file's own source path.
    The test file necessarily contains pattern names like ``rzp_live_`` and
    ``sk-proj-`` as detection signatures.  When those strings appear in the
    git history diff of *this file*, they are not real secrets — they are
    the scanning infrastructure itself.  Approach B from Task 17a: scan
    everything EXCEPT the test file's own diff.
    """
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            "git", "log", "--all", "-p",
            "--", ".", ":!tests/security/test_secrets_not_in_repo.py",
        ],
        cwd=str(repo_root),
        capture_output=True,
        timeout=120,
    )
    # git log --all -p returns 0 even on empty repos
    assert result.returncode == 0, (
        f"git log failed: {result.stderr.decode('utf-8', errors='replace')}"
    )
    # Decode as UTF-8 with replacement for any non-UTF-8 binary diff hunks
    # (e.g., images, compiled assets).  Secret patterns are always ASCII, so
    # replacing non-decodable bytes cannot hide a real secret.
    return result.stdout.decode("utf-8", errors="replace")


def test_no_real_secrets_in_git_history():
    """Scan full git history for secret patterns; fail on any real match.

    This is a single test with 6 pattern checks.  Each pattern is scanned
    independently, and ALL violations are collected before failing so the
    developer sees every leak at once (not one-at-a-time whack-a-mole).
    """
    diff_output = _get_git_log_diff()
    lines = diff_output.splitlines()
    violations: list[str] = []

    # Track current commit hash for violation reporting
    current_commit = "<unknown>"

    for line in lines:
        # Track commit context
        if line.startswith("commit "):
            parts = line.split()
            if len(parts) >= 2 and len(parts[1]) >= 7:
                current_commit = parts[1][:12]

        # ── Pattern 1: rzp_live_ (Razorpay live key prefix) ──────────
        if "rzp_live_" in line.lower():
            if not _is_doc_context(line):
                violations.append(
                    f"[rzp_live_] commit={current_commit} line={line.strip()}"
                )

        # ── Pattern 2: sk-proj- (OpenAI live key prefix) ─────────────
        if "sk-proj-" in line.lower():
            if not _is_doc_context(line):
                violations.append(
                    f"[sk-proj-] commit={current_commit} line={line.strip()}"
                )

        # ── Pattern 3: AIza... (Google API key, 39 chars) ────────────
        if re.search(r"AIza[A-Za-z0-9_-]{35}", line):
            if not _is_doc_context(line):
                violations.append(
                    f"[Google API key] commit={current_commit} line={line.strip()}"
                )

        # ── Pattern 4: JWT_SECRET=<non-empty> ────────────────────────
        jwt_match = re.search(r"JWT_SECRET=([A-Za-z0-9_.+/=-]+)", line)
        if jwt_match:
            value = jwt_match.group(1)
            if (
                value not in _SAFE_JWT_SECRETS
                and not _PLACEHOLDER_RE.match(value)
                and not _is_doc_context(line)
            ):
                violations.append(
                    f"[JWT_SECRET] commit={current_commit} "
                    f"value={value[:20]}... line={line.strip()}"
                )

        # ── Pattern 5: META_ACCESS_TOKEN=<non-empty> ─────────────────
        meta_match = re.search(r"META_ACCESS_TOKEN=([A-Za-z0-9_.+/=-]+)", line)
        if meta_match:
            value = meta_match.group(1)
            if (
                value not in _SAFE_META_TOKENS
                and not _PLACEHOLDER_RE.match(value)
                and not _is_doc_context(line)
            ):
                violations.append(
                    f"[META_ACCESS_TOKEN] commit={current_commit} "
                    f"value={value[:20]}... line={line.strip()}"
                )

        # ── Pattern 6: RAZORPAY_KEY_SECRET=<non-empty> ───────────────
        rzp_match = re.search(
            r"RAZORPAY_KEY_SECRET=([A-Za-z0-9_.+/=-]+)", line
        )
        if rzp_match:
            value = rzp_match.group(1)
            if (
                value not in _SAFE_RAZORPAY_SECRETS
                and not _PLACEHOLDER_RE.match(value)
                and not _is_doc_context(line)
            ):
                violations.append(
                    f"[RAZORPAY_KEY_SECRET] commit={current_commit} "
                    f"value={value[:20]}... line={line.strip()}"
                )

    assert violations == [], (
        f"REAL SECRETS FOUND IN GIT HISTORY — {len(violations)} violation(s).\n"
        "Each must be investigated and the secret ROTATED immediately.\n\n"
        + "\n".join(violations)
    )
