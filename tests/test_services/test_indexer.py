from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import recall.services.indexer as indexer_module
from recall.services.indexer import index_sessions


def test_indexer_indexes_sessions(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("RECALL_DATA_DIR", str(tmp_path / ".local/share/recall"))

    claude_target = tmp_path / ".claude" / "projects" / "proj1"
    codex_target = tmp_path / ".codex" / "sessions" / "s1"
    claude_target.mkdir(parents=True)
    codex_target.mkdir(parents=True)

    claude_fixture = (
        Path(__file__).resolve().parents[2] / "fixtures" / "claude_code" / "session1.jsonl"
    )
    codex_fixture = (
        Path(__file__).resolve().parents[2] / "fixtures" / "codex" / "session1" / "rollout.jsonl"
    )

    shutil.copy(claude_fixture, claude_target / "session1.jsonl")
    shutil.copy(codex_fixture, codex_target / "rollout.jsonl")

    summary = index_sessions(source=None, full=True, recreate=True, verbose=False)
    assert summary.indexed == 2
    assert summary.failed == 0

    db_path = tmp_path / ".local/share/recall" / "recall.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        sessions_row = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        messages_row = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        tool_calls_row = conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()
        assert sessions_row is not None and sessions_row[0] == 2
        assert messages_row is not None and messages_row[0] == 7
        assert tool_calls_row is not None and tool_calls_row[0] == 3
    finally:
        conn.close()

    summary2 = index_sessions(source=None, full=False, recreate=False, verbose=False)
    assert summary2.skipped == 2


def test_indexer_full_reindex_succeeds_on_existing_sessions(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("RECALL_DATA_DIR", str(tmp_path / ".local/share/recall"))

    claude_target = tmp_path / ".claude" / "projects" / "proj1"
    codex_target = tmp_path / ".codex" / "sessions" / "s1"
    claude_target.mkdir(parents=True)
    codex_target.mkdir(parents=True)

    claude_fixture = (
        Path(__file__).resolve().parents[2] / "fixtures" / "claude_code" / "session1.jsonl"
    )
    codex_fixture = (
        Path(__file__).resolve().parents[2] / "fixtures" / "codex" / "session1" / "rollout.jsonl"
    )

    shutil.copy(claude_fixture, claude_target / "session1.jsonl")
    shutil.copy(codex_fixture, codex_target / "rollout.jsonl")

    first = index_sessions(source=None, full=True, recreate=True, verbose=False)
    assert first.indexed == 2
    assert first.failed == 0

    second = index_sessions(source=None, full=True, recreate=False, verbose=False)
    assert second.indexed == 2
    assert second.failed == 0


def test_indexer_preserves_existing_rows_when_fallback_insert_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("RECALL_DATA_DIR", str(tmp_path / ".local/share/recall"))

    claude_target = tmp_path / ".claude" / "projects" / "proj1"
    claude_target.mkdir(parents=True)

    claude_fixture = (
        Path(__file__).resolve().parents[2] / "fixtures" / "claude_code" / "session1.jsonl"
    )
    shutil.copy(claude_fixture, claude_target / "session1.jsonl")

    first = index_sessions(source=None, full=True, recreate=True, verbose=False)
    assert first.indexed == 1
    assert first.failed == 0

    db_path = tmp_path / ".local/share/recall" / "recall.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        before_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        before_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        before_tool_calls = conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()
        assert before_sessions is not None
        assert before_messages is not None
        assert before_tool_calls is not None
        expected = (before_sessions[0], before_messages[0], before_tool_calls[0])
    finally:
        conn.close()

    def fail_insert_messages(_conn, _messages) -> None:
        raise RuntimeError("simulated insert_messages failure")

    monkeypatch.setattr(indexer_module, "insert_messages", fail_insert_messages)

    second = index_sessions(source=None, full=True, recreate=False, verbose=False)
    assert second.indexed == 0
    assert second.failed == 1

    conn = duckdb.connect(str(db_path))
    try:
        after_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        after_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        after_tool_calls = conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()
        assert after_sessions is not None
        assert after_messages is not None
        assert after_tool_calls is not None
        assert (after_sessions[0], after_messages[0], after_tool_calls[0]) == expected
    finally:
        conn.close()
