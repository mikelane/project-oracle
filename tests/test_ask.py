"""Tests for oracle_ask tool handler — intent routing with cache, chunkhound, and haiku fallback."""

from __future__ import annotations

import subprocess
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oracle.cache.command_cache import CommandCache
from oracle.cache.file_cache import FileCache
from oracle.cache.git_cache import GitCache
from oracle.integrations.chunkhound import ChunkhoundClient
from oracle.project import ProjectState, StackInfo
from oracle.storage.store import OracleStore


@pytest.fixture
def store(tmp_path: Path) -> Generator[OracleStore, None, None]:
    db_path = tmp_path / "oracle.db"
    s = OracleStore(db_path)
    yield s
    s.close()


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    project = tmp_path / "git-project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=project, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=project, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=project, capture_output=True, check=True,
    )
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("def hello():\n    return 'world'\n")
    (project / "pyproject.toml").write_text('[project]\nname = "test"\n')
    subprocess.run(["git", "add", "."], cwd=project, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=project, capture_output=True, check=True,
    )
    return project


@pytest.fixture
def mock_project(git_project: Path, store: OracleStore) -> ProjectState:
    """Build a real ProjectState with real caches against a real git repo."""
    stack = StackInfo(lang="python", pkg_mgr="uv", test_cmd="pytest")
    git_cache = GitCache(store=store, project_root=git_project)
    file_cache = FileCache(store=store)
    command_cache = CommandCache(store=store, project_root=git_project)
    return ProjectState(
        root=git_project,
        stack=stack,
        store=store,
        file_cache=file_cache,
        git_cache=git_cache,
        command_cache=command_cache,
        chunkhound=None,
    )


@pytest.mark.medium
class DescribeOracleAsk:
    @pytest.mark.asyncio
    async def it_routes_git_question_to_git_cache(self, mock_project: ProjectState) -> None:
        from oracle.tools.ask import handle_oracle_ask

        result = await handle_oracle_ask("what changed?", mock_project)
        # Git cache get_delta returns full snapshot on first call
        assert "Branch:" in result

    @pytest.mark.asyncio
    async def it_routes_test_question(self, mock_project: ProjectState) -> None:
        from oracle.tools.ask import handle_oracle_ask

        result = await handle_oracle_ask("are tests passing?", mock_project)
        # Should mention test command or no test results
        assert "test" in result.lower() or "pytest" in result.lower()

    @pytest.mark.asyncio
    async def it_routes_structure_question(self, mock_project: ProjectState) -> None:
        from oracle.tools.ask import handle_oracle_ask

        result = await handle_oracle_ask("what's the project structure?", mock_project)
        assert "python" in result.lower()

    @pytest.mark.asyncio
    async def it_returns_project_overview_with_stack_info(
        self, mock_project: ProjectState
    ) -> None:
        from oracle.tools.ask import handle_oracle_ask

        result = await handle_oracle_ask("give me an overview", mock_project)
        assert "python" in result.lower()
        assert "uv" in result.lower()

    @pytest.mark.asyncio
    async def it_falls_back_to_grep_without_chunkhound(
        self, mock_project: ProjectState
    ) -> None:
        from oracle.tools.ask import handle_oracle_ask

        # Code understanding question with no chunkhound → grep fallback
        result = await handle_oracle_ask("where is the hello function?", mock_project)
        # grep should find hello in src/main.py or report no matches
        assert "hello" in result.lower() or "no matches" in result.lower()

    @pytest.mark.asyncio
    async def it_uses_chunkhound_when_available(self, mock_project: ProjectState) -> None:
        from oracle.tools.ask import handle_oracle_ask

        mock_ch = AsyncMock(spec=ChunkhoundClient)
        mock_ch.search = AsyncMock(return_value=[
            {"file": "auth.py", "snippet": "def authenticate(user):"},
        ])
        mock_project.chunkhound = mock_ch

        result = await handle_oracle_ask("find the auth handler", mock_project)
        assert "auth.py" in result
        assert "authenticate" in result

    @pytest.mark.asyncio
    async def it_falls_back_to_grep_when_chunkhound_returns_empty(
        self, mock_project: ProjectState
    ) -> None:
        from oracle.tools.ask import handle_oracle_ask

        mock_ch = AsyncMock(spec=ChunkhoundClient)
        mock_ch.search = AsyncMock(return_value=[])
        mock_project.chunkhound = mock_ch

        result = await handle_oracle_ask("where is the hello function?", mock_project)
        # Falls through to grep, which should find hello in main.py
        assert "hello" in result.lower() or "no matches" in result.lower()

    @pytest.mark.asyncio
    async def it_routes_readiness_question(self, mock_project: ProjectState) -> None:
        from oracle.tools.ask import handle_oracle_ask

        result = await handle_oracle_ask("ready to push?", mock_project)
        # Should mention readiness checks
        assert len(result) > 0

    @pytest.mark.asyncio
    async def it_returns_no_git_cache_message(self) -> None:
        from oracle.tools.ask import handle_oracle_ask

        project = ProjectState(
            root=Path("/fake"),
            stack=StackInfo(lang="python"),
            git_cache=None,
        )
        result = await handle_oracle_ask("what changed?", project)
        assert "no git cache" in result.lower()

    @pytest.mark.asyncio
    async def it_uses_haiku_fallback_for_unknown_intent(
        self, mock_project: ProjectState
    ) -> None:
        from oracle.tools.ask import handle_oracle_ask

        # Patch classify_intent to return UNKNOWN for this question
        with patch("oracle.tools.ask.classify_intent") as mock_classify:
            from oracle.intent import Intent

            mock_classify.return_value = Intent.UNKNOWN

            # Patch the anthropic client to avoid real API calls
            mock_client = MagicMock()
            mock_message = MagicMock()
            mock_message.content = [MagicMock(text="The answer is 42")]
            mock_client.messages.create.return_value = mock_message

            with patch("oracle.tools.ask.anthropic.Anthropic", return_value=mock_client):
                result = await handle_oracle_ask(
                    "what is the meaning of life?", mock_project
                )
                assert "42" in result

    @pytest.mark.asyncio
    async def it_returns_error_when_haiku_sdk_not_configured(
        self, mock_project: ProjectState
    ) -> None:
        from oracle.tools.ask import handle_oracle_ask

        with patch("oracle.tools.ask.classify_intent") as mock_classify:
            from oracle.intent import Intent

            mock_classify.return_value = Intent.UNKNOWN

            with patch(
                "oracle.tools.ask.anthropic.Anthropic",
                side_effect=Exception("API key not set"),
            ):
                result = await handle_oracle_ask(
                    "what is the meaning of life?", mock_project
                )
                assert "unable" in result.lower() or "error" in result.lower()


