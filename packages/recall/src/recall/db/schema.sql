CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('claude_code', 'codex')),
    source_path TEXT UNIQUE NOT NULL,
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

    is_complete BOOLEAN DEFAULT TRUE,
    file_mtime DOUBLE NOT NULL,
    file_size BIGINT NOT NULL,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    idx INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT,
    thinking TEXT,
    timestamp TIMESTAMP,
    has_thinking BOOLEAN DEFAULT FALSE,

    content_embedding FLOAT[384],
    thinking_embedding FLOAT[384],

    UNIQUE(session_id, idx)
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    message_id TEXT REFERENCES messages(id),
    idx INTEGER NOT NULL,

    tool_name TEXT NOT NULL,
    tool_input JSON,

    bash_command TEXT,
    bash_base TEXT,
    bash_sub TEXT,
    is_compound BOOLEAN DEFAULT FALSE,

    bash_embedding FLOAT[384]
);

CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
CREATE INDEX IF NOT EXISTS idx_sessions_cwd ON sessions(cwd);
CREATE INDEX IF NOT EXISTS idx_sessions_git_repo ON sessions(git_repo);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_has_thinking ON messages(has_thinking);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_name ON tool_calls(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_calls_bash_base ON tool_calls(bash_base);
CREATE INDEX IF NOT EXISTS idx_tool_calls_bash_sub ON tool_calls(bash_sub);
