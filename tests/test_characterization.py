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
    def it_produces_stable_no_change_format(self, tmp_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)
        file_path = str(tmp_project / "src" / "main.py")
        cache.smart_read(file_path)
        result = cache.smart_read(file_path)
        assert result.startswith("No changes since last read (")
        assert "ago)" in result
        store.close()

    def it_produces_stable_delta_format(self, tmp_project: Path, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)
        file_path = tmp_project / "src" / "main.py"
        cache.smart_read(str(file_path))
        file_path.write_text("def hello():\n    return 'changed'\n")
        result = cache.smart_read(str(file_path))
        assert result.startswith("Changed since last read:")
        assert "@@" in result  # unified diff marker
        store.close()

    def it_produces_stable_forget_confirmation(self, tmp_project: Path, tmp_path: Path) -> None:
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

        assert "=== Oracle Health (session sess-abc-123) ===" in result
        assert "Hit rate: 67% (2/3 oracle calls)" in result
        assert "Tokens saved: 800 this session" in result
        assert "=== Cumulative ===" in result
        assert "Oracle calls: 4" in result
        assert "Tokens saved: 2,000" in result
        store.close()

    def it_produces_stable_stats_format_with_no_activity(self, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "stats-empty.db")

        result = handle_oracle_stats("unused-session", store)

        assert "=== Oracle Health (session unused-session) ===" in result
        assert "Hit rate: 0% (0/0 oracle calls)" in result
        assert "Tokens saved: 0 this session" in result
        assert "=== Cumulative ===" in result
        store.close()

    def it_formats_large_token_counts_with_commas(self, tmp_path: Path) -> None:
        store = OracleStore(tmp_path / "stats-large.db")
        session_id = "sess-large"
        now = int(time.time())

        store.log_interaction(session_id, "oracle_read", "/big.py", True, 1_234_567, now)

        result = handle_oracle_stats(session_id, store)

        assert "Tokens saved: 1,234,567 this session" in result
        assert "Tokens saved: 1,234,567" in result
        store.close()


@pytest.mark.medium
class DescribeCrossSessionCharacterization:
    def it_produces_full_content_on_cross_session_read(
        self, tmp_project: Path, tmp_path: Path
    ) -> None:
        store = OracleStore(tmp_path / "cross.db")
        file_path = str(tmp_project / "src" / "main.py")
        raw_content = (tmp_project / "src" / "main.py").read_text()

        # Session A: populate cache
        cache_a = FileCache(store)
        cache_a.smart_read(file_path)

        # Session B: fresh FileCache, same store
        cache_b = FileCache(store)
        result = cache_b.smart_read(file_path)

        # Must be exactly the raw file content — no prefix, no wrapper
        assert result == raw_content
        assert not result.startswith("No changes")
        assert not result.startswith("Changed since")

        store.close()
