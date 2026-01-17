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


def _collect_tool_calls(session: Session) -> Iterable[ToolCall]:
    tool_calls: list[ToolCall] = []
    for message in session.messages:
        tool_calls.extend(message.tool_calls)
    tool_calls.extend(session.orphan_tool_calls)
    return tool_calls
