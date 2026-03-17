"""ProjectRegistry — maps file paths to ProjectState instances."""

from __future__ import annotations

import hashlib
from pathlib import Path

from oracle.project import ProjectState, detect_project_root, detect_stack
from oracle.storage.store import OracleStore


class ProjectRegistry:
    """Detects projects from file paths and caches ProjectState instances."""

    def __init__(self, oracle_dir: Path) -> None:
        self._oracle_dir = oracle_dir
        self._projects: dict[Path, ProjectState] = {}
        self._current: ProjectState | None = None

    def for_path(self, path: Path) -> ProjectState | None:
        """Detect project root for path, return cached or new ProjectState."""
        root = detect_project_root(path)
        if root is None:
            return None

        if root in self._projects:
            self._current = self._projects[root]
            return self._current

        project_id = hashlib.sha256(str(root).encode()).hexdigest()[:8]
        stack = detect_stack(root)

        db_dir = self._oracle_dir / "projects" / project_id
        db_dir.mkdir(parents=True, exist_ok=True)
        store = OracleStore(db_dir / "oracle.db")

        project = ProjectState(
            root=root,
            stack=stack,
            project_id=project_id,
            store=store,
        )
        self._projects[root] = project
        self._current = project
        return project

    def current(self) -> ProjectState | None:
        """Return the most recently accessed project."""
        return self._current