class DescribeProjectOverview:
    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_includes_lint_and_type_commands(self, mock_project: ProjectState) -> None:
        from oracle.tools.ask import handle_oracle_ask

        mock_project.stack = StackInfo(
            lang="python", pkg_mgr="uv", test_cmd="pytest",
            lint_cmd="ruff check", type_cmd="mypy",
        )
        result = await handle_oracle_ask("what's the project structure?", mock_project)
        assert "ruff check" in result
        assert "mypy" in result


class DescribeReadinessCheck:
    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_reports_dirty_files_as_not_ready(
        self, mock_project: ProjectState
    ) -> None:
        from oracle.tools.ask import handle_oracle_ask

        # Create a dirty file
        (mock_project.root / "dirty.txt").write_text("uncommitted\n")
        result = await handle_oracle_ask("ready to push?", mock_project)
        assert (
            "dirty" in result.lower()
            or "uncommitted" in result.lower()
            or "not ready" in result.lower()
        )

    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_reports_clean_repo_readiness(self, mock_project: ProjectState) -> None:
        from oracle.tools.ask import handle_oracle_ask

        result = await handle_oracle_ask("ready to merge?", mock_project)
        # Clean repo should indicate readiness
        assert "clean" in result.lower() or "ready" in result.lower()


class DescribeTestStatus:
    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_reports_test_command_when_available(
        self, mock_project: ProjectState
    ) -> None:
        from oracle.tools.ask import handle_oracle_ask

        result = await handle_oracle_ask("are tests passing?", mock_project)
        assert "pytest" in result.lower()

    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_reports_no_test_command_configured(self) -> None:
        from oracle.tools.ask import handle_oracle_ask

        project = ProjectState(
            root=Path("/fake"),
            stack=StackInfo(lang="unknown"),
        )
        result = await handle_oracle_ask("are tests passing?", project)
        assert "no test" in result.lower()

    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_reports_cached_test_result(self, mock_project: ProjectState) -> None:
        from oracle.tools.ask import handle_oracle_ask

        # Seed a cached test result
        assert mock_project.command_cache is not None
        assert mock_project.store is not None
        mock_project.store.upsert_command_result(
            "pytest", "5 passed", 0, "abc123", 1000000
        )
        result = await handle_oracle_ask("are tests passing?", mock_project)
        assert "5 passed" in result


