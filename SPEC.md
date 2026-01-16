# recall Specification

Session recall and analytics for AI agents (Claude Code, Codex).

## Overview

`recall` indexes AI agent session files into a unified DuckDB database, enabling search, analytics, and permission suggestions based on actual usage patterns.

**Primary use case:** Analyze tool usage across Claude Code and Codex sessions to identify safe auto-approve permissions and understand development patterns.

## Design Decisions

### Error Handling

| Scenario | Behavior |
|----------|----------|
| Malformed JSONL line | Skip line, log warning, continue |
| Corrupted session file | Skip file, log error, continue indexing |
| Mid-write session | Parse available lines, mark as incomplete |
| Database corruption | Error on run, `--recreate` flag to backup and rebuild |
| Schema mismatch | Error with clear message, suggest `--recreate` |

### Session Identity

**Session ID generation:** `SHA256(source:absolute_path)[:16]`
- Deterministic - same file always gets same ID
- Collision-resistant across sources
- Reproducible for debugging

**Message ID generation:** `SHA256(session_id:idx)[:16]`
- Unique within session via message index
- Stable across reindexing (same session + idx = same ID)

**ToolCall ID generation:**
- With message: `SHA256(message_id:idx)[:16]` where idx is position within message
- Orphan calls (message_id is null): `SHA256(session_id:orphan:global_idx)[:16]` where global_idx is the tool call's sequential position within the session's orphan calls
- Stable across reindexing (deterministic from source data)

**Orphan tool calls:** Codex `function_call` events that appear outside message blocks are stored with `message_id=NULL`. Their `idx` field represents position among orphan calls in the session (0-indexed).

### Incremental Indexing

**Staleness detection:** `file_mtime + file_size`
- Reindex if either changes
- Stored in `sessions.file_mtime` and `sessions.file_size`
- Skip unchanged files for fast incremental runs

**Reindex workflow (when file changed):**
1. Begin transaction
2. Delete related records in order: tool_calls → messages → sessions (manual cascade)
3. Parse file fresh
4. Insert new session, messages, tool_calls
5. Commit transaction

This ensures atomicity - no partial state on crash or error. The `is_complete` flag is set based on parsing success (FALSE if any lines failed to parse).

**Note:** DuckDB does not support `ON DELETE CASCADE` in foreign key constraints. Deletions must be performed manually in dependency order (children before parents).

### Concurrency

**Advisory file lock** at `~/.local/share/recall/recall.lock`
- Fail fast if another `recall index` is running
- Lock released on process exit (normal or crash)

### Bash Command Parsing

**Strategy:** First command with subcommand extraction

```
Input: "git commit -m 'msg' && git push"
→ bash_base: "git"
→ bash_sub: "commit"
→ is_compound: true

Input: "kubectl get pods -n default"
→ bash_base: "kubectl"
→ bash_sub: "get"
→ is_compound: false

Input: "cat file.txt | grep error"
→ bash_base: "cat"
→ bash_sub: null
→ is_compound: true
```

**Recognized subcommand tools:** git, kubectl, docker, npm, yarn, pnpm, cargo, go, uv, pip, brew, apt, systemctl

### Thinking Content

**Storage:** Separate `thinking` column in messages table
- Full thinking content preserved for search
- `has_thinking` boolean for quick filtering
- Enables search across reasoning when needed

### Full-Text Search

DuckDB's FTS extension provides keyword-based search using inverted indexes and Okapi BM25 scoring.

**Indexed fields (configurable, all enabled by default):**
- Message content (`messages.content`)
- Thinking content (`messages.thinking`)
- Bash commands (`tool_calls.bash_command`)

**Configuration:**

Environment variable: `RECALL_FTS_FIELDS`
- Comma-separated list of fields to index
- Values: `content`, `thinking`, `bash`
- Default: `content,thinking,bash` (all enabled)
- Example: `RECALL_FTS_FIELDS=content,bash` (skip thinking)

Config file (`~/.config/recall/config.toml`):
```toml
[fts]
fields = ["content", "thinking", "bash"]
```

**Index creation:**

The FTS extension is autoloaded when the PRAGMA is called. Indexes are created per-table:

