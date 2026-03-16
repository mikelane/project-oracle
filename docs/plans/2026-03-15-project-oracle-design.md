# Project Oracle — Design Document

**Date:** 2026-03-15
**Status:** Draft
**Author:** Mike Lane + Claude

## Problem

AI coding agents waste significant tokens on three patterns:

1. **Re-reading files** — Agent reads a file, context compacts, agent reads the same file again. Every re-read costs hundreds to thousands of tokens for content the agent already processed.
2. **Multi-step tool choreography** — Agent runs `git status`, then `git diff`, then reads 3 files, then greps for something. Five round trips of reasoning + results when one structured query could suffice.
3. **Rediscovering project structure** — Every new session: glob for files, read configs, figure out the tech stack, find test commands. The agent pays this cost repeatedly for knowledge that rarely changes.

These compound over long sessions and across sessions. The longer the agent works, the more it repeats itself.

## Solution

A **stateful MCP server** (codename: Project Oracle) that maintains a working model of each project the agent interacts with. It acts as a smart proxy layer — caching file reads, command results, and git state, then returning compact deltas on repeat queries instead of full content.

### Key Properties

- **Implicit project discovery** — Auto-detects project root from file paths (git root, package.json, pyproject.toml, go.mod, Cargo.toml). Zero configuration.
- **Per-project persistence** — State survives across Claude Code sessions via SQLite. The agent picks up where it left off.
- **Hybrid query interface** — Structured fast-path tools for common operations (`oracle_read`, `oracle_grep`, `oracle_status`, `oracle_run`) plus a natural language `ask()` fallback.
- **Chunkhound integration** — Delegates code understanding queries (imports, dependencies, semantic search) to chunkhound's AST-based semantic indexing. The oracle handles operational state; chunkhound handles code intelligence.
- **Three-layer agent nudging** — PostToolUse hooks passively build state from built-in tool use, PreToolUse AYLO questions redirect the agent to oracle tools, and oracle tool descriptions explain the token savings.

## Architecture

### High-Level View

```
┌─────────────────────────────────────────────┐
│  Agent (Claude Code)                        │
│  Calls oracle_* tools or built-in tools     │
└──────────┬──────────────────────────────────┘
           │ MCP stdio
┌──────────▼──────────────────────────────────┐
│  Project Oracle Server (FastMCP, Python)    │
│                                             │
│  ┌────────────────────────────────────────┐ │
│  │ Smart Proxy / Cache Layer              │ │
│  │                                        │ │
│  │ oracle_read  → full or delta           │ │
│  │ oracle_grep  → full or delta           │ │
│  │ oracle_status → project health snapshot│ │
│  │ oracle_run   → run + summarize         │ │
│  │ oracle_ask   → route to handler        │ │
│  └───────────────┬────────────────────────┘ │
│                  │                           │
│  ┌───────────────▼────────────────────────┐ │
│  │ Integrations                           │ │
│  │ chunkhound (MCP client, subprocess)    │ │
│  │ git (shell)                            │ │
│  │ FS watcher (watchfiles)                │ │
│  └────────────────────────────────────────┘ │
│                                             │
│  Storage: SQLite per project                │
│  ~/.project-oracle/projects/<hash>/state.db │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│  Claude Code Hooks (parallel)               │
│                                             │
│  PreToolUse (Read/Grep/Bash):               │
│    AYLO question → nudge agent to oracle    │
│                                             │
│  PostToolUse (Read/Grep/Bash):              │
│    Passive ingest → feed results to oracle  │
└─────────────────────────────────────────────┘
```

### Component Layout

```
project-oracle/
├── src/oracle/
│   ├── server.py              # FastMCP entry point, tool definitions
│   ├── project.py             # Project detection + state container
│   ├── registry.py            # Maps paths → ProjectState instances
│   ├── cache/
│   │   ├── file_cache.py      # Content cache + delta computation
│   │   ├── git_cache.py       # Git state (branch, status, log)
│   │   └── command_cache.py   # Test/lint/build result cache
│   ├── tools/
│   │   ├── oracle_read.py     # Smart read: full or delta
│   │   ├── oracle_grep.py     # Cached grep with result diffing
│   │   ├── oracle_status.py   # Aggregated project health
│   │   ├── oracle_run.py      # Run + summarize commands
│   │   └── ask.py             # NL fallback → chunkhound + cache + haiku
│   ├── integrations/
│   │   ├── chunkhound.py      # MCP client to chunkhound subprocess
│   │   ├── git.py             # Git operations
│   │   └── watchers.py        # FS watcher for cache invalidation
│   └── storage/
│       └── store.py           # SQLite per-project persistence
├── hooks/
│   ├── lights-on-oracle-pre.sh   # AYLO PreToolUse nudges
│   └── lights-on-oracle-post.sh  # Passive PostToolUse ingest
├── pyproject.toml
└── tests/
```

