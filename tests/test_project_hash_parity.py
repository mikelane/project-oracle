"""Parity tests for project-ID-from-path hashing.

The PreToolUse hook (`hooks/lights-on-oracle-pre.sh`) and the Python
`ProjectRegistry` both derive a per-project SQLite database directory from
the project root path. They MUST agree byte-for-byte, otherwise the hook
either reads the wrong DB or no DB at all and silently fails open. These
tests pin the algorithm to the Python implementation and exercise the bash
hook's logic side-by-side.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

HOOK_SCRIPT = Path(__file__).resolve().parent.parent / "hooks" / "lights-on-oracle-pre.sh"


def python_project_hash(root: Path) -> str:
    """Match `ProjectRegistry.for_path` derivation in src/oracle/registry.py."""
    return hashlib.sha256(str(root).encode()).hexdigest()[:8]


def bash_project_hash(root: Path) -> str:
    """Run the same shell pipeline the hook uses."""
    result = subprocess.run(
        ["bash", "-c", f'printf "%s" "{root}" | shasum -a 256 | head -c 8'],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.mark.medium
@pytest.mark.parametrize(
    "rel_root",
    [
        "project",
        "project/with space",
        "deep/nested/path",
        "trailing-slash-not-here",
        "unicode-naïve-Ω",
    ],
)
def test_python_and_bash_agree_on_project_hash(tmp_path: Path, rel_root: str) -> None:
    root = tmp_path / rel_root
    root.mkdir(parents=True)

    py_hash = python_project_hash(root)
    sh_hash = bash_project_hash(root)

    assert py_hash == sh_hash, (
        f"Project-hash drift between Python and bash for root={root!r}:\n"
        f"  python -> {py_hash}\n"
        f"  bash   -> {sh_hash}\n"
        "If these disagree, the hook will read the wrong DB."
    )


@pytest.mark.small
def test_hook_script_uses_documented_hash_pipeline() -> None:
    """Pin the bash pipeline so any future edit forces this test to be revisited."""
    text = HOOK_SCRIPT.read_text()
    assert "shasum -a 256 | head -c 8" in text, (
        "Hook no longer derives project ID via `shasum -a 256 | head -c 8`. "
        "If the algorithm changed, update ProjectRegistry to match and revise "
        "the parity test before merging."
    )
