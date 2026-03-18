"""Tests for drain_ingest_queue — JSON ingest queue processor."""

from __future__ import annotations

import json
from pathlib import Path

from pytest_mock import MockerFixture

from oracle.ingest import drain_ingest_queue


class DescribeIngestQueue:
    def it_drains_json_files(self, tmp_path: Path) -> None:
        queue_dir = tmp_path / "ingest"
        queue_dir.mkdir()
        (queue_dir / "001.json").write_text(json.dumps({"tool": "read", "path": "a.py"}))
        (queue_dir / "002.json").write_text(json.dumps({"tool": "run", "cmd": "ls"}))

        entries = drain_ingest_queue(queue_dir)

        assert len(entries) == 2
        assert entries[0]["tool"] == "read"
        assert entries[1]["tool"] == "run"

    def it_removes_processed_files(self, tmp_path: Path) -> None:
        queue_dir = tmp_path / "ingest"
        queue_dir.mkdir()
        (queue_dir / "001.json").write_text(json.dumps({"key": "value"}))

        drain_ingest_queue(queue_dir)

        remaining = list(queue_dir.glob("*.json"))
        assert remaining == []

    def it_returns_empty_for_empty_queue(self, tmp_path: Path) -> None:
        queue_dir = tmp_path / "ingest"
        queue_dir.mkdir()

        entries = drain_ingest_queue(queue_dir)

        assert entries == []

    def it_skips_malformed_json(self, tmp_path: Path) -> None:
        queue_dir = tmp_path / "ingest"
        queue_dir.mkdir()
        (queue_dir / "bad.json").write_text("{not valid json!!!")
        (queue_dir / "good.json").write_text(json.dumps({"ok": True}))

        entries = drain_ingest_queue(queue_dir)

        assert len(entries) == 1
        assert entries[0]["ok"] is True

    def it_handles_nonexistent_queue_dir(self, tmp_path: Path) -> None:
        queue_dir = tmp_path / "does_not_exist"

        entries = drain_ingest_queue(queue_dir)

        assert entries == []

    def it_processes_files_in_sorted_order(self, tmp_path: Path) -> None:
        queue_dir = tmp_path / "ingest"
        queue_dir.mkdir()
        (queue_dir / "003.json").write_text(json.dumps({"order": 3}))
        (queue_dir / "001.json").write_text(json.dumps({"order": 1}))
        (queue_dir / "002.json").write_text(json.dumps({"order": 2}))

        entries = drain_ingest_queue(queue_dir)

        assert [e["order"] for e in entries] == [1, 2, 3]

    def it_removes_malformed_files_too(self, tmp_path: Path) -> None:
        queue_dir = tmp_path / "ingest"
        queue_dir.mkdir()
        (queue_dir / "bad.json").write_text("not json")

        drain_ingest_queue(queue_dir)

        remaining = list(queue_dir.glob("*.json"))
        assert remaining == []

    def it_ignores_non_json_files(self, tmp_path: Path) -> None:
        queue_dir = tmp_path / "ingest"
        queue_dir.mkdir()
        (queue_dir / "readme.txt").write_text("not a json file")
        (queue_dir / "data.json").write_text(json.dumps({"key": "val"}))

        entries = drain_ingest_queue(queue_dir)

        assert len(entries) == 1
        assert entries[0]["key"] == "val"
        # Non-json file should still exist
        assert (queue_dir / "readme.txt").exists()

    def it_continues_when_unlink_fails(self, tmp_path: Path, mocker: MockerFixture) -> None:
        queue_dir = tmp_path / "ingest"
        queue_dir.mkdir()
        (queue_dir / "001.json").write_text(json.dumps({"a": 1}))
        (queue_dir / "002.json").write_text(json.dumps({"b": 2}))

        original_unlink = Path.unlink

        def failing_unlink(self_path: Path, missing_ok: bool = False) -> None:
            if self_path.name == "001.json":
                raise OSError("permission denied")
            original_unlink(self_path, missing_ok=missing_ok)

        mocker.patch.object(Path, "unlink", failing_unlink)
        entries = drain_ingest_queue(queue_dir)

        # Both files were read successfully despite unlink failure on first
        assert len(entries) == 2
        assert entries[0]["a"] == 1
        assert entries[1]["b"] == 2
        # First file still exists (unlink failed), second was deleted
        assert (queue_dir / "001.json").exists()
        assert not (queue_dir / "002.json").exists()
