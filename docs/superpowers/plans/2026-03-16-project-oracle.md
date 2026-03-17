# Project Oracle Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stateful MCP server that caches file reads, command results, and git state per-project, returning compact deltas on repeat queries to reduce agent token usage.

**Architecture:** Smart proxy pattern — structured MCP tools (`oracle_read`, `oracle_grep`, `oracle_status`, `oracle_run`, `oracle_ask`, `oracle_forget`) backed by per-project SQLite persistence, FS watcher for cache invalidation, chunkhound integration for semantic code search, and AYLO hooks for agent nudging.

**Tech Stack:** Python 3.12+, uv, FastMCP, SQLite, watchfiles, zstandard, anthropic SDK (haiku fallback)

**Design doc:** `docs/plans/2026-03-15-project-oracle-design.md`

---

## Testing Standards (MANDATORY — applies to every task)

### Discipline

Every task follows **strict red-green-refactor**:
1. **RED** — Write the smallest failing test. Run it. Confirm it fails for the right reason.
2. **GREEN** — Write the minimum code to make that one test pass. No more.
3. **REFACTOR** — Clean up while green. Stay in scope.
4. **Triangulate** — Add a second example that forces generalization. Repeat from RED.

No production code exists without a failing test that demanded it.

### Naming Convention

```python
class DescribeFileCache:
    """Describe the file cache delta behavior."""

    def it_returns_full_content_on_first_read(self, tmp_project, tmp_path):
        ...

    def it_returns_no_changes_when_file_is_unchanged(self, tmp_project, tmp_path):
        ...

    def it_returns_delta_when_file_has_changed(self, tmp_project, tmp_path):
        ...
```

- Test **classes**: `Describe[ComponentName]` (PascalCase after Describe)
- Test **methods**: `it_[states what happens]` (snake_case, present tense, no "should")
- **No branching, loops, or conditionals in tests.** Use `@pytest.mark.parametrize` for multiple examples.

### Coverage Requirements

**Line and branch coverage** via `coverage`:

```bash
uv run coverage run --branch -m pytest
uv run coverage report --fail-under=95
uv run coverage html  # for inspection
```

- Minimum **95% line coverage**, **90% branch coverage** before any commit.
- `# pragma: no cover` is banned unless justified in a code comment explaining why.

### Mutation Coverage

**Mutation testing** via `pytest-gremlins`:

```bash
uv run pytest --gremlins src/oracle/cache/file_cache.py
```

- Target: **mutation score ≥ 80%** per module.
- Run after every GREEN phase to verify tests actually detect changes.
- Surviving mutants indicate weak assertions — add tests to kill them before proceeding.

### Test Pyramid Enforcement

**Google test sizes** via `pytest-test-categories`:

```python
# Small tests (default) — no I/O, no network, no sleep, single thread
def it_classifies_git_status_intent(self):
    assert classify_intent("what changed?") == Intent.GIT_STATUS

# Medium tests — localhost only, can sleep, threads OK
@pytest.mark.medium
def it_reads_file_from_disk_and_caches(self, tmp_project):
    ...

# Large tests — no constraints (real git repos, subprocesses, network)
@pytest.mark.large
def it_starts_chunkhound_subprocess(self):
    ...
```

Enforcement:
```bash
uv run pytest --enforce-categories --small-ratio=0.7 --medium-ratio=0.25 --large-ratio=0.05
```

At least **70% small**, **25% medium**, **5% large**. The pyramid must hold.

### BDD with Gherkin/Behave

Feature files live in `features/` with step definitions in `features/steps/`:

```gherkin
# features/file_caching.feature
Feature: File content caching

  Scenario: First read returns full content
    Given a project with file "src/main.py" containing "def hello(): pass"
    When the agent calls oracle_read on "src/main.py"
    Then the response contains "def hello(): pass"

  Scenario: Repeat read on unchanged file returns compact delta
    Given a project with file "src/main.py" containing "def hello(): pass"
    And the agent has already read "src/main.py"
    When the agent calls oracle_read on "src/main.py"
    Then the response contains "No changes"

  Scenario: Read after file modification returns diff
    Given a project with file "src/main.py" containing "def hello(): pass"
    And the agent has already read "src/main.py"
    And "src/main.py" is modified to "def hello(): return 42"
    When the agent calls oracle_read on "src/main.py"
    Then the response contains "changed"
```

