"""FileCache — file caching with zstd compression and delta diffing."""

from __future__ import annotations

import difflib
import hashlib
import time
from pathlib import Path

import zstandard as zstd

from oracle.formatting import format_elapsed
from oracle.storage.store import OracleStore

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _compute_delta(old: str, new: str) -> str:
    """Compute a unified diff between old and new content, skipping --- / +++ headers."""
    diff_lines = list(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            n=3,
        )
    )
    # Skip the first two lines (--- and +++ headers)
    filtered = diff_lines[2:] if len(diff_lines) >= 2 else diff_lines
    return "".join(filtered)


class FileCache:
    """Cache file contents with zstd compression; return compact deltas on repeat reads."""

    def __init__(self, store: OracleStore) -> None:
        self._store = store
        self._compressor = zstd.ZstdCompressor(level=3)
        self._decompressor = zstd.ZstdDecompressor()

    def smart_read(self, path: str) -> str:
        """Read a file, returning full content on miss or a compact response on hit."""
        response, _tokens_saved = self.smart_read_with_stats(path)
        return response

    def smart_read_with_stats(self, path: str) -> tuple[str, int]:
        """Read a file, returning (response_text, estimated_tokens_saved)."""
        file_path = Path(path)
        if not file_path.is_file():
            return f"Error: file not found: {path}", 0

        try:
            file_size = file_path.stat().st_size
        except OSError:
            return f"Error: cannot stat file: {path}", 0

        if file_size > _MAX_FILE_SIZE:
            return f"Error: file too large ({file_size:,} bytes, max {_MAX_FILE_SIZE:,})", 0

        content = file_path.read_text()
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        now = int(time.time())

        cached = self._store.get_file_cache(path)

        if cached is None:
            # Cache miss: store and return full content
            compressed = self._compressor.compress(content.encode())
            self._store.upsert_file_cache(path, compressed, content_hash, content_hash, now)
            return content, 0

        # Cache hit: check if content changed
        cached_content = bytes(cached["content"])  # type: ignore[call-overload]
        last_read = int(cached["last_read"])  # type: ignore[call-overload]

        if cached["sha256"] == content_hash:
            # Unchanged
            elapsed = now - last_read
            self._store.upsert_file_cache(
                path,
                cached_content,
                content_hash,
                content_hash,
                now,
            )
            tokens_saved = len(content) // 4
            return f"No changes since last read ({format_elapsed(elapsed)} ago)", tokens_saved

        # Changed: compute delta
        old_content = self._decompressor.decompress(cached_content).decode()
        delta = _compute_delta(old_content, content)
        compressed = self._compressor.compress(content.encode())
        self._store.upsert_file_cache(path, compressed, content_hash, content_hash, now)

        full_tokens = len(content) // 4
        delta_tokens = len(delta) // 4
        tokens_saved = full_tokens - delta_tokens
        return f"Changed since last read:\n{delta}", max(tokens_saved, 0)

    def forget(self, path: str) -> None:
        """Remove a file from cache. Next smart_read returns full content."""
        self._store.delete_file_cache(path)

    def mark_stale(self, path: str, new_disk_hash: str) -> None:
        """Called by FS watcher. Updates disk_sha256 in store."""
        self._store.update_disk_sha256(path, new_disk_hash)
