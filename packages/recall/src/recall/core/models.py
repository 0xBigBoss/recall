from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, ConfigDict

from recall.core.types import Role, Source


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    message_id: str | None
    idx: int
    tool_name: str
    tool_input: dict[str, Any] | None = None

    bash_command: str | None = None
    bash_base: str | None = None
    bash_sub: str | None = None
    is_compound: bool = False

    bash_embedding: list[float] | None = None


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    idx: int
    role: Role
    content: str | None = None
    thinking: str | None = None
    timestamp: datetime | None = None
    has_thinking: bool = False
    tool_calls: list[ToolCall] = Field(default_factory=list)

    content_embedding: list[float] | None = None
    thinking_embedding: list[float] | None = None


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: Source
    source_path: str
    source_session_id: str | None = None

    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int | None = None

    model: str | None = None
    cwd: str | None = None
    git_repo: str | None = None
    git_branch: str | None = None

    message_count: int = 0
    tool_count: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None

    is_complete: bool = True
    file_mtime: float
    file_size: int
    indexed_at: datetime | None = None

    messages: list[Message] = Field(default_factory=list)
    orphan_tool_calls: list[ToolCall] = Field(default_factory=list)
