"""Tests for process_ingest — bridges the ingest queue into the server's cache layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oracle.ingest_bridge import process_ingest
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
        self._enqueue(oracle_dir, {
            "tool_name": "Read",
            "tool_input": {"file_path": file_path},
        })

        registry = ProjectRegistry(oracle_dir)
        # Pre-register project so registry.for_path works
        project = registry.for_path(project_dir / "hello.py")
        assert project is not None
        assert project.store is not None
        project.file_cache = FileCache(project.store)

        def ensure_caches(p: ProjectState) -> None:
            if p.file_cache is None and p.store is not None:
                p.file_cache = FileCache(p.store)

        count = process_ingest(registry, oracle_dir, ensure_caches)

        assert count == 1
        # Verify the cache was populated — second read returns delta
        result = project.file_cache.smart_read(file_path)
        assert "No changes since last read" in result

    def it_ignores_non_read_entries(
        self, tmp_path: Path, oracle_dir: Path, project_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry

        self._enqueue(oracle_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        })
        self._enqueue(oracle_dir, {
            "tool_name": "Grep",
            "tool_input": {"pattern": "hello"},
        })

        registry = ProjectRegistry(oracle_dir)

        count = process_ingest(registry, oracle_dir, lambda p: None)

        assert count == 0

    def it_handles_missing_file_gracefully(
        self, tmp_path: Path, oracle_dir: Path, project_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry

        nonexistent = str(project_dir / "does_not_exist.py")
        self._enqueue(oracle_dir, {
            "tool_name": "Read",
            "tool_input": {"file_path": nonexistent},
        })

        registry = ProjectRegistry(oracle_dir)

        count = process_ingest(registry, oracle_dir, lambda p: None)

        assert count == 0

    def it_handles_empty_queue(
        self, tmp_path: Path, oracle_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry

        registry = ProjectRegistry(oracle_dir)

        count = process_ingest(registry, oracle_dir, lambda p: None)

        assert count == 0

    def it_skips_read_entry_with_no_file_path(
        self, tmp_path: Path, oracle_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry

        self._enqueue(oracle_dir, {
            "tool_name": "Read",
            "tool_input": {},
        })

        registry = ProjectRegistry(oracle_dir)

        count = process_ingest(registry, oracle_dir, lambda p: None)

        assert count == 0

    def it_skips_file_with_no_project_detected(
        self, tmp_path: Path, oracle_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry

        # Create a file outside any project (no .git or project markers)
        bare_dir = tmp_path / "bare"
        bare_dir.mkdir()
        orphan = bare_dir / "orphan.py"
        orphan.write_text("x = 1\n")

        self._enqueue(oracle_dir, {
            "tool_name": "Read",
            "tool_input": {"file_path": str(orphan)},
        })

        registry = ProjectRegistry(oracle_dir)

        count = process_ingest(registry, oracle_dir, lambda p: None)

        assert count == 0

    def it_skips_when_ensure_caches_does_not_wire_file_cache(
        self, tmp_path: Path, oracle_dir: Path, project_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry

        file_path = str(project_dir / "hello.py")
        self._enqueue(oracle_dir, {
            "tool_name": "Read",
            "tool_input": {"file_path": file_path},
        })

        registry = ProjectRegistry(oracle_dir)

        # ensure_caches that deliberately does nothing — file_cache stays None
        count = process_ingest(registry, oracle_dir, lambda p: None)

        assert count == 0
