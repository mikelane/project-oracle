"""Tool handler for oracle_run — run commands through the cache layer."""

from __future__ import annotations

from oracle.cache.command_cache import CommandCache, CommandNotAllowedError


def handle_oracle_run(commands: list[str], command_cache: CommandCache) -> str:
    """Run each command through cache. Return formatted output for all commands."""
    parts: list[str] = []
    for cmd in commands:
        try:
            output = command_cache.run_summarized(cmd)
        except CommandNotAllowedError:
            output = f"Error: command not allowed: {cmd}"
        parts.append(f"$ {cmd}\n{output}")
    return "\n\n".join(parts)
