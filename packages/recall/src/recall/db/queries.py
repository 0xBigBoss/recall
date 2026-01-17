from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime

import duckdb

from recall.core.config import FtsConfig
from recall.core.models import Message, Session, ToolCall


def load_fts_extension(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("INSTALL fts")
    conn.execute("LOAD fts")


def create_fts_indexes(conn: duckdb.DuckDBPyConnection, fts: FtsConfig) -> None:
    if not fts.fields:
        return
    load_fts_extension(conn)
    message_fields = [field for field in ("content", "thinking") if field in fts.fields]
    if message_fields:
        columns = ", ".join(message_fields)
        conn.execute(
            "PRAGMA create_fts_index(messages, id, "
            f"{columns}, stemmer='porter', stopwords='english', overwrite=1)"
        )
    if "bash" in fts.fields:
        conn.execute(
            "PRAGMA create_fts_index(tool_calls, id, bash_command, "
            "stemmer='porter', stopwords='english', overwrite=1)"
        )


def fetch_session_state(
    conn: duckdb.DuckDBPyConnection, source_path: str
) -> tuple[str, float, int] | None:
    row = conn.execute(
        "SELECT id, file_mtime, file_size FROM sessions WHERE source_path = ?",
        [source_path],
    ).fetchone()
    if row is None:
        return None
    session_id, file_mtime, file_size = row
    return str(session_id), float(file_mtime), int(file_size)


def delete_session(conn: duckdb.DuckDBPyConnection, session_id: str) -> None:
    # Delete in order: tool_calls -> messages -> sessions (no CASCADE in DuckDB)
    conn.execute("DELETE FROM tool_calls WHERE session_id = ?", [session_id])
    conn.execute("DELETE FROM messages WHERE session_id = ?", [session_id])
    conn.execute("DELETE FROM sessions WHERE id = ?", [session_id])


def insert_session(conn: duckdb.DuckDBPyConnection, session: Session) -> None:
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
        [
            session.id,
            session.source.value,
            session.source_path,
            session.source_session_id,
            session.started_at,
            session.ended_at,
            session.duration_seconds,
            session.model,
            session.cwd,
            session.git_repo,
            session.git_branch,
            session.message_count,
            session.tool_count,
            session.input_tokens,
            session.output_tokens,
            session.is_complete,
            session.file_mtime,
            session.file_size,
            session.indexed_at or datetime.now(UTC),
        ],
    )


def insert_messages(conn: duckdb.DuckDBPyConnection, messages: Iterable[Message]) -> None:
    rows = [
        (
            message.id,
            message.session_id,
            message.idx,
            message.role.value,
            message.content,
            message.thinking,
            message.timestamp,
            message.has_thinking,
            message.content_embedding,
            message.thinking_embedding,
        )
        for message in messages
    ]
    if not rows:
        return
    conn.executemany(
        """
        INSERT INTO messages (
            id, session_id, idx, role, content, thinking, timestamp, has_thinking,
            content_embedding, thinking_embedding
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def insert_tool_calls(conn: duckdb.DuckDBPyConnection, tool_calls: Iterable[ToolCall]) -> None:
    rows = [
        (
            tool_call.id,
            tool_call.session_id,
            tool_call.message_id,
            tool_call.idx,
            tool_call.tool_name,
            json.dumps(tool_call.tool_input) if tool_call.tool_input is not None else None,
            tool_call.bash_command,
            tool_call.bash_base,
            tool_call.bash_sub,
            tool_call.is_compound,
            tool_call.bash_embedding,
        )
        for tool_call in tool_calls
    ]
    if not rows:
        return
    conn.executemany(
        """
        INSERT INTO tool_calls (
            id, session_id, message_id, idx,
            tool_name, tool_input, bash_command, bash_base, bash_sub, is_compound, bash_embedding
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
