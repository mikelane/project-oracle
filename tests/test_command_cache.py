"""Tests for CommandCache — command result caching with allowlist and shell injection hardening."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from oracle.cache.command_cache import (
    _CHAIN_OPERATORS,
    DEFAULT_ALLOWLIST,
    CommandCache,
    CommandNotAllowedError,
    _format_elapsed,
)
from oracle.storage.store import OracleStore


@pytest.fixture
def store(tmp_path: Path) -> Generator[OracleStore, None, None]:
    db_path = tmp_path / "oracle.db"
    s = OracleStore(db_path)
    yield s
    s.close()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a minimal project directory with source files."""
    project = tmp_path / "myproject"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("def main(): pass\n")
    (project / "src" / "util.py").write_text("def helper(): pass\n")
    return project


@pytest.fixture
def cache(store: OracleStore, project: Path) -> CommandCache:
    return CommandCache(store, project)


@pytest.mark.small
class DescribeFormatElapsed:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (5, "5s"),
            (59, "59s"),
            (60, "1m"),
            (120, "2m"),
            (3599, "59m"),
            (3600, "1h"),
            (7200, "2h"),
        ],
        ids=[
            "five_seconds",
            "fifty_nine_seconds",
            "one_minute",
            "two_minutes",
            "fifty_nine_minutes",
            "one_hour",
            "two_hours",
        ],
    )
    def it_formats_elapsed_time(self, seconds: int, expected: str) -> None:
        assert _format_elapsed(seconds) == expected


@pytest.mark.small
class DescribeChainOperatorsRegex:
    @pytest.mark.parametrize(
        "operator",
        [";", "&", "|", "`", "$", "(", ")"],
    )
    def it_matches_shell_chain_operators(self, operator: str) -> None:
        assert _CHAIN_OPERATORS.search(f"echo {operator} something") is not None

    def it_does_not_match_safe_characters(self) -> None:
        assert _CHAIN_OPERATORS.search("pytest tests/ -v --tb=short") is None


@pytest.mark.small
class DescribeDefaultAllowlist:
    def it_contains_common_dev_commands(self) -> None:
        expected = {"pytest", "ruff", "mypy", "echo", "tsc", "eslint"}
        for cmd in expected:
            assert cmd in DEFAULT_ALLOWLIST


@pytest.mark.medium
class DescribeCommandAllowlist:
    def it_allows_pytest(self, cache: CommandCache) -> None:
        assert cache.is_allowed("pytest") is True

    def it_allows_ruff_check(self, cache: CommandCache) -> None:
        assert cache.is_allowed("ruff check src/") is True

    def it_allows_pytest_with_args(self, cache: CommandCache) -> None:
        assert cache.is_allowed("pytest tests/ -v --tb=short") is True

    def it_allows_mypy(self, cache: CommandCache) -> None:
        assert cache.is_allowed("mypy src/") is True

    def it_allows_go_test(self, cache: CommandCache) -> None:
        assert cache.is_allowed("go test ./...") is True

    def it_allows_npm_test(self, cache: CommandCache) -> None:
        assert cache.is_allowed("npm test") is True

    def it_allows_cargo_test(self, cache: CommandCache) -> None:
        assert cache.is_allowed("cargo test") is True

    def it_rejects_arbitrary_command(self, cache: CommandCache) -> None:
        assert cache.is_allowed("rm -rf /") is False

    def it_rejects_curl(self, cache: CommandCache) -> None:
        assert cache.is_allowed("curl https://evil.com") is False

    def it_rejects_empty_command(self, cache: CommandCache) -> None:
        assert cache.is_allowed("") is False

    def it_rejects_whitespace_only_command(self, cache: CommandCache) -> None:
        assert cache.is_allowed("   ") is False

    def it_accepts_custom_allowlist_entry(self, store: OracleStore, project: Path) -> None:
        cache = CommandCache(store, project, extra_allowed=["make"])
        assert cache.is_allowed("make build") is True

    def it_retains_defaults_with_custom_entries(
        self, store: OracleStore, project: Path
    ) -> None:
        cache = CommandCache(store, project, extra_allowed=["make"])
        assert cache.is_allowed("pytest") is True
        assert cache.is_allowed("make build") is True


@pytest.mark.medium
class DescribeShellInjectionHardening:
    @pytest.mark.parametrize(
        "cmd",
        [
            "pytest; rm -rf /",
            "pytest && curl evil.com",
            "pytest | tee /tmp/leak",
            "echo $(whoami)",
            "echo `id`",
            "pytest || malicious",
            "ruff check & background",
        ],
        ids=[
            "semicolon_chain",
            "and_chain",
            "pipe_chain",
            "dollar_subshell",
            "backtick_subshell",
            "or_chain",
            "background_ampersand",
        ],
    )
    def it_rejects_chained_commands(self, cmd: str, cache: CommandCache) -> None:
        assert cache.is_allowed(cmd) is False

    @pytest.mark.parametrize(
        "cmd",
        [
            "pytest; rm -rf /",
            "echo $(whoami)",
            "ruff check & background",
        ],
        ids=[
            "semicolon_chain",
            "dollar_subshell",
            "background_ampersand",
        ],
    )
    def it_raises_on_run_summarized_with_injection(
        self, cmd: str, cache: CommandCache
    ) -> None:
        with pytest.raises(CommandNotAllowedError):
            cache.run_summarized(cmd)