Step definitions use the **declarative style** — describe WHAT, not HOW. No UI selectors, no implementation details in scenarios.

```bash
uv run behave features/
```

BDD scenarios are written **before** implementation tasks (BDD bootstrap). They must fail initially (RED). Implementation makes them pass (GREEN).

### Property-Based Testing with Hypothesis

For cache and data layers, write property tests alongside example tests:

```python
from hypothesis import given, strategies as st

class DescribeFileCacheProperties:
    @given(content=st.text(min_size=1, max_size=10000))
    def it_round_trips_any_content_through_compression(self, content, tmp_path):
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)
        # Write content to a temp file
        f = tmp_path / "test.py"
        f.write_text(content)
        # First read caches it
        result = cache.smart_read(str(f))
        assert result == content

    @given(old=st.text(min_size=1), new=st.text(min_size=1))
    def it_produces_valid_delta_for_any_content_pair(self, old, new, tmp_path):
        from oracle.cache.file_cache import _compute_delta
        delta = _compute_delta(old, new)
        assert isinstance(delta, str)
```

Target areas: file cache compression round-trips, delta computation, intent classification, ingest queue robustness.

### Fuzz Testing the Ingest Queue

The PostToolUse hook writes arbitrary JSON. The ingest queue must be bulletproof:

```python
from hypothesis import given, strategies as st

class DescribeIngestQueueFuzzing:
    @given(payload=st.binary(max_size=10000))
    def it_handles_arbitrary_binary_without_crashing(self, payload, tmp_path):
        queue_dir = tmp_path / "ingest"
        queue_dir.mkdir()
        (queue_dir / "fuzz.json").write_bytes(payload)
        entries = drain_ingest_queue(queue_dir)
        # Must not raise — returns empty or parsed entries
        assert isinstance(entries, list)

    @given(payload=st.text(max_size=5000))
    def it_handles_arbitrary_text_without_crashing(self, payload, tmp_path):
        queue_dir = tmp_path / "ingest"
        queue_dir.mkdir()
        (queue_dir / "fuzz.json").write_text(payload)
        entries = drain_ingest_queue(queue_dir)
        assert isinstance(entries, list)
```

### Contract Tests for MCP Protocol

Verify tool schemas match what Claude Code expects:

```python
class DescribeMCPContract:
    def it_exposes_all_required_tools(self):
        tool_names = {t.name for t in mcp._tool_manager.list_tools()}
        required = {"oracle_read", "oracle_grep", "oracle_status",
                     "oracle_run", "oracle_ask", "oracle_forget"}
        assert required == tool_names & required

    def it_oracle_read_accepts_path_string(self):
        schema = get_tool_schema("oracle_read")
        assert "path" in schema["properties"]
        assert schema["properties"]["path"]["type"] == "string"

    def it_oracle_run_accepts_list_of_strings(self):
        schema = get_tool_schema("oracle_run")
        assert schema["properties"]["commands"]["type"] == "array"
        assert schema["properties"]["commands"]["items"]["type"] == "string"
```

### Concurrent Access Testing

SQLite and the ingest queue can race:

```python
import asyncio

class DescribeConcurrentAccess:
    @pytest.mark.medium
    @pytest.mark.asyncio
    async def it_handles_simultaneous_reads_without_corruption(self, tmp_project, tmp_path):
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)
        file_path = str(tmp_project / "src" / "main.py")

        # First read to populate cache
        cache.smart_read(file_path)

        # 10 concurrent reads
        results = await asyncio.gather(
            *[asyncio.to_thread(cache.smart_read, file_path) for _ in range(10)]
        )
        assert all("No changes" in r for r in results)

    @pytest.mark.medium
    def it_handles_simultaneous_ingest_writes(self, tmp_path):
        import threading
        queue_dir = tmp_path / "ingest"
        queue_dir.mkdir()

        def write_entry(i):
            (queue_dir / f"{i:010d}.json").write_text(f'{{"tool_name": "Read", "id": {i}}}')

        threads = [threading.Thread(target=write_entry, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        entries = drain_ingest_queue(queue_dir)
        assert len(entries) == 50
```

