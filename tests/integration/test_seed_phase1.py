"""tests/integration/test_seed_phase1.py

Integration tests for scripts/seed_phase1.py.

Tests:
  test_seed_phase1_creates_three_rows       — fresh DB → 1 Org + 1 Branch + 1 Doctor
  test_seed_phase1_idempotent               — run twice → no duplicate rows
  test_seed_phase1_missing_did_exits_cleanly — unset VOBIZ_DID_NUMBER → SystemExit(1)

All tests use the `db` fixture from conftest.py which creates a fresh schema per
test and tears it down afterward. The seed functions are invoked directly (not via
subprocess) so they share the same async session provided by the fixture.

Sensitive data: DID and phone number values in assertions use obviously-fake test
values — never real credentials.
"""

import os
import sys
import pytest

from sqlalchemy import func, select

from backend.models.schema import Organization, Branch, Doctor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _run_seed(
    session,
    did_number: str,
    admin_phone: str,
    owner_email: str,
) -> None:
    """Call seed._seed() directly with explicit values for test isolation.

    The `owner_email` override prevents UNIQUE constraint collisions between
    test runs that share the same persistent database (e.g. the real vachanam_dev
    DB that may already have seed data from a previous manual run).
    """
    from scripts.seed_phase1 import _seed
    await _seed(
        session,
        did_number=did_number,
        admin_phone=admin_phone,
        owner_email=owner_email,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_seed_phase1_creates_three_rows(db):
    """After a fresh seed, exactly 1 Org, 1 Branch, and 1 Doctor must exist."""
    test_did = "+911111166666"
    test_admin = "+919888877777"
    # Unique email per test so it never collides with other test runs or manually-seeded data
    test_email = "test-creates-three@vachanam-phase1.internal"

    await _run_seed(db, test_did, test_admin, test_email)

    org_count = (await db.execute(select(func.count()).select_from(Organization))).scalar()
    branch_count = (await db.execute(select(func.count()).select_from(Branch))).scalar()
    doctor_count = (await db.execute(select(func.count()).select_from(Doctor))).scalar()

    assert org_count == 1, f"Expected 1 org, got {org_count}"
    assert branch_count == 1, f"Expected 1 branch, got {branch_count}"
    assert doctor_count == 1, f"Expected 1 doctor, got {doctor_count}"

    # Spot-check seeded values
    branch = (await db.execute(select(Branch).where(Branch.did_number == test_did))).scalar_one()
    assert branch.name == "Test Clinic Hyderabad"
    assert branch.emergency_contact == test_admin

    doctor = (await db.execute(select(Doctor).where(Doctor.branch_id == branch.id))).scalar_one()
    assert doctor.name == "Dr. Test Kumar"
    assert doctor.is_default_doctor is True
    assert doctor.booking_type == "token"
    assert doctor.daily_token_limit == 50


@pytest.mark.asyncio
async def test_seed_phase1_idempotent(db):
    """Running seed twice must not create duplicate rows.

    Second run must print 'already seeded' and leave row counts unchanged.
    """
    test_did = "+911111177777"
    test_admin = "+919888866666"
    test_email = "test-idempotent@vachanam-phase1.internal"

    # First run
    await _run_seed(db, test_did, test_admin, test_email)

    branch_count_after_first = (
        await db.execute(select(func.count()).select_from(Branch))
    ).scalar()
    assert branch_count_after_first == 1

    # Second run — must be a no-op
    await _run_seed(db, test_did, test_admin, test_email)

    org_count = (await db.execute(select(func.count()).select_from(Organization))).scalar()
    branch_count = (await db.execute(select(func.count()).select_from(Branch))).scalar()
    doctor_count = (await db.execute(select(func.count()).select_from(Doctor))).scalar()

    assert org_count == 1, f"Idempotent run created extra orgs: {org_count}"
    assert branch_count == 1, f"Idempotent run created extra branches: {branch_count}"
    assert doctor_count == 1, f"Idempotent run created extra doctors: {doctor_count}"


@pytest.mark.asyncio
async def test_seed_phase1_missing_did_exits_cleanly(tmp_path):
    """When VOBIZ_DID_NUMBER is absent from both env and .env, the script must
    exit with code 1 and a clear error message — not raise an unhandled exception.

    Strategy: write a minimal .env file (without VOBIZ_DID_NUMBER) to a tmp dir,
    then run the seed script as a subprocess pointing at that tmp dir as the repo
    root. This bypasses load_dotenv reading the real .env which does have the var.
    """
    import subprocess

    # Write a minimal .env that has DATABASE_URL and other required vars but
    # deliberately omits VOBIZ_DID_NUMBER.
    fake_env_file = tmp_path / ".env"
    # These values let the script load settings without hitting unrelated errors,
    # but VOBIZ_DID_NUMBER is absent so the guard fires before any DB query.
    fake_env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://vachanam:localdev123@localhost:5432/vachanam_dev\n"
        "REDIS_URL=redis://localhost:6379\n"
        "JWT_SECRET=fakesecretfortestonly\n"
        "SARVAM_API_KEY=fake\n"
        "OPENAI_API_KEY=fake\n"
        "GEMINI_API_KEY=fake\n"
        "LIVEKIT_URL=wss://fake.fly.dev\n"
        "LIVEKIT_API_KEY=fake\n"
        "LIVEKIT_API_SECRET=fake\n"
        "ADMIN_PHONE=+919000000001\n"
        # VOBIZ_DID_NUMBER intentionally absent
    )

    # Copy scripts/ directory into tmp_path so the subprocess can find seed_phase1.py
    import shutil

    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    shutil.copytree(
        os.path.join(repo_root, "scripts"),
        str(tmp_path / "scripts"),
    )
    # Copy backend/ so imports resolve
    shutil.copytree(
        os.path.join(repo_root, "backend"),
        str(tmp_path / "backend"),
    )

    # Run from tmp_path so load_dotenv finds the fake .env (not the real one)
    env = os.environ.copy()
    env.pop("VOBIZ_DID_NUMBER", None)  # Belt-and-suspenders: remove from proc env too

    result = subprocess.run(
        [sys.executable, "scripts/seed_phase1.py"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
    )

    assert result.returncode != 0, (
        f"Expected non-zero exit when VOBIZ_DID_NUMBER is missing, got 0. "
        f"stdout: {result.stdout!r}  stderr: {result.stderr!r}"
    )
    # The error message must clearly name the missing variable
    assert "VOBIZ_DID_NUMBER" in result.stderr, (
        f"Expected 'VOBIZ_DID_NUMBER' in stderr error message. "
        f"Got: {result.stderr!r}"
    )
