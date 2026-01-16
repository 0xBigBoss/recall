# recall

Session recall and analytics for AI agents (Claude Code, Codex).

Search past sessions, analyze tool usage patterns, and generate permission suggestions from your AI coding history.

## Installation

```bash
# Install from GitHub
uv tool install "recall @ git+https://github.com/0xbigboss/recall.git#subdirectory=packages/recall"

# Or clone and run locally
git clone https://github.com/0xbigboss/recall.git
cd recall
uv sync
uv run recall --help
```

## Quick Start

```bash
# Index your sessions (run first)
recall index

# Search past work
recall search "authentication"
recall search "git rebase" --tool Bash

# List recent sessions
recall list --since 7d
recall list --project /path/to/repo

# View session details
recall show <session-id> --tools

# Analytics
recall stats tools        # Tool usage counts
recall stats bash         # Bash command breakdown
recall stats bash --suggest  # Permission suggestions
```

## Commands

| Command | Description |
|---------|-------------|
| `recall index` | Index sessions from Claude Code and Codex |
| `recall search <query>` | Full-text search across sessions |
| `recall list` | List sessions with filters |
| `recall show <id>` | Display session details |
| `recall stats` | Analytics and usage patterns |

## Claude Code Plugin

Install as a Claude Code plugin for automatic skill integration:

```bash
claude plugin marketplace add 0xbigboss/recall
claude plugin install recall@0xbigboss-recall
```

Or test locally:

```bash
claude --plugin-dir /path/to/recall
```

The skill auto-triggers on prompts like "search my past sessions" or "suggest permissions to auto-approve".

## Data Locations

| Data | Path |
|------|------|
| Database | `~/.local/share/recall/recall.duckdb` |
| Claude Code sessions | `~/.claude/projects/**/*.jsonl` |
| Codex sessions | `~/.codex/sessions/*/rollout.jsonl` |

## Development

```bash
uv sync                    # Install dependencies
uv run pytest              # Run tests
uv run ruff check .        # Lint
uv run pyright             # Type check
```

## License

MIT
