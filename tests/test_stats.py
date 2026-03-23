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

    def it_shows_cache_hit_rate_as_percentage(self, store: OracleStore) -> None:
        from oracle.tools.stats import handle_oracle_stats

        session_id = "sess-abc123"
        store.log_interaction(session_id, "oracle_read", "/a.py", True, 500, 1000)
        store.log_interaction(session_id, "oracle_read", "/b.py", True, 300, 2000)
        store.log_interaction(session_id, "oracle_grep", "pattern", False, 0, 3000)

        result = handle_oracle_stats(session_id, store)

        assert "Hit rate:" in result
        assert "67%" in result
        assert "(2/3 oracle calls)" in result
        assert "800" in result

    def it_shows_per_tool_adoption_rates(self, store: OracleStore) -> None:
        from oracle.tools.stats import handle_oracle_stats

        session_id = "sess-adopt"
        store.log_interaction(session_id, "oracle_read", "/a.py", True, 500, 1000)
        store.log_interaction(session_id, "builtin_read", None, False, 0, 2000)
        store.log_interaction(session_id, "builtin_read", None, False, 0, 3000)
        store.log_interaction(session_id, "builtin_read", None, False, 0, 4000)

        result = handle_oracle_stats(session_id, store)

        assert "Adoption" in result
        assert "read:" in result
        assert "25% oracle" in result
        assert "1 oracle / 3 built-in" in result

    def it_flags_unused_tools(self, store: OracleStore) -> None:
        from oracle.tools.stats import handle_oracle_stats

        session_id = "sess-unused"
        store.log_interaction(session_id, "builtin_grep", None, False, 0, 1000)
        store.log_interaction(session_id, "builtin_grep", None, False, 0, 2000)

        result = handle_oracle_stats(session_id, store)

        assert "grep:" in result
        assert "0% oracle" in result
        assert "<-- never used" in result

    def it_shows_trend_vs_recent_sessions(self, store: OracleStore) -> None:
        from oracle.tools.stats import handle_oracle_stats

        # Prior sessions
        for i in range(1, 4):
            store.log_interaction(f"old-{i}", "oracle_read", "/a.py", True, 100, i * 1000)
            store.log_interaction(f"old-{i}", "oracle_read", "/b.py", False, 0, i * 1000 + 1)
            store.log_interaction(f"old-{i}", "builtin_read", None, False, 0, i * 1000 + 2)

        # Current session: better
        store.log_interaction("current", "oracle_read", "/a.py", True, 500, 100_000)
        store.log_interaction("current", "oracle_read", "/b.py", True, 300, 100_001)

        result = handle_oracle_stats("current", store)

        assert "Trend" in result
        assert "now vs" in result
        assert "avg" in result

    def it_shows_cumulative_section(self, store: OracleStore) -> None:
        from oracle.tools.stats import handle_oracle_stats

        store.log_interaction("sess-1", "oracle_read", "/a.py", True, 500, 1000)
        store.log_interaction("sess-1", "oracle_read", "/b.py", True, 300, 2000)
        store.log_interaction("sess-2", "oracle_read", "/c.py", True, 200, 3000)
        store.log_interaction("sess-2", "oracle_grep", "pat", False, 0, 4000)
        store.log_interaction("sess-2", "builtin_read", None, False, 0, 5000)

        result = handle_oracle_stats("sess-1", store)

        assert "Cumulative" in result
        assert "Oracle calls:" in result
        assert "Built-in calls:" in result
        assert "Overall adoption:" in result
        assert "Cache hit rate:" in result
        assert "Tokens saved:" in result

    def it_returns_zeros_when_no_logs(self, store: OracleStore) -> None:
        from oracle.tools.stats import handle_oracle_stats

        result = handle_oracle_stats("empty-session", store)

        assert "Hit rate: 0%" in result
        assert "0 oracle calls" in result
        assert "Tokens saved: 0" in result

    def it_formats_oracle_health_header(self, store: OracleStore) -> None:
        from oracle.tools.stats import handle_oracle_stats

        store.log_interaction("sess-x", "oracle_read", "/a.py", True, 4500, 1000)

        result = handle_oracle_stats("sess-x", store)

        assert "=== Oracle Health (session sess-x) ===" in result
        assert "Cache Performance:" in result
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
