from __future__ import annotations

from enum import StrEnum


class Source(StrEnum):
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


def parse_source(value: str) -> Source:
    normalized = value.strip().lower()
    match normalized:
        case "claude-code" | "claude_code":
            return Source.CLAUDE_CODE
        case "codex":
            return Source.CODEX
        case _:
            raise ValueError(f"unsupported source: {value}")