@pytest.mark.medium
class DescribeCommandCacheRun:
    def it_runs_allowed_command(self, cache: CommandCache) -> None:
        result = cache.run_summarized("echo hello world")
        assert "hello world" in result

    def it_returns_cached_result_when_unchanged(
        self, cache: CommandCache, project: Path
    ) -> None:
        # First run
        cache.run_summarized("echo cached-test")
        # Second run without changing source files
        result = cache.run_summarized("echo cached-test")
        assert "Cached result" in result
        assert "cached-test" in result

    def it_reruns_when_source_files_change(
        self, cache: CommandCache, project: Path
    ) -> None:
        cache.run_summarized("echo rerun-test")
        # Modify a source file to change the hash
        src_file = project / "src" / "app.py"
        src_file.write_text("def main(): return 42\n")
        result = cache.run_summarized("echo rerun-test")
        # Should be a fresh run, not cached
        assert "Cached result" not in result
        assert "rerun-test" in result

    def it_raises_for_disallowed_command(self, cache: CommandCache) -> None:
        with pytest.raises(CommandNotAllowedError):
            cache.run_summarized("curl https://evil.com")

    def it_caps_output_at_2000_chars(self, cache: CommandCache, project: Path) -> None:
        # Generate output longer than 2000 chars
        # echo with a long repeated string
        long_content = "x" * 3000
        (project / "src" / "longoutput.py").write_text(
            f"# {long_content}\n"
        )
        result = cache.run_summarized(f"echo {'A' * 3000}")
        assert len(result) <= 2000

    def it_handles_command_timeout(self, cache: CommandCache) -> None:
        # Patch subprocess.run to raise TimeoutExpired
        with patch("oracle.cache.command_cache.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep 999", timeout=120)
            result = cache.run_summarized("echo timeout-test")
            assert "timed out" in result.lower()

    def it_includes_stderr_in_output(self, cache: CommandCache) -> None:
        # Use a command that writes to stderr
        # "echo msg >&2" contains &, which is blocked by chain operators.
        # Instead, patch subprocess.run to return stderr.
        with patch("oracle.cache.command_cache.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args="echo test",
                returncode=0,
                stdout="stdout-part\n",
                stderr="stderr-part\n",
            )
            result = cache.run_summarized("echo test")
            assert "stdout-part" in result
            assert "stderr-part" in result

    def it_shows_cached_result_with_elapsed_minutes(
        self, cache: CommandCache, store: OracleStore
    ) -> None:
        # Run a command, then manually backdate the ran_at to simulate 5 minutes ago
        cache.run_summarized("echo elapsed-test")
        now = int(time.time())
        store.upsert_command_result(
            "echo elapsed-test",
            "elapsed-test\n",
            0,
            cache._hash_source_files(),
            now - 300,  # 5 minutes ago
        )
        result = cache.run_summarized("echo elapsed-test")
        assert "Cached result (5m ago)" in result

    def it_shows_cached_result_with_elapsed_hours(
        self, cache: CommandCache, store: OracleStore
    ) -> None:
        cache.run_summarized("echo hours-test")
        now = int(time.time())
        store.upsert_command_result(
            "echo hours-test",
            "hours-test\n",
            0,
            cache._hash_source_files(),
            now - 7200,  # 2 hours ago
        )
        result = cache.run_summarized("echo hours-test")
        assert "Cached result (2h ago)" in result


@pytest.mark.medium
class DescribeSourceFileHashing:
    def it_hashes_python_files(self, cache: CommandCache, project: Path) -> None:
        hash1 = cache._hash_source_files()
        assert len(hash1) == 16  # first 16 hex chars

    def it_changes_when_source_modified(self, cache: CommandCache, project: Path) -> None:
        hash1 = cache._hash_source_files()
        (project / "src" / "app.py").write_text("modified content\n")
        hash2 = cache._hash_source_files()
        assert hash1 != hash2

    def it_is_stable_when_unchanged(self, cache: CommandCache, project: Path) -> None:
        hash1 = cache._hash_source_files()
        hash2 = cache._hash_source_files()
        assert hash1 == hash2

    def it_skips_venv_directories(self, cache: CommandCache, project: Path) -> None:
        (project / ".venv").mkdir()
        (project / ".venv" / "lib.py").write_text("venv code\n")
        hash_with_venv = cache._hash_source_files()
        # Remove venv file and check hash is the same
        (project / ".venv" / "lib.py").unlink()
        hash_without_venv = cache._hash_source_files()
        assert hash_with_venv == hash_without_venv

    def it_skips_node_modules(self, cache: CommandCache, project: Path) -> None:
        (project / "node_modules").mkdir()
        (project / "node_modules" / "dep.js").write_text("module code\n")
        hash_with_nm = cache._hash_source_files()
        (project / "node_modules" / "dep.js").unlink()
        hash_without_nm = cache._hash_source_files()
        assert hash_with_nm == hash_without_nm

    def it_includes_multiple_file_types(self, cache: CommandCache, project: Path) -> None:
        hash1 = cache._hash_source_files()
        (project / "src" / "index.ts").write_text("const x = 1;\n")
        hash2 = cache._hash_source_files()
        assert hash1 != hash2

    def it_ignores_non_source_extension_files(
        self, cache: CommandCache, project: Path
    ) -> None:
        hash1 = cache._hash_source_files()
        # Add a non-source file -- should not change the hash
        (project / "src" / "README.md").write_text("# Docs\n")
        (project / "src" / "data.json").write_text('{"key": "value"}\n')
        hash2 = cache._hash_source_files()
        assert hash1 == hash2

    def it_returns_consistent_hash_for_empty_project(
        self, store: OracleStore, tmp_path: Path
    ) -> None:
        empty_project = tmp_path / "empty"
        empty_project.mkdir()
        cache = CommandCache(store, empty_project)
        hash1 = cache._hash_source_files()
        hash2 = cache._hash_source_files()
        assert hash1 == hash2
        assert len(hash1) == 16