## Tool Behavior

### Token Savings Matrix

| Tool | First call | Repeat (unchanged) | Repeat (changed) |
|------|-----------|-------------------|------------------|
| `oracle_read(path)` | Full content (cached) | `"No changes since last read"` (~3 tokens) | Delta: `"Lines 42-50 changed: ..."` |
| `oracle_grep(pattern)` | Full results (cached) | `"Same N matches as before"` (~6 tokens) | `"+2 new matches in auth.py"` |
| `oracle_status()` | Full project snapshot | `"No changes"` (~2 tokens) | Only changed fields |
| `oracle_run(cmds)` | Run + summarize | Cached if inputs unchanged | Re-run + delta |
| `oracle_ask(question)` | Route to best handler | Context-aware answer | — |

Repeat calls on unchanged state cost 3-10 tokens instead of hundreds or thousands. Savings compound over session length.

## Data Flow

### Passive Learning (PostToolUse Hook)

```
Agent calls Read("src/auth.py")          ← built-in tool
    → Claude Code executes Read internally
    → PostToolUse hook fires
    → Hook writes {tool, path, timestamp} to ~/.project-oracle/ingest/<ts>.json
    → Oracle drains ingest queue on next tool call
    → Oracle caches file content + hash
    → Agent never sees this (passive)
```

The hook writes to a file queue (not SQLite directly) to avoid locking contention between the sync bash hook and the async Python server.

### Active Query (Oracle Tools)

```
Agent calls oracle_read("src/auth.py")
    → Oracle checks file_cache

    Cache miss:
        → Read from disk, store {content, sha256, timestamp}
        → Return full content

    Cache hit, unchanged (sha256 matches disk):
        → Return "No changes since last read (2m ago)"

    Cache hit, changed:
        → Compute diff, update cache
        → Return "Changed since last read:\n- lines 42-50: ..."
```

### The `ask()` Router

Routes natural language to the cheapest handler. No LLM tokens consumed for routing.

```python
async def ask(question: str, project: ProjectState) -> str:
    intent = classify_intent(question)

    match intent:
        case Intent.GIT_STATUS:
            return format_git_delta(project.git_state)
        case Intent.READINESS:
            return await run_readiness_check(project)
        case Intent.TEST_STATUS:
            return format_test_status(project.command_results)
        case Intent.PROJECT_STRUCTURE:
            return format_project_overview(project)
        case Intent.CODE_UNDERSTANDING:
            # Primary path: chunkhound semantic search
            if project.chunkhound:
                results = await project.chunkhound.search(question)
                if results:
                    return format_chunkhound_results(results)
            return await fallback_grep(question, project)
        case Intent.UNKNOWN:
            # Haiku safety net (~$0.001/call, 300 token cap)
            return await haiku_fallback(question, project)
```

**Routing priority:** operational cache (free) → chunkhound embeddings (free) → haiku ($0.001).

### Cache Invalidation

FS watcher (`watchfiles`, Rust-backed) monitors the project root:

- File modified → mark `file_cache` entry stale via `disk_sha256` update
- `.git/HEAD` changed → refresh `git_state`
- File created → lazy (indexed on first access)
- File deleted → remove from cache

## Chunkhound Integration

The oracle spawns chunkhound as a child MCP server and talks to it over stdio (MCP-over-MCP pattern):

```
Claude Code → (stdio) → Project Oracle → (stdio) → Chunkhound MCP
```

### Responsibility Boundary

| Concern | Owner | Why |
|---------|-------|-----|
| AST parsing, semantic chunking | Chunkhound | Core competency (cAST algorithm) |
| Vector embeddings, similarity search | Chunkhound | Has DuckDB/LanceDB indexes |
| "What imports X?", "Find auth code" | Chunkhound | Semantic search across codebase |
| File content caching, delta diffing | Oracle | Tracks what the agent has *seen* |
| Git state, test results, build status | Oracle | Operational state |
| "Has this changed since I last looked?" | Oracle | Agent interaction history |
| Cross-session project memory | Oracle | SQLite persistence |
| Token savings tracking | Oracle | Agent interaction metrics |

**Chunkhound understands code. The oracle understands the agent's relationship to the code.**

### Graceful Degradation

