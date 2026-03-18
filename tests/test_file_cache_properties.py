"""Property tests for FileCache using Hypothesis."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oracle.cache.file_cache import FileCache, _compute_delta
from oracle.storage.store import OracleStore


@pytest.mark.medium
class DescribeFileCacheProperties:
    @given(content=st.text(min_size=1, max_size=10000))
    @settings(max_examples=200)
    def it_round_trips_any_content_through_compression(self, content: str) -> None:
        """Write content to file, smart_read, verify matches what read_text returns.

        Note: write_text/read_text normalize line endings (e.g. \\r -> \\n),
        so we compare against the normalized content, not the raw input.
        """
        tmp = Path(tempfile.mkdtemp())
        try:
            store = OracleStore(tmp / "rt.db")
            fc = FileCache(store)
            f = tmp / "roundtrip.txt"
            f.write_text(content)
            expected = f.read_text()  # normalized by Python's universal newline handling
            result = fc.smart_read(str(f))
            assert result == expected
            store.close()
        finally:
            shutil.rmtree(tmp)

    @given(
        old=st.text(min_size=1, max_size=5000),
        new=st.text(min_size=1, max_size=5000),
    )
    def it_produces_a_string_delta_for_any_content_pair(self, old: str, new: str) -> None:
        """_compute_delta always returns a string, never crashes."""
        delta = _compute_delta(old, new)
        assert isinstance(delta, str)

    @given(content=st.text(min_size=1, max_size=5000))
    @settings(max_examples=200)
    def it_always_returns_no_changes_on_immediate_reread(self, content: str) -> None:
        """First read, then immediate second read, always 'No changes'."""
        tmp = Path(tempfile.mkdtemp())
        try:
            store = OracleStore(tmp / "reread.db")
            fc = FileCache(store)
            f = tmp / "stable.txt"
            f.write_text(content)
            fc.smart_read(str(f))  # first read
            result = fc.smart_read(str(f))  # immediate reread
            assert result.startswith("No changes since last read")
            store.close()
        finally:
            shutil.rmtree(tmp)
