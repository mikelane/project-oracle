#!/bin/bash
# "Are Your Lights On?" — PreToolUse:Read/Grep/Bash
# Nudges the agent to check oracle cache before re-reading files or re-running commands.
# Outputs JSON additionalContext so the agent actually sees the question.
# Always exits 0 (non-blocking, allows the tool to proceed).

set -euo pipefail

emit_pre() {
    local question="$1"
    jq -n --arg q "$question" '{
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

# --- Read: has the oracle already cached this file? ---
if [[ "$TOOL_NAME" == "Read" ]]; then
    emit_pre "Has the oracle already cached this file, or are you about to burn 1000+ tokens re-reading content you already have — content the user is paying for twice?"
    exit 0
fi

# --- Grep: did you already run this search? ---
if [[ "$TOOL_NAME" == "Grep" ]]; then
    emit_pre "Did you already run this search, or are you about to get back the same results you already have while the user watches you repeat yourself?"
    exit 0
fi

# --- Bash: does the oracle have fresh results? ---
if [[ "$TOOL_NAME" == "Bash" ]]; then
    emit_pre "Is this a command the oracle already has fresh results for, or are you about to re-run a 10-second command and make the user wait for an answer the oracle could return instantly?"
    exit 0
fi

exit 0