If chunkhound is not installed or fails to start:
- `CODE_UNDERSTANDING` queries fall back to grep-based search
- `UNKNOWN` queries fall back to haiku
- The agent never sees an error — just potentially less precise answers
- Chunkhound failure is cached per-session (no repeated spawn attempts)

## Persistence

### Storage Layout

```
~/.project-oracle/
├── registry.json              # Project root → project ID mapping (human-readable)
├── ingest/                    # File queue from PostToolUse hooks
│   ├── 1710504000000000.json
│   └── ...
└── projects/
    ├── a1b2c3d4/              # SHA256(project_root)[:8]
    │   ├── state.db           # SQLite — all cached state
    │   └── meta.json          # Stack info, last session timestamp
    └── e5f6g7h8/
        ├── state.db
        └── meta.json
```

### SQLite Schema

```sql
CREATE TABLE file_cache (
    path        TEXT PRIMARY KEY,
    content     BLOB,            -- zstd-compressed file content
    sha256      TEXT NOT NULL,    -- hash of uncompressed content
    disk_sha256 TEXT,             -- last known hash on disk (from watcher)
    first_seen  INTEGER NOT NULL, -- epoch
    last_read   INTEGER NOT NULL, -- epoch: when agent last requested
    read_count  INTEGER DEFAULT 1
);

CREATE TABLE git_state (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    branch      TEXT NOT NULL,
    head_sha    TEXT NOT NULL,
    dirty_files TEXT,             -- JSON array
    staged_files TEXT,            -- JSON array
    recent_log  TEXT,             -- last 20 commits, one-line
    captured_at INTEGER NOT NULL
);

CREATE TABLE command_results (
    command     TEXT PRIMARY KEY,
    output      TEXT NOT NULL,    -- summarized, not raw
    exit_code   INTEGER,
    input_hash  TEXT,             -- hash of source files at run time
    ran_at      INTEGER NOT NULL
);

CREATE TABLE agent_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    tool_name    TEXT NOT NULL,
    input        TEXT,
    cache_hit    INTEGER DEFAULT 0,
    tokens_saved INTEGER DEFAULT 0,
    ts           INTEGER NOT NULL
);

CREATE INDEX idx_file_cache_last_read ON file_cache(last_read);
CREATE INDEX idx_agent_log_session ON agent_log(session_id);
CREATE INDEX idx_command_results_ran ON command_results(ran_at);
```

### Cache Eviction

- Files not read in 30 days → evicted
- Command results older than 24 hours → evicted
- If cache exceeds 50 MB per project → LRU eviction by `last_read`
- `read_count` tracked for future frequency-weighted eviction (LFU/ARC)

### Session Lifecycle

1. **Start** — First tool call triggers project detection → load/create `state.db` → start FS watcher → batch-update `disk_sha256` for cached files
2. **During** — Serve from cache with deltas, log interactions, watcher keeps `disk_sha256` current
3. **End** — Flush in-memory state to SQLite, update `meta.json`, stop watcher, log session summary

## AYLO Hooks

### PreToolUse — Nudge to Oracle

```bash
#!/bin/bash
# "Are Your Lights On?" — PreToolUse:Read/Grep/Bash
# Nudges the agent to check oracle cache before re-reading files or re-running commands.
# Outputs JSON additionalContext so the agent actually sees the question.
# Always exits 0 (non-blocking, allows the tool to proceed).

set -euo pipefail

emit_pre() {
    local question="$1"
    jq -n --arg q "$question" '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "allow",
        additionalContext: $q
      }
    }'
}

TOOL_INPUT=$(cat 2>/dev/null) || true
[[ -z "$TOOL_INPUT" ]] && exit 0

TOOL_NAME=$(echo "$TOOL_INPUT" | jq -r '.tool_name // empty' 2>/dev/null) || true
[[ -z "$TOOL_NAME" ]] && exit 0

# --- Read: has the oracle already cached this file? ---
if [[ "$TOOL_NAME" == "Read" ]]; then
    emit_pre "Has the oracle already cached this file, or are you about to burn 1000+ tokens re-reading content you already have — content the user is paying for twice?"
    exit 0
fi

# --- Grep: did you already run this search? ---
if [[ "$TOOL_NAME" == "Grep" ]]; then
    emit_pre "Did you already run this search, or are you about to get back the same results you already have while the user watches you repeat yourself?"
    exit 0
fi

# --- Bash: does the oracle have fresh results? ---
if [[ "$TOOL_NAME" == "Bash" ]]; then
    emit_pre "Is this a command the oracle already has fresh results for, or are you about to re-run a 10-second command and make the user wait for an answer the oracle could return instantly?"
    exit 0
fi

exit 0
```

