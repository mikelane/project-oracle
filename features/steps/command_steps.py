"""Step definitions for command result caching scenarios."""

from behave import given, when

from oracle.cache.command_cache import CommandCache
from oracle.storage.store import OracleStore
from oracle.tools.run import handle_oracle_run


def _get_or_create_command_cache(context):
    if not hasattr(context, "oracle_store"):
        db_path = context.tmp_dir / "state.db"
        context.oracle_store = OracleStore(db_path)
    if not hasattr(context, "oracle_command_cache"):
        context.oracle_command_cache = CommandCache(context.oracle_store, context.project_root)
    return context.oracle_command_cache


@when('the agent calls oracle_run with "{command}"')
def step_oracle_run(context, command):
    cache = _get_or_create_command_cache(context)
    context.last_response = handle_oracle_run([command], cache)


@given('the agent has run "{command}" before')
def step_agent_has_run_command(context, command):
    cache = _get_or_create_command_cache(context)
    handle_oracle_run([command], cache)


@given("no source files have changed")
def step_no_source_files_changed(context):
    # No-op: since no source files were modified between the first run and
    # the next call, the source hash remains identical and the cache hit occurs.
    pass
