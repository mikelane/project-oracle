"""Tests for git integration wrappers and GitCache with delta diffing."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from oracle.cache.git_cache import GitCache, GitSnapshot
from oracle.integrations.git import (
    get_branch,
    get_dirty_files,
    get_head_sha,
    get_recent_log,
    get_staged_files,
    git_cmd,
)
from oracle.storage.store import OracleStore


@pytest.mark.medium
class DescribeGitIntegration:
    def it_runs_a_git_command(self, git_project: Path) -> None:
        result = git_cmd(["rev-parse", "--abbrev-ref", "HEAD"], cwd=git_project)
        assert result.strip() != ""

    def it_gets_branch_name(self, git_project: Path) -> None:
        branch = get_branch(git_project)
        # git init creates a default branch (main or master depending on config)
        assert branch in ("main", "master")

    def it_gets_head_sha(self, git_project: Path) -> None:
        sha = get_head_sha(git_project)
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)

    def it_returns_empty_for_non_repo(self, tmp_path: Path) -> None:
        assert get_branch(tmp_path) == ""
        assert get_head_sha(tmp_path) == ""

    def it_gets_dirty_files(self, git_project: Path) -> None:
        (git_project / "new_file.txt").write_text("dirty\n")
        dirty = get_dirty_files(git_project)
        assert "new_file.txt" in dirty

    def it_returns_empty_dirty_when_clean(self, git_project: Path) -> None:
        dirty = get_dirty_files(git_project)
        assert dirty == []

    def it_gets_staged_files(self, git_project: Path) -> None:
        (git_project / "staged.txt").write_text("staged\n")
        subprocess.run(
            ["git", "add", "staged.txt"], cwd=git_project, capture_output=True, check=True
        )
        staged = get_staged_files(git_project)
        assert "staged.txt" in staged

    def it_returns_empty_staged_when_none(self, git_project: Path) -> None:
        staged = get_staged_files(git_project)
        assert staged == []

    def it_gets_recent_log(self, git_project: Path) -> None:
        log = get_recent_log(git_project, count=5)
        assert "initial" in log

    def it_returns_empty_string_on_failure(self, tmp_path: Path) -> None:
        result = git_cmd(["log"], cwd=tmp_path)
        assert result == ""

    def it_returns_empty_log_for_non_repo(self, tmp_path: Path) -> None:
        log = get_recent_log(tmp_path)
        assert log == ""

    def it_returns_empty_dirty_for_non_repo(self, tmp_path: Path) -> None:
        dirty = get_dirty_files(tmp_path)
        assert dirty == []

    def it_returns_empty_staged_for_non_repo(self, tmp_path: Path) -> None:
        staged = get_staged_files(tmp_path)
        assert staged == []

    def it_returns_empty_on_oserror(self, tmp_path: Path) -> None:
        # cwd that does not exist triggers OSError
        nonexistent = tmp_path / "does-not-exist"
        result = git_cmd(["status"], cwd=nonexistent)
        assert result == ""


@pytest.mark.medium
class DescribeGitSnapshot:
    def it_has_expected_fields(self) -> None:
        snap = GitSnapshot(
            branch="main",
            head_sha="abc123",
            dirty_files=["file.py"],
            staged_files=["staged.py"],
            recent_log="abc123 initial",
            captured_at=1000,
        )
        assert snap.branch == "main"
        assert snap.head_sha == "abc123"
        assert snap.dirty_files == ["file.py"]
        assert snap.staged_files == ["staged.py"]
        assert snap.recent_log == "abc123 initial"
        assert snap.captured_at == 1000

    def it_defaults_to_empty_lists_and_strings(self) -> None:
        snap = GitSnapshot(branch="main", head_sha="abc123")
        assert snap.dirty_files == []
        assert snap.staged_files == []
        assert snap.recent_log == ""
        assert snap.captured_at == 0


@pytest.mark.medium
class DescribeGitCache:
    def it_captures_branch_name(self, git_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        snapshot = cache.refresh()
        assert snapshot.branch in ("main", "master")

    def it_captures_head_sha(self, git_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        snapshot = cache.refresh()
        assert len(snapshot.head_sha) == 40
        assert all(c in "0123456789abcdef" for c in snapshot.head_sha)

    def it_detects_dirty_files(self, git_project: Path, tmp_path: Path) -> None:
        (git_project / "dirty.txt").write_text("dirty\n")
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        snapshot = cache.refresh()
        assert "dirty.txt" in snapshot.dirty_files

    def it_detects_staged_files(self, git_project: Path, tmp_path: Path) -> None:
        (git_project / "staged.txt").write_text("staged\n")
        subprocess.run(
            ["git", "add", "staged.txt"], cwd=git_project, capture_output=True, check=True
        )
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        snapshot = cache.refresh()
        assert "staged.txt" in snapshot.staged_files

    def it_captures_recent_log(self, git_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        snapshot = cache.refresh()
        assert "initial" in snapshot.recent_log

    def it_reports_no_changes_on_repeat_check(self, git_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        cache.refresh()
        delta = cache.get_delta()
        assert delta == "No changes since last check"

    def it_returns_full_snapshot_on_first_delta(self, git_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        # No refresh called yet — first delta call should return full snapshot
        delta = cache.get_delta()
        assert "Branch:" in delta
        assert "HEAD:" in delta

    def it_reports_new_dirty_files_in_delta(self, git_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        cache.refresh()
        # Now dirty the repo
        (git_project / "new_file.txt").write_text("new\n")
        delta = cache.get_delta()
        assert "new_file.txt" in delta
        assert "New dirty" in delta or "dirty" in delta.lower()

    def it_reports_cleaned_files_in_delta(self, git_project: Path, tmp_path: Path) -> None:
        # Start with a dirty file
        (git_project / "temp.txt").write_text("temp\n")
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        cache.refresh()
        # Clean it by removing
        (git_project / "temp.txt").unlink()
        delta = cache.get_delta()
        assert "temp.txt" in delta
        assert "Cleaned" in delta or "cleaned" in delta.lower()

    def it_reports_branch_change_in_delta(self, git_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        cache.refresh()
        # Create and switch to a new branch
        subprocess.run(
            ["git", "checkout", "-b", "feature-branch"],
            cwd=git_project,
            capture_output=True,
            check=True,
        )
        delta = cache.get_delta()
        assert "feature-branch" in delta
        assert "Branch" in delta

    def it_reports_new_commits_in_delta(self, git_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        cache.refresh()
        # Make a new commit
        (git_project / "commit_file.txt").write_text("committed\n")
        subprocess.run(
            ["git", "add", "commit_file.txt"], cwd=git_project, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "second commit"],
            cwd=git_project,
            capture_output=True,
            check=True,
        )
        delta = cache.get_delta()
        assert "second commit" in delta
        assert "New commits" in delta or "commit" in delta.lower()

    def it_formats_full_snapshot_readably(self, git_project: Path, tmp_path: Path) -> None:
        (git_project / "dirty.txt").write_text("dirty\n")
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        snapshot = cache.refresh()
        formatted = cache._format_full(snapshot)
        assert "Branch:" in formatted
        assert "HEAD:" in formatted
        assert "Dirty files:" in formatted
        assert "dirty.txt" in formatted
        assert "Log:" in formatted

    def it_sets_captured_at_timestamp(self, git_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        snapshot = cache.refresh()
        assert snapshot.captured_at > 0

    def it_reports_newly_staged_files_in_delta(self, git_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        cache.refresh()
        # Stage a new file
        (git_project / "to_stage.txt").write_text("stage me\n")
        subprocess.run(
            ["git", "add", "to_stage.txt"], cwd=git_project, capture_output=True, check=True
        )
        delta = cache.get_delta()
        assert "to_stage.txt" in delta
        assert "Newly staged" in delta

    def it_reports_unstaged_files_in_delta(self, git_project: Path, tmp_path: Path) -> None:
        # Start with a staged file
        (git_project / "was_staged.txt").write_text("staged\n")
        subprocess.run(
            ["git", "add", "was_staged.txt"], cwd=git_project, capture_output=True, check=True
        )
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        cache.refresh()
        # Unstage it
        subprocess.run(
            ["git", "reset", "HEAD", "was_staged.txt"],
            cwd=git_project,
            capture_output=True,
            check=True,
        )
        delta = cache.get_delta()
        assert "was_staged.txt" in delta
        assert "Unstaged" in delta

    def it_formats_full_snapshot_with_staged_files(
        self, git_project: Path, tmp_path: Path
    ) -> None:
        (git_project / "for_stage.txt").write_text("stage\n")
        subprocess.run(
            ["git", "add", "for_stage.txt"], cwd=git_project, capture_output=True, check=True
        )
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        snapshot = cache.refresh()
        formatted = cache._format_full(snapshot)
        assert "Staged files:" in formatted
        assert "for_stage.txt" in formatted

    def it_formats_full_snapshot_without_optional_sections(self, tmp_path: Path) -> None:
        # Snapshot with no dirty, staged, or log
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=tmp_path)
        snapshot = GitSnapshot(branch="main", head_sha="abc123")
        formatted = cache._format_full(snapshot)
        assert "Branch: main" in formatted
        assert "HEAD: abc123" in formatted
        assert "Dirty files:" not in formatted
        assert "Staged files:" not in formatted
        assert "Log:" not in formatted


@pytest.mark.medium
class DescribeGitCacheStats:
    def it_reports_cache_miss_on_first_call(self, git_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        text, is_cache_hit, tokens_saved = cache.get_delta_with_stats()
        assert "Branch:" in text
        assert is_cache_hit is False
        assert tokens_saved == 0

    def it_reports_cache_hit_when_unchanged(self, git_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        cache.get_delta_with_stats()  # first call seeds the snapshot
        text, is_cache_hit, tokens_saved = cache.get_delta_with_stats()
        assert text == "No changes since last check"
        assert is_cache_hit is True
        assert tokens_saved > 0

    def it_estimates_tokens_saved_on_hit(self, git_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        first_text, _, _ = cache.get_delta_with_stats()  # full snapshot
        _, _, tokens_saved = cache.get_delta_with_stats()  # cache hit
        expected_tokens = len(first_text) // 4
        assert tokens_saved == expected_tokens

    def it_reports_zero_tokens_on_miss(self, git_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "oracle.db")
        cache = GitCache(store=store, project_root=git_project)
        _, _, tokens_saved_first = cache.get_delta_with_stats()
        assert tokens_saved_first == 0
        # Make a change so second call is also a miss
        (git_project / "new_file.txt").write_text("new\n")
        _, is_cache_hit, tokens_saved_change = cache.get_delta_with_stats()
        assert is_cache_hit is False
        assert tokens_saved_change == 0
