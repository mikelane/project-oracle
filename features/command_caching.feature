Feature: Command result caching
  The oracle runs allowed commands, caches results, and returns
  cached output when source files haven't changed.

  Scenario: Run an allowed command and get results
    Given a project exists
    When the agent calls oracle_run with "echo hello"
    Then the response contains "hello"

  Scenario: Disallowed command is rejected
    Given a project exists
    When the agent calls oracle_run with "rm -rf /"
    Then the response contains "not allowed" ignoring case

  Scenario: Cached result returned when sources unchanged
    Given a project exists
    And the agent has run "echo hello" before
    And no source files have changed
    When the agent calls oracle_run with "echo hello"
    Then the response contains "cached" ignoring case
