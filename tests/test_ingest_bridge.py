"""Tests for process_ingest — bridges the ingest queue into the server's cache layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oracle.ingest_bridge import IngestResult, process_ingest
from oracle.project import ProjectState


@pytest.mark.medium
class DescribeProcessIngest:
    @pytest.fixture
    def oracle_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / ".project-oracle"
        d.mkdir()
        (d / "projects").mkdir()
        (d / "ingest").mkdir()
        return d

    @pytest.fixture
    def project_dir(self, tmp_path: Path) -> Path:
        project = tmp_path / "test-project"
        project.mkdir()
        (project / ".git").mkdir()
        (project / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (project / "hello.py").write_text("print('hello world')\n")
        return project

    def _enqueue(self, oracle_dir: Path, entry: dict) -> None:  # noqa: ANN001
        """Write an entry into the ingest queue directory."""
        queue_dir = oracle_dir / "ingest"
        queue_dir.mkdir(exist_ok=True)
        # Use a unique filename
        existing = list(queue_dir.glob("*.json"))
        idx = len(existing) + 1
        (queue_dir / f"{idx:06d}.json").write_text(json.dumps(entry))

    def it_populates_file_cache_from_read_entry(
        self, tmp_path: Path, oracle_dir: Path, project_dir: Path
    ) -> None:
        from oracle.cache.file_cache import FileCache
        from oracle.registry import ProjectRegistry

        file_path = str(project_dir / "hello.py")
        self._enqueue(
            oracle_dir,
            {
                "session_id": "sess-test",
                "cwd": str(project_dir),
                "tool_name": "Read",
                "tool_input": {"file_path": file_path},
            },
        )

        registry = ProjectRegistry(oracle_dir)
        # Pre-register project so registry.for_path works
        project = registry.for_path(project_dir / "hello.py")
        assert project is not None
        assert project.store is not None
        project.file_cache = FileCache(project.store)

        def ensure_caches(p: ProjectState) -> None:
            if p.file_cache is None and p.store is not None:
                p.file_cache = FileCache(p.store)

        result = process_ingest(registry, oracle_dir, ensure_caches)

        assert isinstance(result, IngestResult)
        assert result.cache_populated == 1
        # Verify the cache was populated — second read returns delta
        cached = project.file_cache.smart_read(file_path)
        assert "No changes since last read" in cached

    def it_returns_ingest_result_for_non_read_entries(
        self, tmp_path: Path, oracle_dir: Path, project_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry

        self._enqueue(
            oracle_dir,
            {
                "session_id": "sess-test",
                "cwd": str(project_dir),
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
            },
        )
        self._enqueue(
            oracle_dir,
            {
                "session_id": "sess-test",
                "cwd": str(project_dir),
                "tool_name": "Grep",
                "tool_input": {"pattern": "hello"},
            },
        )

        registry = ProjectRegistry(oracle_dir)
        # Pre-register project so for_path works via cwd
        registry.for_path(project_dir)

        result = process_ingest(registry, oracle_dir, lambda p: None)

        assert isinstance(result, IngestResult)
        assert result.cache_populated == 0
        assert result.builtin_logged == 2

    def it_handles_missing_file_gracefully(
        self, tmp_path: Path, oracle_dir: Path, project_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry

        nonexistent = str(project_dir / "does_not_exist.py")
        self._enqueue(
            oracle_dir,
            {
                "session_id": "sess-test",
                "cwd": str(project_dir),
                "tool_name": "Read",
                "tool_input": {"file_path": nonexistent},
            },
        )

        registry = ProjectRegistry(oracle_dir)

        result = process_ingest(registry, oracle_dir, lambda p: None)

        assert result.cache_populated == 0

    def it_handles_empty_queue(self, tmp_path: Path, oracle_dir: Path) -> None:
        from oracle.registry import ProjectRegistry

        registry = ProjectRegistry(oracle_dir)

        result = process_ingest(registry, oracle_dir, lambda p: None)

        assert isinstance(result, IngestResult)
        assert result.cache_populated == 0
        assert result.builtin_logged == 0

    def it_skips_read_entry_with_no_file_path(self, tmp_path: Path, oracle_dir: Path) -> None:
        from oracle.registry import ProjectRegistry

        self._enqueue(
            oracle_dir,
            {
                "session_id": "sess-test",
                "cwd": "/tmp",
                "tool_name": "Read",
                "tool_input": {},
            },
        )

        registry = ProjectRegistry(oracle_dir)

        result = process_ingest(registry, oracle_dir, lambda p: None)

        assert result.cache_populated == 0

    def it_skips_file_with_no_project_detected(self, tmp_path: Path, oracle_dir: Path) -> None:
        from oracle.registry import ProjectRegistry

        # Create a file outside any project (no .git or project markers)
        bare_dir = tmp_path / "bare"
        bare_dir.mkdir()
        orphan = bare_dir / "orphan.py"
        orphan.write_text("x = 1\n")

        self._enqueue(
            oracle_dir,
            {
                "session_id": "sess-test",
                "cwd": str(bare_dir),
                "tool_name": "Read",
                "tool_input": {"file_path": str(orphan)},
            },
        )

        registry = ProjectRegistry(oracle_dir)

        result = process_ingest(registry, oracle_dir, lambda p: None)

        assert result.cache_populated == 0

    def it_skips_when_ensure_caches_does_not_wire_file_cache(
        self, tmp_path: Path, oracle_dir: Path, project_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry

        file_path = str(project_dir / "hello.py")
        self._enqueue(
            oracle_dir,
            {
                "session_id": "sess-test",
                "cwd": str(project_dir),
                "tool_name": "Read",
                "tool_input": {"file_path": file_path},
            },
        )

        registry = ProjectRegistry(oracle_dir)

        # ensure_caches that deliberately does nothing — file_cache stays None
        result = process_ingest(registry, oracle_dir, lambda p: None)

        assert result.cache_populated == 0


@pytest.mark.medium
class DescribeBuiltinToolLogging:
    @pytest.fixture
    def oracle_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / ".project-oracle"
        d.mkdir()
        (d / "projects").mkdir()
        (d / "ingest").mkdir()
        return d

    @pytest.fixture
    def project_dir(self, tmp_path: Path) -> Path:
        project = tmp_path / "test-project"
        project.mkdir()
        (project / ".git").mkdir()
        (project / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (project / "hello.py").write_text("print('hello world')\n")
        return project

    def _enqueue(self, oracle_dir: Path, entry: dict) -> None:  # noqa: ANN001
        queue_dir = oracle_dir / "ingest"
        queue_dir.mkdir(exist_ok=True)
        existing = list(queue_dir.glob("*.json"))
        idx = len(existing) + 1
        (queue_dir / f"{idx:06d}.json").write_text(json.dumps(entry))

    def it_logs_bash_entry_to_agent_log(
        self, tmp_path: Path, oracle_dir: Path, project_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry

        self._enqueue(
            oracle_dir,
            {
                "session_id": "sess-log-test",
                "cwd": str(project_dir),
                "tool_name": "Bash",
                "tool_input": {"command": "ls -la"},
            },
        )

        registry = ProjectRegistry(oracle_dir)
        registry.for_path(project_dir)

        result = process_ingest(registry, oracle_dir, lambda p: None)

        assert result.builtin_logged == 1

        # Verify the entry was written to agent_log in the store
        project = registry.for_path(project_dir)
        assert project is not None
        assert project.store is not None
        row = project.store._conn.execute(
            "SELECT tool_name, cache_hit, tokens_saved FROM agent_log WHERE session_id = ?",
            ("sess-log-test",),
        ).fetchone()
        assert row is not None
        assert row["tool_name"] == "builtin_bash"
        assert row["cache_hit"] == 0
        assert row["tokens_saved"] == 0

    def it_logs_grep_entry_to_agent_log(
        self, tmp_path: Path, oracle_dir: Path, project_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry

        self._enqueue(
            oracle_dir,
            {
                "session_id": "sess-log-test",
                "cwd": str(project_dir),
                "tool_name": "Grep",
                "tool_input": {"pattern": "hello"},
            },
        )

        registry = ProjectRegistry(oracle_dir)
        registry.for_path(project_dir)

        result = process_ingest(registry, oracle_dir, lambda p: None)

        assert result.builtin_logged == 1

        project = registry.for_path(project_dir)
        assert project is not None
        assert project.store is not None
        row = project.store._conn.execute(
            "SELECT tool_name FROM agent_log WHERE session_id = ?",
            ("sess-log-test",),
        ).fetchone()
        assert row is not None
        assert row["tool_name"] == "builtin_grep"

    def it_logs_read_entry_to_agent_log(
        self, tmp_path: Path, oracle_dir: Path, project_dir: Path
    ) -> None:
        from oracle.cache.file_cache import FileCache
        from oracle.registry import ProjectRegistry

        file_path = str(project_dir / "hello.py")
        self._enqueue(
            oracle_dir,
            {
                "session_id": "sess-log-test",
                "cwd": str(project_dir),
                "tool_name": "Read",
                "tool_input": {"file_path": file_path},
            },
        )

        registry = ProjectRegistry(oracle_dir)
        project = registry.for_path(project_dir / "hello.py")
        assert project is not None
        assert project.store is not None
        project.file_cache = FileCache(project.store)

        def ensure_caches(p: ProjectState) -> None:
            if p.file_cache is None and p.store is not None:
                p.file_cache = FileCache(p.store)

        result = process_ingest(registry, oracle_dir, ensure_caches)

        assert result.builtin_logged == 1
        assert result.cache_populated == 1

        row = project.store._conn.execute(
            "SELECT tool_name FROM agent_log WHERE session_id = ?",
            ("sess-log-test",),
        ).fetchone()
        assert row is not None
        assert row["tool_name"] == "builtin_read"

    def it_skips_entry_with_no_session_id(
        self, tmp_path: Path, oracle_dir: Path, project_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry

        self._enqueue(
            oracle_dir,
            {
                "cwd": str(project_dir),
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
            },
        )

        registry = ProjectRegistry(oracle_dir)

        result = process_ingest(registry, oracle_dir, lambda p: None)

        assert result.builtin_logged == 0
        assert result.cache_populated == 0

    def it_skips_entry_with_unmapped_tool_name(
        self, tmp_path: Path, oracle_dir: Path, project_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry

        self._enqueue(
            oracle_dir,
            {
                "session_id": "sess-test",
                "cwd": str(project_dir),
                "tool_name": "Glob",
                "tool_input": {"pattern": "*.py"},
            },
        )

        registry = ProjectRegistry(oracle_dir)

        result = process_ingest(registry, oracle_dir, lambda p: None)

        assert result.builtin_logged == 0

    def it_skips_builtin_logging_when_no_project_resolved_from_cwd(
        self, tmp_path: Path, oracle_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry

        # bare_dir has no project markers
        bare_dir = tmp_path / "bare"
        bare_dir.mkdir()

        self._enqueue(
            oracle_dir,
            {
                "session_id": "sess-test",
                "cwd": str(bare_dir),
                "tool_name": "Bash",
                "tool_input": {"command": "echo hi"},
            },
        )

        registry = ProjectRegistry(oracle_dir)

        result = process_ingest(registry, oracle_dir, lambda p: None)

        assert result.builtin_logged == 0