### Benchmark Tests for Token Savings

Validate the design doc's claims:

```python
@pytest.mark.large
class DescribeTokenSavingsBenchmark:
    def it_saves_tokens_on_unchanged_file_reread(self, tmp_project, tmp_path):
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)
        file_path = str(tmp_project / "src" / "main.py")

        first_result = cache.smart_read(file_path)
        second_result, tokens_saved = cache.smart_read_with_stats(file_path)

        first_tokens = len(first_result) // 4  # rough token estimate
        assert tokens_saved >= first_tokens * 0.8  # at least 80% savings
        assert len(second_result) < len(first_result) * 0.1  # 90% smaller response

    def it_simulates_realistic_session_savings(self, tmp_project, tmp_path):
        """Simulate a 30-minute session and measure total savings."""
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)

        total_saved = 0
        files = [str(tmp_project / "src" / "main.py")]

        # 10 reads, 5 are re-reads
        for i in range(10):
            path = files[0] if i >= 5 else files[0]
            _, saved = cache.smart_read_with_stats(path)
            total_saved += saved

        assert total_saved > 0  # re-reads saved tokens

### Characterization Tests

Pin existing behavior before refactoring:

```python
class DescribeFileCacheCharacterization:
    def it_produces_stable_delta_format(self, tmp_project, tmp_path):
        """Golden-file test: pin the exact delta format."""
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)
        file_path = tmp_project / "src" / "main.py"

        cache.smart_read(str(file_path))
        file_path.write_text("def hello():\n    return 'changed'\n")
        result = cache.smart_read(str(file_path))

        # Pin the format — update this if you intentionally change delta output
        assert result.startswith("Changed since last read:")
        assert "@@ " in result  # unified diff format
```

### Pre-Commit Quality Gate

Every commit must pass:

```bash
# Run in this exact order
uv run pytest --enforce-categories --small-ratio=0.7 --medium-ratio=0.25 --large-ratio=0.05
uv run coverage run --branch -m pytest
uv run coverage report --fail-under=95
uv run pytest --gremlins src/oracle/  # mutation testing
uv run behave features/               # BDD scenarios
uv run ruff check src/ tests/
uv run mypy src/
```

Then run `/review-pr` before finalizing any commit.

---

## Updated Dependencies

```toml
[project]
name = "project-oracle"
version = "0.1.0"
description = "Stateful MCP server that reduces agent token usage via caching and delta diffing"
requires-python = ">=3.12"
dependencies = [
    "mcp[cli]>=1.0",
    "anthropic>=0.40",
    "zstandard>=0.23",
    "watchfiles>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-mock>=3.14",
    "pytest-gremlins>=1.5",
    "pytest-test-categories>=1.2",
    "coverage[toml]>=7.0",
    "hypothesis>=6.100",
    "behave>=1.2",
    "ruff>=0.9",
    "mypy>=1.14",
]

[project.scripts]
project-oracle = "oracle.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.coverage.run]
branch = true
source = ["oracle"]

