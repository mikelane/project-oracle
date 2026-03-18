"""Benchmark tests — verify token savings from caching and delta diffing."""

from __future__ import annotations

from pathlib import Path

import pytest

from oracle.cache.file_cache import FileCache
from oracle.storage.store import OracleStore


@pytest.mark.large
class DescribeTokenSavingsBenchmark:
    @pytest.fixture
    def large_file(self, tmp_path: Path) -> Path:
        """Create a realistically-sized source file (~200 lines) for benchmark tests."""
        f = tmp_path / "large_module.py"
        lines = [f"def function_{i}(x: int) -> int:" for i in range(200)]
        lines += [f"    return x + {i}" for i in range(200)]
        f.write_text("\n".join(lines) + "\n")
        return f

    def it_saves_tokens_on_unchanged_reread(self, large_file: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)
        first_result = cache.smart_read(str(large_file))
        second_result, tokens_saved = cache.smart_read_with_stats(str(large_file))
        first_tokens = len(first_result) // 4
        assert tokens_saved >= first_tokens * 0.8  # at least 80% savings
        assert len(second_result) < len(first_result) * 0.5  # significantly smaller
        store.close()

    def it_saves_tokens_on_small_change(self, large_file: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)
        cache.smart_read(str(large_file))
        # Change a single line in a large file — delta is much smaller than full content
        content = large_file.read_text()
        large_file.write_text(content.replace("function_0", "function_0_changed", 1))
        result, tokens_saved = cache.smart_read_with_stats(str(large_file))
        assert tokens_saved > 0
        assert "changed" in result.lower()
        store.close()

    def it_simulates_session_with_rereads(self, large_file: Path, tmp_path: Path) -> None:
        """Simulate repeated reads typical of a coding session."""
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)
        total_saved = 0
        for _i in range(10):
            _, saved = cache.smart_read_with_stats(str(large_file))
            total_saved += saved
        # 9 out of 10 reads save tokens (first read does not)
        assert total_saved > 0
        store.close()
