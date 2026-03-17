"""Step definitions for file content caching scenarios."""

from behave import given, then, when

from oracle.cache.file_cache import FileCache
from oracle.storage.store import OracleStore
from oracle.tools.forget import handle_oracle_forget
from oracle.tools.read import handle_oracle_read


def _get_or_create_cache(context):
    """Lazily create an OracleStore + FileCache, storing on context with safe names."""
    if not hasattr(context, "oracle_store"):
        db_path = context.tmp_dir / "state.db"
        context.oracle_store = OracleStore(db_path)
        context.oracle_file_cache = FileCache(context.oracle_store)
    return context.oracle_file_cache


@given('a project with file "{path}" containing "{content}"')
def step_project_with_file(context, path, content):
    context.project_root = context.tmp_dir / "project"
    context.project_root.mkdir(exist_ok=True)
    file_path = context.project_root / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)


@given("a project exists")
def step_project_exists(context):
    context.project_root = context.tmp_dir / "project"
    context.project_root.mkdir(exist_ok=True)


@given('the agent has already read "{path}"')
def step_agent_has_read(context, path):
    cache = _get_or_create_cache(context)
    file_path = str(context.project_root / path)
    cache.smart_read(file_path)


@given('"{path}" is modified to contain "{content}"')
def step_file_modified(context, path, content):
    file_path = context.project_root / path
    file_path.write_text(content)


@when('the agent calls oracle_read on "{path}"')
def step_oracle_read(context, path):
    cache = _get_or_create_cache(context)
    file_path = str(context.project_root / path)
    context.last_response = handle_oracle_read(file_path, cache)


@when('the agent calls oracle_forget on "{path}"')
def step_oracle_forget(context, path):
    cache = _get_or_create_cache(context)
    file_path = str(context.project_root / path)
    handle_oracle_forget(file_path, cache)


@then('the response contains "{text}"')
def step_response_contains(context, text):
    assert context.last_response is not None, "No response recorded"
    assert text in context.last_response, f"Expected '{text}' in: {context.last_response}"


@then('the response contains "{text}" ignoring case')
def step_response_contains_ignoring_case(context, text):
    assert context.last_response is not None, "No response recorded"
    assert text.lower() in context.last_response.lower(), (
        f"Expected '{text}' (case-insensitive) in: {context.last_response}"
    )
