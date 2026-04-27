"""Step definitions for hooks.feature — exercise lights-on-oracle-pre.sh against
real SQLite fixtures.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

from behave import given, then, when

from oracle.storage.store import OracleStore

HOOK_SCRIPT = Path(__file__).resolve().parent.parent.parent / "hooks" / "lights-on-oracle-pre.sh"
SESSION_ID = "behave-test-session"


def _setup_project(context) -> Path:
    if hasattr(context, "hook_project_root"):
        return context.hook_project_root
    project = context.tmp_dir / "project"
    project.mkdir(exist_ok=True)
    (project / ".git").mkdir(exist_ok=True)
    (project / "src").mkdir(exist_ok=True)
    context.hook_project_root = project
    context.hook_oracle_dir = context.tmp_dir / "oracle"
    (context.hook_oracle_dir / "projects").mkdir(parents=True, exist_ok=True)
    pid = hashlib.sha256(str(project.resolve()).encode()).hexdigest()[:8]
    context.hook_db_dir = context.hook_oracle_dir / "projects" / pid
    context.hook_db_dir.mkdir(parents=True, exist_ok=True)
    context.hook_db_path = context.hook_db_dir / "oracle.db"
    context.hook_store = OracleStore(context.hook_db_path)
    return project


def _resolve(context, path: str) -> str:
    return str((context.hook_project_root / path).resolve())


def _write_file_cache(context, rel_path: str, content: bytes, disk_sha: str) -> None:
    full = _resolve(context, rel_path)
    context.hook_store.upsert_file_cache(full, content, disk_sha, disk_sha, int(time.time()))


def _record_session(context, rel_path: str) -> None:
    full = _resolve(context, rel_path)
    context.hook_store.record_session_file(SESSION_ID, full, int(time.time()))


def _run_hook(context, payload: dict, file_path_for_resolve: str | None = None) -> None:
    env = os.environ.copy()
    env["ORACLE_DIR"] = str(context.hook_oracle_dir)
    if getattr(context, "hook_path_override", None) is not None:
        env["PATH"] = context.hook_path_override
    if hasattr(context, "hook_store"):
        context.hook_store.close()
        context.hook_store = OracleStore(context.hook_db_path)
    result = subprocess.run(
        [str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    context.hook_exit_code = result.returncode
    context.hook_stdout = result.stdout
    context.hook_stderr = result.stderr
    context.hook_resolved = file_path_for_resolve


def _make_file(context, rel_path: str, content: str = "print('hello')\n") -> str:
    project = _setup_project(context)
    full = project / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    return _resolve(context, rel_path)


@given("Oracle's MCP server is running and tracking the current project")
def step_mcp_running(context):
    _setup_project(context)


@given("the AYLO PreToolUse hook is registered for Read")
def step_hook_registered(context):
    assert HOOK_SCRIPT.exists(), f"Hook script missing: {HOOK_SCRIPT}"


@given(
    "the per-project SQLite database has a session_files table "
    "populated by both the MCP server and the ingest worker"
)
def step_db_has_session_files(context):
    _setup_project(context)
    # session_files exists via _init_schema
    rows = context.hook_store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='session_files'"
    ).fetchall()
    assert rows, "session_files table missing"


@given('the agent called oracle_read on "{rel_path}" earlier in the current session')
def step_agent_oracle_read(context, rel_path):
    full = _make_file(context, rel_path)
    content = Path(full).read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    _write_file_cache(context, rel_path, content, sha)
    _record_session(context, rel_path)


@given('the agent called Read on "{rel_path}" earlier in the current session')
def step_agent_builtin_read(context, rel_path):
    full = _make_file(context, rel_path)
    content = Path(full).read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    _write_file_cache(context, rel_path, content, sha)
    _record_session(context, rel_path)


@given('session_files contains a row for the current session and "{rel_path}"')
def step_session_files_has_row(context, rel_path):
    _make_file(context, rel_path)
    _record_session(context, rel_path)


@given('session_files contains a row for the current session and the resolved target "{rel_path}"')
def step_session_files_has_resolved_target(context, rel_path):
    full = _make_file(context, rel_path)
    content = Path(full).read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    _write_file_cache(context, rel_path, content, sha)
    _record_session(context, rel_path)


@given('"{symlink_path}" is a symbolic link to "{target}"')
def step_symlink(context, symlink_path, target):
    project = _setup_project(context)
    target_full = project / target
    if not target_full.exists():
        target_full.parent.mkdir(parents=True, exist_ok=True)
        target_full.write_text("print('hello')\n")
    sym_full = project / symlink_path
    sym_full.parent.mkdir(parents=True, exist_ok=True)
    if sym_full.exists() or sym_full.is_symlink():
        sym_full.unlink()
    sym_full.symlink_to(target_full)


@given('file_cache.disk_sha256 for "{rel_path}" equals its current on-disk SHA-256')
def step_disk_sha_matches(context, rel_path):
    full = _resolve(context, rel_path)
    content = Path(full).read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    context.hook_store.upsert_file_cache(full, content, sha, sha, int(time.time()))


@given('file_cache.disk_sha256 for "{rel_path}" matches on-disk')
def step_disk_sha_matches_short(context, rel_path):
    step_disk_sha_matches(context, rel_path)


@given('file_cache.disk_sha256 for "{rel_path}" still matches on-disk')
def step_disk_sha_still_matches(context, rel_path):
    step_disk_sha_matches(context, rel_path)


@given('file_cache.disk_sha256 for "{rel_path}" differs from its current on-disk SHA-256')
def step_disk_sha_differs(context, rel_path):
    # Ensure the file exists, then store a stale SHA in file_cache
    _make_file(context, rel_path)
    full = _resolve(context, rel_path)
    content = Path(full).read_bytes()
    stale_sha = "stale" + "0" * 59  # 64-char hex placeholder distinct from real SHA
    context.hook_store.upsert_file_cache(full, content, stale_sha, stale_sha, int(time.time()))


@given('file_cache contains "{rel_path}" with a matching disk_sha256 from a prior session')
def step_cross_session_cache(context, rel_path):
    full = _make_file(context, rel_path)
    content = Path(full).read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    _write_file_cache(context, rel_path, content, sha)


@given('session_files contains no row for the current session and "{rel_path}"')
def step_session_files_no_row(context, rel_path):
    _setup_project(context)
    # Ensure the file exists so the hook can resolve it
    _make_file(context, rel_path)


@given('the agent just called Read on "{rel_path}"')
def step_agent_just_called_read(context, rel_path):
    _make_file(context, rel_path)


@given("the ingest worker has not yet inserted into session_files for that Read")
def step_ingest_not_yet(context):
    pass  # No row recorded


@given("the ingest worker has consumed the event and inserted into session_files")
def step_ingest_consumed(context):
    # already recorded above by step_agent_builtin_read
    pass


@given("the per-project SQLite database file does not exist")
def step_db_missing(context):
    project = _setup_project(context)
    # Close the store and remove the DB file
    context.hook_store.close()
    if context.hook_db_path.exists():
        context.hook_db_path.unlink()
    # Make a placeholder so the file path remains valid for the project,
    # but ensure the actual DB file is missing
    context.hook_resolved_target = project


@given('the agent first called Read on "{rel_path}" with offset 0 and limit 100')
def step_agent_partial_read(context, rel_path):
    _make_file(context, rel_path)


@given("neither timeout nor gtimeout is on PATH")
def step_no_timeout_binary(context):
    # Build a tmp dir with only the helpers the hook genuinely needs (jq,
    # sqlite3, shasum, awk, sed, mktemp, realpath, dirname, printf, cat)
    # but explicitly exclude `timeout` and `gtimeout` so the fallback path
    # is exercised end-to-end.
    isolated = context.tmp_dir / "no-timeout-bin"
    isolated.mkdir(exist_ok=True)
    helpers = [
        "jq",
        "sqlite3",
        "shasum",
        "awk",
        "sed",
        "mktemp",
        "realpath",
        "dirname",
        "printf",
        "cat",
        "bash",
        "head",
        "rm",
    ]
    seen: set[str] = set()
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        if not path_dir:
            continue
        for helper in helpers:
            if helper in seen:
                continue
            candidate = Path(path_dir) / helper
            if candidate.exists():
                link = isolated / helper
                if not link.exists():
                    link.symlink_to(candidate)
                seen.add(helper)
    context.hook_path_override = str(isolated)


@then("stderr is empty")
def step_then_stderr_empty(context):
    assert context.hook_stderr == "", f"Expected empty stderr, got: {context.hook_stderr!r}"


@when("inspecting the hook source for the timeout fallback")
def step_inspect_timeout_fallback(context):
    context.hook_source_text = HOOK_SCRIPT.read_text()


@then('the hook source declares both "timeout" and "gtimeout" as candidates')
def step_then_source_has_candidates(context):
    src = context.hook_source_text
    assert "command -v timeout" in src, "Hook does not probe for `timeout` via command -v"
    assert "command -v gtimeout" in src, "Hook does not probe for `gtimeout` via command -v"


@then("the hook source uses the resolved timeout command via a variable")
def step_then_source_uses_variable(context):
    src = context.hook_source_text
    assert "TIMEOUT_CMD=" in src, "Hook does not assign TIMEOUT_CMD"
    assert '"$TIMEOUT_CMD"' in src, (
        "Hook does not invoke timeout indirectly via $TIMEOUT_CMD — "
        "the literal `timeout` invocation will fail on stock macOS."
    )


@given('the ingest worker added a row for the current session and "{rel_path}"')
def step_ingest_added_row(context, rel_path):
    full = _resolve(context, rel_path)
    content = Path(full).read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    _write_file_cache(context, rel_path, content, sha)
    _record_session(context, rel_path)


@when('the hook fires for Read on "{rel_path}" with no offset or limit')
def step_when_read_no_partial(context, rel_path):
    full = _resolve(context, rel_path)
    payload = {
        "session_id": SESSION_ID,
        "tool_name": "Read",
        "tool_input": {"file_path": full},
    }
    _run_hook(context, payload, file_path_for_resolve=full)


@when('the hook fires for Read on "{rel_path}"')
def step_when_read(context, rel_path):
    step_when_read_no_partial(context, rel_path)


@when('the hook fires for Read on "{rel_path}" with offset {offset:d} and limit {limit:d}')
def step_when_read_partial(context, rel_path, offset, limit):
    full = _resolve(context, rel_path)
    payload = {
        "session_id": SESSION_ID,
        "tool_name": "Read",
        "tool_input": {"file_path": full, "offset": offset, "limit": limit},
    }
    _run_hook(context, payload, file_path_for_resolve=full)


@when("the hook fires for Read on a path outside any tracked project root")
def step_when_read_outside(context):
    _setup_project(context)
    payload = {
        "session_id": SESSION_ID,
        "tool_name": "Read",
        "tool_input": {"file_path": "/etc/hosts"},
    }
    _run_hook(context, payload)


@when('the hook fires for Bash with command "{command}"')
def step_when_bash(context, command):
    _setup_project(context)
    payload = {
        "session_id": SESSION_ID,
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    _run_hook(context, payload)


@when('the hook fires for Grep with pattern "{pattern}"')
def step_when_grep(context, pattern):
    _setup_project(context)
    payload = {
        "session_id": SESSION_ID,
        "tool_name": "Grep",
        "tool_input": {"pattern": pattern},
    }
    _run_hook(context, payload)


@when('inspecting the hook source for "{a}", "{b}", and "{c}"')
def step_inspect_hook_source(context, a, b, c):
    text = HOOK_SCRIPT.read_text()
    context.hook_source_matches = [s for s in (a, b, c) if s in text]


@then("the hook exits with code {code:d}")
def step_then_exit(context, code):
    assert context.hook_exit_code == code, (
        f"Expected exit {code}, got {context.hook_exit_code}.\n"
        f"stdout: {context.hook_stdout}\n"
        f"stderr: {context.hook_stderr}"
    )


@then('stderr contains "{text}"')
def step_then_stderr_contains(context, text):
    assert text in context.hook_stderr, f"Expected '{text}' in stderr; got: {context.hook_stderr!r}"


@then('stderr contains the resolved path of "{rel_path}"')
def step_then_stderr_contains_resolved_path(context, rel_path):
    full = _resolve(context, rel_path)
    assert full in context.hook_stderr, f"Expected '{full}' in stderr; got: {context.hook_stderr!r}"


@then('stdout contains "{text}"')
def step_then_stdout_contains(context, text):
    assert text in context.hook_stdout, f"Expected '{text}' in stdout; got: {context.hook_stdout!r}"


@then("no matches are found")
def step_then_no_matches(context):
    assert context.hook_source_matches == [], (
        f"Expected no matches, found: {context.hook_source_matches}"
    )


@given("Oracle's MCP server is tracking the project")
def step_mcp_tracking(context):
    _setup_project(context)


@given('session_files contains (the current session, "{rel_path}")')
def step_session_files_contains_tuple(context, rel_path):
    full = _make_file(context, rel_path)
    content = Path(full).read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    _write_file_cache(context, rel_path, content, sha)
    _record_session(context, rel_path)


@given('file_cache.disk_sha256 for "{rel_path}" matches its current on-disk SHA-256')
def step_disk_sha_matches_current(context, rel_path):
    step_disk_sha_matches(context, rel_path)


@given("PATH contains gtimeout but NOT timeout")
def step_path_has_gtimeout_only(context):
    # The hook needs `timeout` or `gtimeout` to enforce its SQLite query
    # timeout. To exercise the gtimeout fallback hermetically without
    # depending on the host's coreutils, build an isolated PATH that:
    #   1. Symlinks the helpers the hook needs (jq, sqlite3, shasum, etc.)
    #   2. Does NOT include `timeout`
    #   3. DOES include a `gtimeout` shim that execs the host's actual
    #      timeout-like binary by absolute path (so the hook's
    #      `command -v gtimeout` succeeds and the resulting invocation
    #      really enforces a timeout).
    # If the host has neither `timeout` nor `gtimeout`, skip — there's no
    # way to make a working shim and the scenario can't be exercised.
    host_timeout = shutil.which("timeout") or shutil.which("gtimeout")
    if host_timeout is None:
        context.scenario.skip(
            reason="Host has neither `timeout` nor `gtimeout`; gtimeout shim has nothing to exec."
        )
        return

    isolated = context.tmp_dir / "gtimeout-only-bin"
    isolated.mkdir(exist_ok=True)
    helpers = [
        "jq",
        "sqlite3",
        "shasum",
        "awk",
        "sed",
        "mktemp",
        "realpath",
        "dirname",
        "printf",
        "cat",
        "bash",
        "head",
        "rm",
    ]
    seen: set[str] = set()
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        if not path_dir:
            continue
        for helper in helpers:
            if helper in seen:
                continue
            candidate = Path(path_dir) / helper
            if candidate.exists():
                link = isolated / helper
                if not link.exists():
                    link.symlink_to(candidate)
                seen.add(helper)

    # gtimeout shim: exec the host's real timeout binary by absolute path.
    # The hook will detect this via `command -v gtimeout` and invoke it
    # exactly like the GNU `timeout` it stands in for.
    gtimeout_shim = isolated / "gtimeout"
    gtimeout_shim.write_text(f'#!/bin/bash\nexec "{host_timeout}" "$@"\n')
    gtimeout_shim.chmod(gtimeout_shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Crucially, do NOT symlink `timeout` itself — the hook must fall
    # through to the gtimeout branch.
    context.hook_path_override = str(isolated)


@when('the agent calls Read with file_path "{rel_path}" and no offset/limit')
def step_when_agent_calls_read(context, rel_path):
    step_when_read_no_partial(context, rel_path)
