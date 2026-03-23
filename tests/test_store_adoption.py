"""Tests for OracleStore adoption visibility query methods."""

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
class DescribeGetToolBreakdown:
    def it_returns_per_tool_counts_for_session(self, store: OracleStore) -> None:
        store.log_interaction("sess-1", "oracle_read", "/a.py", True, 500, 1000)
        store.log_interaction("sess-1", "oracle_read", "/b.py", False, 0, 2000)
        store.log_interaction("sess-1", "oracle_grep", "pattern", True, 200, 3000)
        store.log_interaction("sess-1", "builtin_read", None, False, 0, 4000)
        store.log_interaction("sess-2", "oracle_read", "/c.py", True, 100, 5000)

        breakdown = store.get_tool_breakdown(session_id="sess-1")

        by_tool = {row["tool_name"]: row for row in breakdown}
        assert len(by_tool) == 3
        assert by_tool["oracle_read"]["count"] == 2
        assert by_tool["oracle_read"]["hits"] == 1
        assert by_tool["oracle_read"]["tokens_saved"] == 500
        assert by_tool["oracle_grep"]["count"] == 1
        assert by_tool["oracle_grep"]["hits"] == 1
        assert by_tool["builtin_read"]["count"] == 1
        assert by_tool["builtin_read"]["hits"] == 0

    def it_returns_cumulative_when_no_session_id(self, store: OracleStore) -> None:
        store.log_interaction("sess-1", "oracle_read", "/a.py", True, 500, 1000)
        store.log_interaction("sess-2", "oracle_read", "/b.py", True, 300, 2000)
        store.log_interaction("sess-2", "builtin_bash", None, False, 0, 3000)

        breakdown = store.get_tool_breakdown()

        by_tool = {row["tool_name"]: row for row in breakdown}
        assert by_tool["oracle_read"]["count"] == 2
        assert by_tool["oracle_read"]["tokens_saved"] == 800
        assert by_tool["builtin_bash"]["count"] == 1

    def it_returns_empty_list_when_no_data(self, store: OracleStore) -> None:
        breakdown = store.get_tool_breakdown(session_id="nonexistent")

        assert breakdown == []


@pytest.mark.medium
class DescribeGetAdoptionRates:
    def it_computes_read_adoption_rate(self, store: OracleStore) -> None:
        store.log_interaction("sess-1", "oracle_read", "/a.py", True, 500, 1000)
        store.log_interaction("sess-1", "builtin_read", None, False, 0, 2000)
        store.log_interaction("sess-1", "builtin_read", None, False, 0, 3000)
        store.log_interaction("sess-1", "builtin_read", None, False, 0, 4000)
        store.log_interaction("sess-1", "builtin_read", None, False, 0, 5000)

        rates = store.get_adoption_rates(session_id="sess-1")

        assert "read" in rates
        assert rates["read"]["oracle"] == 1
        assert rates["read"]["builtin"] == 4
        assert rates["read"]["rate"] == pytest.approx(0.2)

    def it_returns_zero_rate_when_only_builtin_calls(self, store: OracleStore) -> None:
        store.log_interaction("sess-1", "builtin_grep", None, False, 0, 1000)
        store.log_interaction("sess-1", "builtin_grep", None, False, 0, 2000)

        rates = store.get_adoption_rates(session_id="sess-1")

        assert rates["grep"]["oracle"] == 0
        assert rates["grep"]["builtin"] == 2
        assert rates["grep"]["rate"] == pytest.approx(0.0)

    def it_returns_full_rate_when_only_oracle_calls(self, store: OracleStore) -> None:
        store.log_interaction("sess-1", "oracle_run", "ls", False, 0, 1000)
        store.log_interaction("sess-1", "oracle_run", "pwd", True, 100, 2000)

        rates = store.get_adoption_rates(session_id="sess-1")

        assert rates["run"]["oracle"] == 2
        assert rates["run"]["builtin"] == 0
        assert rates["run"]["rate"] == pytest.approx(1.0)

    def it_handles_no_data(self, store: OracleStore) -> None:
        rates = store.get_adoption_rates(session_id="nonexistent")

        assert rates == {}

    def it_groups_oracle_run_and_builtin_bash_together(self, store: OracleStore) -> None:
        store.log_interaction("sess-1", "oracle_run", "ls", False, 0, 1000)
        store.log_interaction("sess-1", "builtin_bash", None, False, 0, 2000)
        store.log_interaction("sess-1", "builtin_bash", None, False, 0, 3000)

        rates = store.get_adoption_rates(session_id="sess-1")

        assert rates["run"]["oracle"] == 1
        assert rates["run"]["builtin"] == 2
        assert rates["run"]["rate"] == pytest.approx(1 / 3)

    def it_returns_cumulative_rates_when_no_session_id(self, store: OracleStore) -> None:
        store.log_interaction("sess-1", "oracle_read", "/a.py", True, 500, 1000)
        store.log_interaction("sess-2", "builtin_read", None, False, 0, 2000)

        rates = store.get_adoption_rates()

        assert rates["read"]["oracle"] == 1
        assert rates["read"]["builtin"] == 1
        assert rates["read"]["rate"] == pytest.approx(0.5)


