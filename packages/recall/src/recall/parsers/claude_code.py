from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from recall.core.bash import parse_bash_command
from recall.core.ids import message_id as make_message_id
from recall.core.ids import session_id as make_session_id
from recall.core.ids import tool_call_id as make_tool_call_id
from recall.core.models import Message, Session, ToolCall
from recall.core.types import Role, Source


@dataclass
class ClaudeCodeParser:
    source: Source = Source.CLAUDE_CODE

    def discover(self) -> list[Path]:
        root = Path.home() / ".claude/projects"
        if not root.exists():
            return []
        return sorted(root.rglob("*.jsonl"))

    def parse(self, path: Path) -> Session:
        absolute_path = str(path.expanduser().resolve())
        session_id_value = make_session_id(self.source.value, absolute_path)
        file_mtime = path.stat().st_mtime
        file_size = path.stat().st_size

        messages: list[Message] = []
        tool_calls: list[ToolCall] = []
        is_complete = True
        started_at: datetime | None = None
        ended_at: datetime | None = None
        model: str | None = None
        cwd: str | None = None
        git_repo: str | None = None
        git_branch: str | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None

        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    is_complete = False
                    continue

                timestamp = _parse_timestamp(_get_first(entry, "timestamp", "created_at"))
                if timestamp is not None:
                    started_at = timestamp if started_at is None else min(started_at, timestamp)
                    ended_at = timestamp if ended_at is None else max(ended_at, timestamp)

                if model is None:
                    model = _get_first(entry, "model", "model_name")

                if cwd is None:
                    cwd = _get_first(entry, "cwd", "working_directory")
                if git_repo is None:
                    git_repo = _get_first(entry, "git_root", "repo")
                if git_branch is None:
                    git_branch = _get_nested(entry, ("git", "branch"))

                input_tokens = _accumulate_metric(input_tokens, entry.get("inputTokens"))
                output_tokens = _accumulate_metric(output_tokens, entry.get("outputTokens"))

                message_payload = entry.get("message") if isinstance(entry, dict) else None
                if message_payload is None and isinstance(entry, dict) and "role" in entry:
                    message_payload = entry
                if message_payload:
                    message = _parse_message(
                        message_payload=message_payload,
                        session_id=session_id_value,
                        idx=len(messages),
                        timestamp=timestamp,
                    )
                    messages.append(message)
                    for tool_idx, tool_call in enumerate(message.tool_calls):
                        tool_call.idx = tool_idx
                        tool_call.id = make_tool_call_id(message.id, tool_idx)
                        tool_call.session_id = session_id_value
                        tool_call.message_id = message.id
                        tool_calls.append(tool_call)

        message_count = len(messages)
        tool_count = len(tool_calls)
        duration_seconds = None
        if started_at and ended_at:
            duration_seconds = int((ended_at - started_at).total_seconds())

        session = Session(
            id=session_id_value,
            source=self.source,
            source_path=absolute_path,
            source_session_id=path.stem,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
            model=model,
            cwd=cwd,
            git_repo=git_repo,
            git_branch=git_branch,
            message_count=message_count,
            tool_count=tool_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            is_complete=is_complete,
            file_mtime=file_mtime,
            file_size=file_size,
            messages=messages,
        )
        return session


def _parse_message(
    message_payload: dict[str, Any],
    session_id: str,
    idx: int,
    timestamp: datetime | None,
) -> Message:
    role_value = message_payload.get("role") or message_payload.get("sender") or "user"
    try:
        role = Role(role_value)
    except ValueError:
        role = Role.USER

    content = message_payload.get("content")
    text_parts, thinking_parts, tool_calls = _extract_content_blocks(content)

    message_id_value = make_message_id(session_id, idx)
    message = Message(
        id=message_id_value,
        session_id=session_id,
        idx=idx,
        role=role,
        content="\n".join(text_parts) if text_parts else None,
        thinking="\n".join(thinking_parts) if thinking_parts else None,
        timestamp=timestamp,
        has_thinking=bool(thinking_parts),
        tool_calls=tool_calls,
    )
    return message


def _extract_content_blocks(content: Any) -> tuple[list[str], list[str], list[ToolCall]]:
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    if content is None:
        return text_parts, thinking_parts, tool_calls

    if isinstance(content, str):
        text_parts.append(content)
        return text_parts, thinking_parts, tool_calls

    if isinstance(content, dict):
        content = [content]

    if isinstance(content, Iterable):
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type in {"text", "input_text", "output_text"}:
                text_parts.append(str(item.get("text", "")))
            elif item_type == "thinking":
                thinking_parts.append(str(item.get("text", "")))
            elif item_type == "tool_use":
                tool_name = str(item.get("name", ""))
                tool_input = item.get("input")
                tool_calls.append(_build_tool_call(tool_name, tool_input))
    return text_parts, thinking_parts, tool_calls


def _build_tool_call(tool_name: str, tool_input: Any) -> ToolCall:
    bash_command = _extract_bash_command(tool_name, tool_input)
    parsed = parse_bash_command(bash_command) if bash_command else None
    return ToolCall(
        id="",
        session_id="",
        message_id=None,
        idx=0,
        tool_name=tool_name,
        tool_input=tool_input if isinstance(tool_input, dict) else None,
        bash_command=parsed.command if parsed else None,
        bash_base=parsed.base if parsed else None,
        bash_sub=parsed.sub if parsed else None,
        is_compound=parsed.is_compound if parsed else False,
    )


def _extract_bash_command(tool_name: str, tool_input: Any) -> str | None:
    if tool_name.lower() not in {"bash", "shell"}:
        return None
    if isinstance(tool_input, str):
        return tool_input
    if isinstance(tool_input, dict):
        if isinstance(tool_input.get("command"), str):
            return tool_input.get("command")
        if isinstance(tool_input.get("cmd"), str):
            return tool_input.get("cmd")
        if isinstance(tool_input.get("commands"), list):
            return " && ".join(str(cmd) for cmd in tool_input.get("commands") if cmd)
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _get_first(entry: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _get_nested(entry: dict[str, Any], path: tuple[str, ...]) -> str | None:
    current: Any = entry
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    if isinstance(current, str):
        return current
    return None


def _accumulate_metric(existing: int | None, value: Any) -> int | None:
    if value is None:
        return existing
    try:
        number = int(value)
    except (TypeError, ValueError):
        return existing
    if existing is None:
        return number
    return existing + number
