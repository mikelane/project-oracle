"""Tests for file reading via FileCache.smart_read (the production code path)."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from oracle.cache.file_cache import FileCache
from oracle.storage.store import OracleStore


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
class DescribeFileRead:
    def it_returns_full_content_on_first_read(self, cache: FileCache, tmp_path: Path) -> None:
        f = tmp_path / "hello.py"
        f.write_text("print('hello')\n")
        result = cache.smart_read(str(f))
        assert result == "print('hello')\n"

    def it_returns_delta_on_repeat(self, cache: FileCache, tmp_path: Path) -> None:
        f = tmp_path / "changing.py"
        f.write_text("line1\nline2\nline3\n")
        cache.smart_read(str(f))  # first read
        f.write_text("line1\nmodified\nline3\n")
        result = cache.smart_read(str(f))
        assert "Changed since last read:" in result
        assert "+modified" in result

    def it_returns_no_changes_for_unchanged_file(self, cache: FileCache, tmp_path: Path) -> None:
        f = tmp_path / "stable.py"
        f.write_text("x = 1\n")
        cache.smart_read(str(f))  # first read
        result = cache.smart_read(str(f))  # second read, unchanged
        assert result.startswith("No changes since last read")

    def it_returns_error_for_missing_file(self, cache: FileCache, tmp_path: Path) -> None:
        missing = tmp_path / "ghost.py"
        result = cache.smart_read(str(missing))
        assert "Error: file not found" in result
