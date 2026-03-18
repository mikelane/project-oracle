"""Concurrent access tests — verify thread safety of cache and ingest operations."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from oracle.cache.file_cache import FileCache
from oracle.ingest import drain_ingest_queue
from oracle.storage.store import OracleStore


@pytest.mark.medium
class DescribeConcurrentReads:
    @pytest.mark.asyncio
    async def it_handles_simultaneous_reads_without_corruption(
        self, tmp_project: Path, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "state.db"
        file_path = str(tmp_project / "src" / "main.py")

        # Populate the cache with a first read so subsequent reads are cache hits
        store = OracleStore(db_path)
        cache = FileCache(store)
        cache.smart_read(file_path)
        store.close()

        def read_in_thread(i: int) -> str:
            """Each thread gets its own store/cache — the realistic concurrency pattern."""
            s = OracleStore(db_path)
            c = FileCache(s)
            result = c.smart_read(file_path)
            s.close()
            return result

        results = await asyncio.gather(
            *[asyncio.to_thread(read_in_thread, i) for i in range(10)]
        )
        # Each thread has a fresh FileCache (new session), so gets full content
        # (not "No changes"). Verify no corruption: all results are identical.
        assert all(r == results[0] for r in results)


@pytest.mark.medium
class DescribeConcurrentIngest:
    def it_handles_simultaneous_writes(self, tmp_path: Path) -> None:
        queue_dir = tmp_path / "ingest"
        queue_dir.mkdir()

        def write_entry(i: int) -> None:
            (queue_dir / f"{i:010d}.json").write_text(
                f'{{"tool_name": "Read", "id": {i}}}'
            )

        threads = [threading.Thread(target=write_entry, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        entries = drain_ingest_queue(queue_dir)
        assert len(entries) == 50
