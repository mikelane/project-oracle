"""Tests for OracleWatcher — FS watcher for cache invalidation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from watchfiles import Change

from oracle.watcher import OracleWatcher, _source_filter


def _run_watcher_test(
    tmp_path: Path,
    pre_setup_fn: object,
    trigger_fn: object,
    check_fn: object,
    needle: str,
) -> None:
    """Run a watcher test in a fresh event loop.

    pre_setup_fn(tmp_path) creates dirs BEFORE watcher starts.
    trigger_fn(tmp_path) writes files AFTER watcher is ready.
    check_fn(detected) verifies results.
    needle: substring to wait for in detected paths.
    """

    async def _inner() -> list[str]:
        detected: list[str] = []

        def on_change(path: str) -> None:
            detected.append(path)

        pre_setup_fn(tmp_path)  # type: ignore[operator]

        watcher = OracleWatcher(tmp_path, on_change)
        task = asyncio.create_task(watcher.start())

        await asyncio.sleep(1.0)

        trigger_fn(tmp_path)  # type: ignore[operator]

        # Wait for the specific file change, not just any change
        elapsed = 0.0
        while elapsed < 10.0:
            if any(needle in p for p in detected):
                break
            await asyncio.sleep(0.3)
            elapsed += 0.3

        watcher.stop()
        await task
        return detected

    detected = asyncio.run(_inner())
    check_fn(detected)  # type: ignore[operator]


@pytest.mark.medium
class DescribeOracleWatcher:
    def it_detects_file_change(self, tmp_path: Path) -> None:
        def pre_setup(p: Path) -> None:
            pass

        def trigger(p: Path) -> None:
            (p / "hello.py").write_text("print('hello')\n")

        def check(detected: list[str]) -> None:
            assert any("hello.py" in p for p in detected)

        _run_watcher_test(tmp_path, pre_setup, trigger, check, "hello.py")

    def it_stops_cleanly(self, tmp_path: Path) -> None:
        async def _inner() -> None:
            watcher = OracleWatcher(tmp_path, lambda _: None)
            task = asyncio.create_task(watcher.start())

            await asyncio.sleep(1.0)
            watcher.stop()
            await asyncio.wait_for(task, timeout=10.0)

            assert watcher._stop_event.is_set()

        asyncio.run(_inner())

    def it_ignores_git_directory_changes(self, tmp_path: Path) -> None:
        def pre_setup(p: Path) -> None:
            # Create .git dir before watcher starts so dir creation doesn't trigger
            git_dir = p / ".git"
            git_dir.mkdir(exist_ok=True)

        def trigger(p: Path) -> None:
            (p / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
            (p / "source.py").write_text("x = 1\n")

        def check(detected: list[str]) -> None:
            assert any("source.py" in p for p in detected)
            assert not any(".git" in p for p in detected)

        _run_watcher_test(tmp_path, pre_setup, trigger, check, "source.py")

    def it_suppresses_exceptions_from_awatch(self, tmp_path: Path) -> None:
        async def _inner() -> None:
            watcher = OracleWatcher(tmp_path, lambda _: None)

            with patch("oracle.watcher.awatch", new_callable=AsyncMock) as mock_awatch:
                mock_awatch.side_effect = RuntimeError("watcher crashed")
                await watcher.start()

        asyncio.run(_inner())

    def it_ignores_venv_changes(self, tmp_path: Path) -> None:
        def pre_setup(p: Path) -> None:
            # Create .venv dir before watcher starts
            venv_dir = p / ".venv"
            venv_dir.mkdir(exist_ok=True)

        def trigger(p: Path) -> None:
            (p / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
            (p / "app.py").write_text("y = 2\n")

        def check(detected: list[str]) -> None:
            assert any("app.py" in p for p in detected)
            assert not any(".venv" in p for p in detected)

        _run_watcher_test(tmp_path, pre_setup, trigger, check, "app.py")


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