```sql
-- Messages index (content + thinking in one index)
PRAGMA create_fts_index(
    messages,           -- table
    id,                 -- document identifier column
    content, thinking,  -- columns to index
    stemmer = 'porter',
    stopwords = 'english',
    overwrite = 1
);

-- Tool calls index (bash commands only)
PRAGMA create_fts_index(
    tool_calls,
    id,
    bash_command,
    stemmer = 'porter',
    stopwords = 'english',
    overwrite = 1
);
```

**FTS parameters:**
- `stemmer`: Word stemming algorithm (`porter` default, `none` to disable)
- `stopwords`: Common words to ignore (`english` default)
- `ignore`: Regex for characters to skip (default: `(\\.|[^a-z])+`)
- `strip_accents`: Convert accented chars (default: 1)
- `lower`: Convert to lowercase (default: 1)
- `overwrite`: Replace existing index (default: 0)

**Search queries:**

Creating an index generates a `match_bm25` macro in schema `fts_main_<table>`:

```sql
-- Search messages
SELECT m.*, fts_main_messages.match_bm25(
    m.id,
    'search query here',
    fields := 'content'  -- or 'content,thinking', or NULL for all
) AS score
FROM messages m
WHERE score IS NOT NULL
ORDER BY score DESC
LIMIT 10;

-- Search bash commands
SELECT tc.*, fts_main_tool_calls.match_bm25(
    tc.id,
    'git commit',
    fields := 'bash_command'
) AS score
FROM tool_calls tc
WHERE score IS NOT NULL
ORDER BY score DESC;
```

**BM25 parameters:**
- `k` (default 1.2): Term frequency saturation
- `b` (default 0.75): Document length normalization
- `conjunctive` (default 0): Set to 1 to require all keywords match

**Tool input extraction:**
- Bash commands are extracted to `tool_calls.bash_command` for FTS
- Other tool inputs remain in JSON (`tool_input`) and are not FTS-indexed
- Query tool inputs via JSON functions: `tool_input->>'file_path'`

### Project Tracking

**Both git root and cwd tracked:**
- `sessions.cwd` - working directory from session
- `sessions.git_repo` - detected git root (if in repo)
- `sessions.git_branch` - branch at session start (if available)

## Data Model

### Schema

```sql
-- Schema version tracking
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Unified sessions table
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,              -- SHA256(source:path)[:16]
    source TEXT NOT NULL CHECK (source IN ('claude_code', 'codex')),
    source_path TEXT UNIQUE NOT NULL,
    source_session_id TEXT,           -- Original session ID from source

    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    duration_seconds INTEGER,

    model TEXT,
    cwd TEXT,
    git_repo TEXT,                    -- Detected git root
    git_branch TEXT,

    message_count INTEGER DEFAULT 0,
    tool_count INTEGER DEFAULT 0,
    input_tokens INTEGER,             -- NULL if not available
    output_tokens INTEGER,            -- NULL if not available

    is_complete BOOLEAN DEFAULT TRUE, -- FALSE if parsing was partial
    file_mtime DOUBLE NOT NULL,
    file_size BIGINT NOT NULL,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    idx INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT,
    thinking TEXT,                    -- Separate thinking content
    timestamp TIMESTAMP,
    has_thinking BOOLEAN DEFAULT FALSE,

    -- v2: Embedding columns (NULL in v1, populated when semantic search enabled)
    content_embedding FLOAT[384],     -- For semantic search of message content
    thinking_embedding FLOAT[384],    -- For semantic search of thinking blocks

    UNIQUE(session_id, idx)
);

CREATE TABLE tool_calls (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    message_id TEXT REFERENCES messages(id),
    idx INTEGER NOT NULL,

    tool_name TEXT NOT NULL,
    tool_input JSON,                  -- Full tool input preserved

    -- Denormalized Bash fields for fast queries
    bash_command TEXT,                -- Full command string
    bash_base TEXT,                   -- First command (git, kubectl, etc.)
    bash_sub TEXT,                    -- Subcommand (commit, get, etc.)
    is_compound BOOLEAN DEFAULT FALSE, -- Has pipes, &&, ||, etc.

    -- v2: Embedding column (NULL in v1)
    bash_embedding FLOAT[384]         -- For semantic search of bash commands
);

-- Indexes
CREATE INDEX idx_sessions_source ON sessions(source);
CREATE INDEX idx_sessions_cwd ON sessions(cwd);
CREATE INDEX idx_sessions_git_repo ON sessions(git_repo);
CREATE INDEX idx_sessions_started ON sessions(started_at DESC);
CREATE INDEX idx_messages_session ON messages(session_id);
CREATE INDEX idx_messages_has_thinking ON messages(has_thinking);
CREATE INDEX idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX idx_tool_calls_name ON tool_calls(tool_name);
CREATE INDEX idx_tool_calls_bash_base ON tool_calls(bash_base);
CREATE INDEX idx_tool_calls_bash_sub ON tool_calls(bash_sub);

-- FTS indexes (created after data load, see Full-Text Search section)
-- PRAGMA create_fts_index(messages, id, content, thinking, overwrite=1);
-- PRAGMA create_fts_index(tool_calls, id, bash_command, overwrite=1);
```