[tool.coverage.report]
fail_under = 95
show_missing = true
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
warn_return_any = true
warn_unused_configs = true
```

---

## File Structure

```
project-oracle/
├── pyproject.toml
├── src/
│   └── oracle/
│       ├── __init__.py
│       ├── server.py
│       ├── project.py
│       ├── registry.py
│       ├── intent.py
│       ├── watcher.py
│       ├── ingest.py
│       ├── cache/
│       │   ├── __init__.py
│       │   ├── file_cache.py
│       │   ├── git_cache.py
│       │   └── command_cache.py
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── read.py
│       │   ├── grep.py
│       │   ├── status.py
│       │   ├── run.py
│       │   ├── ask.py
│       │   └── forget.py
│       ├── integrations/
│       │   ├── __init__.py
│       │   ├── chunkhound.py
│       │   └── git.py
│       └── storage/
│           ├── __init__.py
│           └── store.py
├── features/
│   ├── file_caching.feature
│   ├── git_state.feature
│   ├── command_caching.feature
│   ├── natural_language.feature
│   ├── environment.py
│   └── steps/
│       ├── file_steps.py
│       ├── git_steps.py
│       ├── command_steps.py
│       └── ask_steps.py
├── hooks/
│   ├── lights-on-oracle-pre.sh
│   └── lights-on-oracle-post.sh
└── tests/
    ├── conftest.py
    ├── test_store.py
    ├── test_project.py
    ├── test_registry.py
    ├── test_file_cache.py
    ├── test_file_cache_properties.py
    ├── test_git_cache.py
    ├── test_command_cache.py
    ├── test_read.py
    ├── test_grep.py
    ├── test_status.py
    ├── test_run.py
    ├── test_ask.py
    ├── test_forget.py
    ├── test_intent.py
    ├── test_chunkhound.py
    ├── test_watcher.py
    ├── test_ingest.py
    ├── test_ingest_fuzz.py
    ├── test_concurrent.py
    ├── test_contract.py
    ├── test_benchmark.py
    ├── test_characterization.py
    └── test_server.py
```

---

## Chunk 0: BDD Bootstrap (Gherkin scenarios — must fail before implementation)

### Task 0: Write Gherkin feature files and behave scaffolding

**Files:**
- Create: `features/file_caching.feature`
- Create: `features/git_state.feature`
- Create: `features/command_caching.feature`
- Create: `features/natural_language.feature`
- Create: `features/environment.py`
- Create: `features/steps/file_steps.py` (stubs only)
- Create: `features/steps/git_steps.py` (stubs only)
- Create: `features/steps/command_steps.py` (stubs only)
- Create: `features/steps/ask_steps.py` (stubs only)

- [ ] **Step 1: Create feature files**

`features/file_caching.feature`:
```gherkin
Feature: File content caching
  The oracle caches file contents and returns compact deltas on repeat reads,
  saving the agent from re-reading unchanged files.

  Scenario: First read returns full file content
    Given a project with file "src/main.py" containing "def hello(): pass"
    When the agent calls oracle_read on "src/main.py"
    Then the response contains "def hello(): pass"

  Scenario: Repeat read on unchanged file returns no-change notice
    Given a project with file "src/main.py" containing "def hello(): pass"
    And the agent has already read "src/main.py"
    When the agent calls oracle_read on "src/main.py"
    Then the response contains "No changes"

  Scenario: Read after file modification returns delta
    Given a project with file "src/main.py" containing "def hello(): pass"
    And the agent has already read "src/main.py"
    And "src/main.py" is modified to contain "def hello(): return 42"
    When the agent calls oracle_read on "src/main.py"
    Then the response contains "changed" ignoring case

  Scenario: Forget clears cache and forces full re-read
    Given a project with file "src/main.py" containing "def hello(): pass"
    And the agent has already read "src/main.py"
    When the agent calls oracle_forget on "src/main.py"
    And the agent calls oracle_read on "src/main.py"
    Then the response contains "def hello(): pass"

  Scenario: Reading nonexistent file returns error
    Given a project exists
    When the agent calls oracle_read on "nonexistent.py"
    Then the response contains "not found" ignoring case
```

`features/git_state.feature`:
```gherkin
Feature: Git state caching
  The oracle tracks git branch, status, and recent commits,
  returning deltas when the state changes.

  Scenario: Status shows current branch and clean state
    Given a git project on branch "main"
    When the agent calls oracle_status
    Then the response contains "main"
    And the response contains "clean"

  Scenario: Status shows dirty files after modification
    Given a git project on branch "main"
    And file "src/app.py" is modified in the working tree
    When the agent calls oracle_status
    Then the response contains "app.py"
