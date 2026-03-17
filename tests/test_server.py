"""Tests for the FastMCP server entry point — oracle.server."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from oracle.project import ProjectState, StackInfo
from oracle.storage.store import OracleStore


class DescribeServerInit:
    """Verify the MCP server is configured correctly at import time."""

    async def it_has_expected_tool_count(self) -> None:
        from oracle.server import mcp

        tools = await mcp.list_tools()
        assert len(tools) == 6

    async def it_exposes_all_required_tool_names(self) -> None:
        from oracle.server import mcp

        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        expected = {
            "oracle_read",
            "oracle_grep",
            "oracle_status",
            "oracle_run",
            "oracle_ask",
            "oracle_forget",
        }
        assert tool_names == expected

    def it_has_correct_server_name(self) -> None:
        from oracle.server import mcp

        assert mcp.name == "project-oracle"


class DescribeEnsureCaches:
    """Verify _ensure_caches wires up cache layers on ProjectState."""

    def it_wires_file_cache_when_missing(self, tmp_path: Path) -> None:
        from oracle.server import _ensure_caches

        store = OracleStore(tmp_path / "oracle.db")
        project = ProjectState(
            root=tmp_path,
            stack=StackInfo(lang="python"),
            store=store,
        )
        assert project.file_cache is None
        _ensure_caches(project)
        assert project.file_cache is not None

    def it_wires_git_cache_when_missing(self, tmp_path: Path) -> None:
        from oracle.server import _ensure_caches

        store = OracleStore(tmp_path / "oracle.db")
        project = ProjectState(
            root=tmp_path,
            stack=StackInfo(lang="python"),
            store=store,
        )
        assert project.git_cache is None
        _ensure_caches(project)
        assert project.git_cache is not None

    def it_wires_command_cache_when_missing(self, tmp_path: Path) -> None:
        from oracle.server import _ensure_caches

        store = OracleStore(tmp_path / "oracle.db")
        project = ProjectState(
            root=tmp_path,
            stack=StackInfo(lang="python"),
            store=store,
        )
        assert project.command_cache is None
        _ensure_caches(project)
        assert project.command_cache is not None

    def it_does_not_replace_existing_caches(self, tmp_path: Path) -> None:
        from oracle.cache.command_cache import CommandCache
        from oracle.cache.file_cache import FileCache
        from oracle.cache.git_cache import GitCache
        from oracle.server import _ensure_caches

        store = OracleStore(tmp_path / "oracle.db")
        fc = FileCache(store)
        gc = GitCache(store, tmp_path)
        cc = CommandCache(store, tmp_path)
        project = ProjectState(
            root=tmp_path,
            stack=StackInfo(lang="python"),
            store=store,
            file_cache=fc,
            git_cache=gc,
            command_cache=cc,
        )
        _ensure_caches(project)
        assert project.file_cache is fc
        assert project.git_cache is gc
        assert project.command_cache is cc

    def it_skips_wiring_when_store_is_none(self) -> None:
        from oracle.server import _ensure_caches

        project = ProjectState(
            root=Path("/nonexistent"),
            stack=StackInfo(lang="python"),
            store=None,
        )
        _ensure_caches(project)
        assert project.file_cache is None
        assert project.git_cache is None
        assert project.command_cache is None


@pytest.mark.medium
class DescribeServerIntegration:
    """Integration tests that exercise the tool functions with real stores."""

    @pytest.fixture
    def oracle_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / ".project-oracle"
        d.mkdir()
        (d / "projects").mkdir()
        return d

    @pytest.fixture
    def tmp_project(self, tmp_path: Path) -> Path:
        project = tmp_path / "test-project"
        project.mkdir()
        (project / ".git").mkdir()
        (project / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (project / "hello.py").write_text("print('hello')\n")
        return project

    def it_reads_file_and_returns_content(
        self, tmp_project: Path, oracle_dir: Path
    ) -> None:
        from oracle.server import _ensure_caches

        with patch.dict(os.environ, {"ORACLE_DIR": str(oracle_dir)}):
            from oracle.registry import ProjectRegistry

            registry = ProjectRegistry(oracle_dir)
            project = registry.for_path(tmp_project / "hello.py")
            assert project is not None
            _ensure_caches(project)
            assert project.file_cache is not None

            result = project.file_cache.smart_read(str(tmp_project / "hello.py"))
            assert "print('hello')" in result

    def it_returns_delta_on_reread(
        self, tmp_project: Path, oracle_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import _ensure_caches

        registry = ProjectRegistry(oracle_dir)
        project = registry.for_path(tmp_project / "hello.py")
        assert project is not None
        _ensure_caches(project)
        assert project.file_cache is not None

        file_path = str(tmp_project / "hello.py")
        # First read: full content
        result1 = project.file_cache.smart_read(file_path)
        assert "print('hello')" in result1

        # Second read (unchanged): delta message
        result2 = project.file_cache.smart_read(file_path)
        assert "No changes since last read" in result2

    def it_forgets_and_rereads(
        self, tmp_project: Path, oracle_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import _ensure_caches

        registry = ProjectRegistry(oracle_dir)
        project = registry.for_path(tmp_project / "hello.py")
        assert project is not None
        _ensure_caches(project)
        assert project.file_cache is not None

        file_path = str(tmp_project / "hello.py")
        # Read, then forget, then re-read should get full content again
        project.file_cache.smart_read(file_path)
        project.file_cache.forget(file_path)
        result = project.file_cache.smart_read(file_path)
        assert "print('hello')" in result

    def it_returns_error_for_unknown_project(self, tmp_path: Path) -> None:
        from oracle.registry import ProjectRegistry

        oracle_dir = tmp_path / ".oracle-empty"
        oracle_dir.mkdir()
        (oracle_dir / "projects").mkdir()
        registry = ProjectRegistry(oracle_dir)

        # A path with no project markers should return None
        no_project = tmp_path / "no-project-here"
        no_project.mkdir()
        result = registry.for_path(no_project / "file.txt")
        assert result is None


class DescribeOracleReadTool:
    """Test the oracle_read tool function directly."""

    def it_returns_file_content_for_valid_path(
        self, tmp_path: Path
    ) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import oracle_read

        oracle_dir = tmp_path / ".oracle"
        oracle_dir.mkdir()
        (oracle_dir / "projects").mkdir()

        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()
        (project_dir / "foo.py").write_text("x = 1\n")

        with patch("oracle.server._registry", ProjectRegistry(oracle_dir)):
            result = oracle_read(str(project_dir / "foo.py"))
            assert "x = 1" in result

    def it_returns_error_when_no_project_detected(self, tmp_path: Path) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import oracle_read

        oracle_dir = tmp_path / ".oracle"
        oracle_dir.mkdir()
        (oracle_dir / "projects").mkdir()

        no_project = tmp_path / "bare"
        no_project.mkdir()
        (no_project / "file.txt").write_text("data")

        with patch("oracle.server._registry", ProjectRegistry(oracle_dir)):
            result = oracle_read(str(no_project / "file.txt"))
            assert "no project detected" in result.lower()


class DescribeOracleGrepTool:
    """Test the oracle_grep tool function."""

    def it_delegates_to_handle_oracle_grep(self, tmp_path: Path) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import oracle_grep

        oracle_dir = tmp_path / ".oracle"
        oracle_dir.mkdir()
        (oracle_dir / "projects").mkdir()

        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()
        (project_dir / "bar.py").write_text("needle_here = True\n")

        with patch("oracle.server._registry", ProjectRegistry(oracle_dir)):
            result = oracle_grep("needle_here", str(project_dir))
            assert "needle_here" in result


class DescribeOracleStatusTool:
    """Test the oracle_status tool function."""

    def it_returns_error_when_no_current_project(self, tmp_path: Path) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import oracle_status

        oracle_dir = tmp_path / ".oracle"
        oracle_dir.mkdir()
        (oracle_dir / "projects").mkdir()

        with patch("oracle.server._registry", ProjectRegistry(oracle_dir)):
            result = oracle_status()
            assert "no active project" in result.lower()

    def it_returns_status_for_active_project(self, tmp_path: Path, git_project: Path) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import oracle_read, oracle_status

        oracle_dir = tmp_path / ".oracle"
        oracle_dir.mkdir()
        (oracle_dir / "projects").mkdir()

        with patch("oracle.server._registry", ProjectRegistry(oracle_dir)):
            # Read a file to set current project
            oracle_read(str(git_project / "file.py"))
            result = oracle_status()
            assert "stack:" in result.lower() or "branch:" in result.lower()


class DescribeOracleRunTool:
    """Test the oracle_run tool function."""

    def it_returns_error_when_no_current_project(self, tmp_path: Path) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import oracle_run

        oracle_dir = tmp_path / ".oracle"
        oracle_dir.mkdir()
        (oracle_dir / "projects").mkdir()

        with patch("oracle.server._registry", ProjectRegistry(oracle_dir)):
            result = oracle_run(["echo hello"])
            assert "no active project" in result.lower()

    def it_runs_allowed_command_for_active_project(self, tmp_path: Path) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import oracle_read, oracle_run

        oracle_dir = tmp_path / ".oracle"
        oracle_dir.mkdir()
        (oracle_dir / "projects").mkdir()

        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()
        (project_dir / "main.py").write_text("x = 1\n")

        with patch("oracle.server._registry", ProjectRegistry(oracle_dir)):
            oracle_read(str(project_dir / "main.py"))
            result = oracle_run(["echo hello"])
            assert "hello" in result


class DescribeOracleAskTool:
    """Test the oracle_ask tool function."""

    def it_returns_error_when_no_current_project(self, tmp_path: Path) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import oracle_ask

        oracle_dir = tmp_path / ".oracle"
        oracle_dir.mkdir()
        (oracle_dir / "projects").mkdir()

        with patch("oracle.server._registry", ProjectRegistry(oracle_dir)):
            result = oracle_ask("what is this?")
            assert "no active project" in result.lower()

    def it_delegates_to_handle_oracle_ask_for_active_project(
        self, tmp_path: Path
    ) -> None:
        import asyncio

        from oracle.registry import ProjectRegistry
        from oracle.server import oracle_ask, oracle_read

        oracle_dir = tmp_path / ".oracle"
        oracle_dir.mkdir()
        (oracle_dir / "projects").mkdir()

        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()
        (project_dir / "main.py").write_text("x = 1\n")

        async def fake_handle(question: str, project: object) -> str:
            return f"Answer to: {question}"

        def run_coro(coro: object) -> str:
            return asyncio.get_event_loop().run_until_complete(coro)  # type: ignore[arg-type]

        with (
            patch("oracle.server._registry", ProjectRegistry(oracle_dir)),
            patch("oracle.server.asyncio.run", side_effect=run_coro),
            patch("oracle.tools.ask.handle_oracle_ask", side_effect=fake_handle),
        ):
            oracle_read(str(project_dir / "main.py"))
            result = oracle_ask("what is the stack?")
            assert "answer to:" in result.lower()


class DescribeOracleForgetTool:
    """Test the oracle_forget tool function."""

    def it_returns_error_when_no_project_detected(self, tmp_path: Path) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import oracle_forget

        oracle_dir = tmp_path / ".oracle"
        oracle_dir.mkdir()
        (oracle_dir / "projects").mkdir()

        no_project = tmp_path / "bare"
        no_project.mkdir()

        with patch("oracle.server._registry", ProjectRegistry(oracle_dir)):
            result = oracle_forget(str(no_project / "file.txt"))
            assert "no project detected" in result.lower()

    def it_clears_cache_for_valid_path(self, tmp_path: Path) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import oracle_forget, oracle_read

        oracle_dir = tmp_path / ".oracle"
        oracle_dir.mkdir()
        (oracle_dir / "projects").mkdir()

        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()
        (project_dir / "file.py").write_text("content\n")

        with patch("oracle.server._registry", ProjectRegistry(oracle_dir)):
            # Read first to populate cache
            oracle_read(str(project_dir / "file.py"))
            # Forget
            result = oracle_forget(str(project_dir / "file.py"))
            assert "cache cleared" in result.lower()


class DescribeAgentLogging:
    """Verify every oracle tool call logs stats to SQLite via store.log_interaction()."""

    @pytest.fixture
    def oracle_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / ".oracle"
        d.mkdir()
        (d / "projects").mkdir()
        return d

    @pytest.fixture
    def project_dir(self, tmp_path: Path) -> Path:
        project = tmp_path / "proj"
        project.mkdir()
        (project / ".git").mkdir()
        (project / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (project / "hello.py").write_text("print('hello world')\n")
        return project

    def it_logs_read_interaction_with_session_id(
        self, tmp_path: Path, oracle_dir: Path, project_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import oracle_read

        registry = ProjectRegistry(oracle_dir)

        with patch("oracle.server._registry", registry):
            oracle_read(str(project_dir / "hello.py"))

        # Retrieve the project to check its store
        project = registry.for_path(project_dir / "hello.py")
        assert project is not None
        assert project.store is not None
        stats = project.store.get_session_stats(project.session_id)
        # At least one log entry exists (total_cache_hits + total_tokens_saved reflect it)
        # First read is a miss, so cache_hit=0, but the log row should exist
        rows = project.store._conn.execute(
            "SELECT * FROM agent_log WHERE session_id = ?", (project.session_id,)
        ).fetchall()
        assert len(rows) >= 1
        assert rows[0]["tool_name"] == "oracle_read"

    def it_logs_cache_hit_on_reread(
        self, tmp_path: Path, oracle_dir: Path, project_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import oracle_read

        registry = ProjectRegistry(oracle_dir)

        with patch("oracle.server._registry", registry):
            oracle_read(str(project_dir / "hello.py"))
            oracle_read(str(project_dir / "hello.py"))

        project = registry.for_path(project_dir / "hello.py")
        assert project is not None
        assert project.store is not None
        stats = project.store.get_session_stats(project.session_id)
        assert stats["total_tokens_saved"] > 0

    def it_logs_grep_as_miss(
        self, tmp_path: Path, oracle_dir: Path, project_dir: Path
    ) -> None:
        from oracle.registry import ProjectRegistry
        from oracle.server import oracle_grep, oracle_read

        registry = ProjectRegistry(oracle_dir)

        with patch("oracle.server._registry", registry):
            # Read first to establish project
            oracle_read(str(project_dir / "hello.py"))
            oracle_grep("print", str(project_dir))

        project = registry.for_path(project_dir / "hello.py")
        assert project is not None
        assert project.store is not None
        rows = project.store._conn.execute(
            "SELECT * FROM agent_log WHERE tool_name = 'oracle_grep'",
        ).fetchall()
        assert len(rows) >= 1
        assert rows[0]["cache_hit"] == 0
        assert rows[0]["tokens_saved"] == 0

    def it_does_not_crash_when_store_is_none(self) -> None:
        from oracle.server import _log

        project = ProjectState(
            root=Path("/nonexistent"),
            stack=StackInfo(lang="python"),
            store=None,
            session_id="test-session",
        )
        # Should not raise
        _log(project, "oracle_read", "/some/path", False, 0)


class DescribeMainEntryPoint:
    """Test the main() entry point."""

    def it_calls_mcp_run(self) -> None:
        from oracle.server import main, mcp

        with patch.object(mcp, "run") as mock_run:
            main()
            mock_run.assert_called_once()
