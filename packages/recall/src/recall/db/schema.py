from __future__ import annotations

from pathlib import Path

import duckdb

SCHEMA_VERSION = 1


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    if not _schema_version_table_exists(conn):
        _apply_schema(conn)
        _set_schema_version(conn)
        return

    current = _get_schema_version(conn)
    if current != SCHEMA_VERSION:
        raise RuntimeError(
            f"schema version mismatch (expected {SCHEMA_VERSION}, found {current}). "
            "Run with --recreate to rebuild."
        )


def _schema_version_table_exists(conn: duckdb.DuckDBPyConnection) -> bool:
    rows = conn.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'schema_version'"
    ).fetchone()
    return bool(rows and rows[0])


def _apply_schema(conn: duckdb.DuckDBPyConnection) -> None:
    schema_path = Path(__file__).with_name("schema.sql")
    sql = schema_path.read_text(encoding="utf-8")
    conn.execute(sql)


def _set_schema_version(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", [SCHEMA_VERSION])


def _get_schema_version(conn: duckdb.DuckDBPyConnection) -> int:
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    if row is None or row[0] is None:
        raise RuntimeError("schema_version table is empty")
    return int(row[0])
