from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
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
