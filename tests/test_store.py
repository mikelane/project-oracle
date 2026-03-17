"""Tests for OracleStore — SQLite persistence layer."""

from __future__ import annotations

import sqlite3
import time
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
class DescribeOracleStoreInit:
    def it_creates_db_file_on_disk(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nested" / "dir" / "oracle.db"
        store = OracleStore(db_path)
        try:
            assert db_path.exists()
        finally:
            store.close()

    def it_supports_context_manager(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ctx.db"
        with OracleStore(db_path) as store:
            store.upsert_file_cache("a.py", b"a", "h1", None, 1000)
        # Connection is closed after with-block; verify data persisted
        with OracleStore(db_path) as store:
            assert store.get_file_cache("a.py") is not None

    def it_is_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "oracle.db"
        store1 = OracleStore(db_path)
        store1.close()
        store2 = OracleStore(db_path)
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = sorted(
                row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")
            )
            conn.close()
            assert tables == ["agent_log", "command_results", "file_cache", "git_state"]
        finally:
            store2.close()

    def it_creates_all_tables_on_init(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sub" / "oracle.db"
        store = OracleStore(db_path)
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = sorted(
                row[0]
                for row in cursor.fetchall()
                if not row[0].startswith("sqlite_")
            )
            conn.close()
            assert tables == ["agent_log", "command_results", "file_cache", "git_state"]
        finally:
            store.close()


@pytest.mark.medium
class DescribeFileCacheOperations:
    def it_upserts_and_retrieves_entries(self, store: OracleStore) -> None:
        store.upsert_file_cache("src/main.py", b"print('hello')", "abc123", None, 1000)
        result = store.get_file_cache("src/main.py")
        assert result is not None
        assert result["path"] == "src/main.py"
        assert result["content"] == b"print('hello')"
        assert result["sha256"] == "abc123"
        assert result["disk_sha256"] is None
        assert result["first_seen"] == 1000
        assert result["last_read"] == 1000
        assert result["read_count"] == 1

    def it_increments_read_count_on_upsert(self, store: OracleStore) -> None:
        store.upsert_file_cache("src/main.py", b"v1", "aaa", None, 1000)
        store.upsert_file_cache("src/main.py", b"v2", "bbb", None, 2000)
        result = store.get_file_cache("src/main.py")
        assert result is not None
        assert result["read_count"] == 2
        assert result["content"] == b"v2"
        assert result["sha256"] == "bbb"
        assert result["first_seen"] == 1000
        assert result["last_read"] == 2000

    def it_returns_none_for_missing_path(self, store: OracleStore) -> None:
        assert store.get_file_cache("nonexistent.py") is None

    def it_deletes_entries(self, store: OracleStore) -> None:
        store.upsert_file_cache("src/main.py", b"data", "abc", None, 1000)
        store.delete_file_cache("src/main.py")
        assert store.get_file_cache("src/main.py") is None

    def it_updates_disk_sha256(self, store: OracleStore) -> None:
        store.upsert_file_cache("src/main.py", b"data", "abc", None, 1000)
        updated = store.update_disk_sha256("src/main.py", "disk_hash_999")
        assert updated is True
        result = store.get_file_cache("src/main.py")
        assert result is not None
        assert result["disk_sha256"] == "disk_hash_999"

    def it_returns_false_when_updating_disk_sha256_for_missing_path(
        self, store: OracleStore
    ) -> None:
        updated = store.update_disk_sha256("nonexistent.py", "some_hash")
        assert updated is False

    def it_lists_all_cached_paths(self, store: OracleStore) -> None:
        store.upsert_file_cache("a.py", b"a", "h1", None, 1000)
        store.upsert_file_cache("b.py", b"b", "h2", None, 1000)
        store.upsert_file_cache("c.py", b"c", "h3", None, 1000)
        paths = store.all_cached_paths()
        assert sorted(paths) == ["a.py", "b.py", "c.py"]


@pytest.mark.medium
class DescribeCommandResults:
    def it_upserts_and_retrieves(self, store: OracleStore) -> None:
        store.upsert_command_result("git status", "clean", 0, "hash1", 5000)
        result = store.get_command_result("git status")
        assert result is not None
        assert result["command"] == "git status"
        assert result["output"] == "clean"
        assert result["exit_code"] == 0
        assert result["input_hash"] == "hash1"
        assert result["ran_at"] == 5000

    def it_returns_none_for_missing(self, store: OracleStore) -> None:
        assert store.get_command_result("nonexistent") is None


@pytest.mark.medium
class DescribeAgentLog:
    def it_logs_and_queries_session_stats(self, store: OracleStore) -> None:
        store.log_interaction("sess-1", "oracle_read", "input1", True, 500, 1000)
        store.log_interaction("sess-1", "oracle_read", "input2", True, 300, 2000)
        stats = store.get_session_stats("sess-1")
        assert stats["total_cache_hits"] == 2
        assert stats["total_tokens_saved"] == 800

    def it_counts_only_cache_hits(self, store: OracleStore) -> None:
        store.log_interaction("sess-2", "oracle_read", "input1", True, 500, 1000)
        store.log_interaction("sess-2", "oracle_read", "input2", False, 0, 2000)
        store.log_interaction("sess-2", "oracle_run", "input3", True, 200, 3000)
        stats = store.get_session_stats("sess-2")
        assert stats["total_cache_hits"] == 2
        assert stats["total_tokens_saved"] == 700

    def it_returns_zero_stats_for_unknown_session(self, store: OracleStore) -> None:
        stats = store.get_session_stats("nonexistent-session")
        assert stats["total_cache_hits"] == 0
        assert stats["total_tokens_saved"] == 0


@pytest.mark.medium
class DescribeEviction:
    def it_evicts_files_older_than_max_age(self, store: OracleStore) -> None:
        now = 1_000_000
        old_ts = now - (31 * 86400)  # 31 days ago
        store.upsert_file_cache("old.py", b"old", "h1", None, old_ts)
        count = store.evict_stale_files(max_age_days=30, now=now)
        assert count == 1
        assert store.get_file_cache("old.py") is None

    def it_preserves_recent_files(self, store: OracleStore) -> None:
        now = 1_000_000
        recent_ts = now - (10 * 86400)  # 10 days ago
        store.upsert_file_cache("recent.py", b"new", "h2", None, recent_ts)
        count = store.evict_stale_files(max_age_days=30, now=now)
        assert count == 0
        assert store.get_file_cache("recent.py") is not None

    def it_evicts_commands_older_than_max_hours(self, store: OracleStore) -> None:
        now = 100_000
        old_ts = now - (25 * 3600)  # 25 hours ago
        store.upsert_command_result("old cmd", "out", 0, None, old_ts)
        count = store.evict_stale_commands(max_age_hours=24, now=now)
        assert count == 1
        assert store.get_command_result("old cmd") is None

    def it_evicts_stale_files_using_current_time_by_default(self, store: OracleStore) -> None:
        old_ts = int(time.time()) - (31 * 86400)
        store.upsert_file_cache("/old.py", b"old", "a", "a", old_ts)
        count = store.evict_stale_files()
        assert count == 1

    def it_evicts_stale_commands_using_current_time_by_default(self, store: OracleStore) -> None:
        old_ts = int(time.time()) - (25 * 3600)
        store.upsert_command_result("old-cmd", "out", 0, "h1", old_ts)
        count = store.evict_stale_commands()
        assert count == 1

    def it_returns_count_of_evicted_entries(self, store: OracleStore) -> None:
        now = 1_000_000
        old_ts = now - (31 * 86400)
        store.upsert_file_cache("a.py", b"a", "h1", None, old_ts)
        store.upsert_file_cache("b.py", b"b", "h2", None, old_ts)
        store.upsert_file_cache("c.py", b"c", "h3", None, now)  # recent, keep
        count = store.evict_stale_files(max_age_days=30, now=now)
        assert count == 2
