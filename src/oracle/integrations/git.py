"""Shell wrappers for git commands."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def git_cmd(args: list[str], cwd: Path) -> str:
    """Run git command, return stdout. Empty string on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        logger.warning("git command failed: %s", args, exc_info=True)
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


def get_branch(cwd: Path) -> str:
    """Return the current branch name, or empty string on failure."""
    return git_cmd(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd).strip()


def get_head_sha(cwd: Path) -> str:
    """Return the full HEAD commit SHA, or empty string on failure."""
    return git_cmd(["rev-parse", "HEAD"], cwd=cwd).strip()


def get_dirty_files(cwd: Path) -> list[str]:
    """Return list of dirty (modified/untracked) file paths."""
    output = git_cmd(["status", "--porcelain"], cwd=cwd)
    if not output:
        return []
    return [line[3:] for line in output.strip().splitlines() if len(line) > 3]


def get_staged_files(cwd: Path) -> list[str]:
    """Return list of staged file paths."""
    output = git_cmd(["diff", "--cached", "--name-only"], cwd=cwd)
    if not output:
        return []
    return [f for f in output.strip().splitlines() if f]


def get_recent_log(cwd: Path, count: int = 20) -> str:
    """Return recent git log as a string, or empty string on failure."""
    return git_cmd(["log", "--oneline", f"-{count}"], cwd=cwd).strip()
