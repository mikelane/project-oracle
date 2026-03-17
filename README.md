# Project Oracle

**A stateful MCP server that remembers what your AI agent has already seen.**

Project Oracle sits between Claude Code and your codebase, caching file reads, command results, and git state across sessions. When the agent re-reads an unchanged file, Oracle returns `"No changes since last read"` instead of the full content — saving hundreds of tokens per call and cutting repeat-read costs by 95%+.

---

## Table of Contents

- [The Problem](#the-problem)
- [How It Works](#how-it-works)
- [Token Savings](#token-savings)
- [Tools](#tools)
- [Installation](#installation)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Chunkhound Integration](#chunkhound-integration)
- [Development](#development)
- [License](#license)

---

## The Problem

AI coding agents waste tokens on three patterns that compound over long sessions:

1. **Re-reading files** — Agent reads a file, context compacts, agent reads the same unchanged file again. Every re-read costs hundreds to thousands of tokens for content already processed.
2. **Multi-step tool choreography** — `git status` → `git diff` → read 3 files → grep for something. Five round trips when one structured query would suffice.
3. **Rediscovering project structure** — Every new session: glob for files, read configs, figure out the tech stack, find test commands. The agent pays this cost repeatedly for knowledge that rarely changes.

These compound across sessions. Project Oracle eliminates the redundancy.

## How It Works

Oracle is a [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that acts as a **smart proxy** between the agent and your project:

```
Agent (Claude Code)
    │
    │ calls oracle_read("src/auth.py")
    │
    ▼
Project Oracle (MCP server)
    │
    ├─ Cache miss?  → Read from disk, compress with zstd, store in SQLite, return full content
    ├─ Cache hit, unchanged?  → Return "No changes since last read (2m ago)"  [~3 tokens]
    └─ Cache hit, changed?  → Compute unified diff, return only the delta
```

**Three layers of agent integration:**

| Layer | Mechanism | What it does |
|-------|-----------|-------------|
| **Passive learning** | PostToolUse hooks | When the agent uses built-in `Read`/`Grep`/`Bash`, hooks silently feed the results to Oracle's cache |
| **Active nudging** | PreToolUse AYLO hooks | Before the agent re-reads a file, a question nudges it toward `oracle_read` instead |
| **Direct tools** | 6 MCP tools | `oracle_read`, `oracle_grep`, `oracle_status`, `oracle_run`, `oracle_ask`, `oracle_forget` |

State persists in per-project SQLite databases, so the agent picks up where it left off across sessions.

## Token Savings (Projected)

> **Not yet benchmarked.** Per-operation savings are straightforward math (3-token cache hit vs. 800-token file re-read). Session-level savings depend on how often the agent actually re-reads unchanged files — we'll measure that from `agent_log` data once the server is running in real sessions.

| Scenario | Without Oracle | With Oracle | Projected Savings |
|----------|---------------|-------------|-------------------|
| Re-read unchanged 200-line file | ~800 tokens | ~3 tokens | ~99% |
| Re-read file with 5 lines changed | ~800 tokens | ~50 tokens | ~94% |
| Repeat `git status` (no changes) | ~100 tokens | ~2 tokens | ~98% |
| Repeat grep (same results) | ~300 tokens | ~6 tokens | ~98% |
| Project overview (cached) | ~500 tokens | ~80 tokens | ~84% |

## Tools

### `oracle_read(path)`

Read a file with automatic caching and delta diffing.

- **First call:** Returns full file content (cached for next time)
- **Repeat, unchanged:** `"No changes since last read (2m ago)"` — 3 tokens
- **Repeat, changed:** Returns only the unified diff of what changed

### `oracle_grep(pattern, path=".")`

Search source files for a regex pattern. Returns up to 50 matches.

### `oracle_status()`

Aggregated project health snapshot: language stack, git branch, clean/dirty state, cached file count.

### `oracle_run(commands)`

Run allowlisted commands (test runners, linters, type checkers) through the cache layer. Returns cached results when source files haven't changed. Rejects arbitrary shell commands.

**Default allowlist:** `pytest`, `ruff`, `mypy`, `go test`, `go build`, `npm test`, `pnpm test`, `eslint`, `tsc`, `cargo test`, `cargo build`

### `oracle_ask(question)`

Natural-language questions about the project, routed to the cheapest handler:

```
"what changed?"         → git cache (free)
"are we ready to push?" → readiness check (free)
"are tests passing?"    → command cache (free)
"what's the tech stack?"→ project overview (free)
"find auth middleware"  → chunkhound or grep (free)
"explain this pattern"  → Claude Haiku fallback (~$0.001)
```

No LLM is used for routing — a keyword classifier maps questions to intents.

### `oracle_forget(path)`

Clear the cache for a specific file. The next `oracle_read` returns full content. Use when you need a guaranteed fresh read.

## Installation

### Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** (recommended) or pip
- **[jq](https://jqlang.github.io/jq/)** (required for AYLO hooks)
- **Claude Code** with MCP support

### Install

```bash
# Clone the repository
git clone https://github.com/mikelane/project-oracle.git
cd project-oracle

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

### Verify

```bash
# Should print server info and exit
uv run project-oracle --help
```

## Configuration

### 1. Register the MCP server

Add to your Claude Code settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "project-oracle": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/project-oracle", "project-oracle"]
    }
  }
}
```

### 2. Install the AYLO hooks

Copy the hook scripts and register them in your Claude Code settings:

```bash
# Copy hooks to your Claude config
cp hooks/lights-on-oracle-pre.sh ~/.claude/hooks/
cp hooks/lights-on-oracle-post.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/lights-on-oracle-pre.sh
chmod +x ~/.claude/hooks/lights-on-oracle-post.sh
```

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read",
        "hooks": [{ "type": "command", "command": "bash ~/.claude/hooks/lights-on-oracle-pre.sh" }]
      },
      {
        "matcher": "Grep",
        "hooks": [{ "type": "command", "command": "bash ~/.claude/hooks/lights-on-oracle-pre.sh" }]
      },
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "bash ~/.claude/hooks/lights-on-oracle-pre.sh" }]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Read",
        "hooks": [{ "type": "command", "command": "bash ~/.claude/hooks/lights-on-oracle-post.sh" }]
      },
      {
        "matcher": "Grep",
        "hooks": [{ "type": "command", "command": "bash ~/.claude/hooks/lights-on-oracle-post.sh" }]
      },
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "bash ~/.claude/hooks/lights-on-oracle-post.sh" }]
      }
    ]
  }
}
```

### 3. (Optional) Configure the Anthropic API key

Only needed if you want the `oracle_ask` Haiku fallback for unroutable questions:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ORACLE_DIR` | `~/.project-oracle` | Root directory for all Oracle state |
| `ANTHROPIC_API_KEY` | — | Required only for `oracle_ask` Haiku fallback |

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Agent (Claude Code)                            │
│  Calls oracle_* tools or built-in tools         │
└──────────┬──────────────────────────────────────┘
           │ MCP stdio
