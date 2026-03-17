"""Bug hunt tests — proving suspected bugs with failing tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from oracle.storage.store import OracleStore


@pytest.mark.medium
class DescribeOracleStatusCacheHitLogging:
    """oracle_status logs cache_hit/tokens_saved by calling get_delta_with_stats()
    AFTER handle_oracle_status() calls refresh(). Since refresh() sets _last_snapshot
    to current, get_delta_with_stats() always sees 'no changes' and reports a cache hit
    even on the very first call. This inflates token savings stats."""

    def it_reports_cache_miss_on_first_oracle_status_call(
        self, git_project: Path, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        """The very first oracle_status call returns fresh data — it is NOT a cache hit.
        But the current code logs it as a hit because refresh() poisons the delta check."""
        from oracle.server import oracle_status

        oracle_dir = tmp_path / ".oracle"
        oracle_dir.mkdir()
        (oracle_dir / "projects").mkdir()

        from oracle.registry import ProjectRegistry

        registry = ProjectRegistry(oracle_dir)

        mocker.patch("oracle.server._registry", registry)
        # First, read a file so registry.current() is set
        from oracle.server import oracle_read

        oracle_read(str(git_project / "file.py"))

        project = registry.current()
        assert project is not None
        assert project.store is not None

        # Now call oracle_status for the first time
        oracle_status()

        # Check the agent_log — the oracle_status entry should be a cache miss
        rows = project.store._conn.execute(
            "SELECT * FROM agent_log WHERE tool_name = 'oracle_status'"
        ).fetchall()
        assert len(rows) >= 1
        # BUG: This assertion will fail because the code always logs cache_hit=1
        # due to refresh() being called before get_delta_with_stats()
        assert rows[0]["cache_hit"] == 0, (
            "First oracle_status call should be a cache miss, "
            f"but got cache_hit={rows[0]['cache_hit']}"
        )


@pytest.mark.medium
class DescribeIngestBridgeToolInputNotDict:
    """process_ingest crashes with AttributeError when tool_input is not a dict.

    entry.get("tool_input", {}).get("file_path") — the default {} only applies
    when the key is missing. If tool_input is present but is a string, list, or int,
    calling .get() on it raises AttributeError.
    """

    def it_handles_non_dict_tool_input_without_crashing(
        self, tmp_path: Path
    ) -> None:
        from oracle.ingest_bridge import process_ingest
        from oracle.registry import ProjectRegistry

        oracle_dir = tmp_path / ".project-oracle"
        oracle_dir.mkdir()
        (oracle_dir / "projects").mkdir()
        queue_dir = oracle_dir / "ingest"
        queue_dir.mkdir()

        # Write a Read entry where tool_input is a string, not a dict
        entry = {"tool_name": "Read", "tool_input": "/some/path.py"}
        (queue_dir / "000001.json").write_text(json.dumps(entry))

        registry = ProjectRegistry(oracle_dir)

        # BUG: This will raise AttributeError: 'str' object has no attribute 'get'
        count = process_ingest(registry, oracle_dir, lambda p: None)
        assert count == 0


@pytest.mark.medium
class DescribeCommandCacheHashRaceCondition:
    """_hash_source_files collects files via rglob then stats them in a second pass.
    If a file is deleted between collection and stat, FileNotFoundError crashes the hash."""

    def it_handles_file_deleted_between_rglob_and_stat(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        from oracle.cache.command_cache import CommandCache

        project = tmp_path / "proj"
        project.mkdir()
        src = project / "src"
        src.mkdir()
        (src / "a.py").write_text("a = 1\n")
        ephemeral = src / "b.py"
        ephemeral.write_text("b = 2\n")

        store = OracleStore(tmp_path / "oracle.db")
        cache = CommandCache(store, project)

        # Patch Path.stat to simulate file deletion after rglob collects it
        original_stat = Path.stat

        def flaky_stat(self_path: Path, *args: object, **kwargs: object) -> object:
            if self_path.name == "b.py":
                raise FileNotFoundError(f"No such file: {self_path}")
            return original_stat(self_path, *args, **kwargs)

        mocker.patch.object(Path, "stat", flaky_stat)
        # BUG: This crashes with FileNotFoundError
        result = cache._hash_source_files()
        # Should return a valid hash (just skipping the missing file)
        assert isinstance(result, str)
        assert len(result) == 16
