"""Tests for OracleWatcher — FS watcher for cache invalidation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from watchfiles import Change

from oracle.watcher import OracleWatcher, _source_filter


async def _fake_awatch(
    *args: Any,
    stop_event: asyncio.Event | None = None,
    watch_filter: Any = None,
    **kwargs: Any,
) -> Any:
    """Fake awatch that yields controlled change sets, respecting the watch_filter."""
    changes = [
        {(Change.modified, "/project/src/main.py")},
        {(Change.modified, "/project/.git/HEAD")},
        {(Change.modified, "/project/.venv/lib/site.py")},
        {(Change.modified, "/project/src/utils.py")},
    ]
    for change_set in changes:
        if stop_event and stop_event.is_set():
            return
        # Apply the watch_filter if provided (just like real awatch does)
        if watch_filter:
            change_set = {(c, p) for c, p in change_set if watch_filter(c, p)}
        if change_set:
            yield change_set
    # Wait for stop signal
    if stop_event:
        await stop_event.wait()


@pytest.mark.medium
class DescribeOracleWatcher:
    def it_dispatches_callbacks_for_detected_changes(self) -> None:
        detected: list[str] = []

        async def _inner() -> None:
            watcher = OracleWatcher(Path("/project"), lambda p: detected.append(p))
            with patch("oracle.watcher.awatch", new=_fake_awatch):
                task = asyncio.create_task(watcher.start())
                await asyncio.sleep(0.1)
                watcher.stop()
                await task

        asyncio.run(_inner())
        # Should only see source files, not .git or .venv (filtered by _source_filter)
        assert any("main.py" in p for p in detected)
        assert any("utils.py" in p for p in detected)

    def it_filters_out_git_and_venv_via_watch_filter(self) -> None:
        detected: list[str] = []

        async def _inner() -> None:
            watcher = OracleWatcher(Path("/project"), lambda p: detected.append(p))
            with patch("oracle.watcher.awatch", new=_fake_awatch):
                task = asyncio.create_task(watcher.start())
                await asyncio.sleep(0.1)
                watcher.stop()
                await task

        asyncio.run(_inner())
        assert not any(".git" in p for p in detected)
        assert not any(".venv" in p for p in detected)

    def it_stops_cleanly(self) -> None:
        async def _inner() -> None:
            watcher = OracleWatcher(Path("/project"), lambda _: None)
            with patch("oracle.watcher.awatch", new=_fake_awatch):
                task = asyncio.create_task(watcher.start())
                await asyncio.sleep(0.1)
                watcher.stop()
                await asyncio.wait_for(task, timeout=5.0)
            assert watcher._stop_event.is_set()

        asyncio.run(_inner())

    def it_suppresses_exceptions_from_awatch(self) -> None:
        async def _inner() -> None:
            watcher = OracleWatcher(Path("/project"), lambda _: None)
            with patch("oracle.watcher.awatch", new_callable=AsyncMock) as mock_awatch:
                mock_awatch.side_effect = RuntimeError("watcher crashed")
                await watcher.start()

        asyncio.run(_inner())


class DescribeSourceFilter:
    def it_allows_source_files(self) -> None:
        assert _source_filter(Change.modified, "/project/src/main.py") is True

    def it_rejects_git_paths(self) -> None:
        assert _source_filter(Change.modified, "/project/.git/HEAD") is False

    def it_rejects_venv_paths(self) -> None:
        assert _source_filter(Change.modified, "/project/.venv/lib/site.py") is False

    def it_rejects_node_modules(self) -> None:
        assert _source_filter(Change.modified, "/project/node_modules/pkg/index.js") is False

    def it_rejects_pycache_paths(self) -> None:
        assert _source_filter(Change.modified, "/project/__pycache__/mod.cpython-312.pyc") is False

    def it_rejects_mypy_cache_paths(self) -> None:
        assert _source_filter(Change.modified, "/project/.mypy_cache/3.12/mod.meta.json") is False
