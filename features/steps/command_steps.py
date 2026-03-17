"""Step definitions for command result caching scenarios."""

from behave import given, when

from oracle.cache.command_cache import CommandCache, CommandNotAllowedError
from oracle.storage.store import OracleStore


def _get_or_create_command_cache(context):
    if not hasattr(context, "oracle_store"):
        db_path = context.tmp_dir / "state.db"
        context.oracle_store = OracleStore(db_path)
    if not hasattr(context, "oracle_command_cache"):
        context.oracle_command_cache = CommandCache(
            context.oracle_store, context.project_root, extra_allowed=["echo"]
        )
    return context.oracle_command_cache


@when('the agent calls oracle_run with "{command}"')
def step_oracle_run(context, command):
    cache = _get_or_create_command_cache(context)
    try:
        output = cache.run_summarized(command)
    except CommandNotAllowedError:
        output = f"Error: command not allowed: {command}"
    context.last_response = f"$ {command}\n{output}"


@given('the agent has run "{command}" before')
def step_agent_has_run_command(context, command):
    cache = _get_or_create_command_cache(context)
    try:
        cache.run_summarized(command)
    except CommandNotAllowedError:
        pass


@given("no source files have changed")
def step_no_source_files_changed(context):
    # No-op: since no source files were modified between the first run and
    # the next call, the source hash remains identical and the cache hit occurs.
    pass
