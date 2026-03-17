"""FastMCP server entry point — wires registry, caches, and tool handlers."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from oracle.project import ProjectState
from oracle.registry import ProjectRegistry

mcp = FastMCP(
    "project-oracle",
    instructions=(
        "Stateful project oracle that caches file reads, command results, "
        "and git state across sessions. Prefer oracle_* tools over built-in "
        "Read/Grep/Bash for repeat operations — they return compact deltas "
        "instead of full content."
    ),
)

_oracle_dir = Path(os.environ.get("ORACLE_DIR", str(Path.home() / ".project-oracle")))
_registry = ProjectRegistry(_oracle_dir)


def _ensure_caches(project: ProjectState) -> None:
    """Wire up cache layers if not already initialized."""
    if project.store is None:
        return
    if project.file_cache is None:
        from oracle.cache.file_cache import FileCache

        project.file_cache = FileCache(project.store)
    if project.git_cache is None:
        from oracle.cache.git_cache import GitCache

        project.git_cache = GitCache(project.store, project.root)
    if project.command_cache is None:
        from oracle.cache.command_cache import CommandCache

        project.command_cache = CommandCache(project.store, project.root)


@mcp.tool()
def oracle_read(path: str) -> str:
    """Read a file, returning full content on first read or a compact delta on repeat reads."""
    resolved = Path(path).resolve()
    project = _registry.for_path(resolved)
    if project is None:
        return f"Error: no project detected for path: {path}"
    _ensure_caches(project)
    from oracle.tools.read import handle_oracle_read

    assert project.file_cache is not None
    return handle_oracle_read(str(resolved), project.file_cache)


@mcp.tool()
def oracle_grep(pattern: str, path: str = ".") -> str:
    """Search source files for a regex pattern. Returns up to 50 matches."""
    from oracle.tools.grep import handle_oracle_grep

    return handle_oracle_grep(pattern, path)


@mcp.tool()
def oracle_status() -> str:
    """Return current project status: stack info, git branch, clean/dirty state."""
    project = _registry.current()
    if project is None:
        return "Error: no active project. Call oracle_read first to detect a project."
    _ensure_caches(project)
    from oracle.tools.status import handle_oracle_status

    assert project.git_cache is not None
    assert project.store is not None
    return handle_oracle_status(project.stack, project.git_cache, project.store)


@mcp.tool()
def oracle_run(commands: list[str]) -> str:
    """Run allowlisted commands through the cache layer. Returns cached results when unchanged."""
    project = _registry.current()
    if project is None:
        return "Error: no active project. Call oracle_read first to detect a project."
    _ensure_caches(project)
    from oracle.tools.run import handle_oracle_run

    assert project.command_cache is not None
    return handle_oracle_run(commands, project.command_cache)


@mcp.tool()
def oracle_ask(question: str) -> str:
    """Ask a natural-language question about the project. Routes to cache, grep, or Haiku."""
    project = _registry.current()
    if project is None:
        return "Error: no active project. Call oracle_read first to detect a project."
    _ensure_caches(project)
    from oracle.tools.ask import handle_oracle_ask

    return asyncio.run(handle_oracle_ask(question, project))


@mcp.tool()
def oracle_forget(path: str) -> str:
    """Clear the file cache for a path. Next oracle_read returns full content."""
    resolved = Path(path).resolve()
    project = _registry.for_path(resolved)
    if project is None:
        return f"Error: no project detected for path: {path}"
    _ensure_caches(project)
    from oracle.tools.forget import handle_oracle_forget

    assert project.file_cache is not None
    return handle_oracle_forget(str(resolved), project.file_cache)


def main() -> None:
    """Entry point for the project-oracle MCP server."""
    mcp.run()
