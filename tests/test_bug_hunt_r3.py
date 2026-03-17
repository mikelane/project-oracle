"""Bug hunt round 3 — proving suspected bugs with failing tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

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
class DescribeFileCacheStatReadRace:
    """smart_read_with_stats calls stat() (line 52) then read_text() (line 60).
    If the file is deleted between those two calls, read_text() raises
    FileNotFoundError (a subclass of OSError). The except clause on line 61
    only catches UnicodeDecodeError and ValueError, so the function crashes
    with an unhandled FileNotFoundError."""

    def it_returns_error_when_file_vanishes_between_stat_and_read(
        self, cache: FileCache, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        f = tmp_path / "vanishing.py"
        f.write_text("content\n")

        original_read_text = Path.read_text

        def flaky_read_text(self_path: Path, *args: object, **kwargs: object) -> str:
            if self_path == f:
                raise FileNotFoundError(f"No such file: {self_path}")
            return original_read_text(self_path, *args, **kwargs)

        mocker.patch.object(Path, "read_text", flaky_read_text)

        result, tokens_saved = cache.smart_read_with_stats(str(f))
        assert "error" in result.lower(), (
            f"Expected error message when file vanishes between stat and read, got: {result}"
        )
        assert tokens_saved == 0


@pytest.mark.medium
class DescribeFileCachePermissionDenied:
    """smart_read_with_stats catches UnicodeDecodeError and ValueError from
    read_text() (line 61-62). But PermissionError (a subclass of OSError)
    is NOT caught. If the file exists and is under the size limit but is not
    readable, read_text() raises PermissionError and the function crashes."""

    def it_returns_error_when_file_is_not_readable(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        f = tmp_path / "noperm.py"
        f.write_text("secret\n")
        f.chmod(0o000)
        try:
            result, tokens_saved = cache.smart_read_with_stats(str(f))
            assert "error" in result.lower(), (
                f"Expected error for unreadable file, got: {result}"
            )
            assert tokens_saved == 0
        finally:
            f.chmod(0o644)
