"""Tests for oracle_forget tool handler."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from oracle.cache.file_cache import FileCache
from oracle.storage.store import OracleStore
from oracle.tools.forget import handle_oracle_forget


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
class DescribeOracleForget:
    def it_forces_full_reread(self, cache: FileCache, tmp_path: Path) -> None:
        f = tmp_path / "forgettable.py"
        f.write_text("original\n")
        cache.smart_read(str(f))  # populate cache
        handle_oracle_forget(str(f), cache)
        result = cache.smart_read(str(f))  # should return full content
        assert result == "original\n"

    def it_returns_confirmation_message(self, cache: FileCache, tmp_path: Path) -> None:
        f = tmp_path / "forgettable.py"
        f.write_text("content\n")
        cache.smart_read(str(f))  # populate cache
        result = handle_oracle_forget(str(f), cache)
        assert "Cache cleared" in result
        assert str(f) in result
        assert "Next oracle_read will return full content" in result

    def it_returns_confirmation_even_for_uncached_path(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        path = str(tmp_path / "never_cached.py")
        result = handle_oracle_forget(path, cache)
        assert "Cache cleared" in result
        assert path in result