class DescribeReadinessNoGitCache:
    @pytest.mark.asyncio
    async def it_reports_no_git_cache(self) -> None:
        from oracle.tools.ask import handle_oracle_ask

        project = ProjectState(
            root=Path("/fake"),
            stack=StackInfo(lang="python"),
            git_cache=None,
        )
        result = await handle_oracle_ask("ready to push?", project)
        assert "no git cache" in result.lower()

    @pytest.mark.asyncio
    async def it_includes_test_cmd_without_command_cache(self) -> None:
        from oracle.tools.ask import handle_oracle_ask

        project = ProjectState(
            root=Path("/fake"),
            stack=StackInfo(lang="python", test_cmd="pytest"),
            git_cache=None,
            command_cache=None,
        )
        result = await handle_oracle_ask("ready to push?", project)
        assert "test command" in result.lower()
        assert "pytest" in result.lower()


class DescribeReadinessWithStagedFiles:
    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_reports_staged_files(self, mock_project: ProjectState) -> None:
        from oracle.tools.ask import handle_oracle_ask

        # Stage a new file
        new_file = mock_project.root / "staged.py"
        new_file.write_text("x = 1\n")
        subprocess.run(
            ["git", "add", "staged.py"],
            cwd=mock_project.root, capture_output=True, check=True,
        )
        result = await handle_oracle_ask("ready to push?", mock_project)
        assert "staged" in result.lower()


class DescribeFallbackGrep:
    @pytest.mark.asyncio
    async def it_returns_no_matches_for_stop_words_only(self) -> None:
        from oracle.tools.ask import handle_oracle_ask

        project = ProjectState(
            root=Path("/fake/nonexistent"),
            stack=StackInfo(lang="python"),
        )
        result = await handle_oracle_ask("what is the?", project)
        assert "no matches" in result.lower()

    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_handles_grep_timeout(self, mock_project: ProjectState) -> None:
        from oracle.tools.ask import handle_oracle_ask

        with patch(
            "oracle.tools.ask.subprocess.run",
            side_effect=subprocess.TimeoutExpired("grep", 10),
        ):
            result = await handle_oracle_ask("where is xyznonexistent?", mock_project)
            assert "no matches" in result.lower()

    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_handles_grep_no_results(self, mock_project: ProjectState) -> None:
        from oracle.tools.ask import handle_oracle_ask

        result = await handle_oracle_ask(
            "where is totallyuniquenonexistentfunction?", mock_project
        )
        assert "no matches" in result.lower()

    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_finds_keyword_in_source_files(self, mock_project: ProjectState) -> None:
        """Grep returns actual results when keyword exists in source files."""
        from oracle.tools.ask import handle_oracle_ask

        # "hello" exists in src/main.py in the git_project fixture
        result = await handle_oracle_ask("explain hello logic", mock_project)
        assert "match" in result.lower()
        assert "hello" in result.lower()

    @pytest.mark.asyncio
    async def it_filters_empty_words_from_punctuation(self) -> None:
        """Question with trailing punctuation that strips to empty should be filtered."""
        from oracle.tools.ask import _fallback_grep

        # "!!! ??? ..." strips to empty strings, plus stop words
        result = _fallback_grep("!!! ??? ... what is the", Path("/nonexistent"))
        assert "no matches" in result.lower()

    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_handles_grep_with_nonzero_returncode(self, mock_project: ProjectState) -> None:
        """Grep returning nonzero (no match) produces no results for that keyword."""
        from oracle.tools.ask import handle_oracle_ask

        # Mock grep to return returncode=1 (no matches) with empty stdout
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("oracle.tools.ask.subprocess.run", return_value=mock_result):
            result = await handle_oracle_ask(
                "explain xyznonexistent logic", mock_project
            )
            assert "no matches" in result.lower()

    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_handles_grep_with_zero_returncode_but_empty_stdout(
        self, mock_project: ProjectState
    ) -> None:
        """Grep returning 0 but empty stdout produces no results."""
        from oracle.tools.ask import handle_oracle_ask

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "   "  # Whitespace only
        with patch("oracle.tools.ask.subprocess.run", return_value=mock_result):
            result = await handle_oracle_ask(
                "explain xyznonexistent logic", mock_project
            )
            assert "no matches" in result.lower()


