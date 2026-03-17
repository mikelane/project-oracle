"""Tests for oracle_status tool handler."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from oracle.cache.git_cache import GitCache
from oracle.project import StackInfo
from oracle.storage.store import OracleStore
from oracle.tools.status import handle_oracle_status


@pytest.fixture
def store(tmp_path: Path) -> Generator[OracleStore, None, None]:
    db_path = tmp_path / "oracle.db"
    s = OracleStore(db_path)
    yield s
    s.close()


@pytest.mark.medium
class DescribeOracleStatus:
    def it_includes_stack_info(self, tmp_path: Path, store: OracleStore) -> None:
        stack = StackInfo(lang="python", pkg_mgr="uv", test_cmd="pytest")
        git_cache = GitCache(store=store, project_root=tmp_path)
        result = handle_oracle_status(stack, git_cache, store)
        assert "python" in result
        assert "uv" in result
        assert "pytest" in result

    def it_includes_git_branch(
        self, git_project: Path, tmp_path: Path, store: OracleStore
    ) -> None:
        stack = StackInfo(lang="python")
        git_cache = GitCache(store=store, project_root=git_project)
        result = handle_oracle_status(stack, git_cache, store)
        # git_project fixture creates a repo on main or master
        assert "main" in result or "master" in result

    def it_shows_clean_when_no_dirty_files(
        self, git_project: Path, tmp_path: Path, store: OracleStore
    ) -> None:
        stack = StackInfo(lang="python")
        git_cache = GitCache(store=store, project_root=git_project)
        result = handle_oracle_status(stack, git_cache, store)
        assert "Clean" in result

    def it_shows_dirty_when_files_modified(
        self, git_project: Path, tmp_path: Path, store: OracleStore
    ) -> None:
        (git_project / "dirty.txt").write_text("dirty\n")
        stack = StackInfo(lang="python")
        git_cache = GitCache(store=store, project_root=git_project)
        result = handle_oracle_status(stack, git_cache, store)
        assert "Dirty" in result

    def it_includes_head_sha(
        self, git_project: Path, tmp_path: Path, store: OracleStore
    ) -> None:
        stack = StackInfo(lang="python")
        git_cache = GitCache(store=store, project_root=git_project)
        result = handle_oracle_status(stack, git_cache, store)
        assert "HEAD:" in result

    def it_handles_missing_optional_fields(
        self, tmp_path: Path, store: OracleStore
    ) -> None:
        stack = StackInfo(lang="unknown")
        git_cache = GitCache(store=store, project_root=tmp_path)
        result = handle_oracle_status(stack, git_cache, store)
        assert "unknown" in result
        # Should not crash on missing pkg_mgr, test_cmd etc.
        assert "Stack:" in result
