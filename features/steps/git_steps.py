"""Step definitions for git state caching scenarios."""
from behave import given, when


@given('a git project on branch "{branch}"')
def step_git_project_on_branch(context, branch):
    raise NotImplementedError("Implement after git cache layer exists")


@given('file "{path}" is modified in the working tree')
def step_file_modified_in_working_tree(context, path):
    raise NotImplementedError("Implement after git cache layer exists")


@when("the agent calls oracle_status")
def step_oracle_status(context):
    raise NotImplementedError("Implement after git cache layer exists")
