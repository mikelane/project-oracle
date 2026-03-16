"""Step definitions for command result caching scenarios."""
from behave import given, when


@when('the agent calls oracle_run with "{command}"')
def step_oracle_run(context, command):
    raise NotImplementedError("Implement after command cache layer exists")


@given('the agent has run "{command}" before')
def step_agent_has_run_command(context, command):
    raise NotImplementedError("Implement after command cache layer exists")


@given("no source files have changed")
def step_no_source_files_changed(context):
    raise NotImplementedError("Implement after command cache layer exists")
