"""CommandCache — cached command execution with allowlist and shell injection hardening."""

from __future__ import annotations

import hashlib
import re
import subprocess
import time
from pathlib import Path

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
    "echo",
)

_CHAIN_OPERATORS = re.compile(r"[;&|`$()]")

_SOURCE_EXTENSIONS = (".py", ".ts", ".js", ".go", ".rs")
_SKIP_DIRS = {".venv", "node_modules"}

_MAX_OUTPUT_CHARS = 2000
_COMMAND_TIMEOUT = 120


class CommandNotAllowedError(Exception):
    """Raised when a command is not on the allowlist or contains shell injection."""


def _format_elapsed(seconds: int) -> str:
    """Format elapsed seconds as a human-readable string."""
    if seconds >= 3600:
        return f"{seconds // 3600}h"
    if seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


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
        if _CHAIN_OPERATORS.search(command):
            return False
        cmd_parts = command.strip().split()
        if not cmd_parts:
            return False
        return any(command.strip().startswith(prefix) for prefix in self._allowlist)

    def run_summarized(self, command: str) -> str:
        """Run a command if allowed, caching the result keyed by source file hash."""
        if not self.is_allowed(command):
            raise CommandNotAllowedError(f"Command not allowed: {command}")

        input_hash = self._hash_source_files()
        now = int(time.time())

        # Check cache
        cached = self._store.get_command_result(command)
        if cached is not None and cached["input_hash"] == input_hash:
            ran_at = int(cached["ran_at"])  # type: ignore[call-overload]
            elapsed = now - ran_at
            output = str(cached["output"])
            return f"Cached result ({_format_elapsed(elapsed)} ago):\n{output}"

        # Run the command
        try:
            result = subprocess.run(
                command,
                shell=True,  # noqa: S602
                capture_output=True,
                text=True,
                timeout=_COMMAND_TIMEOUT,
                cwd=self._project_root,
            )
        except subprocess.TimeoutExpired:
            return f"Command timed out after {_COMMAND_TIMEOUT}s: {command}"

        # Combine stdout and stderr, cap at max output
        output = result.stdout
        if result.stderr:
            output = output + result.stderr
        output = output[:_MAX_OUTPUT_CHARS]

        # Store in cache
        self._store.upsert_command_result(command, output, result.returncode, input_hash, now)

        return output

    def _hash_source_files(self) -> str:
        """SHA256 of mtime_ns for all source files, skipping .venv and node_modules."""
        hasher = hashlib.sha256()
        source_files: list[Path] = []

        for path in sorted(self._project_root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix not in _SOURCE_EXTENSIONS:
                continue
            # Skip excluded directories
            if any(skip in path.parts for skip in _SKIP_DIRS):
                continue
            source_files.append(path)

        for path in source_files:
            hasher.update(f"{path}:{path.stat().st_mtime_ns}".encode())

        return hasher.hexdigest()[:16]
