"""Step definitions for git state caching scenarios."""

import subprocess

from behave import given, when

from oracle.cache.git_cache import GitCache
from oracle.storage.store import OracleStore


def _get_or_create_git_cache(context):
    if not hasattr(context, "oracle_store"):
        db_path = context.tmp_dir / "state.db"
        context.oracle_store = OracleStore(db_path)
    if not hasattr(context, "oracle_git_cache"):
        context.oracle_git_cache = GitCache(context.oracle_store, context.project_root)
    return context.oracle_git_cache


def _git(args, cwd):
    """Run a git command, suppressing output."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@given('a git project on branch "{branch}"')
def step_git_project_on_branch(context, branch):
    context.project_root = context.tmp_dir / "project"
    context.project_root.mkdir(exist_ok=True)
    _git(["init", "-b", branch], context.project_root)
    _git(["config", "user.email", "test@test.com"], context.project_root)
    _git(["config", "user.name", "Test"], context.project_root)
    # Create an initial commit so HEAD exists
    readme = context.project_root / "README.md"
    readme.write_text("init")
    _git(["add", "README.md"], context.project_root)
    _git(["commit", "-m", "init", "--no-gpg-sign"], context.project_root)
    context.oracle_has_git = True


@given('file "{path}" is modified in the working tree')
def step_file_modified_in_working_tree(context, path):
    file_path = context.project_root / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    # First track the file so git knows about it
    file_path.write_text("original")
    _git(["add", str(path)], context.project_root)
    _git(["commit", "-m", f"add {path}", "--no-gpg-sign"], context.project_root)
    # Now modify it so it appears as dirty (modified)
    file_path.write_text("modified content")


@when("the agent calls oracle_status")
def step_oracle_status(context):
    git_cache = _get_or_create_git_cache(context)
    snapshot = git_cache.refresh()
    lines = [f"Branch: {snapshot.branch}", f"HEAD: {snapshot.head_sha}"]
    if snapshot.dirty_files:
        lines.append("dirty: " + ", ".join(snapshot.dirty_files))
    else:
        lines.append("clean")
    context.last_response = "\n".join(lines)
