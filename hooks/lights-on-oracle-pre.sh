#!/bin/bash
# "Are Your Lights On?" — PreToolUse:Read/Grep/Bash
# Redirects the agent to oracle_* tools instead of built-in Read/Grep/Bash.
# Uses a per-session counter to escalate from nudge → warning → demand.
# Always exits 0 (non-blocking), but the message gets harder to ignore.

set -euo pipefail

# --- Per-session escalation counter ---
COUNTER_DIR="${TMPDIR:-/tmp}/oracle-aylo-$$"
mkdir -p "$COUNTER_DIR" 2>/dev/null || true

get_count() {
    local tool="$1"
    local f="$COUNTER_DIR/$tool"
    if [[ -f "$f" ]]; then
        read -r n < "$f"
        echo "$((n + 1))"
    else
        echo "1"
    fi
}

set_count() {
    local tool="$1" count="$2"
    echo "$count" > "$COUNTER_DIR/$tool" 2>/dev/null || true
}

emit_pre() {
    local msg="$1"
    jq -n --arg q "$msg" '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "allow",
        additionalContext: $q
      }
    }'
}

TOOL_INPUT=$(cat 2>/dev/null) || true
[[ -z "$TOOL_INPUT" ]] && exit 0

TOOL_NAME=$(echo "$TOOL_INPUT" | jq -r '.tool_name // empty' 2>/dev/null) || true
[[ -z "$TOOL_NAME" ]] && exit 0

# --- Read ---
if [[ "$TOOL_NAME" == "Read" ]]; then
    N=$(get_count Read)
    set_count Read "$N"
    if (( N <= 2 )); then
        emit_pre "STOP. Check: do you already have this file's content in your conversation context? If yes, you don't need to read it again. If no, use oracle_read (mcp__project-oracle__oracle_read) instead of Read — it caches the content so your next read costs 3 tokens instead of hundreds."
    elif (( N <= 5 )); then
        emit_pre "This is Read call #$N this session. You have used Read $N times instead of oracle_read. Each one adds hundreds of tokens to context that oracle_read would have served from cache. Use oracle_read for file reads — it returns full content on first call and compact deltas on repeats."
    else
        emit_pre "Read call #$N. You are consistently ignoring oracle_read. Every Read call bypasses the cache and wastes tokens. The oracle_read tool (mcp__project-oracle__oracle_read) does the same thing but tracks what you've seen. USE IT."
    fi
    exit 0
fi

# --- Grep ---
if [[ "$TOOL_NAME" == "Grep" ]]; then
    N=$(get_count Grep)
    set_count Grep "$N"
    if (( N <= 2 )); then
        emit_pre "STOP. Use oracle_grep (mcp__project-oracle__oracle_grep) instead of Grep. It returns the same results but caches them — if you search for the same pattern again, you get the answer instantly instead of re-scanning the codebase."
    else
        emit_pre "Grep call #$N. Use oracle_grep (mcp__project-oracle__oracle_grep). It caches results so repeated searches cost nothing."
    fi
    exit 0
fi

# --- Bash ---
if [[ "$TOOL_NAME" == "Bash" ]]; then
    N=$(get_count Bash)
    set_count Bash "$N"
    if (( N <= 2 )); then
        emit_pre "Check: is this a test/lint/build command? If so, use oracle_run (mcp__project-oracle__oracle_run) instead — it caches results keyed by source file hashes. If the code hasn't changed since last run, you get the cached result instantly instead of waiting for the command to execute."
    else
        emit_pre "Bash call #$N. For test/lint/build commands, oracle_run (mcp__project-oracle__oracle_run) returns cached results when source files haven't changed. Use it."
    fi
    exit 0
fi

exit 0