┌──────────▼──────────────────────────────────────┐
│  Project Oracle Server (FastMCP)                │
│                                                 │
│  ┌────────────────────────────────────────────┐ │
│  │ Tools                                      │ │
│  │ oracle_read  → FileCache → full or delta   │ │
│  │ oracle_grep  → ripgrep wrapper             │ │
│  │ oracle_status → GitCache + StackInfo       │ │
│  │ oracle_run   → CommandCache (allowlisted)  │ │
│  │ oracle_ask   → intent router               │ │
│  │ oracle_forget → cache invalidation         │ │
│  └───────────────┬────────────────────────────┘ │
│                  │                               │
│  ┌───────────────▼────────────────────────────┐ │
│  │ Caches                                     │ │
│  │ FileCache    — zstd compression + SHA-256  │ │
│  │ GitCache     — branch, status, log deltas  │ │
│  │ CommandCache — allowlisted cmd results     │ │
│  └───────────────┬────────────────────────────┘ │
│                  │                               │
│  Storage: SQLite (WAL mode) per project          │
│  ~/.project-oracle/projects/<hash>/state.db      │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│  Claude Code Hooks (run in parallel)             │
│                                                  │
│  PreToolUse: AYLO nudges → "use oracle instead"  │
│  PostToolUse: passive ingest → feed to cache     │
└──────────────────────────────────────────────────┘
```

### Project detection

Oracle auto-detects project roots by walking up from file paths, looking for `.git`, `package.json`, `pyproject.toml`, `go.mod`, or `Cargo.toml`. Each detected project gets its own SQLite database. No configuration needed.

### Stack detection

Once a project root is found, Oracle identifies the language and package manager:

| Marker | Language | Package Manager Detection |
|--------|----------|--------------------------|
| `pyproject.toml` / `setup.py` | Python | `uv.lock` → uv, `poetry.lock` → poetry, else pip |
| `package.json` | Node.js | `pnpm-lock.yaml` → pnpm, `yarn.lock` → yarn, else npm |
| `go.mod` | Go | go |
| `Cargo.toml` | Rust | cargo |

### Cache invalidation

A filesystem watcher ([watchfiles](https://github.com/samuelcolvin/watchfiles), Rust-backed) monitors each project root:

- **File modified** → cached entry marked stale via `disk_sha256` update
- **`.git/HEAD` changed** → git state refreshed
- **File deleted** → removed from cache

The watcher filters out `.git`, `.venv`, `node_modules`, `__pycache__`, and `.mypy_cache`.

### Cache eviction

- Files not read in 30 days → evicted
- Command results older than 24 hours → evicted
- Per-project cache exceeds 50 MB → LRU eviction by `last_read`

### Data layout

```
~/.project-oracle/
├── registry.json           # project root → ID mapping
├── ingest/                 # file queue from PostToolUse hooks
│   └── *.json
└── projects/
    └── a1b2c3d4/           # SHA-256(project_root)[:8]
        ├── state.db        # SQLite — all cached state
        └── meta.json       # stack info, last session timestamp
