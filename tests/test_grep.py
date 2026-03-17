"""Tests for oracle_grep tool handler."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from oracle.tools.grep import handle_oracle_grep


@pytest.mark.medium
class DescribeOracleGrep:
    def it_finds_matching_pattern(self, tmp_path: Path) -> None:
        (tmp_path / "hello.py").write_text("def hello():\n    return 'world'\n")
        result = handle_oracle_grep("hello", str(tmp_path))
        assert "1 match" in result or "matches" in result
        assert "hello" in result

    def it_returns_no_matches_message(self, tmp_path: Path) -> None:
        (tmp_path / "hello.py").write_text("def hello():\n    return 'world'\n")
        result = handle_oracle_grep("zzz_nonexistent_zzz", str(tmp_path))
        assert "No matches" in result

    def it_caps_results_at_50(self, tmp_path: Path) -> None:
        # Create a file with more than 50 matching lines
        lines = [f"match_line_{i}" for i in range(100)]
        (tmp_path / "many.py").write_text("\n".join(lines) + "\n")
        result = handle_oracle_grep("match_line_", str(tmp_path))
        assert "50 matches" in result
        # Should contain the truncation notice
        assert "capped" in result.lower() or "truncated" in result.lower()

    def it_uses_singular_match_for_one_result(self, tmp_path: Path) -> None:
        (tmp_path / "single.py").write_text("unique_singleton_value\n")
        result = handle_oracle_grep("unique_singleton_value", str(tmp_path))
        assert result.startswith("1 match:")
        assert "matches" not in result.split("\n")[0]

    def it_uses_plural_matches_for_two_results(self, tmp_path: Path) -> None:
        (tmp_path / "two.py").write_text("dup_value\ndup_value\n")
        result = handle_oracle_grep("dup_value", str(tmp_path))
        assert result.startswith("2 matches:")

    def it_searches_multiple_file_types(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("target_pattern\n")
        (tmp_path / "util.ts").write_text("target_pattern\n")
        result = handle_oracle_grep("target_pattern", str(tmp_path))
        assert "app.py" in result
        assert "util.ts" in result

    def it_handles_nonexistent_path(self, tmp_path: Path) -> None:
        missing = str(tmp_path / "nonexistent_dir")
        result = handle_oracle_grep("pattern", missing)
        assert "No matches" in result

    def it_handles_grep_timeout(self, tmp_path: Path) -> None:
        (tmp_path / "file.py").write_text("content\n")
        with patch("oracle.tools.grep.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="grep", timeout=30)
            result = handle_oracle_grep("content", str(tmp_path))
            assert "No matches" in result

    def it_handles_oserror(self, tmp_path: Path) -> None:
        (tmp_path / "file.py").write_text("content\n")
        with patch("oracle.tools.grep.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("grep not found")
            result = handle_oracle_grep("content", str(tmp_path))
            assert "No matches" in result
