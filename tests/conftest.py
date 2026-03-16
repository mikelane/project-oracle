from __future__ import annotations

import sqlite3
import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    project = tmp_path / "test-project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("def hello():\n    return 'world'\n")
    (project / "pyproject.toml").write_text('[project]\nname = "test"\n')
    return project


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    project = tmp_path / "git-project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=project,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=project,
        capture_output=True,
        check=True,
    )
    (project / "file.py").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=project, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial", "--no-gpg-sign"],
        cwd=project,
        capture_output=True,
        check=True,
    )
    return project


@pytest.fixture
def in_memory_db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def oracle_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".project-oracle"
    d.mkdir()
    (d / "projects").mkdir()
    (d / "ingest").mkdir()
    return d
