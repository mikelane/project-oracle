"""Tests for project root detection and stack detection."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.medium
class DescribeDetectProjectRoot:
    def it_finds_git_root(self, tmp_path: Path) -> None:
        from oracle.project import detect_project_root

        project = tmp_path / "myproject"
        project.mkdir()
        (project / ".git").mkdir()
        subdir = project / "src" / "pkg"
        subdir.mkdir(parents=True)

        result = detect_project_root(subdir)
        assert result == project

    def it_returns_none_when_no_marker_exists(self, tmp_path: Path) -> None:
        from oracle.project import detect_project_root

        bare = tmp_path / "no-project"
        bare.mkdir()

        result = detect_project_root(bare)
        assert result is None

    def it_finds_pyproject_root(self, tmp_path: Path) -> None:
        from oracle.project import detect_project_root

        project = tmp_path / "pyproj"
        project.mkdir()
        (project / "pyproject.toml").write_text("[project]\n")
        subdir = project / "src"
        subdir.mkdir()

        result = detect_project_root(subdir)
        assert result == project

    def it_prefers_nearest_marker_walking_up(self, tmp_path: Path) -> None:
        from oracle.project import detect_project_root

        outer = tmp_path / "outer"
        outer.mkdir()
        (outer / ".git").mkdir()

        inner = outer / "inner"
        inner.mkdir()
        (inner / "package.json").write_text("{}\n")

        deep = inner / "src"
        deep.mkdir()

        result = detect_project_root(deep)
        assert result == inner

    def it_starts_from_parent_when_given_a_file(self, tmp_path: Path) -> None:
        from oracle.project import detect_project_root

        project = tmp_path / "filetest"
        project.mkdir()
        (project / "go.mod").write_text("module example\n")
        a_file = project / "main.go"
        a_file.write_text("package main\n")

        result = detect_project_root(a_file)
        assert result == project

    def it_starts_from_parent_when_path_does_not_exist(self, tmp_path: Path) -> None:
        from oracle.project import detect_project_root

        project = tmp_path / "ghost"
        project.mkdir()
        (project / "Cargo.toml").write_text("[package]\n")
        nonexistent = project / "src" / "lib.rs"

        result = detect_project_root(nonexistent)
        assert result == project


@pytest.mark.medium
class DescribeDetectStack:
    def it_detects_python_uv(self, tmp_path: Path) -> None:
        from oracle.project import StackInfo, detect_stack

        (tmp_path / "pyproject.toml").write_text("[project]\n")
        (tmp_path / "uv.lock").write_text("")

        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="python", pkg_mgr="uv")

    def it_detects_python_poetry(self, tmp_path: Path) -> None:
        from oracle.project import StackInfo, detect_stack

        (tmp_path / "pyproject.toml").write_text("[project]\n")
        (tmp_path / "poetry.lock").write_text("")

        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="python", pkg_mgr="poetry")

    def it_detects_python_pip_as_default(self, tmp_path: Path) -> None:
        from oracle.project import StackInfo, detect_stack

        (tmp_path / "pyproject.toml").write_text("[project]\n")

        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="python", pkg_mgr="pip")

    def it_detects_python_from_setup_py(self, tmp_path: Path) -> None:
        from oracle.project import StackInfo, detect_stack

        (tmp_path / "setup.py").write_text("from setuptools import setup\n")

        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="python", pkg_mgr="pip")

    def it_detects_node_pnpm(self, tmp_path: Path) -> None:
        from oracle.project import StackInfo, detect_stack

        (tmp_path / "package.json").write_text("{}\n")
        (tmp_path / "pnpm-lock.yaml").write_text("")

        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="node", pkg_mgr="pnpm")

    def it_detects_node_yarn(self, tmp_path: Path) -> None:
        from oracle.project import StackInfo, detect_stack

        (tmp_path / "package.json").write_text("{}\n")
        (tmp_path / "yarn.lock").write_text("")

        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="node", pkg_mgr="yarn")

    def it_detects_node_npm_as_default(self, tmp_path: Path) -> None:
        from oracle.project import StackInfo, detect_stack

        (tmp_path / "package.json").write_text("{}\n")

        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="node", pkg_mgr="npm")

    def it_detects_go(self, tmp_path: Path) -> None:
        from oracle.project import StackInfo, detect_stack

        (tmp_path / "go.mod").write_text("module example\n")

        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="go", pkg_mgr="go")

    def it_detects_rust(self, tmp_path: Path) -> None:
        from oracle.project import StackInfo, detect_stack

        (tmp_path / "Cargo.toml").write_text("[package]\n")

        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="rust", pkg_mgr="cargo")

    def it_returns_unknown_for_empty_dir(self, tmp_path: Path) -> None:
        from oracle.project import StackInfo, detect_stack

        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="unknown")


class DescribeProjectState:
    def it_holds_project_root_and_stack(self) -> None:
        from oracle.project import ProjectState, StackInfo

        state = ProjectState(
            root=Path("/tmp/proj"),
            stack=StackInfo(lang="python", pkg_mgr="uv"),
        )
        assert state.root == Path("/tmp/proj")
        assert state.stack.lang == "python"
        assert state.stack.pkg_mgr == "uv"

    def it_has_sensible_defaults(self) -> None:
        from oracle.project import ProjectState, StackInfo

        state = ProjectState(
            root=Path("/tmp/proj"),
            stack=StackInfo(lang="go"),
        )
        assert state.project_id == ""
        assert state.store is None
        assert state.file_cache is None
        assert state.git_cache is None
        assert state.command_cache is None
        assert state.chunkhound is None
        assert state.chunkhound_failed is False
        assert state.session_id == ""
