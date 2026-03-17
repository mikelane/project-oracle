"""Tests for oracle_read tool handler."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from oracle.cache.file_cache import FileCache
from oracle.storage.store import OracleStore
from oracle.tools.read import handle_oracle_read


@pytest.fixture
def store(tmp_path: Path) -> Generator[OracleStore, None, None]:
    db_path = tmp_path / "oracle.db"
    s = OracleStore(db_path)
    yield s
    s.close()


@pytest.fixture
def cache(store: OracleStore) -> FileCache:
    return FileCache(store)


@pytest.mark.medium
class DescribeOracleRead:
    def it_returns_full_content_on_first_read(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        f = tmp_path / "hello.py"
        f.write_text("print('hello')\n")
        result = handle_oracle_read(str(f), cache)
        assert result == "print('hello')\n"

    def it_returns_delta_on_repeat(self, cache: FileCache, tmp_path: Path) -> None:
        f = tmp_path / "changing.py"
        f.write_text("line1\nline2\nline3\n")
        handle_oracle_read(str(f), cache)  # first read
        f.write_text("line1\nmodified\nline3\n")
        result = handle_oracle_read(str(f), cache)
        assert "Changed since last read:" in result
        assert "+modified" in result

    def it_returns_no_changes_for_unchanged_file(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        f = tmp_path / "stable.py"
        f.write_text("x = 1\n")
        handle_oracle_read(str(f), cache)  # first read
        result = handle_oracle_read(str(f), cache)  # second read, unchanged
        assert result.startswith("No changes since last read")

    def it_returns_error_for_missing_file(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        missing = tmp_path / "ghost.py"
        result = handle_oracle_read(str(missing), cache)
        assert "Error: file not found" in result
