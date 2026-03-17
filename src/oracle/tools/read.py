"""Tool handler for oracle_read — read files with caching and delta diffing."""

from __future__ import annotations

from oracle.cache.file_cache import FileCache


def handle_oracle_read(path: str, file_cache: FileCache) -> str:
    """Read a file, returning full content on miss or a compact delta on hit."""
    return file_cache.smart_read(path)
