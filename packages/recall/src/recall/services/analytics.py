from __future__ import annotations

from dataclasses import dataclass

import duckdb

from recall.core.config import AppConfig
from recall.db import connect


DANGEROUS_BASES = {
    "rm",
    "sudo",
    "chmod",
    "chown",
    "dd",
    "mkfs",
    "mount",
    "umount",
    "shutdown",
    "reboot",
    "kill",
    "killall",
}


@dataclass(frozen=True)
class OverviewStats:
    sessions: int
    messages: int
    tool_calls: int
    bash_calls: int


@dataclass(frozen=True)
class ToolStat:
    tool_name: str
    count: int


@dataclass(frozen=True)
class BashStat:
    bash_base: str | None
    bash_sub: str | None
    count: int
    is_compound: bool


@dataclass(frozen=True)
class PermissionSuggestion:
    pattern: str
    count: int
    confidence: str
    reason: str


@dataclass(frozen=True)
class PermissionSkipped:
    pattern: str
    count: int
    reason: str


def overview() -> OverviewStats:
    config = AppConfig.load()
    conn = connect(config)
    try:
        sessions = _count(conn, "sessions")
        messages = _count(conn, "messages")
        tool_calls = _count(conn, "tool_calls")
        bash_calls = conn.execute(
            "SELECT COUNT(*) FROM tool_calls WHERE bash_command IS NOT NULL"
        ).fetchone()[0]
        return OverviewStats(
            sessions=sessions,
            messages=messages,
            tool_calls=tool_calls,
            bash_calls=int(bash_calls),
        )
    finally:
        conn.close()


def tool_usage(limit: int = 50) -> list[ToolStat]:
    config = AppConfig.load()
    conn = connect(config)
    try:
        rows = conn.execute(
            """
            SELECT tool_name, COUNT(*) AS count
            FROM tool_calls
            GROUP BY tool_name
            ORDER BY count DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        return [ToolStat(tool_name=row[0], count=int(row[1])) for row in rows]
    finally:
        conn.close()


def bash_breakdown(limit: int = 100) -> list[BashStat]:
    config = AppConfig.load()
    conn = connect(config)
    try:
        rows = conn.execute(
            """
            SELECT bash_base, bash_sub, COUNT(*) AS count, MAX(is_compound) AS is_compound
            FROM tool_calls
            WHERE bash_command IS NOT NULL
            GROUP BY bash_base, bash_sub
            ORDER BY count DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        return [
            BashStat(
                bash_base=row[0],
                bash_sub=row[1],
                count=int(row[2]),
                is_compound=bool(row[3]),
            )
            for row in rows
        ]
    finally:
        conn.close()


def bash_suggestions(
    high_threshold: int = 50, medium_threshold: int = 10
) -> tuple[list[PermissionSuggestion], list[PermissionSkipped]]:
    suggestions: list[PermissionSuggestion] = []
    skipped: list[PermissionSkipped] = []
    for stat in bash_breakdown(limit=500):
        base = (stat.bash_base or "").strip()
        if not base:
            continue
        pattern = _format_pattern(base, stat.bash_sub)
        if base in DANGEROUS_BASES:
            skipped.append(
                PermissionSkipped(pattern=pattern, count=stat.count, reason="Destructive command")
            )
            continue
        if stat.is_compound:
            suggestions.append(
                PermissionSuggestion(
                    pattern=pattern,
                    count=stat.count,
                    confidence="review",
                    reason="Contains compound operators",
                )
            )
            continue
        if stat.count >= high_threshold:
            suggestions.append(
                PermissionSuggestion(
                    pattern=pattern,
                    count=stat.count,
                    confidence="high",
                    reason="No dangerous patterns detected",
                )
            )
        elif stat.count >= medium_threshold:
            suggestions.append(
                PermissionSuggestion(
                    pattern=pattern,
                    count=stat.count,
                    confidence="medium",
                    reason="No dangerous patterns detected",
                )
            )
        else:
            suggestions.append(
                PermissionSuggestion(
                    pattern=pattern,
                    count=stat.count,
                    confidence="review",
                    reason="Low usage volume",
                )
            )
    return suggestions, skipped


def token_usage(limit: int = 50) -> list[tuple[str | None, int, int]]:
    config = AppConfig.load()
    conn = connect(config)
    try:
        rows = conn.execute(
            """
            SELECT git_repo, SUM(COALESCE(input_tokens, 0)) AS input_tokens,
                   SUM(COALESCE(output_tokens, 0)) AS output_tokens
            FROM sessions
            GROUP BY git_repo
            ORDER BY input_tokens + output_tokens DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        return [
            (row[0], int(row[1] or 0), int(row[2] or 0))
            for row in rows
        ]
    finally:
        conn.close()


def _format_pattern(base: str, sub: str | None) -> str:
    if sub:
        return f"{base} {sub}"
    return f"{base} *"


def _count(conn: duckdb.DuckDBPyConnection, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0]) if row else 0
