#!/bin/bash
# "Are Your Lights On?" — PostToolUse:Read/Grep/Bash
# Feeds tool usage data to the oracle's cache so it builds state
# even when the agent bypasses oracle tools.
# Outputs JSON additionalContext so the agent actually sees the question.
# Always exits 0 (non-blocking).

set -euo pipefail

TOOL_INPUT=$(cat 2>/dev/null) || true
[[ -z "$TOOL_INPUT" ]] && exit 0

TOOL_NAME=$(echo "$TOOL_INPUT" | jq -r '.tool_name // empty' 2>/dev/null) || true
[[ -z "$TOOL_NAME" ]] && exit 0

ORACLE_DIR="$HOME/.project-oracle"
QUEUE_DIR="$ORACLE_DIR/ingest"
mkdir -p "$QUEUE_DIR"

TIMESTAMP=$(date +%s%N)
echo "$TOOL_INPUT" > "$QUEUE_DIR/${TIMESTAMP}.json" &

exit 0
