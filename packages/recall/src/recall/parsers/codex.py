from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Iterable

from recall.core.bash import parse_bash_command
from recall.core.ids import message_id as make_message_id
from recall.core.ids import session_id as make_session_id
from recall.core.ids import tool_call_id as make_tool_call_id
from recall.core.models import Message, Session, ToolCall
from recall.core.types import Role, Source


@dataclass
class CodexParser:
    source: Source = Source.CODEX

    def discover(self) -> list[Path]:
        root = Path.home() / ".codex/sessions"
        if not root.exists():
            return []
        return sorted(root.glob("**/rollout*.jsonl"))

    def parse(self, path: Path) -> Session:
        absolute_path = str(path.expanduser().resolve())
        session_id_value = make_session_id(self.source.value, absolute_path)
        file_mtime = path.stat().st_mtime
        file_size = path.stat().st_size

        messages: list[Message] = []
        tool_calls: list[ToolCall] = []
        orphan_tool_calls: list[ToolCall] = []
        is_complete = True
        started_at: datetime | None = None
        ended_at: datetime | None = None
        cwd: str | None = None
        git_branch: str | None = None
        git_repo: str | None = None
        source_session_id: str | None = None

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
                if entry_type == "session_meta":
                    payload = entry.get("payload", {})
                    source_session_id = payload.get("id") or source_session_id
                    cwd = payload.get("cwd") or cwd
                    git_info = payload.get("git", {}) if isinstance(payload.get("git"), dict) else {}
                    git_branch = git_info.get("branch") or git_branch
                    git_repo = git_info.get("root") or git_repo
                    meta_ts = _parse_timestamp(payload.get("timestamp"))
                    if meta_ts is not None:
                        started_at = meta_ts if started_at is None else min(started_at, meta_ts)
                        ended_at = meta_ts if ended_at is None else max(ended_at, meta_ts)
                elif entry_type == "event_msg":
                    payload = entry.get("payload", {})
                    payload_type = payload.get("type")
                    if payload_type == "user_message":
                        message = _build_plain_message(
                            role=Role.USER,
                            text=str(payload.get("message", "")),
                            session_id=session_id_value,
                            idx=len(messages),
                            timestamp=timestamp,
                        )
                        messages.append(message)
                    elif payload_type == "agent_message":
                        message = _build_plain_message(
                            role=Role.ASSISTANT,
                            text=str(payload.get("message", "")),
                            session_id=session_id_value,
                            idx=len(messages),
                            timestamp=timestamp,
                        )
                        messages.append(message)
                    elif payload_type == "function_call":
                        tool_name = str(payload.get("name", ""))
                        tool_input = payload.get("parameters")
                        tool_call = _build_tool_call(tool_name, tool_input)
                        orphan_tool_calls.append(tool_call)
                elif entry_type == "message":
                    payload = entry.get("payload", {})
                    role_value = payload.get("role", "user")
                    try:
                        role = Role(role_value)
                    except ValueError:
                        role = Role.USER
                    content = payload.get("content")
                    message = _parse_message(
                        content=content,
                        role=role,
                        session_id=session_id_value,
                        idx=len(messages),
                        timestamp=timestamp,
                    )
                    messages.append(message)

        for message in messages:
            for tool_idx, tool_call in enumerate(message.tool_calls):
                tool_call.idx = tool_idx
                tool_call.id = make_tool_call_id(message.id, tool_idx)
                tool_call.session_id = session_id_value
                tool_call.message_id = message.id
                tool_calls.append(tool_call)

        for orphan_idx, tool_call in enumerate(orphan_tool_calls):
            tool_call.idx = orphan_idx
            tool_call.id = make_tool_call_id(None, orphan_idx, session_id_value=session_id_value)
            tool_call.session_id = session_id_value
            tool_call.message_id = None
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
            source_session_id=source_session_id,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
            model=None,
            cwd=cwd,
            git_repo=git_repo,
            git_branch=git_branch,
            message_count=message_count,
            tool_count=tool_count,
            input_tokens=None,
            output_tokens=None,
            is_complete=is_complete,
            file_mtime=file_mtime,
            file_size=file_size,
            messages=messages,
            orphan_tool_calls=orphan_tool_calls,
        )
        return session


def _build_plain_message(
    role: Role, text: str, session_id: str, idx: int, timestamp: datetime | None
) -> Message:
    message_id_value = make_message_id(session_id, idx)
    return Message(
        id=message_id_value,
        session_id=session_id,
        idx=idx,
        role=role,
        content=text or None,
        thinking=None,
        timestamp=timestamp,
        has_thinking=False,
        tool_calls=[],
    )


def _parse_message(
    content: Any,
    role: Role,
    session_id: str,
    idx: int,
    timestamp: datetime | None,
) -> Message:
    text_parts, thinking_parts, tool_calls = _extract_content_blocks(content)
    message_id_value = make_message_id(session_id, idx)
    return Message(
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
