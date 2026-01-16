from __future__ import annotations

from pathlib import Path

from recall.parsers.codex import CodexParser


def test_codex_parser_parses_orphans() -> None:
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "codex" / "session1" / "rollout.jsonl"
    parser = CodexParser()
    session = parser.parse(fixture)

    assert session.source_session_id == "codex123"
    assert session.cwd == "/repo"
    assert session.git_branch == "main"
    assert session.message_count == 3

    assert len(session.orphan_tool_calls) == 1
    orphan = session.orphan_tool_calls[0]
    assert orphan.tool_name == "shell"
    assert orphan.bash_command == "ls -la"

    tool_calls = session.messages[-1].tool_calls
    assert len(tool_calls) == 1
    assert tool_calls[0].bash_command == "pwd"
