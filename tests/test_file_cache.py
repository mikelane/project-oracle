"""Tests for FileCache — file caching with delta diffing."""

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


class DescribeFormatElapsed:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (30, "30s"),
            (90, "1m"),
            (7200, "2h"),
        ],
    )
    def it_formats_elapsed_time(self, seconds: int, expected: str) -> None:
        from oracle.cache.file_cache import _format_elapsed

        assert _format_elapsed(seconds) == expected


class DescribeComputeDelta:
    def it_produces_unified_diff(self) -> None:
        from oracle.cache.file_cache import _compute_delta

        old = "line1\nline2\nline3\n"
        new = "line1\nmodified\nline3\n"
        delta = _compute_delta(old, new)
        assert "-line2" in delta
        assert "+modified" in delta
        # Should not contain --- / +++ header lines
        assert "---" not in delta
        assert "+++" not in delta

    def it_returns_empty_for_identical_content(self) -> None:
        from oracle.cache.file_cache import _compute_delta

        content = "same\ncontent\n"
        assert _compute_delta(content, content) == ""


@pytest.mark.medium
class DescribeFileCacheRead:
    def it_returns_full_content_on_first_read(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        f = tmp_path / "hello.py"
        f.write_text("print('hello')\n")
        result = cache.smart_read(str(f))
        assert result == "print('hello')\n"

    def it_returns_no_changes_when_file_is_unchanged(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        f = tmp_path / "stable.py"
        f.write_text("x = 1\n")
        cache.smart_read(str(f))  # first read populates cache
        result = cache.smart_read(str(f))  # second read, unchanged
        assert result.startswith("No changes since last read")

    def it_returns_delta_when_file_has_changed(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        f = tmp_path / "changing.py"
        f.write_text("line1\nline2\nline3\n")
        cache.smart_read(str(f))  # populate cache
        f.write_text("line1\nmodified\nline3\n")
        result = cache.smart_read(str(f))
        assert "Changed since last read:" in result
        assert "-line2" in result
        assert "+modified" in result

    def it_returns_error_for_nonexistent_file(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        missing = tmp_path / "ghost.py"
        result = cache.smart_read(str(missing))
        assert result == f"Error: file not found: {missing}"

    def it_includes_elapsed_time_in_no_change_response(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        f = tmp_path / "timed.py"
        f.write_text("content\n")
        cache.smart_read(str(f))
        result = cache.smart_read(str(f))
        # Elapsed time is 0 seconds (immediate reread)
        assert "0s ago" in result


@pytest.mark.medium
class DescribeFileCacheForget:
    def it_forces_full_reread_after_forget(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        f = tmp_path / "forgettable.py"
        f.write_text("original\n")
        cache.smart_read(str(f))  # populate cache
        cache.forget(str(f))
        result = cache.smart_read(str(f))  # should return full content, not "No changes"
        assert result == "original\n"

    def it_is_noop_for_nonexistent_path(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        # Should not raise
        cache.forget(str(tmp_path / "never_cached.py"))


@pytest.mark.medium
class DescribeFileCacheTokenEstimate:
    def it_reports_tokens_saved_on_cache_hit(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        f = tmp_path / "tokens.py"
        content = "a" * 400  # 400 chars => ~100 tokens
        f.write_text(content)
        cache.smart_read(str(f))  # first read
        _response, tokens_saved = cache.smart_read_with_stats(str(f))  # cache hit
        assert tokens_saved == len(content) // 4
        assert tokens_saved == 100

    def it_reports_zero_tokens_on_first_read(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        f = tmp_path / "first.py"
        f.write_text("new content\n")
        _response, tokens_saved = cache.smart_read_with_stats(str(f))
        assert tokens_saved == 0

    def it_returns_integer_token_estimates_on_cache_hit(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        f = tmp_path / "int_tokens.py"
        f.write_text("a" * 400)
        cache.smart_read(str(f))
        _, tokens_saved = cache.smart_read_with_stats(str(f))
        assert isinstance(tokens_saved, int)

    def it_returns_integer_token_estimates_on_delta(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        f = tmp_path / "int_delta.py"
        # Large file with many unique lines so the delta is small
        lines = [f"def func_{i}(): return {i}" for i in range(200)]
        f.write_text("\n".join(lines) + "\n")
        cache.smart_read(str(f))
        # Change only one line so delta is much smaller than full content
        lines[0] = "def func_0(): return 'changed'"
        f.write_text("\n".join(lines) + "\n")
        _, tokens_saved = cache.smart_read_with_stats(str(f))
        assert tokens_saved > 0, "tokens_saved must be positive to test the type"
        assert isinstance(tokens_saved, int)

    def it_reports_fewer_tokens_saved_for_delta_than_full_content(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        f = tmp_path / "delta_tokens.py"
        original = "line1\nline2\nline3\nline4\nline5\n" * 20
        f.write_text(original)
        first_result = cache.smart_read(str(f))
        full_token_estimate = len(first_result) // 4

        # Modify file slightly
        f.write_text(original.replace("line3", "changed", 1))

        _, tokens_saved = cache.smart_read_with_stats(str(f))
        assert 0 < tokens_saved < full_token_estimate


@pytest.mark.medium
class DescribeFileCacheMarkStale:
    def it_updates_disk_sha256_in_store(
        self, cache: FileCache, store: OracleStore, tmp_path: Path
    ) -> None:
        f = tmp_path / "watched.py"
        f.write_text("original\n")
        cache.smart_read(str(f))  # populate cache
        cache.mark_stale(str(f), "new_disk_hash_abc")
        row = store.get_file_cache(str(f))
        assert row is not None
        assert row["disk_sha256"] == "new_disk_hash_abc"