```

`features/command_caching.feature`:
```gherkin
Feature: Command result caching
  The oracle runs allowed commands, caches results, and returns
  cached output when source files haven't changed.

  Scenario: Run an allowed command and get results
    Given a project exists
    When the agent calls oracle_run with "echo hello"
    Then the response contains "hello"

  Scenario: Disallowed command is rejected
    Given a project exists
    When the agent calls oracle_run with "rm -rf /"
    Then the response contains "not allowed" ignoring case

  Scenario: Cached result returned when sources unchanged
    Given a project exists
    And the agent has run "echo hello" before
    And no source files have changed
    When the agent calls oracle_run with "echo hello"
    Then the response contains "cached" ignoring case
```

`features/natural_language.feature`:
```gherkin
Feature: Natural language queries
  The oracle routes plain English questions to the appropriate handler
  without consuming LLM tokens for routing.

  Scenario: Git question routes to git cache
    Given a git project on branch "main"
    When the agent asks "what changed?"
    Then the response is about git status

  Scenario: Test question routes to command cache
    Given a project exists
    When the agent asks "are tests passing?"
    Then the response is about test status

  Scenario: Structure question routes to project overview
    Given a project with a Python stack
    When the agent asks "what's the project structure?"
    Then the response contains "python" ignoring case
```

- [ ] **Step 2: Create environment.py and stub step files**

`features/environment.py`:
```python
"""Behave environment setup — creates temp directories for each scenario."""
import shutil
import tempfile
from pathlib import Path


def before_scenario(context, scenario):
    context.tmp_dir = Path(tempfile.mkdtemp())
    context.project_root = None
    context.last_response = None


def after_scenario(context, scenario):
    shutil.rmtree(context.tmp_dir, ignore_errors=True)
```

`features/steps/file_steps.py` (stubs that raise NotImplementedError):
```python
from behave import given, when, then


@given('a project with file "{path}" containing "{content}"')
def step_project_with_file(context, path, content):
    raise NotImplementedError("Implement after cache layer exists")


@given("a project exists")
def step_project_exists(context):
    raise NotImplementedError("Implement after project detection exists")


@given('the agent has already read "{path}"')
def step_agent_has_read(context, path):
    raise NotImplementedError("Implement after oracle_read exists")


@given('"{path}" is modified to contain "{content}"')
def step_file_modified(context, path, content):
    raise NotImplementedError("Implement after file cache exists")


@when('the agent calls oracle_read on "{path}"')
def step_oracle_read(context, path):
    raise NotImplementedError("Implement after oracle_read exists")


@when('the agent calls oracle_forget on "{path}"')
def step_oracle_forget(context, path):
    raise NotImplementedError("Implement after oracle_forget exists")


@then('the response contains "{text}"')
def step_response_contains(context, text):
    assert context.last_response is not None
    assert text in context.last_response


@then('the response contains "{text}" ignoring case')
def step_response_contains_case_insensitive(context, text):
    assert context.last_response is not None
    assert text.lower() in context.last_response.lower()
```

`features/steps/git_steps.py`, `features/steps/command_steps.py`, `features/steps/ask_steps.py` — similarly stubbed with `raise NotImplementedError`.

- [ ] **Step 3: Run behave to confirm all scenarios fail**

Run: `uv run behave features/ --no-capture`
Expected: All scenarios FAIL with NotImplementedError — this is the RED state.

- [ ] **Step 4: Commit the BDD bootstrap**

```bash
git add features/
git commit -m "test: BDD bootstrap — failing Gherkin scenarios for all oracle behaviors

All scenarios fail with NotImplementedError. Implementation will make them pass.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Chunk 1: Foundation (Scaffolding, Storage, Project Detection)

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/oracle/__init__.py`
- Create: `src/oracle/cache/__init__.py`
- Create: `src/oracle/tools/__init__.py`
- Create: `src/oracle/integrations/__init__.py`
- Create: `src/oracle/storage/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create pyproject.toml** (use the Updated Dependencies section above)

- [ ] **Step 2: Create package init files** — empty `__init__.py` in all packages

- [ ] **Step 3: Create tests/conftest.py with shared fixtures**