class DescribeFallbackGrepUnit:
    """Direct unit tests on _fallback_grep to kill mutants."""

    @pytest.mark.medium
    def it_returns_matches_when_keyword_found(self, tmp_path: Path) -> None:
        from oracle.tools.ask import _fallback_grep

        (tmp_path / "code.py").write_text("def authenticate(user): pass\n")
        result = _fallback_grep("authenticate", tmp_path)
        assert "match" in result.lower()
        assert "authenticate" in result

    @pytest.mark.medium
    def it_returns_no_matches_when_keyword_not_found(self, tmp_path: Path) -> None:
        from oracle.tools.ask import _fallback_grep

        (tmp_path / "code.py").write_text("def hello(): pass\n")
        result = _fallback_grep("xyznonexistent", tmp_path)
        assert "no matches" in result.lower()

    @pytest.mark.medium
    def it_excludes_stop_words_from_keywords(self, tmp_path: Path) -> None:
        """Line 125: 'w and w not in stop_words' -- mutating 'and' to 'or' includes stop words.

        File contains 'what' (a stop word). Real code ignores it. Mutant greps for it and finds it.
        """
        from oracle.tools.ask import _fallback_grep

        # File contains the word "what" which is a stop word
        (tmp_path / "code.py").write_text("what = 42\n")
        # Question has ONLY stop words → should return "No matches"
        result = _fallback_grep("what is the", tmp_path)
        assert "no matches" in result.lower()
        # Mutant (or) would grep for "what" and find "what = 42", returning matches

    @pytest.mark.medium
    def it_returns_no_matches_for_only_stop_words(self, tmp_path: Path) -> None:
        """Line 127: 'if not keywords' -- mutating 'not' to identity skips early return."""
        from oracle.tools.ask import _fallback_grep

        (tmp_path / "code.py").write_text("def hello(): pass\n")
        result = _fallback_grep("what is the", tmp_path)
        assert "no matches" in result.lower()
        # Verify the question is echoed back in the message
        assert "what is the" in result.lower()

    @pytest.mark.medium
    def it_only_includes_results_with_zero_returncode(self, tmp_path: Path) -> None:
        """Line 149: 'returncode == 0' -- mutating to '!=' would include no-match runs.

        Keyword 'xyznotfound' doesn't exist → grep returns 1. Real code skips.
        Mutant (!=) would try to include stdout from failed grep (empty). No visible change.
        So we also test keyword that DOES exist to verify the positive path.
        """
        from oracle.tools.ask import _fallback_grep

        (tmp_path / "code.py").write_text("def hello(): pass\n")
        # Keyword exists: should get matches
        found = _fallback_grep("hello", tmp_path)
        assert "match" in found.lower()
        assert "hello" in found
        # Keyword doesn't exist: should get no matches
        notfound = _fallback_grep("xyznotfound", tmp_path)
        assert "no matches" in notfound.lower()

    @pytest.mark.medium
    def it_requires_both_returncode_zero_and_nonempty_stdout(self, tmp_path: Path) -> None:
        """Line 149: 'and' -- mutating to 'or' includes results when either condition is true.

        With 'or': a non-matching grep (returncode=1, stdout="") would still enter the branch
        because `result.stdout.strip()` is falsy but `result.returncode == 0` check is bypassed.
        We test that a non-matching keyword produces no results.
        """
        from oracle.tools.ask import _fallback_grep

        (tmp_path / "code.py").write_text("specific_unique_content_xyz\n")
        # Match: should return results
        result = _fallback_grep("specific_unique_content_xyz", tmp_path)
        assert "match" in result.lower()
        assert "specific_unique_content_xyz" in result
        # Non-match: should return no results
        result2 = _fallback_grep("zzz_totally_absent", tmp_path)
        assert "no matches" in result2.lower()


class DescribeHaikuFallback:
    @pytest.mark.asyncio
    async def it_handles_empty_haiku_response(self, mock_project: ProjectState) -> None:
        from oracle.tools.ask import handle_oracle_ask

        with patch("oracle.tools.ask.classify_intent") as mock_classify:
            from oracle.intent import Intent

            mock_classify.return_value = Intent.UNKNOWN

            mock_client = MagicMock()
            mock_message = MagicMock()
            mock_message.content = []  # Empty content
            mock_client.messages.create.return_value = mock_message

            with patch("oracle.tools.ask.anthropic.Anthropic", return_value=mock_client):
                result = await handle_oracle_ask(
                    "what is the meaning of life?", mock_project
                )
                assert "unable" in result.lower()
