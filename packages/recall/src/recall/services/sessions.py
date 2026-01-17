from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from recall.core.config import AppConfig
from recall.core.models import Message, Session, ToolCall
from recall.core.types import Role, Source
from recall.db import connect


@dataclass(frozen=True)
class SessionSummary:
    id: str
    source: str
    started_at: datetime | None
    ended_at: datetime | None
    cwd: str | None
    git_repo: str | None
    git_branch: str | None
    message_count: int
    tool_count: int
    is_complete: bool


def list_sessions(
    *,
    source: Source | None,
    since: datetime | None,
    project: str | None,
    limit: int = 50,
) -> list[SessionSummary]:
    config = AppConfig.load()
    conn = connect(config)
    try:
        where_parts: list[str] = []
        params: list[object] = []
        if source is not None:
            where_parts.append("source = ?")
            params.append(source.value)
        if since is not None:
            where_parts.append("COALESCE(started_at, indexed_at) >= ?")
            params.append(since)
        if project:
            where_parts.append("git_repo ILIKE ?")
            params.append(f"%{project}%")
        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        sql = f"""
            SELECT id, source, started_at, ended_at, cwd, git_repo, git_branch,
                   message_count, tool_count, is_complete
            FROM sessions
            {where_clause}
            ORDER BY started_at DESC NULLS LAST, indexed_at DESC
            LIMIT {limit}
        """
        rows = conn.execute(sql, params).fetchall()
        return [
            SessionSummary(
                id=row[0],
                source=row[1],
                started_at=row[2],
                ended_at=row[3],
                cwd=row[4],
                git_repo=row[5],
                git_branch=row[6],
                message_count=int(row[7]),
                tool_count=int(row[8]),
                is_complete=bool(row[9]),
            )
            for row in rows
        ]
    finally:
        conn.close()


def load_session(session_id: str, *, include_tools: bool) -> Session:
    config = AppConfig.load()
    conn = connect(config)
    try:
        session_row = conn.execute(
            """
            SELECT id, source, source_path, source_session_id,
                   started_at, ended_at, duration_seconds,
                   model, cwd, git_repo, git_branch,
                   message_count, tool_count, input_tokens,
                   output_tokens, is_complete, file_mtime, file_size, indexed_at
            FROM sessions
            WHERE id = ?
            """,
            [session_id],
        ).fetchone()
        if session_row is None:
            raise ValueError(f"session not found: {session_id}")

        session = Session(
            id=session_row[0],
            source=Source(session_row[1]),
            source_path=session_row[2],
            source_session_id=session_row[3],
            started_at=session_row[4],
            ended_at=session_row[5],
            duration_seconds=session_row[6],
            model=session_row[7],
            cwd=session_row[8],
            git_repo=session_row[9],
            git_branch=session_row[10],
            message_count=int(session_row[11]),
            tool_count=int(session_row[12]),
            input_tokens=session_row[13],
            output_tokens=session_row[14],
            is_complete=bool(session_row[15]),
            file_mtime=float(session_row[16]),
            file_size=int(session_row[17]),
            indexed_at=session_row[18],
            messages=[],
            orphan_tool_calls=[],
        )

        message_rows = conn.execute(
            """
            SELECT id, session_id, idx, role, content, thinking, timestamp, has_thinking
            FROM messages
            WHERE session_id = ?
            ORDER BY idx ASC
            """,
            [session_id],
        ).fetchall()
        messages = [
            Message(
                id=row[0],
                session_id=row[1],
                idx=int(row[2]),
                role=Role(row[3]),
                content=row[4],
                thinking=row[5],
                timestamp=row[6],
                has_thinking=bool(row[7]),
                tool_calls=[],
            )
            for row in message_rows
        ]
        session.messages = messages

        if include_tools:
            tool_rows = conn.execute(
                """
                SELECT id, session_id, message_id, idx, tool_name, tool_input,
                       bash_command, bash_base, bash_sub, is_compound
                FROM tool_calls
                WHERE session_id = ?
                ORDER BY idx ASC
                """,
                [session_id],
            ).fetchall()
            tool_calls = [
                ToolCall(
                    id=row[0],
                    session_id=row[1],
                    message_id=row[2],
                    idx=int(row[3]),
                    tool_name=row[4],
                    tool_input=_parse_tool_input(row[5]),
                    bash_command=row[6],
                    bash_base=row[7],
                    bash_sub=row[8],
                    is_compound=bool(row[9]),
                )
                for row in tool_rows
            ]
            message_lookup = {message.id: message for message in messages}
            for tool_call in tool_calls:
                if tool_call.message_id and tool_call.message_id in message_lookup:
                    message_lookup[tool_call.message_id].tool_calls.append(tool_call)
                else:
                    session.orphan_tool_calls.append(tool_call)

        return session
    finally:
        conn.close()


def _parse_tool_input(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value  # type: ignore[return-value]
    if isinstance(value, str):
        try:
            import json

            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return None
