# recall

Session recall and analytics for AI agents (Claude Code, Codex).

## Vision

A **memory layer** for AI-assisted development:
- Index and search across all agent sessions
- Unified schema - query Claude Code and Codex together
- Analytics on tool usage, patterns, costs
- Permission suggestions based on actual usage
- Fully local, no external dependencies beyond Python + DuckDB

## Design Principles

- **Zero external dependencies** beyond Python + DuckDB + Typer + Pydantic
- **Single command runnable** via `uvx recall`
- **Unified schema** - query across Claude Code + Codex seamlessly
- **Local only** - data stays on your machine
- **Monorepo structure** - properly modularized for growth

## Project Structure

```
recall/
├── pyproject.toml                  # Workspace root
├── uv.lock
├── README.md
├── .python-version                 # 3.12
├── .gitignore
│
├── packages/
│   └── recall/                     # Main package
│       ├── pyproject.toml
│       └── src/
│           └── recall/
│               ├── __init__.py
│               ├── py.typed
│               │
│               ├── core/           # Domain models (no deps)
│               │   ├── __init__.py
│               │   ├── models.py   # Session, Message, ToolCall
│               │   └── types.py    # Enums, type aliases
│               │
│               ├── db/             # Storage layer
│               │   ├── __init__.py
│               │   ├── connection.py
│               │   ├── schema.sql
│               │   ├── schema.py   # Load + migrate
│               │   └── queries.py
│               │
│               ├── parsers/        # Source adapters
│               │   ├── __init__.py
│               │   ├── protocol.py # Parser protocol
│               │   ├── claude_code.py
│               │   ├── codex.py
│               │   └── registry.py
│               │
│               ├── services/       # Business logic
│               │   ├── __init__.py
│               │   ├── indexer.py
│               │   ├── search.py
│               │   └── analytics.py
│               │
│               └── cli/            # Typer CLI
│                   ├── __init__.py
│                   ├── app.py      # Main app
│                   ├── index.py
│                   ├── search.py
│                   ├── list.py
│                   └── stats.py
│
├── tests/
│   ├── conftest.py
│   ├── fixtures/                   # Sample JSONL files
│   │   ├── claude_code/
│   │   └── codex/
│   ├── test_parsers/
│   ├── test_services/
│   └── test_cli/
│
└── .claude/
    └── skills/
        └── recall/
            └── SKILL.md
```

## Module Dependency Graph

```
cli/          →  services/  →  parsers/  →  core/
                    ↓              ↓
                   db/         core/
                    ↓
                  core/
```

- `core/` - Zero dependencies, pure Python + Pydantic
- `db/` - Depends on `core/`, `duckdb`
- `parsers/` - Depends on `core/`
- `services/` - Depends on `core/`, `db/`, `parsers/`
- `cli/` - Depends on `services/`, `typer`

## Database Schema

```sql
-- Unified sessions table
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('claude_code', 'codex')),
    source_path TEXT UNIQUE,
    source_session_id TEXT,

    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    duration_seconds INTEGER,

    model TEXT,
    cwd TEXT,
    git_repo TEXT,
    git_branch TEXT,

    message_count INTEGER DEFAULT 0,
    tool_count INTEGER DEFAULT 0,
    input_tokens INTEGER,
    output_tokens INTEGER,

    file_mtime DOUBLE,
    file_size BIGINT,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT,
    timestamp TIMESTAMP,
    has_thinking BOOLEAN DEFAULT FALSE,

    UNIQUE(session_id, idx)
);

CREATE TABLE tool_calls (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    message_id TEXT REFERENCES messages(id) ON DELETE CASCADE,
    idx INTEGER,

    tool_name TEXT NOT NULL,
    tool_input JSON,

    -- Denormalized Bash fields for fast queries
    bash_command TEXT,
    bash_base TEXT,
    bash_sub TEXT
);

-- Indexes
CREATE INDEX idx_sessions_source ON sessions(source);
CREATE INDEX idx_sessions_cwd ON sessions(cwd);
CREATE INDEX idx_sessions_started ON sessions(started_at DESC);
CREATE INDEX idx_messages_session ON messages(session_id);
CREATE INDEX idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX idx_tool_calls_name ON tool_calls(tool_name);
CREATE INDEX idx_tool_calls_bash_base ON tool_calls(bash_base);

-- FTS
INSTALL fts;
LOAD fts;
PRAGMA create_fts_index('messages', 'id', 'content', overwrite=1);
```

## Core Models

```python
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Source(StrEnum):
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"


class ToolCall(BaseModel):
    id: str
    tool_name: str
    tool_input: dict[str, Any] | None = None
    bash_command: str | None = None
    bash_base: str | None = None
    bash_sub: str | None = None


class Message(BaseModel):
    id: str
    idx: int
    role: str
    content: str | None = None
    timestamp: datetime | None = None
    has_thinking: bool = False
    tool_calls: list[ToolCall] = Field(default_factory=list)


class Session(BaseModel):
    id: str
    source: Source
    source_path: str | None = None
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

    messages: list[Message] = Field(default_factory=list)
```

## CLI Commands

```bash
recall index                      # index all sources (incremental)
recall index --full               # force reindex
recall index --source claude-code # specific source

recall search "auth"              # FTS across all sessions
recall search "kubectl" --tool Bash
recall search --source codex "error"

recall list                       # recent sessions (both sources)
recall list --source claude-code
recall list --since 7d

recall stats                      # overview
recall stats tools                # tool frequency
recall stats bash                 # bash breakdown
recall stats bash --suggest       # generate permission rules

recall show <id>                  # show session
recall show <id> --tools          # include tool calls
```

## Session Locations

### Claude Code
- `~/.claude/projects/<project-path>/<session-id>.jsonl`

### Codex
- `~/.codex/sessions/<session_id>/rollout.jsonl`
- `~/.codex/history.jsonl`

## Database Location

```
~/.local/share/recall/recall.duckdb
```

## Tech Stack

| Tool | Purpose |
|------|---------|
| `uv` | Package manager, venv, workspaces |
| `typer` | CLI framework |
| `pydantic` | Data models, validation |
| `duckdb` | Storage + FTS + analytics |
| `ruff` | Linting + formatting |
| `pyright` | Type checking |
| `pytest` | Testing |

## Implementation Order

1. Scaffold monorepo structure
2. Implement `core/models.py` - domain models
3. Implement `db/schema.sql` and `db/connection.py`
4. Implement `parsers/claude_code.py` - port existing logic
5. Implement `parsers/codex.py`
6. Implement `services/indexer.py`
7. Implement `cli/` - basic commands
8. Add FTS search
9. Implement `services/analytics.py` - stats, suggestions
10. Add tests
11. Create skill SKILL.md
12. Publish to PyPI

## Distribution

| Channel | Method |
|---------|--------|
| PyPI | `uv pip install recall` |
| uvx | `uvx recall index` |
| Skill | `.claude/skills/recall/SKILL.md` |
