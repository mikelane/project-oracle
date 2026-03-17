"""Characterization tests — golden-file tests pinning output formats for refactoring safety."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from oracle.cache.file_cache import FileCache
from oracle.storage.store import OracleStore
from oracle.tools.forget import handle_oracle_forget
from oracle.tools.stats import handle_oracle_stats


@pytest.mark.medium
class DescribeFileCacheCharacterization:
    def it_produces_stable_no_change_format(
        self, tmp_project: Path, tmp_path: Path
    ) -> None:
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)
        file_path = str(tmp_project / "src" / "main.py")
        cache.smart_read(file_path)
        result = cache.smart_read(file_path)
        assert result.startswith("No changes since last read (")
        assert "ago)" in result
        store.close()

    def it_produces_stable_delta_format(
        self, tmp_project: Path, tmp_path: Path
    ) -> None:
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)
        file_path = tmp_project / "src" / "main.py"
        cache.smart_read(str(file_path))
        file_path.write_text("def hello():\n    return 'changed'\n")
        result = cache.smart_read(str(file_path))
        assert result.startswith("Changed since last read:")
        assert "@@" in result  # unified diff marker
        store.close()

    def it_produces_stable_forget_confirmation(
        self, tmp_project: Path, tmp_path: Path
    ) -> None:
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)
        file_path = str(tmp_project / "src" / "main.py")
        result = handle_oracle_forget(file_path, cache)
        assert "Cache cleared for" in result
        assert "Next oracle_read will return full content" in result
        store.close()


@pytest.mark.medium
class DescribeOracleStatsCharacterization:
    """Pin the exact text layout of handle_oracle_stats() so future changes cannot
    accidentally break the output format that agents parse."""

    def it_produces_stable_stats_format_with_activity(self, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "stats.db")
        session_id = "sess-abc-123"
        now = int(time.time())

        # Log 3 interactions: 2 cache hits (saving 500 and 300 tokens), 1 miss
        store.log_interaction(session_id, "oracle_read", "/a.py", True, 500, now)
        store.log_interaction(session_id, "oracle_read", "/b.py", True, 300, now + 1)
        store.log_interaction(session_id, "oracle_read", "/c.py", False, 0, now + 2)

        # Log 1 interaction on a different session (cache hit, 1200 tokens saved)
        store.log_interaction("other-session", "oracle_read", "/d.py", True, 1200, now + 3)

        result = handle_oracle_stats(session_id, store)

        expected = (
            "Session (sess-abc-123):\n"
            "  Tool calls: 3\n"
            "  Cache hits: 2\n"
            "  Tokens saved: 800\n"
            "\n"
            "All sessions:\n"
            "  Tool calls: 4\n"
            "  Cache hits: 3\n"
            "  Tokens saved: 2,000"
        )
        assert result == expected
        store.close()

    def it_produces_stable_stats_format_with_no_activity(self, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "stats-empty.db")

        result = handle_oracle_stats("unused-session", store)

        expected = (
            "Session (unused-session):\n"
            "  Tool calls: 0\n"
            "  Cache hits: 0\n"
            "  Tokens saved: 0\n"
            "\n"
            "All sessions:\n"
            "  Tool calls: 0\n"
            "  Cache hits: 0\n"
            "  Tokens saved: 0"
        )
        assert result == expected
        store.close()

    def it_formats_large_token_counts_with_commas(self, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "stats-large.db")
        session_id = "sess-large"
        now = int(time.time())

        store.log_interaction(session_id, "oracle_read", "/big.py", True, 1_234_567, now)

        result = handle_oracle_stats(session_id, store)

        assert "Tokens saved: 1,234,567" in result
        # Verify both session and cumulative sections have the comma-formatted value
        lines = result.splitlines()
        # Line 3: session tokens saved; line 8: cumulative tokens saved
        # (blank line at index 4 separates the two sections)
        assert lines[3] == "  Tokens saved: 1,234,567"
        assert lines[8] == "  Tokens saved: 1,234,567"
        store.close()