### Pydantic Models

These models are **domain objects** that map directly to database rows. They include all DB fields for insert/query operations. Nested relationships (Session.messages, Message.tool_calls) are populated when loading full session data.

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
    session_id: str              # FK to sessions.id
    message_id: str | None       # FK to messages.id (nullable for orphan calls)
    idx: int                     # Position within message
    tool_name: str
    tool_input: dict[str, Any] | None = None

    # Bash-specific (denormalized)
    bash_command: str | None = None
    bash_base: str | None = None
    bash_sub: str | None = None
    is_compound: bool = False

    # v2: Embedding (NULL in v1)
    bash_embedding: list[float] | None = None

class Message(BaseModel):
    id: str
    session_id: str              # FK to sessions.id
    idx: int                     # Position within session
    role: str                    # user, assistant, system
    content: str | None = None
    thinking: str | None = None
    timestamp: datetime | None = None
    has_thinking: bool = False
    tool_calls: list[ToolCall] = Field(default_factory=list)  # Populated on load

    # v2: Embeddings (NULL in v1)
    content_embedding: list[float] | None = None
    thinking_embedding: list[float] | None = None

class Session(BaseModel):
    id: str
    source: Source
    source_path: str
    source_session_id: str | None = None  # Original ID from source file

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
    file_mtime: float              # File modification time (for staleness)
    file_size: int                 # File size in bytes (for staleness)
    indexed_at: datetime | None = None  # When this session was indexed

    messages: list[Message] = Field(default_factory=list)  # Populated on load
```

## CLI Interface

### Commands

```bash
# Indexing
recall index                        # Incremental index all sources
recall index --full                 # Force full reindex
recall index --source claude-code   # Index specific source
recall index --recreate             # Backup old DB and rebuild

# Search
recall search "auth"                # FTS across all content
recall search "kubectl" --tool Bash # Filter by tool
recall search --source codex "err"  # Filter by source
recall search --json                # JSON output

# List sessions
recall list                         # Recent sessions
recall list --source claude-code    # Filter by source
recall list --since 7d              # Time filter
recall list --project /path/to/repo # Filter by git repo
recall list --json                  # JSON output

# Analytics
recall stats                        # Overview dashboard
recall stats tools                  # Tool usage frequency
recall stats bash                   # Bash command breakdown
recall stats bash --suggest         # Generate permission rules
recall stats tokens                 # Token usage by project/time
recall stats --json                 # JSON output

# Session details
recall show <id>                    # Conversation transcript
recall show <id> --tools            # Include tool calls
recall show <id> --thinking         # Include thinking blocks
recall show <id> --json             # JSON output
```

### Output Formats

**Default:** Human-readable, conversation-style
```
[2024-01-15 10:30] Session abc123 (claude_code)
Project: /Users/allen/myproject
Duration: 45m | Messages: 23 | Tools: 47

user: Help me fix the auth bug
assistant: I'll investigate the authentication...
  [Bash] git status
  [Read] src/auth/handler.ts
