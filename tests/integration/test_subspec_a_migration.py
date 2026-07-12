"""Sub-spec A schema migration tests.

Verifies that the Alembic migration 2026_06_09_subspec_a_schema applied correctly.
These tests use the `db` fixture which runs create_all from SQLAlchemy metadata
(ORM model must match migration exactly).

Tests cover:
- doctors new columns
- doctor_unavailability table + UNIQUE constraint
- followup_tasks new columns
- tokens new columns
- calendar_write_tasks table
- user_role enum contains 'doctor'
- compound indexes ix_tokens_branch_date + ix_tokens_branch_doctor_date
"""
import pytest
from sqlalchemy import inspect, text


# ---------------------------------------------------------------------------
# Helper: get column names for a table (sync via run_sync)
# ---------------------------------------------------------------------------

def _get_columns(conn, table_name: str) -> set[str]:
    return {col["name"] for col in inspect(conn).get_columns(table_name)}


def _get_tables(conn) -> set[str]:
    return set(inspect(conn).get_table_names())


def _get_indexes(conn, table_name: str) -> set[str]:
    return {i["name"] for i in inspect(conn).get_indexes(table_name)}


def _get_unique_constraints(conn, table_name: str) -> set[str]:
    return {uc["name"] for uc in inspect(conn).get_unique_constraints(table_name)}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_doctor_new_columns(db):
    """doctors table must have all 6 new columns from sub-spec A §3.1."""
    from backend.database import engine
    async with engine.connect() as conn:
        cols = await conn.run_sync(_get_columns, "doctors")
    for required in [
        "available_weekdays",
        "post_treatment_followup",
        "walkins_closed_today_date",
        "calendar_event_id_recurring",
        "user_id",
        "invited_email",
    ]:
        assert required in cols, f"doctors table is missing column: {required}"


@pytest.mark.asyncio
async def test_doctor_unavailability_table_exists(db):
    """doctor_unavailability table must exist."""
    from backend.database import engine
    async with engine.connect() as conn:
        tables = await conn.run_sync(_get_tables)
    assert "doctor_unavailability" in tables, "doctor_unavailability table not found"


@pytest.mark.asyncio
async def test_doctor_unavailability_columns(db):
    """doctor_unavailability must have all required columns."""
    from backend.database import engine
    async with engine.connect() as conn:
        cols = await conn.run_sync(_get_columns, "doctor_unavailability")
    for required in [
        "id", "branch_id", "doctor_id", "date", "reason",
        "created_by_user_id", "created_at",
    ]:
        assert required in cols, f"doctor_unavailability missing column: {required}"


@pytest.mark.asyncio
async def test_doctor_unavailability_unique_constraint(db):
    """doctor_unavailability must have UNIQUE(doctor_id, date) constraint."""
    from backend.database import engine
    async with engine.connect() as conn:
        ucs = await conn.run_sync(_get_unique_constraints, "doctor_unavailability")
    assert "uq_doctor_unavailability_doctor_date" in ucs, (
        f"UNIQUE constraint uq_doctor_unavailability_doctor_date not found; got: {ucs}"
    )


@pytest.mark.asyncio
async def test_token_new_columns(db):
    """tokens table must have cancelled_by_user_id and emergency_reason columns."""
    from backend.database import engine
    async with engine.connect() as conn:
        cols = await conn.run_sync(_get_columns, "tokens")
    for required in ["cancelled_by_user_id", "emergency_reason"]:
        assert required in cols, f"tokens table is missing column: {required}"


@pytest.mark.asyncio
async def test_followup_task_new_columns(db):
    """followup_tasks table must have task_type and token_id columns."""
    from backend.database import engine
    async with engine.connect() as conn:
        cols = await conn.run_sync(_get_columns, "followup_tasks")
    for required in ["task_type", "token_id"]:
        assert required in cols, f"followup_tasks table is missing column: {required}"


@pytest.mark.asyncio
async def test_calendar_write_tasks_table(db):
    """calendar_write_tasks table must exist."""
    from backend.database import engine
    async with engine.connect() as conn:
        tables = await conn.run_sync(_get_tables)
    assert "calendar_write_tasks" in tables, "calendar_write_tasks table not found"


@pytest.mark.asyncio
async def test_calendar_write_tasks_columns(db):
    """calendar_write_tasks must have all required columns."""
    from backend.database import engine
    async with engine.connect() as conn:
        cols = await conn.run_sync(_get_columns, "calendar_write_tasks")
    for required in [
        "id", "branch_id", "token_id", "operation", "payload_json",
        "google_event_id", "status", "attempts", "last_error",
        "next_attempt_at", "created_at", "updated_at",
    ]:
        assert required in cols, f"calendar_write_tasks missing column: {required}"


@pytest.mark.asyncio
async def test_user_role_enum_has_doctor(db):
    """user_role Postgres enum must include the 'doctor' value."""
    from backend.database import engine
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT unnest(enum_range(NULL::user_role))")
        )
        vals = {r[0] for r in result}
    assert "doctor" in vals, (
        f"user_role enum does not contain 'doctor'; current values: {vals}"
    )


@pytest.mark.asyncio
async def test_compound_indexes_present(db):
    """tokens table must have both compound indexes added for TD-018."""
    from backend.database import engine
    async with engine.connect() as conn:
        idx = await conn.run_sync(_get_indexes, "tokens")
    assert "ix_tokens_branch_date" in idx, (
        f"Missing index ix_tokens_branch_date; found: {idx}"
    )
    assert "ix_tokens_branch_doctor_date" in idx, (
        f"Missing index ix_tokens_branch_doctor_date; found: {idx}"
    )


@pytest.mark.asyncio
async def test_doctor_unavailability_branch_date_index(db):
    """doctor_unavailability must have index on (branch_id, date)."""
    from backend.database import engine
    async with engine.connect() as conn:
        idx = await conn.run_sync(_get_indexes, "doctor_unavailability")
    assert "ix_doctor_unavailability_branch_date" in idx, (
        f"Missing index ix_doctor_unavailability_branch_date; found: {idx}"
    )


@pytest.mark.asyncio
async def test_calendar_write_tasks_status_next_index(db):
    """calendar_write_tasks must have index on (status, next_attempt_at)."""
    from backend.database import engine
    async with engine.connect() as conn:
        idx = await conn.run_sync(_get_indexes, "calendar_write_tasks")
    assert "ix_calendar_tasks_status_next" in idx, (
        f"Missing index ix_calendar_tasks_status_next; found: {idx}"
    )
