"""Ingest bridge — drains the hook queue and pre-populates file caches."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from oracle.ingest import drain_ingest_queue
from oracle.project import ProjectState
from oracle.registry import ProjectRegistry


def process_ingest(
    registry: ProjectRegistry,
    oracle_dir: Path,
    ensure_caches_fn: Callable[[ProjectState], None],
) -> int:
    """Drain the ingest queue and pre-populate file caches for Read entries.

    Returns the count of entries that successfully populated the cache.
    """
    entries = drain_ingest_queue(oracle_dir / "ingest")
    populated = 0

    for entry in entries:
        if entry.get("tool_name") != "Read":
            continue

        tool_input = entry.get("tool_input", {})
        if not isinstance(tool_input, dict):
            continue
        file_path = tool_input.get("file_path")
        if file_path is None:
            continue

        resolved = Path(file_path).resolve()
        if not resolved.is_file():
            continue

        project = registry.for_path(resolved)
        if project is None:
            continue

        ensure_caches_fn(project)

        if project.file_cache is None:
            continue

        project.file_cache.smart_read(str(resolved))
        populated += 1

    return populated