### PostToolUse — Passive Ingest

```bash
#!/bin/bash
# "Are Your Lights On?" — PostToolUse:Read/Grep/Bash
# Feeds tool usage data to the oracle's cache so it builds state
# even when the agent bypasses oracle tools.
# Outputs JSON additionalContext so the agent actually sees the question.
# Always exits 0 (non-blocking).

set -euo pipefail

TOOL_INPUT=$(cat 2>/dev/null) || true
[[ -z "$TOOL_INPUT" ]] && exit 0

TOOL_NAME=$(echo "$TOOL_INPUT" | jq -r '.tool_name // empty' 2>/dev/null) || true
[[ -z "$TOOL_NAME" ]] && exit 0

ORACLE_DIR="$HOME/.project-oracle"
QUEUE_DIR="$ORACLE_DIR/ingest"
mkdir -p "$QUEUE_DIR"

TIMESTAMP=$(date +%s%N)
echo "$TOOL_INPUT" > "$QUEUE_DIR/${TIMESTAMP}.json" &

exit 0
```

## Registration

### MCP Server (settings.json)

```json
{
  "mcpServers": {
    "project-oracle": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "<path-to-project-oracle>", "project-oracle"]
    }
  }
}
```

### Hooks (settings.json)

Register `lights-on-oracle-pre.sh` as PreToolUse on `Read`, `Grep`, `Bash`.
Register `lights-on-oracle-post.sh` as PostToolUse on `Read`, `Grep`, `Bash`.

## Dependencies

```toml
[project]
name = "project-oracle"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "mcp[cli]>=1.0",
    "anthropic>=0.40",
    "zstandard>=0.23",
    "watchfiles>=1.0",
]
```

## Token Savings Model

### Per-Operation Estimates

| Scenario | Without Oracle | With Oracle | Savings |
|----------|---------------|-------------|---------|
| Re-read unchanged 200-line file | ~800 tokens | ~3 tokens | 797 |
| Re-read changed file (5 lines differ) | ~800 tokens | ~50 tokens | 750 |
| Repeat `git status` (no changes) | ~100 tokens | ~2 tokens | 98 |
| Repeat grep (same results) | ~300 tokens | ~6 tokens | 294 |
| Project overview (cached) | ~500 tokens (multiple tool calls) | ~80 tokens (one call) | 420 |

### Session-Level Projection

A typical 30-minute coding session with an agent involves roughly:
- 10-15 file reads (5-8 are re-reads) → ~4,000 tokens saved
- 5-8 git status checks (3-5 redundant) → ~400 tokens saved
- 3-5 grep searches (1-2 repeated) → ~500 tokens saved
- 2-3 project structure queries → ~800 tokens saved

**Estimated savings per session: ~5,700 tokens (~15-20% of typical session usage)**

Cross-session persistence multiplies this: the oracle starts warm on the second session, saving the entire project discovery phase.

## Resolved Design Decisions

1. **`oracle_forget(path)` tool** — Yes. Exposes a cache-bypass mechanism for when the agent needs a guaranteed fresh read. Clears the cached entry and forces a full re-read on the next `oracle_read()` call.

2. **`oracle_run` command allowlist** — Commands are validated against an allowlist of patterns (test runners, linters, type checkers, build tools). Arbitrary shell commands are rejected. The allowlist is configurable per-project via `meta.json`. Default allowlist: `pytest`, `ruff`, `mypy`, `go test`, `go build`, `npm test`, `pnpm test`, `eslint`, `tsc`, `cargo test`, `cargo build`.

3. **Multi-worktree support** — Each worktree is treated as a separate project. Project root detection uses the working directory, not the git common dir. Two worktrees of the same repo get independent `state.db` files under different hashes (`SHA256(worktree_path)[:8]`), since their file state diverges.

4. **Agent log → chunkhound relevance feedback** — Yes. Frequently-read files (high `read_count`) are boosted in chunkhound search results when available. Hot paths are hot for a reason — the agent's access pattern is a useful relevance signal.

5. **Server lifecycle: per-session spawn** — The MCP server spawns fresh per-session (this is how stdio MCP servers work by default). No daemon management, no orphan processes. Chunkhound starts lazily on first code understanding query, not on session open. Cold start cost is ~200-500ms (SQLite load + batch `stat()` for cache validation), which is acceptable.

## Open Questions

None remaining — all resolved. Implementation can proceed.
