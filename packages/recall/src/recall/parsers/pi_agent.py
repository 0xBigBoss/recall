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
class PiAgentParser:
    source: Source = Source.PI_AGENT

    def discover(self) -> list[Path]:
        root = Path.home() / ".pi" / "agent" / "sessions"
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
        source_session_id: str | None = None
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

                timestamp = _parse_timestamp(entry.get("timestamp"))
                if timestamp is not None:
                    started_at = timestamp if started_at is None else min(started_at, timestamp)
                    ended_at = timestamp if ended_at is None else max(ended_at, timestamp)

                entry_type = entry.get("type")
                if entry_type == "session":
                    source_session_id = _coerce_str(entry.get("id")) or source_session_id
                    cwd = _coerce_str(entry.get("cwd")) or cwd
                elif entry_type == "model_change":
                    model = _coerce_str(entry.get("modelId")) or model
                elif entry_type == "message":
                    message_payload = entry.get("message")
                    if not isinstance(message_payload, dict):
                        continue
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

                    usage = message_payload.get("usage")
                    if isinstance(usage, dict):
                        input_tokens = _accumulate_metric(input_tokens, usage.get("input"))
                        output_tokens = _accumulate_metric(output_tokens, usage.get("output"))

        duration_seconds = None
        if started_at and ended_at:
            duration_seconds = int((ended_at - started_at).total_seconds())

        return Session(
            id=session_id_value,
            source=self.source,
            source_path=absolute_path,
            source_session_id=source_session_id,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
            model=model,
            cwd=cwd,
            git_repo=None,
            git_branch=None,
            message_count=len(messages),
            tool_count=len(tool_calls),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            is_complete=is_complete,
            file_mtime=file_mtime,
            file_size=file_size,
            messages=messages,
        )


def _parse_message(
    message_payload: dict[str, Any],
    session_id: str,
    idx: int,
    timestamp: datetime | None,
) -> Message:
    role = _parse_role(message_payload.get("role"))
    text_parts, thinking_parts, tool_calls = _extract_content_blocks(message_payload.get("content"))
    return Message(
        id=make_message_id(session_id, idx),
        session_id=session_id,
        idx=idx,
        role=role,
        content="\n".join(text_parts) if text_parts else None,
        thinking="\n".join(thinking_parts) if thinking_parts else None,
        timestamp=timestamp,
        has_thinking=bool(thinking_parts),
        tool_calls=tool_calls,
    )


def _parse_role(value: Any) -> Role:
    normalized = _coerce_str(value) or "user"
    match normalized:
        case "assistant":
            return Role.ASSISTANT
        case "toolResult" | "system":
            return Role.SYSTEM
        case _:
            return Role.USER


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
    if not isinstance(content, Iterable):
        return text_parts, thinking_parts, tool_calls

    for item in content:
        if isinstance(item, str):
            text_parts.append(item)
            continue
        if not isinstance(item, dict):
            continue

        item_type = item.get("type")
        if item_type in {"text", "input_text", "output_text"}:
            text = _coerce_str(item.get("text"))
            if text:
                text_parts.append(text)
        elif item_type == "thinking":
            thinking = _coerce_str(item.get("thinking")) or _coerce_str(item.get("text"))
            if thinking:
                thinking_parts.append(thinking)
        elif item_type == "toolCall":
            tool_name = _coerce_str(item.get("name")) or ""
            tool_input = _parse_tool_arguments(item.get("arguments"))
            tool_calls.append(_build_tool_call(tool_name, tool_input))

    return text_parts, thinking_parts, tool_calls


def _parse_tool_arguments(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _build_tool_call(tool_name: str, tool_input: dict[str, Any] | None) -> ToolCall:
    bash_command = _extract_bash_command(tool_name, tool_input)
    parsed = parse_bash_command(bash_command) if bash_command else None
    return ToolCall(
        id="",
        session_id="",
        message_id=None,
        idx=0,
        tool_name=tool_name,
        tool_input=tool_input,
        bash_command=parsed.command if parsed else None,
        bash_base=parsed.base if parsed else None,
        bash_sub=parsed.sub if parsed else None,
        is_compound=parsed.is_compound if parsed else False,
    )


def _extract_bash_command(tool_name: str, tool_input: dict[str, Any] | None) -> str | None:
    if tool_name.lower() not in {"bash", "shell", "exec_command", "shell_command"}:
        return None
    if not tool_input:
        return None
    if isinstance(tool_input.get("command"), str):
        return tool_input["command"]
    if isinstance(tool_input.get("cmd"), str):
        return tool_input["cmd"]
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _coerce_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
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
