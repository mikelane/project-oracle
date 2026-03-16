"""Step definitions for file content caching scenarios."""
from behave import given, then, when


@given('a project with file "{path}" containing "{content}"')
def step_project_with_file(context, path, content):
    raise NotImplementedError("Implement after cache layer exists")


@given("a project exists")
def step_project_exists(context):
    raise NotImplementedError("Implement after cache layer exists")


@given('the agent has already read "{path}"')
def step_agent_has_read(context, path):
    raise NotImplementedError("Implement after cache layer exists")


@given('"{path}" is modified to contain "{content}"')
def step_file_modified(context, path, content):
    raise NotImplementedError("Implement after cache layer exists")


@when('the agent calls oracle_read on "{path}"')
def step_oracle_read(context, path):
    raise NotImplementedError("Implement after cache layer exists")


@when('the agent calls oracle_forget on "{path}"')
def step_oracle_forget(context, path):
    raise NotImplementedError("Implement after cache layer exists")


@then('the response contains "{text}"')
def step_response_contains(context, text):
    raise NotImplementedError("Implement after cache layer exists")


@then('the response contains "{text}" ignoring case')
def step_response_contains_ignoring_case(context, text):
    raise NotImplementedError("Implement after cache layer exists")
