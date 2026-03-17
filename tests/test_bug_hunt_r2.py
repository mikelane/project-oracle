"""Bug hunt round 2 — proving suspected bugs with failing tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from oracle.cache.command_cache import CommandCache
from oracle.cache.file_cache import FileCache
from oracle.storage.store import OracleStore


@pytest.fixture
def store(tmp_path: Path) -> Generator[OracleStore, None, None]:
    db_path = tmp_path / "oracle.db"
    s = OracleStore(db_path)
    yield s
    s.close()


@pytest.fixture
def cache(store: OracleStore) -> FileCache:
    return FileCache(store)


@pytest.fixture
def cmd_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("x = 1\n")
    return project


@pytest.fixture
def cmd_cache(store: OracleStore, cmd_project: Path) -> CommandCache:
    return CommandCache(store, cmd_project, extra_allowed=["echo"])


@pytest.mark.medium
class DescribeFileCacheBinaryFileHandling:
    """file_cache.smart_read_with_stats calls file_path.read_text() on line 59
    without catching UnicodeDecodeError. A binary file under the 10MB size limit
    will pass the size check but crash on read_text()."""

    def it_returns_an_error_instead_of_crashing_on_binary_files(
        self, cache: FileCache, tmp_path: Path
    ) -> None:
        binary_file = tmp_path / "image.bin"
        # Write bytes that are not valid UTF-8
        binary_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xff\xfe\xfd")

        result, tokens_saved = cache.smart_read_with_stats(str(binary_file))
        # Should return an error message, not crash with UnicodeDecodeError
        assert "error" in result.lower()
        assert tokens_saved == 0


@pytest.mark.medium
class DescribeCommandCacheShlexCrash:
    """shlex.split raises ValueError on commands with unclosed quotes.
    The is_allowed check passes because quote characters are not in _DANGEROUS_CHARS.
    But shlex.split('pytest "unclosed') on line 103 crashes with ValueError
    before subprocess.run is ever called."""

    def it_returns_an_error_instead_of_crashing_on_unclosed_quotes(
        self, cmd_cache: CommandCache
    ) -> None:
        # 'echo "unclosed' passes is_allowed (no dangerous chars)
        # but shlex.split raises ValueError: No closing quotation
        # The fix: catch ValueError and return an error tuple, or reject in is_allowed.
        output, is_hit, tokens = cmd_cache.run_summarized_with_stats('echo "unclosed')
        assert "error" in output.lower()
        assert is_hit is False
        assert tokens == 0


@pytest.mark.medium
class DescribeOracleGrepPathConfinementBypass:
    """oracle_grep skips path confinement when no project is active.

    When path != ".", the code does:
        project = _registry.current()
        if project is not None and not resolved_grep.is_relative_to(project.root):
            return error

    If current() is None (no prior oracle_read), the `project is not None` check
    short-circuits, skipping confinement entirely. The grep proceeds on any path."""

    def it_rejects_arbitrary_paths_when_no_project_is_active(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import oracle_grep

        oracle_dir = tmp_path / ".oracle"
        oracle_dir.mkdir()
        (oracle_dir / "projects").mkdir()

        registry = ProjectRegistry(oracle_dir)
        mocker.patch("oracle.server._registry", registry)
        # Do NOT call oracle_read first — registry.current() is None

        # Create a file outside any project to grep
        secret = tmp_path / "secrets"
        secret.mkdir()
        (secret / "passwords.py").write_text("admin_password = 'hunter2'\n")

        result = oracle_grep("admin_password", str(secret))
        # BUG: this will return matches from outside any project root
        # because confinement is skipped when current() is None
        assert "error" in result.lower(), (
            f"Expected an error when grepping outside project root with no active project, "
            f"but got: {result}"
        )


@pytest.mark.medium
class DescribeFallbackGrepRegexInjection:
    """_fallback_grep in ask.py extracts keywords from user questions and passes
    them directly to 'grep -rn' as regex patterns. Keywords containing regex
    metacharacters (brackets, plus, asterisk, etc.) cause grep to fail with
    a regex error or match unintended content.

    Example: question "where is config[prod]" extracts keyword "config[prod]"
    which is an invalid regex (unclosed bracket class)."""

    def it_finds_literal_matches_when_keyword_contains_regex_metacharacters(
        self, tmp_path: Path
    ) -> None:
        from oracle.tools.ask import _fallback_grep

        # Create a source file where ONLY the regex-metachar keyword matches
        (tmp_path / "settings.py").write_text("config[prod = 'value'\n")

        # "config[prod" is the only non-stop-word keyword.
        # It has an unclosed bracket — invalid regex for grep.
        result = _fallback_grep("where is config[prod", tmp_path)
        # BUG: grep interprets "config[prod" as regex (unclosed char class),
        # returns exit code 2, and returns "No matches" even though the
        # literal string exists in the file.
        # The result should contain actual file matches (with line numbers),
        # not just the "No matches" error message.
        assert "match(es):" in result, (
            f"Expected grep to find the literal string 'config[prod' in "
            f"settings.py, but got: {result}"
        )


@pytest.mark.medium
class DescribeCommandCacheMissingBinary:
    """subprocess.run with shell=False raises FileNotFoundError when the command
    binary doesn't exist. The code only catches TimeoutExpired. If an allowed
    command (e.g. 'pytest') isn't installed, run_summarized_with_stats crashes
    with an unhandled FileNotFoundError."""

    def it_returns_an_error_instead_of_crashing_when_binary_not_found(
        self, store: OracleStore, cmd_project: Path
    ) -> None:
        # Add a nonexistent command to the allowlist
        cache = CommandCache(store, cmd_project, extra_allowed=["nonexistent_tool_xyz"])
        output, is_hit, tokens = cache.run_summarized_with_stats(
            "nonexistent_tool_xyz --version"
        )
        # Should return an error message, not crash with FileNotFoundError
        assert "error" in output.lower()
        assert is_hit is False
        assert tokens == 0
