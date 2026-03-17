"""End-to-end integration tests for Project Oracle pipelines."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from oracle.cache.file_cache import FileCache
from oracle.ingest_bridge import process_ingest
from oracle.project import ProjectState
from oracle.registry import ProjectRegistry


@pytest.mark.medium
class DescribeLoggingPipeline:
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
        return project

    @pytest.fixture
    def registry(self, oracle_dir: Path) -> ProjectRegistry:
        return ProjectRegistry(oracle_dir)

    def it_logs_read_and_surfaces_in_stats(
        self,
        project_dir: Path,
        registry: ProjectRegistry,
    ) -> None:
        # Create a real file in the project
        target = project_dir / "example.py"
        target.write_text("def greet():\n    return 'hello'\n")

        # Wire up project and caches
        project = registry.for_path(target)
        assert project is not None
        assert project.store is not None
        project.file_cache = FileCache(project.store)

        file_path = str(target)

        # First read: cache miss, tokens_saved == 0
        response1, tokens_saved1 = project.file_cache.smart_read_with_stats(file_path)
        assert tokens_saved1 == 0

        # Second read: cache hit, tokens_saved > 0 (file unchanged)
        response2, tokens_saved2 = project.file_cache.smart_read_with_stats(file_path)
        assert tokens_saved2 > 0

        # Log both interactions
        session_id = project.session_id
        now = int(time.time())
        project.store.log_interaction(
            session_id, "oracle_read", file_path, tokens_saved1 > 0, tokens_saved1, now
        )
        project.store.log_interaction(
            session_id, "oracle_read", file_path, tokens_saved2 > 0, tokens_saved2, now
        )

        # Verify aggregated stats
        stats = project.store.get_session_stats(session_id)
        assert stats["total_cache_hits"] == 1
        assert stats["total_tokens_saved"] > 0
        assert stats["total_tokens_saved"] == tokens_saved2

    def it_logs_across_multiple_tools(
        self,
        project_dir: Path,
        registry: ProjectRegistry,
    ) -> None:
        # Wire up project
        target = project_dir / "multi.py"
        target.write_text("x = 1\n")
        project = registry.for_path(target)
        assert project is not None
        assert project.store is not None

        session_id = project.session_id
        now = int(time.time())

        # Log 3 interactions with different tool_names
        project.store.log_interaction(
            session_id, "oracle_read", "src/main.py", True, 500, now
        )
        project.store.log_interaction(
            session_id, "oracle_run", "git status", False, 0, now
        )
        project.store.log_interaction(
            session_id, "oracle_grep", "pattern", True, 200, now
        )

        stats = project.store.get_session_stats(session_id)
        assert stats["total_cache_hits"] == 2
        assert stats["total_tokens_saved"] == 700


@pytest.mark.medium
class DescribeIngestPipeline:
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
        return project

    @pytest.fixture
    def registry(self, oracle_dir: Path) -> ProjectRegistry:
        return ProjectRegistry(oracle_dir)

    @staticmethod
    def _ensure_caches(project: ProjectState) -> None:
        """Wire up FileCache if not already present."""
        if project.file_cache is None and project.store is not None:
            project.file_cache = FileCache(project.store)

    @staticmethod
    def _enqueue(oracle_dir: Path, entry: dict) -> None:  # noqa: ANN001
        """Write an entry into the ingest queue directory."""
        queue_dir = oracle_dir / "ingest"
        queue_dir.mkdir(exist_ok=True)
        existing = list(queue_dir.glob("*.json"))
        idx = len(existing) + 1
        (queue_dir / f"{idx:06d}.json").write_text(json.dumps(entry))

    def it_ingests_hook_read_into_file_cache(
        self,
        oracle_dir: Path,
        project_dir: Path,
        registry: ProjectRegistry,
    ) -> None:
        # Create a real file
        target = project_dir / "cached_via_ingest.py"
        target.write_text("print('ingested')\n")
        file_path = str(target)

        # Write a Read-type JSON into the ingest queue
        self._enqueue(oracle_dir, {
            "tool_name": "Read",
            "tool_input": {"file_path": file_path},
        })

        # Pre-register the project so registry.for_path works during ingest
        project = registry.for_path(target)
        assert project is not None
        assert project.store is not None
        project.file_cache = FileCache(project.store)

        # Process the ingest queue — this should cache the file
        count = process_ingest(registry, oracle_dir, self._ensure_caches)
        assert count == 1

        # Now a direct smart_read_with_stats should be a cache hit
        response, tokens_saved = project.file_cache.smart_read_with_stats(file_path)
        assert tokens_saved > 0
        assert "No changes since last read" in response

    def it_ignores_non_read_ingest_entries(
        self,
        oracle_dir: Path,
        project_dir: Path,
        registry: ProjectRegistry,
    ) -> None:
        # Create a real file for the later cache check
        target = project_dir / "not_ingested.py"
        target.write_text("print('not cached')\n")
        file_path = str(target)

        # Enqueue a Grep-type entry (not Read)
        self._enqueue(oracle_dir, {
            "tool_name": "Grep",
            "tool_input": {"pattern": "hello", "path": str(project_dir)},
        })

        # Pre-register project
        project = registry.for_path(target)
        assert project is not None
        assert project.store is not None
        project.file_cache = FileCache(project.store)

        # Process ingest — Grep entries are ignored
        count = process_ingest(registry, oracle_dir, self._ensure_caches)
        assert count == 0

        # smart_read_with_stats on the file is a cache miss (ingest didn't cache it)
        response, tokens_saved = project.file_cache.smart_read_with_stats(file_path)
        assert tokens_saved == 0
        assert response == "print('not cached')\n"
