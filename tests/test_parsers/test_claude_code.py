from __future__ import annotations

from pathlib import Path

from recall.parsers.claude_code import ClaudeCodeParser


def test_claude_code_parser_parses_messages() -> None:
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "claude_code" / "session1.jsonl"
    parser = ClaudeCodeParser()
    session = parser.parse(fixture)

    assert session.message_count == 4
    assert session.input_tokens == 5
    assert session.output_tokens == 7

    tool_calls = session.messages[1].tool_calls
    assert len(tool_calls) == 1
    tool_call = tool_calls[0]
    assert tool_call.tool_name == "bash"
    assert tool_call.bash_command == "git status"
    assert tool_call.bash_base == "git"
    assert tool_call.bash_sub == "status"
