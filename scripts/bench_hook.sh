#!/bin/bash
# Benchmarks the lights-on-oracle-pre.sh PreToolUse hook on a redundant
# Read input. Builds a SQLite fixture with at least 1000 file_cache rows
# and 1000 session_files rows distributed across 10+ session_ids, then
# runs the hook 100 times against the same redundant-Read input and
# reports p50 / p99 wall-clock times.
#
# Per the issue AC: p50 < 30ms and p99 < 50ms on an M-series Mac.
# CI does not enforce these budgets; the script is for manual verification.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$REPO_ROOT/hooks/lights-on-oracle-pre.sh"

if [[ ! -x "$HOOK" ]]; then
    echo "Hook not executable: $HOOK" >&2
    exit 1
fi

WORKDIR="$(mktemp -d -t bench-hook.XXXXXX)"
trap 'rm -rf "$WORKDIR"' EXIT

PROJECT_DIR="$WORKDIR/project"
ORACLE_DIR="$WORKDIR/oracle"
mkdir -p "$PROJECT_DIR/src" "$ORACLE_DIR/projects"
(cd "$PROJECT_DIR" && git init -q)

PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" - "$PROJECT_DIR" "$ORACLE_DIR" <<'PY'
import hashlib
import sqlite3
import sys
import time
from pathlib import Path

project_dir = Path(sys.argv[1]).resolve()
oracle_dir = Path(sys.argv[2]).resolve()

target_rel = "src/foo.py"
target_path = project_dir / target_rel
target_path.write_text("print('benchmark target')\n")
target_full = str(target_path.resolve())
target_sha = hashlib.sha256(target_path.read_bytes()).hexdigest()

pid = hashlib.sha256(str(project_dir).encode()).hexdigest()[:8]
db_dir = oracle_dir / "projects" / pid
db_dir.mkdir(parents=True, exist_ok=True)
db_path = db_dir / "oracle.db"

conn = sqlite3.connect(str(db_path))
conn.executescript(
    """
    CREATE TABLE IF NOT EXISTS file_cache (
        path TEXT PRIMARY KEY,
        content BLOB,
        sha256 TEXT NOT NULL,
        disk_sha256 TEXT,
        first_seen INTEGER NOT NULL,
        last_read INTEGER NOT NULL,
        read_count INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS session_files (
        session_id TEXT NOT NULL,
        path TEXT NOT NULL,
        served_at INTEGER NOT NULL,
        PRIMARY KEY (session_id, path)
    );
    """
)
now = int(time.time())

# Insert the target plus 999 sibling rows in file_cache.
fake_content = b"# filler\n" * 4
fake_sha = hashlib.sha256(fake_content).hexdigest()
rows = [
    (target_full, target_path.read_bytes(), target_sha, target_sha, now, now)
]
for i in range(999):
    sibling_path = str(project_dir / "src" / f"sibling_{i}.py")
    rows.append((sibling_path, fake_content, fake_sha, fake_sha, now, now))
conn.executemany(
    "INSERT OR REPLACE INTO file_cache "
    "(path, content, sha256, disk_sha256, first_seen, last_read) "
    "VALUES (?, ?, ?, ?, ?, ?)",
    rows,
)

# Distribute 1000 session_files rows across 10 session_ids; the bench
# session is the first one and gets the target row.
session_rows = [("bench-session", target_full, now)]
for sid_idx in range(10):
    sid = f"sess-{sid_idx:02d}"
    for j in range(100 if sid_idx > 0 else 99):
        session_rows.append(
            (sid, str(project_dir / "src" / f"sibling_{sid_idx * 100 + j}.py"), now)
        )
conn.executemany(
    "INSERT OR REPLACE INTO session_files (session_id, path, served_at) VALUES (?, ?, ?)",
    session_rows,
)
conn.commit()
conn.close()

print(f"DB={db_path}")
print(f"TARGET_PATH={target_full}")
PY

# Build hook input JSON in a file so we feed identical input each iteration.
INPUT_FILE="$WORKDIR/input.json"
"$PYTHON_BIN" - "$WORKDIR" "$PROJECT_DIR" <<'PY'
import json
import sys
from pathlib import Path

workdir = Path(sys.argv[1])
project_dir = Path(sys.argv[2]).resolve()
target = str((project_dir / "src" / "foo.py").resolve())
payload = {
    "session_id": "bench-session",
    "tool_name": "Read",
    "tool_input": {"file_path": target},
}
(workdir / "input.json").write_text(json.dumps(payload))
PY

ITERATIONS="${ITERATIONS:-100}"
TIMINGS_FILE="$WORKDIR/timings.txt"
: > "$TIMINGS_FILE"

export ORACLE_DIR

# Sanity check: hook exits 2 on the redundant input.
if "$HOOK" < "$INPUT_FILE" > /dev/null 2>&1; then
    echo "Sanity check failed: hook should have exited 2 (block) on redundant input." >&2
    exit 1
fi

# Use Python to drive the loop — much lower per-iteration overhead than
# spawning a Python subprocess just to read a clock between bash forks.
"$PYTHON_BIN" - "$HOOK" "$INPUT_FILE" "$TIMINGS_FILE" "$ITERATIONS" "$ORACLE_DIR" <<'PY'
import os
import subprocess
import sys
import time
from pathlib import Path

hook, input_file, timings_file, iterations, oracle_dir = sys.argv[1:6]
input_bytes = Path(input_file).read_bytes()
env = os.environ.copy()
env["ORACLE_DIR"] = oracle_dir

with Path(timings_file).open("w") as f:
    for _ in range(int(iterations)):
        start = time.perf_counter_ns()
        subprocess.run(
            [hook],
            input=input_bytes,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            check=False,
        )
        elapsed = time.perf_counter_ns() - start
        f.write(f"{elapsed}\n")
PY

"$PYTHON_BIN" - "$TIMINGS_FILE" <<'PY'
import statistics
import sys
from pathlib import Path

timings_ns = [int(x) for x in Path(sys.argv[1]).read_text().splitlines() if x.strip()]
timings_ms = [n / 1_000_000 for n in timings_ns]
n = len(timings_ms)
p50 = statistics.median(timings_ms)
p99 = statistics.quantiles(timings_ms, n=100, method="inclusive")[98]
print(f"iterations: {n}")
print(f"p50: {p50:.2f} ms")
print(f"p99: {p99:.2f} ms")
print(f"min: {min(timings_ms):.2f} ms")
print(f"max: {max(timings_ms):.2f} ms")
print()
print("budget (per issue #13 AC): p50 < 30ms, p99 < 50ms")
status = "PASS" if (p50 < 30 and p99 < 50) else "FAIL"
print(f"status: {status}")
PY
