Feature: File content caching
  The oracle caches file contents and returns compact deltas on repeat reads,
  saving the agent from re-reading unchanged files.

  Scenario: First read returns full file content
    Given a project with file "src/main.py" containing "def hello(): pass"
    When the agent calls oracle_read on "src/main.py"
    Then the response contains "def hello(): pass"

  Scenario: Repeat read on unchanged file returns no-change notice
    Given a project with file "src/main.py" containing "def hello(): pass"
    And the agent has already read "src/main.py"
    When the agent calls oracle_read on "src/main.py"
    Then the response contains "No changes"

  Scenario: Read after file modification returns delta
    Given a project with file "src/main.py" containing "def hello(): pass"
    And the agent has already read "src/main.py"
    And "src/main.py" is modified to contain "def hello(): return 42"
    When the agent calls oracle_read on "src/main.py"
    Then the response contains "changed" ignoring case

  Scenario: Forget clears cache and forces full re-read
    Given a project with file "src/main.py" containing "def hello(): pass"
    And the agent has already read "src/main.py"
    When the agent calls oracle_forget on "src/main.py"
    And the agent calls oracle_read on "src/main.py"
    Then the response contains "def hello(): pass"

  Scenario: Reading nonexistent file returns error
    Given a project exists
    When the agent calls oracle_read on "nonexistent.py"
    Then the response contains "not found" ignoring case
