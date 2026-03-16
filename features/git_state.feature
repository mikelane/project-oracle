Feature: Git state caching
  The oracle tracks git branch, status, and recent commits,
  returning deltas when the state changes.

  Scenario: Status shows current branch and clean state
    Given a git project on branch "main"
    When the agent calls oracle_status
    Then the response contains "main"
    And the response contains "clean"

  Scenario: Status shows dirty files after modification
    Given a git project on branch "main"
    And file "src/app.py" is modified in the working tree
    When the agent calls oracle_status
    Then the response contains "app.py"
