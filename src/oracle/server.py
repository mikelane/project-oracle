"""FastMCP server entry point — wires registry, caches, and tool handlers."""

from __future__ import annotations

import asyncio
import os
import time
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


def _before_tool() -> None:
    """Drain the ingest queue and pre-populate caches before every tool call."""
    from oracle.ingest_bridge import process_ingest

    process_ingest(_registry, _oracle_dir, _ensure_caches)


def _log(
    project: ProjectState,
    tool_name: str,
    input_data: str | None,
    cache_hit: bool,
    tokens_saved: int,
) -> None:
    """Record a tool interaction to the agent log. No-op when store is not wired."""
    if project.store is None:
        return
    project.store.log_interaction(
        project.session_id, tool_name, input_data, cache_hit, tokens_saved, int(time.time())
    )


@mcp.tool()
def oracle_read(path: str) -> str:
    """Read a file, returning full content on first read or a compact delta on repeat reads."""
    _before_tool()
    resolved = Path(path).resolve()
    project = _registry.for_path(resolved)
    if project is None:
        return f"Error: no project detected for path: {path}"
    if not resolved.is_relative_to(project.root):
        return f"Error: path {path} is outside project root"
    _ensure_caches(project)
    if project.file_cache is None:
        return "Error: file cache not initialized"
    response, tokens_saved = project.file_cache.smart_read_with_stats(str(resolved))
    cache_hit = tokens_saved > 0
    _log(project, "oracle_read", str(resolved), cache_hit, tokens_saved)
    return response


@mcp.tool()
def oracle_grep(pattern: str, path: str = ".") -> str:
    """Search source files for a regex pattern. Returns up to 50 matches."""
    _before_tool()
    from oracle.tools.grep import handle_oracle_grep

    if path != ".":
        resolved_grep = Path(path).resolve()
        project = _registry.current()
        if project is not None and not resolved_grep.is_relative_to(project.root):
            return f"Error: path {path} is outside project root"

    result = handle_oracle_grep(pattern, path)
    project = _registry.current()
    if project is not None:
        _log(project, "oracle_grep", pattern, False, 0)
    return result


@mcp.tool()
def oracle_status() -> str:
    """Return current project status: stack info, git branch, clean/dirty state."""
    _before_tool()
    project = _registry.current()
    if project is None:
        return "Error: no active project. Call oracle_read first to detect a project."
    _ensure_caches(project)
    from oracle.tools.status import handle_oracle_status

    if project.git_cache is None:
        return "Error: git cache not initialized"
    if project.store is None:
        return "Error: store not initialized"
    # Capture delta stats BEFORE handle_oracle_status calls refresh(),
    # which would poison _last_snapshot and make get_delta_with_stats()
    # always report "no changes" (false cache hit).
    _delta_text, cache_hit, tokens_saved = project.git_cache.get_delta_with_stats()
    result = handle_oracle_status(project.stack, project.git_cache, project.store)
    _log(project, "oracle_status", None, cache_hit, tokens_saved)
    return result


@mcp.tool()
def oracle_run(commands: list[str]) -> str:
    """Run allowlisted commands through the cache layer. Returns cached results when unchanged."""
    _before_tool()
    from oracle.cache.command_cache import CommandNotAllowedError

    project = _registry.current()
    if project is None:
        return "Error: no active project. Call oracle_read first to detect a project."
    _ensure_caches(project)
    if project.command_cache is None:
        return "Error: command cache not initialized"

    parts: list[str] = []
    total_tokens_saved = 0
    any_cache_hit = False
    for cmd in commands:
        try:
            output, cache_hit, tokens_saved = project.command_cache.run_summarized_with_stats(cmd)
        except CommandNotAllowedError:
            output = f"Error: command not allowed: {cmd}"
            cache_hit = False
            tokens_saved = 0
        if cache_hit:
            any_cache_hit = True
        total_tokens_saved += tokens_saved
        parts.append(f"$ {cmd}\n{output}")

    _log(project, "oracle_run", "; ".join(commands), any_cache_hit, total_tokens_saved)
    return "\n\n".join(parts)


@mcp.tool()
def oracle_ask(question: str) -> str:
    """Ask a natural-language question about the project. Routes to cache, grep, or Haiku."""
    _before_tool()
    project = _registry.current()
    if project is None:
        return "Error: no active project. Call oracle_read first to detect a project."
    _ensure_caches(project)
    from oracle.tools.ask import handle_oracle_ask

    result = asyncio.run(handle_oracle_ask(question, project))
    _log(project, "oracle_ask", question, False, 0)
    return result


@mcp.tool()
def oracle_forget(path: str) -> str:
    """Clear the file cache for a path. Next oracle_read returns full content."""
    _before_tool()
    resolved = Path(path).resolve()
    project = _registry.for_path(resolved)
    if project is None:
        return f"Error: no project detected for path: {path}"
    _ensure_caches(project)
    from oracle.tools.forget import handle_oracle_forget

    if project.file_cache is None:
        return "Error: file cache not initialized"
    result = handle_oracle_forget(str(resolved), project.file_cache)
    _log(project, "oracle_forget", str(resolved), False, 0)
    return result


@mcp.tool()
def oracle_stats() -> str:
    """Return token savings stats for the current session and cumulative across all sessions."""
    _before_tool()
    project = _registry.current()
    if project is None:
        return "Error: no active project. Call oracle_read first to detect a project."
    from oracle.tools.stats import handle_oracle_stats

    if project.store is None:
        return "Error: store not initialized"
    return handle_oracle_stats(project.session_id, project.store)


def main() -> None:
    """Entry point for the project-oracle MCP server."""
    mcp.run()