```

**JSON (--json flag):** Machine-readable for scripting
```json
{
  "id": "abc123",
  "source": "claude_code",
  "started_at": "2024-01-15T10:30:00Z",
  "messages": [...]
}
```

### Verbosity

- Default: Progress bars, summary stats
- `-v/--verbose`: Detailed file-by-file logging

### Flag Normalization

**`--source` flag:**
- CLI accepts: `claude-code`, `codex` (kebab-case for CLI ergonomics)
- Internally normalized to: `claude_code`, `codex` (schema values)
- Mapping: `claude-code` → `claude_code`

**`--since` flag:**
- Accepts relative durations: `7d`, `24h`, `30m`, `1w`
- Accepts absolute timestamps: `2024-01-15`, `2024-01-15T10:30:00`
- Parsed to UTC datetime for query

**`--project` flag:**
- Filters by `sessions.git_repo` (git root path)
- Accepts partial paths: `--project myrepo` matches `/Users/allen/myrepo`

**Tool name normalization:**
- Tool names stored as-is from source (case-sensitive)
- `--tool` filter is case-insensitive match

### Permission Suggestions

`recall stats bash --suggest` generates permission rules for Claude Code auto-approve:

**Output format (human-readable):**
```
Suggested Bash Permissions
==========================

High confidence (>=50 uses, no dangerous patterns):
  - git *           (523 uses)
  - npm test        (89 uses)
  - ruff check *    (67 uses)

Medium confidence (>=10 uses):
  - pytest *        (45 uses)
  - uv sync         (32 uses)

Review carefully (contains arguments/pipes):
  - docker build *  (12 uses)

Not suggested (contains rm, sudo, or writes):
  - rm -rf *        (3 uses) [SKIPPED]
