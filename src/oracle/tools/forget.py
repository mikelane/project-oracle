"""Tool handler for oracle_forget — clear file cache for a given path."""

from __future__ import annotations

from oracle.cache.file_cache import FileCache


def handle_oracle_forget(path: str, file_cache: FileCache) -> str:
    """Clear cache for path. Next oracle_read returns full content."""
    file_cache.forget(path)
    return f"Cache cleared for {path}. Next oracle_read will return full content."
