"""OracleStore — SQLite persistence layer for Project Oracle."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import TypedDict, cast


class SessionStats(TypedDict):
    total_cache_hits: int
    total_tokens_saved: int


class ToolBreakdownRow(TypedDict):
    tool_name: str
    count: int
    hits: int
    tokens_saved: int


class AdoptionCategoryRate(TypedDict):
    oracle: int
    builtin: int
    rate: float


class SessionComparison(TypedDict):
    current_hit_rate: float
    avg_hit_rate: float
    current_adoption_rate: float
    avg_adoption_rate: float
    trend: str


_TREND_THRESHOLD: float = 0.05


def _in_clause(n: int) -> str:
    return ",".join("?" * n)


def _determine_trend(
    current_hit: float, avg_hit: float, current_adopt: float, avg_adopt: float
) -> str:
    combined_diff = (current_hit - avg_hit) + (current_adopt - avg_adopt)
    if combined_diff > _TREND_THRESHOLD:
        return "improving"
    if combined_diff < -_TREND_THRESHOLD:
        return "declining"
    return "stable"


class OracleStore:
    """SQLite-backed storage for file cache, git state, command results, and agent logs."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def __enter__(self) -> OracleStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS file_cache (
                path        TEXT PRIMARY KEY,
                content     BLOB,
                sha256      TEXT NOT NULL,
                disk_sha256 TEXT,
                first_seen  INTEGER NOT NULL,
                last_read   INTEGER NOT NULL,
                read_count  INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS git_state (
                id          INTEGER PRIMARY KEY,
                branch      TEXT NOT NULL,
                head_sha    TEXT NOT NULL,
                dirty_files TEXT,
                staged_files TEXT,
                recent_log  TEXT,
                captured_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS command_results (
                command     TEXT PRIMARY KEY,
                output      TEXT NOT NULL,
                exit_code   INTEGER,
                input_hash  TEXT,
                ran_at      INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_log (
                id           INTEGER PRIMARY KEY,
                session_id   TEXT NOT NULL,
                tool_name    TEXT NOT NULL,
                input        TEXT,
                cache_hit    INTEGER DEFAULT 0,
                tokens_saved INTEGER DEFAULT 0,
                ts           INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_file_cache_last_read ON file_cache(last_read);
            CREATE INDEX IF NOT EXISTS idx_agent_log_session ON agent_log(session_id);
            CREATE INDEX IF NOT EXISTS idx_command_results_ran ON command_results(ran_at);
            """
        )

    def close(self) -> None:
        self._conn.close()

    def upsert_file_cache(
        self,
        path: str,
        content: bytes,
        sha256: str,
        disk_sha256: str | None,
        timestamp: int,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO file_cache
                (path, content, sha256, disk_sha256, first_seen, last_read, read_count)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(path) DO UPDATE SET
                content = excluded.content,
                sha256 = excluded.sha256,
                disk_sha256 = excluded.disk_sha256,
                last_read = excluded.last_read,
                read_count = read_count + 1
            """,
            (path, content, sha256, disk_sha256, timestamp, timestamp),
        )
        self._conn.commit()

    def delete_file_cache(self, path: str) -> None:
        self._conn.execute("DELETE FROM file_cache WHERE path = ?", (path,))
        self._conn.commit()

    def update_disk_sha256(self, path: str, disk_sha256: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE file_cache SET disk_sha256 = ? WHERE path = ?",
            (disk_sha256, path),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def all_cached_paths(self) -> list[str]:
        rows = self._conn.execute("SELECT path FROM file_cache").fetchall()
        return [row[0] for row in rows]

    def get_file_cache(self, path: str) -> dict[str, object] | None:
        row = self._conn.execute("SELECT * FROM file_cache WHERE path = ?", (path,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def upsert_command_result(
        self,
        command: str,
        output: str,
        exit_code: int | None,
        input_hash: str | None,
        timestamp: int,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO command_results (command, output, exit_code, input_hash, ran_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(command) DO UPDATE SET
                output = excluded.output,
                exit_code = excluded.exit_code,
                input_hash = excluded.input_hash,
                ran_at = excluded.ran_at
            """,
            (command, output, exit_code, input_hash, timestamp),
        )
        self._conn.commit()

    def get_command_result(self, command: str) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT * FROM command_results WHERE command = ?", (command,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def log_interaction(
        self,
        session_id: str,
        tool_name: str,
        input_data: str | None,
        cache_hit: bool,
        tokens_saved: int,
        timestamp: int,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO agent_log (session_id, tool_name, input, cache_hit, tokens_saved, ts)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, tool_name, input_data, int(cache_hit), tokens_saved, timestamp),
        )
        self._conn.commit()

    def get_session_stats(self, session_id: str) -> SessionStats:
        row = self._conn.execute(
            """
            SELECT
                SUM(cache_hit) AS total_cache_hits,
                SUM(tokens_saved) AS total_tokens_saved
            FROM agent_log
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        # SUM() on empty result returns NULL for all columns simultaneously,
        # so checking one column is sufficient.
        if row is None or row["total_cache_hits"] is None:
            return {"total_cache_hits": 0, "total_tokens_saved": 0}
        return {
            "total_cache_hits": row["total_cache_hits"],
            "total_tokens_saved": row["total_tokens_saved"],
        }

    def get_cumulative_stats(self) -> SessionStats:
        row = self._conn.execute(
            """
            SELECT
                SUM(cache_hit) AS total_cache_hits,
                SUM(tokens_saved) AS total_tokens_saved
            FROM agent_log
            """
        ).fetchone()
        if row is None or row["total_cache_hits"] is None:
            return {"total_cache_hits": 0, "total_tokens_saved": 0}
        return {
            "total_cache_hits": row["total_cache_hits"],
            "total_tokens_saved": row["total_tokens_saved"],
        }

    def get_session_call_count(self, session_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM agent_log WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row["cnt"] if row is not None else 0

    def get_cumulative_call_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM agent_log").fetchone()
        return row["cnt"] if row is not None else 0

    def get_tool_breakdown(self, session_id: str | None = None) -> list[ToolBreakdownRow]:
        if session_id is not None:
            rows = self._conn.execute(
                """
                SELECT
                    tool_name,
                    COUNT(*) AS count,
                    SUM(cache_hit) AS hits,
                    SUM(tokens_saved) AS tokens_saved
                FROM agent_log
                WHERE session_id = ?
                GROUP BY tool_name
                ORDER BY COUNT(*) DESC
                """,
                (session_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT
                    tool_name,
                    COUNT(*) AS count,
                    SUM(cache_hit) AS hits,
                    SUM(tokens_saved) AS tokens_saved
                FROM agent_log
                GROUP BY tool_name
                ORDER BY COUNT(*) DESC
                """
            ).fetchall()
        return [cast(ToolBreakdownRow, dict(row)) for row in rows]

    def get_adoption_rates(self, session_id: str | None = None) -> dict[str, AdoptionCategoryRate]:
        breakdown = self.get_tool_breakdown(session_id)
        if not breakdown:
            return {}

        # Map tool names to categories
        category_map = {
            "oracle_read": "read",
            "builtin_read": "read",
            "oracle_grep": "grep",
            "builtin_grep": "grep",
            "oracle_run": "run",
            "builtin_bash": "run",
        }

        categories: dict[str, dict[str, int]] = {}
        for row in breakdown:
            tool = row["tool_name"]
            category = category_map.get(tool)
            if category is None:
                continue

            if category not in categories:
                categories[category] = {"oracle": 0, "builtin": 0}

            count = row["count"]
            if tool.startswith("oracle_"):
                categories[category]["oracle"] += count
            else:
                categories[category]["builtin"] += count

        result: dict[str, AdoptionCategoryRate] = {}
        for category, counts in categories.items():
            total = counts["oracle"] + counts["builtin"]
            rate = counts["oracle"] / total if total > 0 else 0.0
            result[category] = AdoptionCategoryRate(
                oracle=counts["oracle"],
                builtin=counts["builtin"],
                rate=rate,
            )

        return result

    def get_session_comparison(self, session_id: str) -> SessionComparison:
        current_hit_rate, current_adoption_rate = self._current_session_rates(session_id)

        other_sessions = self._conn.execute(
            """
            SELECT session_id
            FROM agent_log
            WHERE session_id != ?
            GROUP BY session_id
            ORDER BY MAX(ts) DESC
            LIMIT 5
            """,
            (session_id,),
        ).fetchall()

        if not other_sessions:
            return SessionComparison(
                current_hit_rate=current_hit_rate,
                avg_hit_rate=0.0,
                current_adoption_rate=current_adoption_rate,
                avg_adoption_rate=0.0,
                trend="stable",
            )

        session_ids = [row["session_id"] for row in other_sessions]
        avg_hit_rate, avg_adoption_rate = self._recent_session_averages(session_ids)
        trend = _determine_trend(
            current_hit_rate, avg_hit_rate, current_adoption_rate, avg_adoption_rate
        )

        return SessionComparison(
            current_hit_rate=current_hit_rate,
            avg_hit_rate=avg_hit_rate,
            current_adoption_rate=current_adoption_rate,
            avg_adoption_rate=avg_adoption_rate,
            trend=trend,
        )

    def _current_session_rates(self, session_id: str) -> tuple[float, float]:
        oracle_row = self._conn.execute(
            """
            SELECT COUNT(*) AS total, SUM(cache_hit) AS hits
            FROM agent_log
            WHERE session_id = ? AND tool_name LIKE 'oracle_%'
            """,
            (session_id,),
        ).fetchone()

        total_row = self._conn.execute(
            "SELECT COUNT(*) AS total FROM agent_log WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        oracle_total = oracle_row["total"] if oracle_row else 0
        oracle_hits = oracle_row["hits"] if oracle_row and oracle_row["hits"] else 0
        all_total = total_row["total"] if total_row else 0

        hit_rate = oracle_hits / oracle_total if oracle_total > 0 else 0.0
        adoption_rate = oracle_total / all_total if all_total > 0 else 0.0
        return hit_rate, adoption_rate

    def _recent_session_averages(self, session_ids: list[str]) -> tuple[float, float]:
        placeholders = _in_clause(len(session_ids))

        oracle_rows = self._conn.execute(
            f"""
            SELECT session_id,
                   COUNT(*) AS total,
                   SUM(cache_hit) AS hits
            FROM agent_log
            WHERE session_id IN ({placeholders}) AND tool_name LIKE 'oracle_%'
            GROUP BY session_id
            """,
            session_ids,
        ).fetchall()

        total_rows = self._conn.execute(
            f"""
            SELECT session_id, COUNT(*) AS total
            FROM agent_log
            WHERE session_id IN ({placeholders})
            GROUP BY session_id
            """,
            session_ids,
        ).fetchall()

        hit_rates = []
        for row in oracle_rows:
            total = row["total"]
            hits = row["hits"] or 0
            if total > 0:
                hit_rates.append(hits / total)

        adoption_rates = []
        oracle_by_session = {row["session_id"]: row["total"] for row in oracle_rows}
        total_by_session = {row["session_id"]: row["total"] for row in total_rows}
        for sid in session_ids:
            oracle_count = oracle_by_session.get(sid, 0)
            total_count = total_by_session.get(sid, 0)
            if total_count > 0:
                adoption_rates.append(oracle_count / total_count)

        avg_hit = sum(hit_rates) / len(hit_rates) if hit_rates else 0.0
        avg_adoption = sum(adoption_rates) / len(adoption_rates) if adoption_rates else 0.0
        return avg_hit, avg_adoption

    def evict_stale_files(self, max_age_days: int = 30, now: int | None = None) -> int:
        if now is None:
            now = int(time.time())
        cutoff = now - (max_age_days * 86400)
        cursor = self._conn.execute("DELETE FROM file_cache WHERE last_read < ?", (cutoff,))
        self._conn.commit()
        return cursor.rowcount

    def evict_stale_commands(self, max_age_hours: int = 24, now: int | None = None) -> int:
        if now is None:
            now = int(time.time())
        cutoff = now - (max_age_hours * 3600)
        cursor = self._conn.execute("DELETE FROM command_results WHERE ran_at < ?", (cutoff,))
        self._conn.commit()
        return cursor.rowcount
