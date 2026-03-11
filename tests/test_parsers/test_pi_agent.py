from __future__ import annotations

from pathlib import Path

from recall.core.types import Role
from recall.parsers.pi_agent import PiAgentParser


def test_pi_agent_parser_parses_messages_and_tool_calls() -> None:
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "pi_agent" / "session1.jsonl"
    parser = PiAgentParser()
    session = parser.parse(fixture)

    assert session.source_session_id == "pi-session-123"
    assert session.cwd == "/repo/pi"
    assert session.model == "gpt-5.4"
    assert session.message_count == 4
    assert session.tool_count == 1

    user_message = session.messages[0]
    assert user_message.role == Role.USER
    assert user_message.content == "List the files in this repo."

    assistant_message = session.messages[1]
    assert assistant_message.role == Role.ASSISTANT
    assert assistant_message.content == "Checking the repository contents."
    assert assistant_message.thinking == "Need to inspect the repository tree first."
    assert assistant_message.has_thinking is True
    assert len(assistant_message.tool_calls) == 1
    tool_call = assistant_message.tool_calls[0]
    assert tool_call.tool_name == "bash"
    assert tool_call.tool_input == {"command": "ls -la"}
    assert tool_call.bash_command == "ls -la"
    assert tool_call.bash_base == "ls"

    tool_result = session.messages[2]
    assert tool_result.role == Role.SYSTEM
    assert "README.md" in (tool_result.content or "")

    final_message = session.messages[3]
    assert final_message.role == Role.ASSISTANT
    assert final_message.content == "I found the project files."
