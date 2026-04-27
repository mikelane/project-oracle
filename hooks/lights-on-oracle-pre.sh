#!/bin/bash
# "Are Your Lights On?" — PreToolUse:Read/Grep/Bash
# Read: binary block when the file is provably redundant within the current
#   Claude Code session — i.e., (session_id, path) is in session_files AND
#   file_cache.disk_sha256 matches the on-disk SHA-256. Any other case
#   exits 0 (allow). Failure modes (timeout, missing DB, malformed input,
#   non-tracked path, partial read) all exit 0.
# Grep / Bash: advisory behavior only — emit additionalContext nudging
#   toward oracle_grep / oracle_run. No escalation, no blocking.

set -euo pipefail

ORACLE_DIR="${ORACLE_DIR:-$HOME/.project-oracle}"
PROJECT_MARKERS=(.git package.json pyproject.toml go.mod Cargo.toml)
SQLITE_BUSY_TIMEOUT_MS=30
SQLITE_QUERY_TIMEOUT_S=2

# Resolve a portable timer. macOS does not ship GNU `timeout` by default;
# `brew install coreutils` provides `gtimeout`. If neither is present the
# Read binary-block path will fail open silently (see below) — Bash and
# Grep advisories do not need a timer and stay functional regardless.
if command -v timeout >/dev/null 2>&1; then
    TIMEOUT_CMD=timeout
elif command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_CMD=gtimeout
else
    TIMEOUT_CMD=
fi

emit_advisory() {
    local msg="$1"
    jq -n --arg q "$msg" '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "allow",
        additionalContext: $q
      }
    }'
}

find_project_root() {
    # Walk up from $1 looking for any PROJECT_MARKER. Echo the root or
    # nothing if not found.
    local current="$1"
    [[ -d "$current" ]] || current="$(dirname "$current")"
    while [[ -n "$current" && "$current" != "/" ]]; do
        for marker in "${PROJECT_MARKERS[@]}"; do
            if [[ -e "$current/$marker" ]]; then
                echo "$current"
                return 0
            fi
        done
        current="$(dirname "$current")"
    done
    return 1
}

project_db_path() {
    # Echo the per-project SQLite database path for project root $1.
    # Returns 0 even if the file doesn't exist; callers must check.
    local root="$1"
    local pid
    pid="$(printf '%s' "$root" | shasum -a 256 | head -c 8)"
    echo "$ORACLE_DIR/projects/$pid/oracle.db"
}

