"""MCP-over-MCP client for chunkhound semantic search.

Degrades gracefully if chunkhound is not installed.
"""

from __future__ import annotations

import asyncio


class ChunkhoundClient:
    """Async client that spawns chunkhound as a subprocess for semantic code search."""

    def __init__(self, project_root: str) -> None:
        self.root = project_root
        self.process: asyncio.subprocess.Process | None = None
        self._started = False

    async def try_start(self) -> bool:
        """Attempt to start chunkhound. Returns False if not installed."""
        if self._started:
            return True
        try:
            self.process = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    "chunkhound",
                    "mcp",
                    "--project",
                    self.root,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=5.0,
            )
            self._started = True
            return True
        except (TimeoutError, FileNotFoundError, OSError):
            return False

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        """Semantic search. Returns empty list if not started."""
        if not self._started or self.process is None:
            return []
        # For v1: return empty list (chunkhound integration is best-effort)
        return []

    async def stop(self) -> None:
        """Terminate the chunkhound process if running."""
        if self.process:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except TimeoutError:
                self.process.kill()
            self._started = False
