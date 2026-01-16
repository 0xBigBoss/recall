from __future__ import annotations

from recall.core.types import Source
from recall.parsers.claude_code import ClaudeCodeParser
from recall.parsers.codex import CodexParser
from recall.parsers.protocol import SessionParser


_PARSERS: list[SessionParser] = [ClaudeCodeParser(), CodexParser()]


def all_parsers() -> list[SessionParser]:
    return list(_PARSERS)


def get_parser(source: Source) -> SessionParser:
    for parser in _PARSERS:
        if parser.source == source:
            return parser
    raise ValueError(f"no parser registered for source {source}")