_aylo_main() {
    TOOL_INPUT=$(cat 2>/dev/null) || true
    [[ -z "$TOOL_INPUT" ]] && exit 0

    # Single jq call extracts everything we might need: tool_name, session_id,
    # file_path, and presence flags for offset/limit. Tab-separated values are
    # split by IFS read below. Each tab-separated cell is "-" when absent so
    # bash can detect missing fields without ambiguity.
    JQ_OUT=$(printf '%s' "$TOOL_INPUT" | jq -r '
        [
            .tool_name // "",
            .session_id // "",
            .tool_input.file_path // "",
            (if (.tool_input | has("offset")) then "1" else "" end),
            (if (.tool_input | has("limit")) then "1" else "" end)
        ] | @tsv
    ' 2>/dev/null) || exit 0

    IFS=$'\t' read -r TOOL_NAME SESSION_ID FILE_PATH HAS_OFFSET HAS_LIMIT <<< "$JQ_OUT"
    [[ -z "$TOOL_NAME" ]] && exit 0

    # --- Grep: advisory only ---
    if [[ "$TOOL_NAME" == "Grep" ]]; then
        emit_advisory "Use oracle_grep (mcp__project-oracle__oracle_grep) instead of Grep. It returns the same results but caches them — repeated searches cost nothing."
        exit 0
    fi

    # --- Bash: advisory only ---
    if [[ "$TOOL_NAME" == "Bash" ]]; then
        emit_advisory "Check: is this a test/lint/build command? If so, use oracle_run (mcp__project-oracle__oracle_run) instead — it caches results keyed by source file hashes. If the code hasn't changed since last run, you get the cached result instantly instead of waiting for the command to execute."
        exit 0
    fi

    # --- Read: binary block on provably redundant reads ---
    if [[ "$TOOL_NAME" != "Read" ]]; then
        exit 0
    fi

    # No portable timer means we cannot enforce the SQLite query timeout, so
    # the Read binary block is unavailable on this platform. Fail open
    # silently — Bash and Grep advisories already ran above.
    [[ -z "$TIMEOUT_CMD" ]] && exit 0

    [[ -z "$SESSION_ID" ]] && exit 0
    [[ -z "$FILE_PATH" ]] && exit 0

    # Partial read (non-default offset or limit) → allow.
    if [[ -n "$HAS_OFFSET" || -n "$HAS_LIMIT" ]]; then
        exit 0
    fi

    # Resolve path (canonicalize symlinks). If realpath fails (worktree
    # deleted, dangling symlink) → allow.
    RESOLVED_PATH=$(realpath "$FILE_PATH" 2>/dev/null) || exit 0
    [[ -z "$RESOLVED_PATH" ]] && exit 0

    # Path must be inside a tracked project root.
    PROJECT_ROOT=$(find_project_root "$RESOLVED_PATH") || exit 0
    [[ -z "$PROJECT_ROOT" ]] && exit 0

    DB_PATH=$(project_db_path "$PROJECT_ROOT")
    [[ -f "$DB_PATH" ]] || exit 0

    # Lookup cached disk_sha256 for (session_id, path) AND compute the on-disk
    # SHA in parallel. Both are independent and the bottleneck is fork/exec
    # overhead, so running shasum in the background while sqlite3 executes
    # halves the serial cost on the hot path.
    ESCAPED_SESSION=$(printf '%s' "$SESSION_ID" | sed "s/'/''/g")
    ESCAPED_PATH=$(printf '%s' "$RESOLVED_PATH" | sed "s/'/''/g")
    DISK_SHA_FILE=$(mktemp -t aylo-disk-sha.XXXXXX) || exit 0
    trap 'rm -f "$DISK_SHA_FILE"' EXIT

    (shasum -a 256 "$RESOLVED_PATH" 2>/dev/null | awk '{print $1}' > "$DISK_SHA_FILE") &
    DISK_SHA_PID=$!

    CACHED_SHA=$("$TIMEOUT_CMD" "$SQLITE_QUERY_TIMEOUT_S" sqlite3 \
        -readonly \
        -batch \
        -noheader \
        -list \
        -cmd ".timeout $SQLITE_BUSY_TIMEOUT_MS" \
        "$DB_PATH" \
        "SELECT f.disk_sha256 FROM file_cache f JOIN session_files s ON s.path = f.path WHERE s.session_id = '$ESCAPED_SESSION' AND f.path = '$ESCAPED_PATH';" 2>/dev/null) || {
        wait "$DISK_SHA_PID" 2>/dev/null || true
        exit 0
    }

    wait "$DISK_SHA_PID" 2>/dev/null || true
    DISK_SHA=$(<"$DISK_SHA_FILE")

    [[ -z "$CACHED_SHA" || "$CACHED_SHA" == "NULL" ]] && exit 0
    [[ -z "$DISK_SHA" ]] && exit 0

    # Block iff cached disk SHA matches current on-disk SHA.
    if [[ "$CACHED_SHA" == "$DISK_SHA" ]]; then
        printf 'File unchanged since last read: %s\nThe agent already has this content from earlier in the session. Skip this Read; reuse the prior content. If the cached content was lost, use oracle_read for a compact delta.\n' \
            "$RESOLVED_PATH" >&2
        exit 2
    fi

    exit 0
}

# Run main logic only when executed directly. Sourcing the script (e.g., from
# tests/test_project_hash_parity.py) loads the helper functions without firing
# the hook's main pipeline.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    _aylo_main "$@"
fi