```

**Confidence thresholds:**
- High: >=50 uses AND no dangerous patterns (rm, sudo, chmod, etc.)
- Medium: >=10 uses AND no dangerous patterns
- Low/Review: <10 uses OR contains pipes/complex arguments

**Output format (JSON with --json):**
```json
{
  "suggestions": [
    {
      "pattern": "git *",
      "count": 523,
      "confidence": "high",
      "reason": "No dangerous patterns detected"
    },
    {
      "pattern": "npm test",
      "count": 89,
      "confidence": "high",
      "reason": "Read-only test command"
    }
  ],
  "skipped": [
    {
      "pattern": "rm -rf *",
      "count": 3,
      "reason": "Destructive command"
    }
  ]
}
```

**Permission rule generation:**
- Groups by `bash_base` + `bash_sub`
- Applies safety heuristics (skip rm, sudo, chmod, etc.)
- Wildcards added for common argument patterns

## Session Sources

### Claude Code

**Location:** `~/.claude/projects/<encoded-path>/<session-id>.jsonl`

**Format:** JSONL with message objects containing:
- `type`: message type
- `message`: content object with role, content blocks
- `costUSD`, `inputTokens`, `outputTokens`: usage data (when present)

### Codex

**Location:**
- `~/.codex/sessions/<session_id>/rollout.jsonl` - Full session data
- `~/.codex/history.jsonl` - Session index (not parsed, use rollout files)

**Session ID source:** `payload.id` from `session_meta` entry in rollout.jsonl

**Format:** JSONL with entry types:

```jsonl
{"type": "session_meta", "payload": {"id": "abc123", "timestamp": "...", "cwd": "/path", "cli_version": "1.0", "git": {"branch": "main", "commit_hash": "..."}}}
{"type": "event_msg", "timestamp": "...", "payload": {"type": "user_message", "message": "Help me..."}}
{"type": "event_msg", "timestamp": "...", "payload": {"type": "agent_message", "message": "I'll help..."}}
{"type": "event_msg", "timestamp": "...", "payload": {"type": "function_call", "name": "shell", "parameters": {...}}}
{"type": "message", "timestamp": "...", "payload": {"role": "assistant", "content": [{"type": "text", "text": "..."}, {"type": "tool_use", "name": "shell", ...}]}}
```

**Entry type mapping:**
| Entry Type | Payload Type | Maps To |
|------------|--------------|---------|
| `session_meta` | - | Session metadata (id, cwd, git) |
| `event_msg` | `user_message` | Message(role="user") |
| `event_msg` | `agent_message` | Message(role="assistant") |
| `event_msg` | `function_call` | ToolCall |
| `message` | - | Legacy format: Message + embedded ToolCalls |

**Notes:**
- Both `event_msg` and `message` formats may appear in same file (legacy support)
- Tool calls in `message` format are embedded in `content` array as `tool_use` blocks
- `history.jsonl` contains session summaries but lacks full message data

## File Locations

| File | Location |
|------|----------|
| Database | `~/.local/share/recall/recall.duckdb` |
| Lock file | `~/.local/share/recall/recall.lock` |
| Config | `~/.config/recall/config.toml` (optional) |
| Logs | stderr (not persisted) |

## MVP Criteria (v1.0)

### Must Work

1. **Indexing**
   - [ ] Parse Claude Code sessions from `~/.claude/projects/`
   - [ ] Parse Codex sessions from `~/.codex/sessions/`
   - [ ] Incremental indexing (skip unchanged files)
   - [ ] Handle malformed files gracefully (skip + log)
   - [ ] Advisory lock prevents concurrent runs

2. **Search**
   - [ ] FTS search across message content
   - [ ] Filter by source, tool name
   - [ ] Results show session context

3. **List**
   - [ ] List sessions with timestamp, source, project
   - [ ] Filter by source, time range
   - [ ] Sort by recency

4. **Stats**
   - [ ] Tool usage frequency
   - [ ] Bash command breakdown (base + subcommand)
   - [ ] Basic permission suggestions

5. **Show**
   - [ ] Display session as conversation
   - [ ] Include tool calls with `--tools`

6. **Output**
   - [ ] Human-readable default
   - [ ] JSON output with `--json`

### Out of Scope for v1

- Watch mode / live indexing
- Session deletion
- Remote/cloud storage
- Cost calculations (just raw tokens)
- Export to other formats
- Web UI

## Future Considerations

### v1.1 Candidates

- Cost calculation with model pricing
- Export to markdown/HTML
- Session tagging/bookmarking
- Custom source plugins

### v2 Candidates

- Watch mode with fsevents
- MCP server for agent access
- Cross-machine sync
- Session diffing
- **Semantic/vector search**: Schema already includes nullable `FLOAT[384]` embedding columns. v2 implementation:
  - Populate `content_embedding`, `thinking_embedding`, `bash_embedding` via embedding model
  - Default model: all-MiniLM-L6-v2 (384 dims, runs locally via sentence-transformers)
  - Alternative: OpenAI text-embedding-3-small (1536 dims - would require schema migration)
  - Search via `array_cosine_similarity(query_embedding, content_embedding)`
  - Hybrid search: Convex Combination `α*norm_vector + (1-α)*norm_fts` with α=0.7 default
  - Backfill existing data: `recall index --embed` to populate embeddings for all messages

## Implementation Notes

Learnings captured during v1 implementation:

### DuckDB Constraints

1. **No CASCADE support**: Foreign key constraints cannot use `ON DELETE CASCADE`, `SET NULL`, or `SET DEFAULT`. Deletions must be performed manually in dependency order (tool_calls → messages → sessions).

2. **FTS extension autoloads**: The FTS extension is automatically loaded when `PRAGMA create_fts_index` is called. No need for explicit `INSTALL fts; LOAD fts;` in most cases.

3. **FTS creates schema**: Creating an FTS index generates a `fts_main_<table>` schema with the `match_bm25()` macro for queries.

### uv Workspace Setup

For monorepo with `uv` workspaces:
- Dev dependencies go in root `pyproject.toml` under `[dependency-groups]`
- Workspace packages need `[tool.uv.sources]` mapping: `recall = { workspace = true }`
- Set `default-groups = ["dev"]` in `[tool.uv]` for automatic dev dep installation
- Package `readme` paths cannot reference files outside the package directory

### Testing

- Fixtures should be accessible from test files via relative paths
- Use `Path(__file__).resolve().parents[N]` carefully - verify the correct ancestor level
- DuckDB in-memory databases work well for isolated test runs
