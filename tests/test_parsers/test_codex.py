from __future__ import annotations

from pathlib import Path

from recall.parsers.codex import CodexParser


def test_codex_parser_parses_orphans() -> None:
    fixture_dir = Path(__file__).resolve().parents[2] / "fixtures" / "codex" / "session1"
    fixture = fixture_dir / "rollout.jsonl"
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


def test_codex_parser_response_item_tool_calls() -> None:
    """Parse response_item entries: function_call, custom_tool_call, web_search_call."""
    fixture_dir = Path(__file__).resolve().parents[2] / "fixtures" / "codex" / "session2"
    fixture = next(fixture_dir.glob("rollout-*.jsonl"))
    parser = CodexParser()
    session = parser.parse(fixture)

    assert session.source_session_id == "codex456"
    assert session.cwd == "/project"
    assert session.git_branch == "feature"
    assert session.message_count == 2

    # 2 exec_command + 1 apply_patch + 1 web_search = 4 orphan tool calls
    assert len(session.orphan_tool_calls) == 4
    assert session.tool_count == 4

    exec1 = session.orphan_tool_calls[0]
    assert exec1.tool_name == "exec_command"
    assert exec1.bash_command == "npm test"

    patch = session.orphan_tool_calls[1]
    assert patch.tool_name == "apply_patch"
    assert patch.bash_command is None

    web = session.orphan_tool_calls[2]
    assert web.tool_name == "web_search"
    assert web.tool_input == {"url": "https://docs.example.com"}

    exec2 = session.orphan_tool_calls[3]
    assert exec2.tool_name == "exec_command"
    assert exec2.bash_command == "git status"
