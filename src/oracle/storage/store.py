"""OracleStore — SQLite persistence layer for Project Oracle."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class OracleStore:
    """SQLite-backed storage for file cache, git state, command results, and agent logs."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

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
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
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
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
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

    def update_disk_sha256(self, path: str, disk_sha256: str) -> None:
        self._conn.execute(
            "UPDATE file_cache SET disk_sha256 = ? WHERE path = ?",
            (disk_sha256, path),
        )
        self._conn.commit()

    def all_cached_paths(self) -> list[str]:
        rows = self._conn.execute("SELECT path FROM file_cache").fetchall()
        return [row[0] for row in rows]

    def get_file_cache(self, path: str) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT * FROM file_cache WHERE path = ?", (path,)
        ).fetchone()
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

    def get_session_stats(self, session_id: str) -> dict[str, int]:
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
        if row is None or row["total_cache_hits"] is None:
            return {"total_cache_hits": 0, "total_tokens_saved": 0}
        return {
            "total_cache_hits": row["total_cache_hits"],
            "total_tokens_saved": row["total_tokens_saved"],
        }

    def evict_stale_files(self, max_age_days: int = 30, now: int | None = None) -> int:
        if now is None:
            now = int(time.time())
        cutoff = now - (max_age_days * 86400)
        cursor = self._conn.execute(
            "DELETE FROM file_cache WHERE last_read < ?", (cutoff,)
        )
        self._conn.commit()
        return cursor.rowcount

    def evict_stale_commands(self, max_age_hours: int = 24, now: int | None = None) -> int:
        if now is None:
            now = int(time.time())
        cutoff = now - (max_age_hours * 3600)
        cursor = self._conn.execute(
            "DELETE FROM command_results WHERE ran_at < ?", (cutoff,)
        )
        self._conn.commit()
        return cursor.rowcount