```python
from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    project = tmp_path / "test-project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("def hello():\n    return 'world'\n")
    (project / "pyproject.toml").write_text('[project]\nname = "test"\n')
    return project


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    project = tmp_path / "git-project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=project, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=project, capture_output=True, check=True,
    )
    (project / "file.py").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=project, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial", "--no-gpg-sign"],
        cwd=project, capture_output=True, check=True,
    )
    return project


@pytest.fixture
def in_memory_db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def oracle_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".project-oracle"
    d.mkdir()
    (d / "projects").mkdir()
    (d / "ingest").mkdir()
    return d
```

- [ ] **Step 4: Install dependencies and verify**

```bash
cd /path/to/worktree && uv sync --all-groups
uv run pytest --co -q  # should show "no tests ran"
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/ tests/conftest.py
git commit -m "feat: project scaffolding with dependencies and test fixtures

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: SQLite storage layer

(Same as original plan Task 2, but with Describe/it_ naming. Full code in original plan.)

**Key change — test class naming:**

```python
class DescribeOracleStoreInit:
    def it_creates_all_tables_on_init(self, tmp_path): ...
    def it_creates_db_file_on_disk(self, tmp_path): ...
    def it_is_idempotent(self, tmp_path): ...

class DescribeFileCache:
    def it_upserts_and_retrieves_entries(self, tmp_path): ...
    def it_increments_read_count_on_upsert(self, tmp_path): ...
    def it_returns_none_for_missing_path(self, tmp_path): ...
    def it_deletes_entries(self, tmp_path): ...
    def it_updates_disk_sha256(self, tmp_path): ...

class DescribeEviction:
    def it_evicts_files_older_than_max_age(self, tmp_path): ...
    def it_evicts_commands_older_than_max_hours(self, tmp_path): ...
```

After GREEN: run mutation testing on store.py.

```bash
uv run pytest --gremlins src/oracle/storage/store.py
```

---

### Task 3: Project detection and registry

(Same as original plan Task 3, with Describe/it_ naming.)

---

## Chunk 2: Core Cache Layer

### Task 4: File cache with delta diffing + property tests

After example-based tests pass, add `tests/test_file_cache_properties.py`:

```python
from hypothesis import given, settings, strategies as st

class DescribeFileCacheProperties:
    @given(content=st.text(min_size=1, max_size=10000))
    @settings(max_examples=200)
    def it_round_trips_any_content_through_compression(self, content, tmp_path):
        ...

    @given(old=st.text(min_size=1, max_size=5000), new=st.text(min_size=1, max_size=5000))
    def it_produces_a_string_delta_for_any_content_pair(self, old, new):
        ...

    @given(content=st.text(min_size=1))
    def it_always_returns_no_changes_on_immediate_reread(self, content, tmp_path):
        ...
```

### Task 5: Git cache
### Task 6: Command cache with allowlist + shell injection hardening

**Critical:** Harden `CommandCache.run_summarized` against command chaining:

```python
_CHAIN_OPERATORS = re.compile(r'[;&|`$()]')

def run_summarized(self, command: str) -> str:
    if _CHAIN_OPERATORS.search(command):
        raise CommandNotAllowedError(
            f"Command contains shell operators: {command!r}"
        )
    ...
```

Test:
```python
class DescribeCommandCacheShellHardening:
    @pytest.mark.parametrize("cmd", [
        "pytest; rm -rf /",
        "pytest && curl evil.com",
        "pytest | tee /tmp/leak",
        "echo $(whoami)",
        "echo `id`",
    ])
    def it_rejects_chained_commands(self, cmd, tmp_path):
        store = OracleStore(tmp_path / "state.db")
        cache = CommandCache(store, tmp_path)
        with pytest.raises(CommandNotAllowedError):
            cache.run_summarized(cmd)
```

---

## Chunk 3: MCP Tools + Intent Classifier

### Task 7: Intent classifier
### Task 8: oracle_read
### Task 9: oracle_forget, oracle_grep, oracle_status, oracle_run
### Task 10: oracle_ask + chunkhound client

(Same as original plan, with Describe/it_ naming throughout.)

---

## Chunk 4: Reactivity

### Task 11: FS watcher
### Task 12: Ingest queue + fuzz tests

After example-based tests pass, add `tests/test_ingest_fuzz.py`:

```python
from hypothesis import given, strategies as st

