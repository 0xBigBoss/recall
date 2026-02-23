from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import duckdb

from recall.core.config import AppConfig
from recall.core.models import Session, ToolCall
from recall.core.types import Source
from recall.db import (
    advisory_lock,
    connect,
    create_fts_indexes,
    delete_session,
    fetch_session_state,
    insert_messages,
    insert_session,
    insert_tool_calls,
)
from recall.parsers import SessionParser, all_parsers, get_parser

logger = logging.getLogger("recall.indexer")


@dataclass(frozen=True)
class IndexSummary:
    total: int
    indexed: int
    skipped: int
    failed: int


@dataclass(frozen=True)
class PersistedSessionRows:
    session_row: tuple[object, ...]
    message_rows: list[tuple[object, ...]]
    tool_call_rows: list[tuple[object, ...]]


def index_sessions(
    *,
    source: Source | None,
    full: bool,
    recreate: bool,
    verbose: bool,
) -> IndexSummary:
    config = AppConfig.load()
    if verbose:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)

    if recreate:
        full = True

    with advisory_lock(config.lock_path):
        conn = connect(config, recreate=recreate)
        try:
            paths = _discover_paths(source)
            indexed = 0
            skipped = 0
            failed = 0
            for parser, path in paths:
                try:
                    if not full and _is_unchanged(conn, path):
                        skipped += 1
                        logger.info("skip unchanged %s", path)
                        continue
                    session = parser.parse(path)
                    _write_session(conn, session)
                    indexed += 1
                    logger.info("indexed %s", path)
                except Exception as err:
                    failed += 1
                    logger.error("failed to index %s: %s", path, err)
            if indexed:
                create_fts_indexes(conn, config.fts)
            return IndexSummary(total=len(paths), indexed=indexed, skipped=skipped, failed=failed)
        finally:
            conn.close()


def _discover_paths(source: Source | None) -> list[tuple[SessionParser, Path]]:
    parsers = [get_parser(source)] if source else all_parsers()
    paths: list[tuple[SessionParser, Path]] = []
    for parser in parsers:
        for path in parser.discover():
            paths.append((parser, path))
    return paths


def _is_unchanged(conn: duckdb.DuckDBPyConnection, path: Path) -> bool:
    state = fetch_session_state(conn, str(path.expanduser().resolve()))
    if state is None:
        return False
    _, stored_mtime, stored_size = state
    stat = path.stat()
    return stored_mtime == stat.st_mtime and stored_size == stat.st_size


def _write_session(conn: duckdb.DuckDBPyConnection, session: Session) -> None:
    try:
        _write_session_transactional(conn, session)
    except Exception as err:
        if not _is_duckdb_fk_delete_limitation(err):
            raise
        logger.warning(
            "retrying session write with DuckDB-compatible delete path for session %s",
            session.id,
        )
        _write_session_duckdb_compatible(conn, session)


def _write_session_transactional(conn: duckdb.DuckDBPyConnection, session: Session) -> None:
    conn.execute("BEGIN")
    try:
        delete_session(conn, session.id)
        insert_session(conn, session)
        insert_messages(conn, session.messages)
        tool_calls = _collect_tool_calls(session)
        insert_tool_calls(conn, tool_calls)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _write_session_duckdb_compatible(conn: duckdb.DuckDBPyConnection, session: Session) -> None:
    # DuckDB currently fails FK checks for delete-then-parent-delete sequences
    # when performed inside one explicit transaction. Keep deletes in autocommit
    # mode and wrap inserts in a transaction. Snapshot existing rows so a failed
    # insert can restore the previous persisted session instead of losing data.
    previous_rows = _load_persisted_session_rows(conn, session.id)
    delete_session(conn, session.id)

    conn.execute("BEGIN")
    try:
        insert_session(conn, session)
        insert_messages(conn, session.messages)
        tool_calls = _collect_tool_calls(session)
        insert_tool_calls(conn, tool_calls)
        conn.execute("COMMIT")
    except Exception as err:
        conn.execute("ROLLBACK")
        if previous_rows is not None:
            _restore_persisted_session_rows(conn, previous_rows)
            logger.warning("restored previously indexed session %s after write failure", session.id)
        raise err


def _load_persisted_session_rows(
    conn: duckdb.DuckDBPyConnection, session_id: str
) -> PersistedSessionRows | None:
    session_row = conn.execute(
        """
        SELECT
            id, source, source_path, source_session_id,
            started_at, ended_at, duration_seconds,
            model, cwd, git_repo, git_branch,
            message_count, tool_count, input_tokens, output_tokens,
            is_complete, file_mtime, file_size, indexed_at
        FROM sessions
        WHERE id = ?
        """,
        [session_id],
    ).fetchone()
    if session_row is None:
        return None

    message_rows = conn.execute(
        """
        SELECT
            id, session_id, idx, role, content, thinking, timestamp, has_thinking,
            content_embedding, thinking_embedding
        FROM messages
        WHERE session_id = ?
        ORDER BY idx
        """,
        [session_id],
    ).fetchall()
    tool_call_rows = conn.execute(
        """
        SELECT
            id, session_id, message_id, idx,
            tool_name, tool_input, bash_command, bash_base, bash_sub, is_compound, bash_embedding
        FROM tool_calls
        WHERE session_id = ?
        ORDER BY idx
        """,
        [session_id],
    ).fetchall()

    return PersistedSessionRows(
        session_row=tuple(session_row),
        message_rows=[tuple(row) for row in message_rows],
        tool_call_rows=[tuple(row) for row in tool_call_rows],
    )


def _restore_persisted_session_rows(
    conn: duckdb.DuckDBPyConnection, rows: PersistedSessionRows
) -> None:
    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            INSERT INTO sessions (
                id, source, source_path, source_session_id,
                started_at, ended_at, duration_seconds,
                model, cwd, git_repo, git_branch,
                message_count, tool_count, input_tokens, output_tokens,
                is_complete, file_mtime, file_size, indexed_at
            ) VALUES (
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?
            )
            """,
            list(rows.session_row),
        )
        if rows.message_rows:
            conn.executemany(
                """
                INSERT INTO messages (
                    id, session_id, idx, role, content, thinking, timestamp, has_thinking,
                    content_embedding, thinking_embedding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows.message_rows,
            )
        if rows.tool_call_rows:
            conn.executemany(
                """
                INSERT INTO tool_calls (
                    id, session_id, message_id, idx,
                    tool_name, tool_input, bash_command, bash_base, bash_sub, is_compound,
                    bash_embedding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows.tool_call_rows,
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _is_duckdb_fk_delete_limitation(err: Exception) -> bool:
    message = str(err).lower()
    return (
        "violates foreign key constraint" in message
        and "still referenced by a foreign key" in message
        and ("message_id" in message or "session_id" in message)
    )


def _collect_tool_calls(session: Session) -> Iterable[ToolCall]:
    tool_calls: list[ToolCall] = []
    for message in session.messages:
        tool_calls.extend(message.tool_calls)
    tool_calls.extend(session.orphan_tool_calls)
    return tool_calls