@pytest.mark.medium
class DescribeGetSessionComparison:
    def it_compares_current_to_recent_average(self, store: OracleStore) -> None:
        # 5 prior sessions with ~20% hit rates and ~20% adoption
        for i in range(1, 6):
            store.log_interaction(f"old-{i}", "oracle_read", "/a.py", True, 100, i * 1000)
            store.log_interaction(f"old-{i}", "oracle_read", "/b.py", False, 0, i * 1000 + 1)
            store.log_interaction(f"old-{i}", "oracle_read", "/c.py", False, 0, i * 1000 + 2)
            store.log_interaction(f"old-{i}", "oracle_read", "/d.py", False, 0, i * 1000 + 3)
            store.log_interaction(f"old-{i}", "oracle_read", "/e.py", False, 0, i * 1000 + 4)
            store.log_interaction(f"old-{i}", "builtin_read", None, False, 0, i * 1000 + 5)
            store.log_interaction(f"old-{i}", "builtin_read", None, False, 0, i * 1000 + 6)
            store.log_interaction(f"old-{i}", "builtin_read", None, False, 0, i * 1000 + 7)
            store.log_interaction(f"old-{i}", "builtin_read", None, False, 0, i * 1000 + 8)
            store.log_interaction(f"old-{i}", "builtin_read", None, False, 0, i * 1000 + 9)

        # Current session: better hit rate and adoption
        store.log_interaction("current", "oracle_read", "/a.py", True, 500, 100_000)
        store.log_interaction("current", "oracle_read", "/b.py", True, 300, 100_001)
        store.log_interaction("current", "oracle_read", "/c.py", False, 0, 100_002)
        store.log_interaction("current", "builtin_read", None, False, 0, 100_003)

        comparison = store.get_session_comparison("current")

        assert comparison["current_hit_rate"] == pytest.approx(2 / 3, abs=0.01)
        assert comparison["avg_hit_rate"] == pytest.approx(1 / 5, abs=0.01)
        assert comparison["current_adoption_rate"] == pytest.approx(3 / 4, abs=0.01)
        assert comparison["avg_adoption_rate"] == pytest.approx(5 / 10, abs=0.01)
        assert comparison["trend"] == "improving"

    def it_returns_stable_when_no_prior_sessions(self, store: OracleStore) -> None:
        store.log_interaction("only-sess", "oracle_read", "/a.py", True, 500, 1000)

        comparison = store.get_session_comparison("only-sess")

        assert comparison["trend"] == "stable"
        assert comparison["current_hit_rate"] == pytest.approx(1.0)
        assert comparison["avg_hit_rate"] == pytest.approx(0.0)

    def it_returns_declining_when_current_is_worse(self, store: OracleStore) -> None:
        # Prior sessions with high hit rates
        for i in range(1, 4):
            store.log_interaction(f"old-{i}", "oracle_read", "/a.py", True, 100, i * 1000)
            store.log_interaction(f"old-{i}", "oracle_read", "/b.py", True, 100, i * 1000 + 1)

        # Current session: no hits
        store.log_interaction("current", "oracle_read", "/a.py", False, 0, 100_000)
        store.log_interaction("current", "oracle_read", "/b.py", False, 0, 100_001)
        store.log_interaction("current", "builtin_read", None, False, 0, 100_002)

        comparison = store.get_session_comparison("current")

        assert comparison["current_hit_rate"] == pytest.approx(0.0)
        assert comparison["avg_hit_rate"] == pytest.approx(1.0)
        assert comparison["trend"] == "declining"
