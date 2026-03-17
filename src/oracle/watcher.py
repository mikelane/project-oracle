"""FS watcher — watches project root for file changes using watchfiles (Rust-backed)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from watchfiles import Change, awatch


class OracleWatcher:
    """Async file-system watcher that notifies on source-file changes."""

    def __init__(self, project_root: Path, on_change: Callable[[str], None]) -> None:
        self.root = project_root
        self.on_change = on_change
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Watch for changes until stop() is called."""
        try:
            async for changes in awatch(
                self.root, stop_event=self._stop_event, watch_filter=_source_filter
            ):
                for _change_type, path in changes:
                    self.on_change(path)
        except Exception:
            pass

    def stop(self) -> None:
        """Signal the watcher to stop."""
        self._stop_event.set()


def _source_filter(change: Change, path: str) -> bool:
    """Return True for source files, False for ignored directories."""
    skip_dirs = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache"}
    return not any(part in skip_dirs for part in Path(path).parts)
