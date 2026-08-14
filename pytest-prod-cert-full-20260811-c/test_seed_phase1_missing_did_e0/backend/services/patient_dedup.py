"""One-time patient de-duplication SQL, shared by the y22 migration and its test.

Postgres-only. MERGE_SQL repoints child rows (tokens, treatment_notes,
followup_tasks) from duplicate patients to the earliest-created canonical row
per (branch_id, phone, lower(name)), then deletes the duplicates.
BACKFILL_PRIMARY_SQL marks exactly one is_primary owner per phone (earliest
created_at) and every NULL-phone row as its own primary.

Statements run in list order. Idempotent enough to re-run: after a merge there
are no duplicates left, so the repoint/delete become no-ops.
"""

# ponytail: raw SQL, not ORM — this is a bulk one-time cleanup; window functions
# do it in one pass per table instead of N per-row loads.

_RANK = """
WITH ranked AS (
    SELECT id,
           first_value(id) OVER (
               PARTITION BY branch_id, phone, lower(name)
               ORDER BY created_at ASC, id ASC
           ) AS canonical_id
    FROM patients
    WHERE phone IS NOT NULL
)
"""

MERGE_SQL: list[str] = [
    _RANK + """
    UPDATE tokens t SET patient_id = r.canonical_id
    FROM ranked r
    WHERE t.patient_id = r.id AND r.id <> r.canonical_id;
    """,
    _RANK + """
    UPDATE treatment_notes tn SET patient_id = r.canonical_id
    FROM ranked r
    WHERE tn.patient_id = r.id AND r.id <> r.canonical_id;
    """,
    _RANK + """
    UPDATE followup_tasks ft SET patient_id = r.canonical_id
    FROM ranked r
    WHERE ft.patient_id = r.id AND r.id <> r.canonical_id;
    """,
    _RANK + """
    DELETE FROM patients p
    USING ranked r
    WHERE p.id = r.id AND r.id <> r.canonical_id;
    """,
]

BACKFILL_PRIMARY_SQL: list[str] = [
    "UPDATE patients SET is_primary = TRUE WHERE phone IS NULL;",
    """
    WITH ranked AS (
        SELECT id,
               first_value(id) OVER (
                   PARTITION BY branch_id, phone
                   ORDER BY created_at ASC, id ASC
               ) AS primary_id
        FROM patients
        WHERE phone IS NOT NULL
    )
    UPDATE patients p SET is_primary = TRUE
    FROM ranked r
    WHERE p.id = r.id AND r.id = r.primary_id;
    """,
]
