from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import duckdb

from recall.core.config import AppConfig
from recall.core.types import Source
from recall.db import connect, load_fts_extension


@dataclass(frozen=True)
class SearchResult:
    kind: Literal["message", "tool_call"]
    session_id: str
    source: str
    source_path: str | None
    score: float
    message_id: str | None
    tool_call_id: str | None
    role: str | None
    content: str | None
    thinking: str | None
    timestamp: str | None
    tool_name: str | None
    bash_command: str | None


def search(
    *,
    query: str,
    source: Source | None,
    tool: str | None,
    limit: int = 20,
) -> list[SearchResult]:
    config = AppConfig.load()
    conn = connect(config)
    try:
        load_fts_extension(conn)
        if tool:
            return _search_tool_calls(conn, query, source, tool, limit)
        return _search_all(conn, query, source, limit, config.fts.fields)
    except duckdb.Error as err:
        raise RuntimeError("search failed: run `recall index` to create FTS indexes") from err
    finally:
        conn.close()


def _search_all(
    conn: duckdb.DuckDBPyConnection,
    query: str,
    source: Source | None,
    limit: int,
    fields: tuple[str, ...],
) -> list[SearchResult]:
    results: list[SearchResult] = []
    message_fields = [field for field in ("content", "thinking") if field in fields]
    if message_fields:
        results.extend(_search_messages(conn, query, source, limit, message_fields))
    if "bash" in fields:
        results.extend(_search_tool_calls(conn, query, source, None, limit))
    results.sort(key=lambda item: item.score, reverse=True)
    return results[:limit]


def _search_messages(
    conn: duckdb.DuckDBPyConnection,
    query: str,
    source: Source | None,
    limit: int,
    fields: list[str],
) -> list[SearchResult]:
    fields_value = ",".join(fields)
    where_clause = ""
    params: list[object] = [query, fields_value]
    if source is not None:
        where_clause = "WHERE s.source = ?"
        params.append(source.value)

    sql = f"""
        WITH ranked AS (
            SELECT
                m.id AS message_id,
                m.session_id,
                m.role,
                m.content,
                m.thinking,
                m.timestamp,
                s.source,
                s.source_path,
                fts_main_messages.match_bm25(m.id, ?, fields := ?) AS score
            FROM messages m
            JOIN sessions s ON s.id = m.session_id
            {where_clause}
        )
        SELECT * FROM ranked
        WHERE score IS NOT NULL
        ORDER BY score DESC
        LIMIT {limit}
    """
    rows = conn.execute(sql, params).fetchall()
    return [
        SearchResult(
            kind="message",
            session_id=row[1],
            source=row[6],
            source_path=row[7],
            score=float(row[8]),
            message_id=row[0],
            tool_call_id=None,
            role=row[2],
            content=row[3],
            thinking=row[4],
            timestamp=str(row[5]) if row[5] is not None else None,
            tool_name=None,
            bash_command=None,
        )
        for row in rows
    ]


def _search_tool_calls(
    conn: duckdb.DuckDBPyConnection,
    query: str,
    source: Source | None,
    tool: str | None,
    limit: int,
) -> list[SearchResult]:
    where_parts: list[str] = []
    params: list[object] = [query]
    if tool:
        where_parts.append("LOWER(tc.tool_name) = LOWER(?)")
        params.append(tool)
    if source is not None:
        where_parts.append("s.source = ?")
        params.append(source.value)
    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    sql = f"""
        WITH ranked AS (
            SELECT
                tc.id AS tool_call_id,
                tc.session_id,
                tc.message_id,
                tc.tool_name,
                tc.bash_command,
                s.source,
                s.source_path,
                fts_main_tool_calls.match_bm25(tc.id, ?, fields := 'bash_command') AS score
            FROM tool_calls tc
            JOIN sessions s ON s.id = tc.session_id
            {where_clause}
        )
        SELECT * FROM ranked
        WHERE score IS NOT NULL
        ORDER BY score DESC
        LIMIT {limit}
    """
    rows = conn.execute(sql, params).fetchall()
    return [
        SearchResult(
            kind="tool_call",
            session_id=row[1],
            source=row[5],
            source_path=row[6],
            score=float(row[7]),
            message_id=row[2],
            tool_call_id=row[0],
            role=None,
            content=None,
            thinking=None,
            timestamp=None,
            tool_name=row[3],
            bash_command=row[4],
        )
        for row in rows
    ]
