"""Tool handler for oracle_grep — search files for a pattern using grep."""

from __future__ import annotations

import subprocess
from pathlib import Path

_SOURCE_GLOBS = ("*.py", "*.ts", "*.js", "*.go", "*.rs", "*.tsx", "*.jsx", "*.java", "*.rb")
_MAX_MATCHES = 50
_GREP_TIMEOUT = 30


def handle_oracle_grep(pattern: str, path: str) -> str:
    """Search for pattern in source files under path. Cap at 50 matches."""
    search_path = Path(path)
    if not search_path.exists():
        return f"No matches for pattern: {pattern}"

    include_args: list[str] = []
    for glob in _SOURCE_GLOBS:
        include_args.extend(["--include", glob])

    try:
        result = subprocess.run(
            ["grep", "-rn", *include_args, pattern, str(search_path)],
            capture_output=True,
            text=True,
            timeout=_GREP_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"Error: grep failed for pattern '{pattern}': {exc}"

    if result.returncode != 0 or not result.stdout.strip():
        return f"No matches for pattern: {pattern}"

    lines = result.stdout.strip().splitlines()
    total = len(lines)
    truncated = total > _MAX_MATCHES
    display_lines = lines[:_MAX_MATCHES]

    if truncated:
        header = f"{_MAX_MATCHES} matches (truncated from {total}):"
    else:
        count_word = "match" if total == 1 else "matches"
        header = f"{total} {count_word}:"

    return header + "\n" + "\n".join(display_lines)