```

## Chunkhound Integration

Oracle optionally delegates code understanding queries to [chunkhound](https://github.com/mikelane/chunkhound)'s AST-based semantic indexing:

```
Claude Code → (stdio) → Project Oracle → (stdio) → Chunkhound MCP
```

| Concern | Owner |
|---------|-------|
| AST parsing, semantic chunking, vector search | Chunkhound |
| File caching, delta diffing, agent interaction history | Oracle |
| "What imports X?" / "Find auth code" | Chunkhound |
| "Has this changed since I last looked?" | Oracle |

**Chunkhound understands code. Oracle understands the agent's relationship to the code.**

If chunkhound is not installed or fails to start, Oracle degrades gracefully — code understanding queries fall back to keyword-based grep, and unroutable questions fall back to Claude Haiku. The agent never sees an error.

## Development

### Setup

```bash
git clone https://github.com/mikelane/project-oracle.git
cd project-oracle
uv sync --all-groups
```

### Testing

The project uses strict TDD with multiple testing layers:

```bash
# Run all tests
uv run pytest

# Run with coverage (95% minimum enforced)
uv run coverage run --branch -m pytest
uv run coverage report --fail-under=95

# Run mutation testing
uv run pytest --gremlins src/oracle/cache/file_cache.py

# Run BDD scenarios
uv run behave

# Type checking
uv run mypy src/

# Linting
uv run ruff check src/ tests/
```

### Test categories

Tests follow [Google test size classification](https://testing.googleblog.com/2010/12/test-sizes.html):

| Size | Constraints | Marker |
|------|------------|--------|
| **Small** (default) | No I/O, no network, no sleep, single thread | None |
| **Medium** | Localhost only, threads OK | `@pytest.mark.medium` |
| **Large** | No constraints | `@pytest.mark.large` |

### Project structure

```
src/oracle/
├── server.py           # FastMCP entry point, tool definitions
├── project.py          # Project root + stack detection
├── registry.py         # Path → ProjectState mapping
├── intent.py           # Keyword-based intent classifier
├── ingest.py           # File queue processing from hooks
├── watcher.py          # FS watcher for cache invalidation
├── cache/
│   ├── file_cache.py   # zstd compression + delta diffing
│   ├── git_cache.py    # Git state snapshots + deltas
│   └── command_cache.py# Allowlisted command result caching
├── tools/
│   ├── read.py         # oracle_read handler
│   ├── grep.py         # oracle_grep handler
│   ├── status.py       # oracle_status handler
│   ├── run.py          # oracle_run handler
│   ├── ask.py          # oracle_ask intent router
│   └── forget.py       # oracle_forget handler
├── integrations/
│   └── chunkhound.py   # MCP client to chunkhound subprocess
└── storage/
    └── store.py        # SQLite persistence layer (WAL mode)

hooks/
├── lights-on-oracle-pre.sh   # PreToolUse AYLO nudges
└── lights-on-oracle-post.sh  # PostToolUse passive ingest

features/
├── file_caching.feature      # BDD: file read/delta behavior
├── git_state.feature         # BDD: git status caching
├── command_caching.feature   # BDD: command result caching
└── natural_language.feature  # BDD: oracle_ask routing
```

## License

MIT
