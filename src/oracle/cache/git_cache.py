"""GitCache — git state caching with snapshot capture and delta diffing."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from oracle.integrations.git import (
    get_branch,
    get_dirty_files,
    get_head_sha,
    get_recent_log,
    get_staged_files,
)
from oracle.storage.store import OracleStore


@dataclass
class GitSnapshot:
    """Immutable snapshot of git repository state at a point in time."""

    branch: str
    head_sha: str
    dirty_files: list[str] = field(default_factory=list)
    staged_files: list[str] = field(default_factory=list)
    recent_log: str = ""
    captured_at: int = 0


class GitCache:
    """Cache git state and return compact deltas when state changes."""

    def __init__(self, store: OracleStore, project_root: Path) -> None:
        self._store = store
        self._root = project_root
        self._last_snapshot: GitSnapshot | None = None

    def refresh(self) -> GitSnapshot:
        """Capture current git state and store as the last snapshot."""
        snapshot = GitSnapshot(
            branch=get_branch(self._root),
            head_sha=get_head_sha(self._root),
            dirty_files=get_dirty_files(self._root),
            staged_files=get_staged_files(self._root),
            recent_log=get_recent_log(self._root),
            captured_at=int(time.time()),
        )
        self._last_snapshot = snapshot
        return snapshot

    def get_delta(self) -> str:
        """Compare current state against last snapshot, returning only changes.

        First call (no previous snapshot): return full formatted snapshot.
        Subsequent calls: return only what changed.
        If nothing changed: "No changes since last check".
        """
        current = self._capture_current()

        if self._last_snapshot is None:
            self._last_snapshot = current
            return self._format_full(current)

        changes: list[str] = []

        if current.branch != self._last_snapshot.branch:
            changes.append(
                f"Branch changed: {self._last_snapshot.branch} -> {current.branch}"
            )

        if current.head_sha != self._last_snapshot.head_sha:
            # Find new commits by diffing the log
            old_lines = set(self._last_snapshot.recent_log.splitlines())
            new_lines = current.recent_log.splitlines()
            new_commits = [line for line in new_lines if line not in old_lines]
            if new_commits:
                changes.append("New commits:\n  " + "\n  ".join(new_commits))

        old_dirty = set(self._last_snapshot.dirty_files)
        new_dirty = set(current.dirty_files)
        added_dirty = new_dirty - old_dirty
        cleaned = old_dirty - new_dirty

        if added_dirty:
            changes.append("New dirty files: " + ", ".join(sorted(added_dirty)))
        if cleaned:
            changes.append("Cleaned files: " + ", ".join(sorted(cleaned)))

        old_staged = set(self._last_snapshot.staged_files)
        new_staged = set(current.staged_files)
        added_staged = new_staged - old_staged
        unstaged = old_staged - new_staged

        if added_staged:
            changes.append("Newly staged: " + ", ".join(sorted(added_staged)))
        if unstaged:
            changes.append("Unstaged: " + ", ".join(sorted(unstaged)))

        self._last_snapshot = current

        if not changes:
            return "No changes since last check"

        return "\n".join(changes)

    def _capture_current(self) -> GitSnapshot:
        """Capture current git state without storing it."""
        return GitSnapshot(
            branch=get_branch(self._root),
            head_sha=get_head_sha(self._root),
            dirty_files=get_dirty_files(self._root),
            staged_files=get_staged_files(self._root),
            recent_log=get_recent_log(self._root),
            captured_at=int(time.time()),
        )

    def _format_full(self, snapshot: GitSnapshot) -> str:
        """Human-readable full snapshot."""
        lines = [
            f"Branch: {snapshot.branch}",
            f"HEAD: {snapshot.head_sha}",
        ]
        if snapshot.dirty_files:
            lines.append(f"Dirty files: {', '.join(snapshot.dirty_files)}")
        if snapshot.staged_files:
            lines.append(f"Staged files: {', '.join(snapshot.staged_files)}")
        if snapshot.recent_log:
            lines.append(f"Log:\n  {snapshot.recent_log.replace(chr(10), chr(10) + '  ')}")
        return "\n".join(lines)
