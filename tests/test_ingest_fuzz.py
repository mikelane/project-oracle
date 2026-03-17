"""Fuzz tests for drain_ingest_queue using Hypothesis."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from oracle.ingest import drain_ingest_queue


class DescribeIngestQueueFuzzing:
    @settings(max_examples=200)
    @given(payload=st.binary(max_size=10000))
    def it_handles_arbitrary_binary_without_crashing(self, payload: bytes) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue_dir = Path(td) / "ingest"
            queue_dir.mkdir()
            (queue_dir / "fuzz.json").write_bytes(payload)

            entries = drain_ingest_queue(queue_dir)

            assert isinstance(entries, list)

    @settings(max_examples=200)
    @given(payload=st.text(max_size=5000))
    def it_handles_arbitrary_text_without_crashing(self, payload: str) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue_dir = Path(td) / "ingest"
            queue_dir.mkdir()
            (queue_dir / "fuzz.json").write_text(payload)

            entries = drain_ingest_queue(queue_dir)

            assert isinstance(entries, list)

    @settings(max_examples=200)
    @given(
        data=st.dictionaries(
            keys=st.text(min_size=1, max_size=50),
            values=st.one_of(
                st.text(max_size=100),
                st.integers(),
                st.floats(allow_nan=False),
                st.booleans(),
                st.none(),
            ),
            max_size=20,
        )
    )
    def it_round_trips_valid_json_dicts(self, data: dict) -> None:  # type: ignore[type-arg]
        with tempfile.TemporaryDirectory() as td:
            queue_dir = Path(td) / "ingest"
            queue_dir.mkdir()
            (queue_dir / "fuzz.json").write_text(json.dumps(data))

            entries = drain_ingest_queue(queue_dir)

            assert len(entries) == 1
            assert entries[0] == data

    @settings(max_examples=200)
    @given(count=st.integers(min_value=0, max_value=50))
    def it_handles_variable_queue_sizes(self, count: int) -> None:
        with tempfile.TemporaryDirectory() as td:
            queue_dir = Path(td) / "ingest"
            queue_dir.mkdir()
            for i in range(count):
                (queue_dir / f"{i:04d}.json").write_text(json.dumps({"i": i}))

            entries = drain_ingest_queue(queue_dir)

            assert len(entries) == count
            # Files should be cleaned up
            remaining = list(queue_dir.glob("*.json"))
            assert remaining == []
