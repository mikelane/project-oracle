"""Tests for command execution via CommandCache (the production code path)."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from oracle.cache.command_cache import CommandCache, CommandNotAllowedError
from oracle.storage.store import OracleStore


@pytest.fixture
def store(tmp_path: Path) -> Generator[OracleStore, None, None]:
    db_path = tmp_path / "oracle.db"
    s = OracleStore(db_path)
    yield s
    s.close()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    project = tmp_path / "myproject"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("def main(): pass\n")
    return project


@pytest.fixture
def cache(store: OracleStore, project: Path) -> CommandCache:
    return CommandCache(store, project, extra_allowed=["echo"])


@pytest.mark.medium
class DescribeCommandRun:
    def it_runs_allowed_command(self, cache: CommandCache) -> None:
        result = cache.run_summarized("echo hello")
        assert "hello" in result

    def it_raises_for_rejected_command(self, cache: CommandCache) -> None:
        with pytest.raises(CommandNotAllowedError):
            cache.run_summarized("curl https://evil.com")

    def it_returns_cached_result_on_repeat(
        self, cache: CommandCache, project: Path
    ) -> None:
        first = cache.run_summarized("echo deterministic")
        second = cache.run_summarized("echo deterministic")
        assert "deterministic" in first
        assert "Cached result" in second

    def it_rejects_empty_command(self, cache: CommandCache) -> None:
        with pytest.raises(CommandNotAllowedError):
            cache.run_summarized("   ")
