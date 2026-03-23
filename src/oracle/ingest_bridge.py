"""Ingest bridge — drains the hook queue and pre-populates file caches."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from oracle.ingest import drain_ingest_queue
from oracle.project import ProjectState
from oracle.registry import ProjectRegistry

BUILTIN_TOOL_MAP: dict[str, str] = {
    "Read": "builtin_read",
    "Grep": "builtin_grep",
    "Bash": "builtin_bash",
}


@dataclass
class IngestResult:
    cache_populated: int
    builtin_logged: int


def process_ingest(
    registry: ProjectRegistry,
    oracle_dir: Path,
    ensure_caches_fn: Callable[[ProjectState], None],
) -> IngestResult:
    """Drain the ingest queue, log built-in tool usage, and pre-populate caches.

    Returns an IngestResult with counts of cache entries populated and
    built-in tools logged.
    """
    entries = drain_ingest_queue(oracle_dir / "ingest")
    populated = 0
    builtin_logged = 0

    for entry in entries:
        tool_name = entry.get("tool_name")
        session_id = entry.get("session_id")
        builtin_name = BUILTIN_TOOL_MAP.get(tool_name, "") if tool_name else ""

        if not session_id or not builtin_name:
            continue

        tool_input = entry.get("tool_input", {})
        if not isinstance(tool_input, dict):
            continue

        # Resolve project: Read uses file_path, others use cwd
        if tool_name == "Read":
            file_path = tool_input.get("file_path")
            if file_path is None:
                continue
            resolved = Path(file_path).resolve()
            project = registry.for_path(resolved)
        else:
            cwd = entry.get("cwd")
            if not cwd:
                continue
            project = registry.for_path(Path(cwd))

        if project is None or project.store is None:
            continue

        # Log to agent_log
        project.store.log_interaction(
            session_id=session_id,
            tool_name=builtin_name,
            input_data=None,
            cache_hit=False,
            tokens_saved=0,
            timestamp=int(time.time()),
        )
        builtin_logged += 1

        # For Read entries, also populate the file cache
        if tool_name == "Read":
            file_path = tool_input.get("file_path")
            if file_path is None:
                continue
            resolved = Path(file_path).resolve()
            if not resolved.is_file():
                continue

            ensure_caches_fn(project)

            if project.file_cache is None:
                continue

            project.file_cache.smart_read(str(resolved))
            populated += 1

    return IngestResult(cache_populated=populated, builtin_logged=builtin_logged)
