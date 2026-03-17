"""Step definitions for natural language query scenarios."""

import asyncio

from behave import given, then, when

from oracle.cache.command_cache import CommandCache
from oracle.cache.git_cache import GitCache
from oracle.project import ProjectState, StackInfo
from oracle.storage.store import OracleStore
from oracle.tools.ask import handle_oracle_ask


def _get_or_create_project_state(context):
    if not hasattr(context, "oracle_project_state"):
        db_path = context.tmp_dir / "state.db"
        if not hasattr(context, "oracle_store"):
            context.oracle_store = OracleStore(db_path)

        stack = getattr(context, "oracle_stack_info", StackInfo(lang="unknown"))

        git_cache = None
        if getattr(context, "oracle_has_git", False):
            git_cache = GitCache(context.oracle_store, context.project_root)

        command_cache = CommandCache(context.oracle_store, context.project_root)

        context.oracle_project_state = ProjectState(
            root=context.project_root,
            stack=stack,
            store=context.oracle_store,
            git_cache=git_cache,
            command_cache=command_cache,
        )
    return context.oracle_project_state


@given("a project with a Python stack")
def step_project_with_python_stack(context):
    context.project_root = context.tmp_dir / "project"
    context.project_root.mkdir(exist_ok=True)
    # Create a pyproject.toml so detect_stack would find Python
    (context.project_root / "pyproject.toml").write_text('[project]\nname = "test"\n')
    context.oracle_stack_info = StackInfo(lang="python", pkg_mgr="pip")


@when('the agent asks "{question}"')
def step_agent_asks(context, question):
    project = _get_or_create_project_state(context)
    context.last_response = asyncio.run(handle_oracle_ask(question, project))


@then("the response is about git status")
def step_response_about_git_status(context):
    assert context.last_response is not None, "No response recorded"
    response_lower = context.last_response.lower()
    git_keywords = ("branch", "clean", "dirty", "head", "commit", "changed", "status")
    assert any(kw in response_lower for kw in git_keywords), (
        f"Expected git-related content in: {context.last_response}"
    )


@then("the response is about test status")
def step_response_about_test_status(context):
    assert context.last_response is not None, "No response recorded"
    response_lower = context.last_response.lower()
    test_keywords = ("test", "no cached", "no test command", "configured", "result")
    assert any(kw in response_lower for kw in test_keywords), (
        f"Expected test-related content in: {context.last_response}"
    )
