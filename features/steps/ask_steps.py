"""Step definitions for natural language query scenarios."""
from behave import given, then, when


@given("a project with a Python stack")
def step_project_with_python_stack(context):
    raise NotImplementedError("Implement after intent classifier exists")


@when('the agent asks "{question}"')
def step_agent_asks(context, question):
    raise NotImplementedError("Implement after intent classifier exists")


@then("the response is about git status")
def step_response_about_git_status(context):
    raise NotImplementedError("Implement after intent classifier exists")


@then("the response is about test status")
def step_response_about_test_status(context):
    raise NotImplementedError("Implement after intent classifier exists")
