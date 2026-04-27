@ISSUE-13
Feature: PreToolUse hook blocks only provably redundant Reads in the current session
  The hook is binary on Read: exit 2 to block when the file was both served
  this session and is unchanged on disk; exit 0 in every other case. Bash
  and Grep stay advisory.

  Background:
    Given Oracle's MCP server is running and tracking the current project
    And the AYLO PreToolUse hook is registered for Read
    And the per-project SQLite database has a session_files table populated by both the MCP server and the ingest worker

  @ISSUE-13
  Scenario: Redundant Read served via oracle_read this session is blocked
    Given the agent called oracle_read on "src/foo.py" earlier in the current session
    And session_files contains a row for the current session and "src/foo.py"
    And file_cache.disk_sha256 for "src/foo.py" equals its current on-disk SHA-256
    When the hook fires for Read on "src/foo.py" with no offset or limit
    Then the hook exits with code 2
    And stderr contains "File unchanged since last read"
    And stderr contains the resolved path of "src/foo.py"

  @ISSUE-13
  Scenario: Redundant Read after PostToolUse ingest is blocked
    Given the agent called Read on "src/foo.py" earlier in the current session
    And the ingest worker has consumed the event and inserted into session_files
    And file_cache.disk_sha256 for "src/foo.py" still matches on-disk
    When the hook fires for Read on "src/foo.py" with no offset or limit
    Then the hook exits with code 2

  @ISSUE-13
  Scenario: Cross-session unchanged file with no current-session record is allowed
    Given file_cache contains "src/legacy.py" with a matching disk_sha256 from a prior session
    And session_files contains no row for the current session and "src/legacy.py"
    When the hook fires for Read on "src/legacy.py"
    Then the hook exits with code 0

  @ISSUE-13
  Scenario: First Read of a file in the current session is allowed
    Given session_files contains no row for the current session and "src/bar.py"
    When the hook fires for Read on "src/bar.py"
    Then the hook exits with code 0

  @ISSUE-13
  Scenario: Read of a changed file is allowed even if served this session
    Given session_files contains a row for the current session and "src/baz.py"
    And file_cache.disk_sha256 for "src/baz.py" differs from its current on-disk SHA-256
    When the hook fires for Read on "src/baz.py"
    Then the hook exits with code 0

  @ISSUE-13
  Scenario: Ingest race — agent re-reads before the ingest worker has processed the prior Read
    Given the agent just called Read on "src/quick.py"
    And the ingest worker has not yet inserted into session_files for that Read
    When the hook fires for Read on "src/quick.py"
    Then the hook exits with code 0

  @ISSUE-13
  Scenario: Oracle SQLite unreachable falls back to allow
    Given the per-project SQLite database file does not exist
    When the hook fires for Read on "src/foo.py"
    Then the hook exits with code 0

  @ISSUE-13
  Scenario: Partial Read overrides the would-block SHA-match path
    Given the agent called Read on "src/foo.py" earlier in the current session
    And session_files contains a row for the current session and "src/foo.py"
    And file_cache.disk_sha256 for "src/foo.py" matches on-disk
    When the hook fires for Read on "src/foo.py" with offset 0 and limit 100
    Then the hook exits with code 0

  @ISSUE-13
  Scenario: Partial Read of an unseen file is allowed
    Given session_files contains no row for the current session and "src/never.py"
    When the hook fires for Read on "src/never.py" with offset 10 and limit 50
    Then the hook exits with code 0

  @ISSUE-13
  Scenario: Full Read after a partial Read is blocked
    Given the agent first called Read on "src/foo.py" with offset 0 and limit 100
    And the ingest worker added a row for the current session and "src/foo.py"
    And file_cache.disk_sha256 for "src/foo.py" still matches on-disk
    When the hook fires for Read on "src/foo.py" with no offset or limit
    Then the hook exits with code 2

  @ISSUE-13
  Scenario: Path outside any tracked project is allowed
    When the hook fires for Read on a path outside any tracked project root
    Then the hook exits with code 0

  @ISSUE-13
  Scenario: Symlink whose resolved target is in session_files is blocked
    Given "src/symlink.py" is a symbolic link to "src/foo.py"
    And session_files contains a row for the current session and the resolved target "src/foo.py"
    And file_cache.disk_sha256 for "src/foo.py" matches on-disk
    When the hook fires for Read on "src/symlink.py"
    Then the hook exits with code 2

  @ISSUE-13
  Scenario: Escalation counter is removed from the hook source
    When inspecting the hook source for "get_count", "set_count", and "COUNTER_DIR"
    Then no matches are found

  @ISSUE-13
  Scenario: Bash advisory remains intact and non-blocking
    When the hook fires for Bash with command "ls -la"
    Then the hook exits with code 0
    And stdout contains "additionalContext"
    And stdout contains "oracle_run"

  @ISSUE-13
  Scenario: Grep advisory remains intact and non-blocking
    When the hook fires for Grep with pattern "needle"
    Then the hook exits with code 0
    And stdout contains "additionalContext"
    And stdout contains "oracle_grep"

  @ISSUE-13
  Scenario: No timeout binary on PATH fails open silently
    Given the agent called Read on "src/foo.py" earlier in the current session
    And file_cache.disk_sha256 for "src/foo.py" matches on-disk
    And neither timeout nor gtimeout is on PATH
    When the hook fires for Read on "src/foo.py" with no offset or limit
    Then the hook exits with code 0
    And stderr is empty

  @ISSUE-13
  Scenario: Hook source explicitly detects timeout/gtimeout availability
    When inspecting the hook source for the timeout fallback
    Then the hook source declares both "timeout" and "gtimeout" as candidates
    And the hook source uses the resolved timeout command via a variable
