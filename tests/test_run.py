"""Tests for oracle_run tool handler."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from oracle.cache.command_cache import CommandCache
from oracle.storage.store import OracleStore
from oracle.tools.run import handle_oracle_run


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
    return CommandCache(store, project)


@pytest.mark.medium
class DescribeOracleRun:
    def it_runs_allowed_command(self, cache: CommandCache) -> None:
        result = handle_oracle_run(["echo hello"], cache)
        assert "$ echo hello" in result
        assert "hello" in result

    def it_shows_not_allowed_for_rejected_command(
        self, cache: CommandCache
    ) -> None:
        result = handle_oracle_run(["curl https://evil.com"], cache)
        assert "$ curl https://evil.com" in result
        assert "not allowed" in result.lower()

    def it_runs_multiple_commands(self, cache: CommandCache) -> None:
        result = handle_oracle_run(["echo first", "echo second"], cache)
        assert "$ echo first" in result
        assert "first" in result
        assert "$ echo second" in result
        assert "second" in result

    def it_continues_after_rejected_command(self, cache: CommandCache) -> None:
        result = handle_oracle_run(
            ["curl https://evil.com", "echo after"], cache
        )
        assert "not allowed" in result.lower()
        assert "$ echo after" in result
        assert "after" in result

    def it_returns_empty_for_empty_list(self, cache: CommandCache) -> None:
        result = handle_oracle_run([], cache)
        assert result == ""