class DescribeIngestQueueFuzzing:
    @given(payload=st.binary(max_size=10000))
    def it_handles_arbitrary_binary_without_crashing(self, payload, tmp_path):
        queue_dir = tmp_path / "ingest"
        queue_dir.mkdir()
        (queue_dir / "fuzz.json").write_bytes(payload)
        entries = drain_ingest_queue(queue_dir)
        assert isinstance(entries, list)

    @given(payload=st.text(max_size=5000))
    def it_handles_arbitrary_text_without_crashing(self, payload, tmp_path):
        queue_dir = tmp_path / "ingest"
        queue_dir.mkdir()
        (queue_dir / "fuzz.json").write_text(payload)
        entries = drain_ingest_queue(queue_dir)
        assert isinstance(entries, list)
```

---

## Chunk 5: Server + Hooks + Cross-Cutting Tests

### Task 13: FastMCP server entry point
### Task 14: AYLO hooks

### Task 15: Contract tests

`tests/test_contract.py`:
```python
from oracle.server import mcp

class DescribeMCPContract:
    def it_exposes_exactly_six_tools(self):
        tools = mcp._tool_manager.list_tools()
        assert len(tools) == 6

    def it_exposes_all_required_tool_names(self):
        tool_names = {t.name for t in mcp._tool_manager.list_tools()}
        required = {"oracle_read", "oracle_grep", "oracle_status",
                     "oracle_run", "oracle_ask", "oracle_forget"}
        assert required <= tool_names

    def it_oracle_read_requires_path_parameter(self):
        # Verify the tool schema matches the MCP protocol contract
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        read_tool = tools["oracle_read"]
        assert "path" in read_tool.inputSchema["properties"]

    def it_oracle_run_requires_commands_list(self):
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}
        run_tool = tools["oracle_run"]
        assert run_tool.inputSchema["properties"]["commands"]["type"] == "array"
```

### Task 16: Concurrent access tests

`tests/test_concurrent.py` — tests from the Testing Standards section above.

### Task 17: Benchmark tests

`tests/test_benchmark.py` — tests from the Testing Standards section above.

### Task 18: Characterization tests

`tests/test_characterization.py` — golden-file tests pinning delta format and status output format.

### Task 19: Wire up BDD step definitions

Update all `features/steps/*.py` to call real oracle code. Run `behave` — all scenarios should now pass.

```bash
uv run behave features/ --no-capture
```

### Task 20: Full quality gate

- [ ] Run the complete quality gate:

```bash
uv run pytest --enforce-categories --small-ratio=0.7 --medium-ratio=0.25 --large-ratio=0.05
uv run coverage run --branch -m pytest
uv run coverage report --fail-under=95
uv run pytest --gremlins src/oracle/
uv run behave features/
uv run ruff check src/ tests/
uv run mypy src/
```

- [ ] Run `/review-pr` on the full diff

- [ ] All green → ready for release

---

## Summary

| Chunk | Tasks | Delivers |
|-------|-------|----------|
| **0: BDD Bootstrap** | 0 | Failing Gherkin scenarios for all behaviors |
| **1: Foundation** | 1-3 | Scaffolding, SQLite store, project detection, registry |
| **2: Core Cache** | 4-6 | File cache + properties, git cache, command cache + hardening |
| **3: MCP Tools** | 7-10 | Intent classifier, all 6 tool handlers |
| **4: Reactivity** | 11-12 | FS watcher, ingest queue + fuzz tests |
| **5: Server + Cross-cutting** | 13-20 | Server, hooks, contract/concurrent/benchmark/characterization tests, BDD wiring, quality gate |

20 tasks. Strict TDD with triangulation. 95% line coverage, 80%+ mutation score, 70/25/5 test pyramid, BDD scenarios, property-based tests, fuzz tests, contract tests, concurrency tests, benchmarks, and characterization tests. `/review-pr` before every commit.
