"""CommandCache — cached command execution with allowlist and shell injection hardening."""

from __future__ import annotations

import hashlib
import re
import shlex
import subprocess
import time
from pathlib import Path

from oracle.formatting import format_elapsed
from oracle.storage.store import OracleStore

DEFAULT_ALLOWLIST: tuple[str, ...] = (
    "pytest",
    "ruff",
    "mypy",
    "go test",
    "go build",
    "go vet",
    "npm test",
    "pnpm test",
    "eslint",
    "tsc",
    "cargo test",
    "cargo build",
    "cargo clippy",
)

_DANGEROUS_CHARS = re.compile(r"[;&|`$()>\n\r\t<{}!#~]")

_SOURCE_EXTENSIONS = (".py", ".ts", ".js", ".go", ".rs")
_SKIP_DIRS = {".venv", "node_modules"}

_MAX_OUTPUT_CHARS = 2000
_COMMAND_TIMEOUT = 120


class CommandNotAllowedError(Exception):
    """Raised when a command is not on the allowlist or contains shell injection."""


class CommandCache:
    """Cache command results, keyed by command + source file hash. Rejects disallowed commands."""

    def __init__(
        self,
        store: OracleStore,
        project_root: Path,
        extra_allowed: list[str] | None = None,
    ) -> None:
        self._store = store
        self._project_root = project_root
        self._allowlist: tuple[str, ...] = DEFAULT_ALLOWLIST
        if extra_allowed:
            self._allowlist = DEFAULT_ALLOWLIST + tuple(extra_allowed)

    def is_allowed(self, command: str) -> bool:
        """Check if command starts with an allowed prefix and has no shell injection."""
        if _DANGEROUS_CHARS.search(command):
            return False
        cmd_parts = command.strip().split()
        if not cmd_parts:
            return False
        return any(command.strip().startswith(prefix) for prefix in self._allowlist)

    def get_cached_result(self, command: str) -> dict[str, object] | None:
        """Return the cached result for a command, or None if not cached."""
        return self._store.get_command_result(command)

    def run_summarized(self, command: str) -> str:
        """Run a command if allowed, caching the result keyed by source file hash."""
        output, _is_cache_hit, _tokens_saved = self.run_summarized_with_stats(command)
        return output

    def run_summarized_with_stats(self, command: str) -> tuple[str, bool, int]:
        """Run a command if allowed, returning (output, is_cache_hit, tokens_saved).

        On cache hit: is_cache_hit=True, tokens_saved=len(cached_output)//4.
        On miss (fresh run): is_cache_hit=False, tokens_saved=0.
        On CommandNotAllowedError: propagates (not caught).
        """
        if not self.is_allowed(command):
            raise CommandNotAllowedError(f"Command not allowed: {command}")

        input_hash = self._hash_source_files()
        now = int(time.time())

        # Check cache
        cached = self._store.get_command_result(command)
        if cached is not None and cached["input_hash"] == input_hash:
            ran_at = int(cached["ran_at"])  # type: ignore[call-overload]
            elapsed = now - ran_at
            cached_output = str(cached["output"])
            tokens_saved = len(cached_output) // 4
            text = f"Cached result ({format_elapsed(elapsed)} ago):\n{cached_output}"
            return text, True, tokens_saved

        # Run the command
        try:
            args = shlex.split(command)
        except ValueError as exc:
            return f"Error: invalid command syntax: {exc}", False, 0

        try:
            result = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=_COMMAND_TIMEOUT,
                cwd=self._project_root,
            )
        except subprocess.TimeoutExpired:
            return f"Command timed out after {_COMMAND_TIMEOUT}s: {command}", False, 0
        except OSError as exc:
            return f"Error: failed to execute command: {exc}", False, 0

        # Combine stdout and stderr, cap at max output
        output = result.stdout
        if result.stderr:
            output = output + result.stderr
        output = output[:_MAX_OUTPUT_CHARS]

        # Store in cache
        self._store.upsert_command_result(command, output, result.returncode, input_hash, now)

        return output, False, 0

    def _hash_source_files(self) -> str:
        """SHA256 of mtime_ns for all source files, skipping .venv and node_modules."""
        hasher = hashlib.sha256()

        for path in sorted(self._project_root.rglob("*")):
            try:
                if not path.is_file():
                    continue
            except OSError:
                continue
            if path.suffix not in _SOURCE_EXTENSIONS:
                continue
            if any(skip in path.parts for skip in _SKIP_DIRS):
                continue
            try:
                hasher.update(f"{path}:{path.stat().st_mtime_ns}".encode())
            except OSError:
                continue

        return hasher.hexdigest()[:16]
