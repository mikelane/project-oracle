"""Tests for ProjectRegistry — project detection and caching."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.medium
class DescribeProjectRegistry:
    def it_detects_project_from_file_path(self, tmp_project: Path, oracle_dir: Path) -> None:
        from oracle.registry import ProjectRegistry

        registry = ProjectRegistry(oracle_dir)
        result = registry.for_path(tmp_project / "src" / "main.py")

        assert result is not None
        assert result.root == tmp_project
        assert result.stack.lang == "python"

    def it_returns_none_for_no_project(self, tmp_path: Path, oracle_dir: Path) -> None:
        from oracle.registry import ProjectRegistry

        bare = tmp_path / "nowhere"
        bare.mkdir()

        registry = ProjectRegistry(oracle_dir)
        result = registry.for_path(bare)
        assert result is None

    def it_caches_project_state(self, tmp_project: Path, oracle_dir: Path) -> None:
        from oracle.registry import ProjectRegistry

        registry = ProjectRegistry(oracle_dir)
        first = registry.for_path(tmp_project / "src" / "main.py")
        second = registry.for_path(tmp_project / "src" / "main.py")

        assert first is second

    def it_generates_deterministic_project_id(self, tmp_project: Path, oracle_dir: Path) -> None:
        import hashlib

        from oracle.registry import ProjectRegistry

        registry = ProjectRegistry(oracle_dir)
        result = registry.for_path(tmp_project / "src" / "main.py")

        expected_id = hashlib.sha256(str(tmp_project).encode()).hexdigest()[:8]
        assert result is not None
        assert result.project_id == expected_id

    def it_creates_project_db_directory(self, tmp_project: Path, oracle_dir: Path) -> None:
        from oracle.registry import ProjectRegistry

        registry = ProjectRegistry(oracle_dir)
        result = registry.for_path(tmp_project / "src" / "main.py")

        assert result is not None
        db_dir = oracle_dir / "projects" / result.project_id
        assert db_dir.exists()
        assert (db_dir / "oracle.db").exists()

    def it_creates_oracle_store(self, tmp_project: Path, oracle_dir: Path) -> None:
        from oracle.registry import ProjectRegistry

        registry = ProjectRegistry(oracle_dir)
        result = registry.for_path(tmp_project / "src" / "main.py")

        assert result is not None
        assert result.store is not None

    def it_returns_current_project(self, tmp_project: Path, oracle_dir: Path) -> None:
        from oracle.registry import ProjectRegistry

        registry = ProjectRegistry(oracle_dir)
        assert registry.current() is None

        result = registry.for_path(tmp_project / "src" / "main.py")
        assert registry.current() is result

    def it_handles_preexisting_project_directory(
        self, tmp_project: Path, oracle_dir: Path
    ) -> None:
        """Simulates a second session where the project dir already exists on disk.

        Ensures mkdir(exist_ok=True) is used so pre-existing directories don't
        raise FileExistsError.
        """
        from oracle.registry import ProjectRegistry

        registry1 = ProjectRegistry(oracle_dir)
        project1 = registry1.for_path(tmp_project / "src" / "main.py")
        assert project1 is not None

        # Pre-create the directory to guarantee it exists before second registry
        db_dir = oracle_dir / "projects" / project1.project_id
        assert db_dir.is_dir()

        # New registry instance (simulating new session) — dir already exists on disk
        registry2 = ProjectRegistry(oracle_dir)
        # This must NOT raise FileExistsError
        project2 = registry2.for_path(tmp_project / "src" / "main.py")
        assert project2 is not None
        assert project2.project_id == project1.project_id

    def it_creates_nested_project_directory_from_scratch(
        self, tmp_project: Path, tmp_path: Path
    ) -> None:
        """Ensures parents=True creates intermediate directories.

        The oracle_dir fixture pre-creates 'projects/', but this test uses a
        bare oracle_dir where 'projects/' does NOT exist, so mkdir must create
        the parent chain.
        """
        from oracle.registry import ProjectRegistry

        bare_oracle = tmp_path / "fresh-oracle"
        bare_oracle.mkdir()
        # Intentionally NOT creating bare_oracle / "projects"

        registry = ProjectRegistry(bare_oracle)
        result = registry.for_path(tmp_project / "src" / "main.py")
        assert result is not None
        db_dir = bare_oracle / "projects" / result.project_id
        assert db_dir.is_dir()
