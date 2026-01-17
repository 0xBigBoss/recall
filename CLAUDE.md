# recall

Session recall and analytics for AI agents (Claude Code, Codex).

## Quick Start

```bash
uv sync                    # Install dependencies
uv run recall index        # Index all sessions
uv run recall list         # List recent sessions
uv run recall stats tools  # Show tool usage
uv run recall search "git" # Search across sessions
```

## Development

```bash
uv sync                    # Install deps (includes dev tools)
uv run lefthook install    # Set up git hooks
uv run pytest              # Run tests
uv run ruff check .        # Lint
uvx ty check               # Type check
```

## Project Structure

```
packages/recall/src/recall/
├── core/           # Domain models, config, ID generation, bash parsing
├── db/             # DuckDB schema, connection, queries
├── parsers/        # Claude Code and Codex JSONL parsers
├── services/       # Indexing, search, analytics business logic
└── cli/            # Typer CLI commands
```

## Key Files

- `SPEC.md` - Full specification with schema, CLI, and design decisions
- `PLAN.md` - Architecture overview and module dependencies
- `packages/recall/src/recall/db/schema.sql` - Database schema

## Architecture

```
cli/ → services/ → parsers/ → core/
         ↓            ↓
        db/        core/
         ↓
       core/
```

- `core/` - Zero external deps, pure Python + Pydantic
- `db/` - DuckDB operations, FTS setup
- `parsers/` - Source-specific JSONL parsing
- `services/` - Business logic orchestration
- `cli/` - User-facing commands

## Data Locations

| Data | Path |
|------|------|
| Database | `~/.local/share/recall/recall.duckdb` |
| Lock file | `~/.local/share/recall/recall.lock` |
| Claude Code sessions | `~/.claude/projects/**/*.jsonl` |
| Codex sessions | `~/.codex/sessions/**/rollout*.jsonl` |

## CLI Commands

```bash
recall index [--full] [--source claude-code|codex] [--recreate] [-v]
recall search <query> [--tool <name>] [--source] [--json]
recall list [--source] [--since 7d] [--project <path>] [--json]
recall stats [tools|bash|tokens] [--suggest] [--json]
recall show <session-id> [--tools] [--thinking] [--json]
```

## Testing

Tests use fixtures in `tests/fixtures/` (symlinked to `fixtures/` at repo root).

```bash
uv run pytest -q           # Run all tests
uv run pytest -k parser    # Run parser tests only
```

## DuckDB Notes

- No `ON DELETE CASCADE` support - deletions done manually in order
- FTS via `PRAGMA create_fts_index()` - creates `fts_main_<table>.match_bm25()` macro
- Schema includes nullable `FLOAT[384]` embedding columns for future v2 semantic search
