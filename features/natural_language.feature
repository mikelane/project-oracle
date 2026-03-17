Feature: Natural language queries
  The oracle routes plain English questions to the appropriate handler
  without consuming LLM tokens for routing.

  Scenario: Git question routes to git cache
    Given a git project on branch "main"
    When the agent asks "what changed?"
    Then the response is about git status

  Scenario: Test question routes to command cache
    Given a project exists
    When the agent asks "are tests passing?"
    Then the response is about test status

  Scenario: Structure question routes to project overview
    Given a project with a Python stack
    When the agent asks "what's the project structure?"
    Then the response contains "python" ignoring case
