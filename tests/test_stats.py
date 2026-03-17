"""Tests for oracle_stats tool and cumulative store methods."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from oracle.storage.store import OracleStore


@pytest.fixture
def store(tmp_path: Path) -> Generator[OracleStore, None, None]:
    db_path = tmp_path / "oracle.db"
    s = OracleStore(db_path)
    yield s
    s.close()


@pytest.mark.medium
class DescribeOracleStats:
    """Tests for the handle_oracle_stats tool handler."""

    def it_returns_session_stats(self, store: OracleStore) -> None:
        from oracle.tools.stats import handle_oracle_stats

        session_id = "sess-abc123"
        store.log_interaction(session_id, "oracle_read", "/a.py", True, 500, 1000)
        store.log_interaction(session_id, "oracle_read", "/b.py", True, 300, 2000)
        store.log_interaction(session_id, "oracle_grep", "pattern", False, 0, 3000)

        result = handle_oracle_stats(session_id, store)
        assert "Session (sess-abc123):" in result
        assert "Tool calls: 3" in result
        assert "Cache hits: 2" in result
        assert "Tokens saved: 800" in result

    def it_returns_cumulative_stats(self, store: OracleStore) -> None:
        from oracle.tools.stats import handle_oracle_stats

        store.log_interaction("sess-1", "oracle_read", "/a.py", True, 500, 1000)
        store.log_interaction("sess-1", "oracle_read", "/b.py", True, 300, 2000)
        store.log_interaction("sess-2", "oracle_read", "/c.py", True, 200, 3000)
        store.log_interaction("sess-2", "oracle_grep", "pat", False, 0, 4000)

        result = handle_oracle_stats("sess-1", store)
        assert "All sessions:" in result
        assert "Tool calls: 4" in result
        assert "Cache hits: 3" in result
        assert "Tokens saved: 1,000" in result

    def it_returns_zeros_when_no_logs(self, store: OracleStore) -> None:
        from oracle.tools.stats import handle_oracle_stats

        result = handle_oracle_stats("empty-session", store)
        assert "Tool calls: 0" in result
        assert "Cache hits: 0" in result
        assert "Tokens saved: 0" in result

    def it_formats_as_readable_text(self, store: OracleStore) -> None:
        from oracle.tools.stats import handle_oracle_stats

        store.log_interaction("sess-x", "oracle_read", "/a.py", True, 4500, 1000)

        result = handle_oracle_stats("sess-x", store)
        assert "Session (" in result
        assert "Cache hits:" in result
        assert "Tokens saved:" in result
        assert "All sessions:" in result
        assert "4,500" in result


@pytest.mark.medium
class DescribeStoreCumulativeStats:
    """Tests for OracleStore.get_cumulative_stats and call count methods."""

    def it_returns_cumulative_stats_across_sessions(self, store: OracleStore) -> None:
        store.log_interaction("sess-1", "oracle_read", "/a.py", True, 500, 1000)
        store.log_interaction("sess-1", "oracle_read", "/b.py", True, 300, 2000)
        store.log_interaction("sess-2", "oracle_read", "/c.py", True, 200, 3000)
        store.log_interaction("sess-2", "oracle_grep", "pat", False, 0, 4000)

        stats = store.get_cumulative_stats()
        assert stats["total_cache_hits"] == 3
        assert stats["total_tokens_saved"] == 1000

    def it_returns_zeros_when_empty(self, store: OracleStore) -> None:
        stats = store.get_cumulative_stats()
        assert stats["total_cache_hits"] == 0
        assert stats["total_tokens_saved"] == 0

    def it_returns_session_call_count(self, store: OracleStore) -> None:
        store.log_interaction("sess-1", "oracle_read", "/a.py", True, 500, 1000)
        store.log_interaction("sess-1", "oracle_read", "/b.py", False, 0, 2000)
        store.log_interaction("sess-2", "oracle_grep", "pat", False, 0, 3000)

        assert store.get_session_call_count("sess-1") == 2
        assert store.get_session_call_count("sess-2") == 1
        assert store.get_session_call_count("nonexistent") == 0

    def it_returns_cumulative_call_count(self, store: OracleStore) -> None:
        store.log_interaction("sess-1", "oracle_read", "/a.py", True, 500, 1000)
        store.log_interaction("sess-1", "oracle_read", "/b.py", False, 0, 2000)
        store.log_interaction("sess-2", "oracle_grep", "pat", False, 0, 3000)

        assert store.get_cumulative_call_count() == 3

    def it_returns_zero_cumulative_call_count_when_empty(self, store: OracleStore) -> None:
        assert store.get_cumulative_call_count() == 0
