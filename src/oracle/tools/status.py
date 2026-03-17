"""Tool handler for oracle_status — project and git status summary."""

from __future__ import annotations

from oracle.cache.git_cache import GitCache
from oracle.project import StackInfo
from oracle.storage.store import OracleStore


def handle_oracle_status(
    stack: StackInfo, git_cache: GitCache, store: OracleStore
) -> str:
    """Return formatted project status: stack, git state, clean/dirty."""
    snapshot = git_cache.refresh()

    lines: list[str] = []
    lines.append(f"Stack: {stack.lang}")
    if stack.pkg_mgr:
        lines.append(f"Package manager: {stack.pkg_mgr}")
    if stack.test_cmd:
        lines.append(f"Test command: {stack.test_cmd}")

    lines.append(f"Branch: {snapshot.branch}")
    lines.append(f"HEAD: {snapshot.head_sha}")

    if snapshot.dirty_files:
        lines.append(f"Dirty ({len(snapshot.dirty_files)} files)")
    else:
        lines.append("Clean")

    return "\n".join(lines)
