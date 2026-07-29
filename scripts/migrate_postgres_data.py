"""Copy Vachanam's public data between PostgreSQL databases safely.

The source is held in one read-only, repeatable-read snapshot. The target copy
is one transaction, so a failure leaves the target unchanged.
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
from urllib.parse import urlsplit, urlunsplit

import psycopg
from dotenv import dotenv_values
from psycopg import sql


def _postgres_url(raw: str) -> str:
    """Return a psycopg URL and require TLS for non-local hosts."""
    raw = raw.replace("postgresql+asyncpg://", "postgresql://", 1)
    parts = urlsplit(raw)
    if parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
        query = parts.query
        if "sslmode=" not in query:
            query = f"{query}&sslmode=require" if query else "sslmode=require"
        raw = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, query, parts.fragment)
        )
    return raw


def _table_names(conn: psycopg.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public' AND tablename <> 'alembic_version'
            """
        )
    }


def _copy_order(conn: psycopg.Connection, tables: set[str]) -> list[str]:
    dependencies: dict[str, set[str]] = {table: set() for table in tables}
    dependents: dict[str, set[str]] = defaultdict(set)
    rows = conn.execute(
        """
        SELECT tc.table_name, ccu.table_name AS referenced_table
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.constraint_column_usage AS ccu
          ON ccu.constraint_schema = tc.constraint_schema
         AND ccu.constraint_name = tc.constraint_name
        WHERE tc.table_schema = 'public'
          AND tc.constraint_type = 'FOREIGN KEY'
        """
    )
    for table, referenced in rows:
        if table in tables and referenced in tables and table != referenced:
            dependencies[table].add(referenced)
            dependents[referenced].add(table)

    ready = sorted(table for table, deps in dependencies.items() if not deps)
    order: list[str] = []
    while ready:
        table = ready.pop(0)
        order.append(table)
        for dependent in sorted(dependents[table]):
            dependencies[dependent].discard(table)
            if not dependencies[dependent] and dependent not in order:
                ready.append(dependent)
        ready.sort()

    unresolved = sorted(tables - set(order))
    if unresolved:
        raise RuntimeError(f"Foreign-key cycle prevents safe copy: {unresolved}")
    return order


def _columns(conn: psycopg.Connection, table: str) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
    ]


def _fingerprint(conn: psycopg.Connection, table: str) -> tuple[int, str]:
    """Return a privacy-safe count and order-independent content hash."""
    query = sql.SQL(
        """
        SELECT count(*)::bigint,
               coalesce(md5(string_agg(row_hash, '' ORDER BY row_hash)), md5(''))
        FROM (
            SELECT md5(to_jsonb(item)::text) AS row_hash
            FROM {} AS item
        ) AS rows
        """
    ).format(sql.Identifier("public", table))
    count, digest = conn.execute(query).fetchone()
    return count, digest


def migrate(source_url: str, target_url: str) -> dict[str, int]:
    source_parts = urlsplit(source_url)
    target_parts = urlsplit(target_url)
    if (
        source_parts.hostname,
        source_parts.port,
        source_parts.path,
    ) == (
        target_parts.hostname,
        target_parts.port,
        target_parts.path,
    ):
        raise RuntimeError("Source and target resolve to the same database")

    copied: dict[str, int] = {}
    with (
        psycopg.connect(source_url, autocommit=False) as source,
        psycopg.connect(target_url, autocommit=False) as target,
    ):
        source.execute(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
        )
        source_tables = _table_names(source)
        target_tables = _table_names(target)
        if source_tables != target_tables:
            raise RuntimeError(
                "Schema table mismatch: "
                f"source_only={sorted(source_tables - target_tables)}, "
                f"target_only={sorted(target_tables - source_tables)}"
            )

        occupied = {
            table
            for table in target_tables
            if target.execute(
                sql.SQL("SELECT EXISTS (SELECT 1 FROM {} LIMIT 1)").format(
                    sql.Identifier("public", table)
                )
            ).fetchone()[0]
        }
        if occupied:
            raise RuntimeError(f"Target tables are not empty: {sorted(occupied)}")

        for table in _copy_order(target, target_tables):
            source_columns = _columns(source, table)
            target_columns = _columns(target, table)
            if set(source_columns) != set(target_columns):
                raise RuntimeError(f"Column mismatch for public.{table}")

            identifiers = sql.SQL(", ").join(map(sql.Identifier, source_columns))
            export_sql = sql.SQL("COPY {} ({}) TO STDOUT").format(
                sql.Identifier("public", table), identifiers
            )
            import_sql = sql.SQL("COPY {} ({}) FROM STDIN").format(
                sql.Identifier("public", table), identifiers
            )
            with (
                source.cursor().copy(export_sql) as export,
                target.cursor().copy(import_sql) as destination,
            ):
                for block in export:
                    destination.write(block)

            source_fingerprint = _fingerprint(source, table)
            target_fingerprint = _fingerprint(target, table)
            if source_fingerprint != target_fingerprint:
                raise RuntimeError(f"Content verification failed for public.{table}")
            copied[table] = target_fingerprint[0]

        target.commit()
        source.rollback()
    return copied


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-env", default="DATABASE_URL")
    parser.add_argument("--target-env", default="SUPABASE_MIGRATION_URL")
    args = parser.parse_args()

    values = {**dotenv_values(".env"), **os.environ}
    source = values.get(args.source_env)
    target = values.get(args.target_env)
    if not source or not target:
        raise SystemExit("Source or target database URL is missing")

    copied = migrate(_postgres_url(source), _postgres_url(target))
    for table, count in copied.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()
