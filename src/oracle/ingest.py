"""Ingest queue — drains JSON files written by the PostToolUse hook."""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def drain_ingest_queue(queue_dir: Path) -> list[dict[str, Any]]:
    """Read and delete all .json files from queue_dir, returning parsed entries."""
    entries: list[dict[str, Any]] = []
    if not queue_dir.exists():
        return entries
    for json_file in sorted(queue_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text())
            entries.append(data)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            logger.debug("Skipping malformed ingest entry: %s", json_file)
        finally:
            with contextlib.suppress(OSError):
                json_file.unlink()
    return entries
