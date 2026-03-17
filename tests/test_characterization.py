"""Characterization tests — golden-file tests pinning output formats for refactoring safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from oracle.cache.file_cache import FileCache
from oracle.storage.store import OracleStore
from oracle.tools.forget import handle_oracle_forget


@pytest.mark.medium
class DescribeFileCacheCharacterization:
    def it_produces_stable_no_change_format(
        self, tmp_project: Path, tmp_path: Path
    ) -> None:
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)
        file_path = str(tmp_project / "src" / "main.py")
        cache.smart_read(file_path)
        result = cache.smart_read(file_path)
        assert result.startswith("No changes since last read (")
        assert "ago)" in result
        store.close()

    def it_produces_stable_delta_format(
        self, tmp_project: Path, tmp_path: Path
    ) -> None:
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)
        file_path = tmp_project / "src" / "main.py"
        cache.smart_read(str(file_path))
        file_path.write_text("def hello():\n    return 'changed'\n")
        result = cache.smart_read(str(file_path))
        assert result.startswith("Changed since last read:")
        assert "@@" in result  # unified diff marker
        store.close()

    def it_produces_stable_forget_confirmation(
        self, tmp_project: Path, tmp_path: Path
    ) -> None:
        store = OracleStore(tmp_path / "state.db")
        cache = FileCache(store)
        file_path = str(tmp_project / "src" / "main.py")
        result = handle_oracle_forget(file_path, cache)
        assert "Cache cleared for" in result
        assert "Next oracle_read will return full content" in result
        store.close()
