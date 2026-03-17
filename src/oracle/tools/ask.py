"""Tool handler for oracle_ask — intent-based routing to cache, chunkhound, or haiku."""

from __future__ import annotations

import subprocess
from pathlib import Path

import anthropic

from oracle.intent import Intent, classify_intent
from oracle.project import ProjectState


async def handle_oracle_ask(question: str, project: ProjectState) -> str:
    """Route a natural-language question to the appropriate handler via intent classification."""
    intent = classify_intent(question)

    match intent:
        case Intent.GIT_STATUS:
            return _git_status(project)
        case Intent.READINESS:
            return _readiness_check(project)
        case Intent.TEST_STATUS:
            return _test_status(project)
        case Intent.PROJECT_STRUCTURE:
            return _project_overview(project)
        case Intent.CODE_UNDERSTANDING:
            return await _code_understanding(question, project)
        case Intent.UNKNOWN:
            return await _haiku_fallback(question, project)

    return "Unable to process question"  # pragma: no cover


def _git_status(project: ProjectState) -> str:
    """Return git delta from cache."""
    if project.git_cache is None:
        return "No git cache available"
    return project.git_cache.get_delta()


def _readiness_check(project: ProjectState) -> str:
    """Check if the project is ready to push/merge."""
    lines: list[str] = []

    if project.git_cache is not None:
        snapshot = project.git_cache.refresh()
        if snapshot.dirty_files:
            lines.append(
                f"Not ready: {len(snapshot.dirty_files)} dirty file(s): "
                + ", ".join(snapshot.dirty_files)
            )
        else:
            lines.append("Working tree is clean")

        if snapshot.staged_files:
            lines.append(f"Staged files: {', '.join(snapshot.staged_files)}")
    else:
        lines.append("No git cache available")

    if project.command_cache is not None and project.stack.test_cmd:
        if project.command_cache.is_allowed(project.stack.test_cmd):
            lines.append(f"Test command available: {project.stack.test_cmd}")
    elif project.stack.test_cmd:
        lines.append(f"Test command: {project.stack.test_cmd}")

    return "\n".join(lines)


def _test_status(project: ProjectState) -> str:
    """Report test status from command cache or stack info."""
    if project.stack.test_cmd:
        if project.command_cache is not None:
            cached = project.command_cache.get_cached_result(project.stack.test_cmd)
            if cached is not None:
                return f"Last {project.stack.test_cmd} result:\n{cached['output']}"
        return (
            f"Test command configured: {project.stack.test_cmd}\n"
            "No cached test results yet. Run oracle_run to execute."
        )
    return "No test command configured for this project"


def _project_overview(project: ProjectState) -> str:
    """Return a summary of the project stack and structure."""
    lines: list[str] = []
    lines.append(f"Language: {project.stack.lang}")
    if project.stack.pkg_mgr:
        lines.append(f"Package manager: {project.stack.pkg_mgr}")
    if project.stack.test_cmd:
        lines.append(f"Test command: {project.stack.test_cmd}")
    if project.stack.lint_cmd:
        lines.append(f"Lint command: {project.stack.lint_cmd}")
    if project.stack.type_cmd:
        lines.append(f"Type check command: {project.stack.type_cmd}")
    lines.append(f"Root: {project.root}")
    return "\n".join(lines)


async def _code_understanding(question: str, project: ProjectState) -> str:
    """Try chunkhound first, fall back to grep."""
    if project.chunkhound is not None:
        results = await project.chunkhound.search(question)
        if results:
            return _format_chunkhound_results(results)
    return _fallback_grep(question, project.root)


def _format_chunkhound_results(results: list[dict[str, str]]) -> str:
    """Format chunkhound search results for display."""
    lines: list[str] = []
    for result in results:
        file_path = result.get("file", "unknown")
        snippet = result.get("snippet", "")
        lines.append(f"## {file_path}\n{snippet}")
    return "\n\n".join(lines)


def _fallback_grep(question: str, root: Path) -> str:
    """Extract keywords from question and grep for them in source files."""
    # Extract meaningful words (skip common question words)
    stop_words = {
        "what", "where", "how", "is", "the", "a", "an", "in", "of", "to",
        "and", "or", "for", "with", "this", "that", "are", "does", "do",
        "can", "find", "show", "me", "my", "it", "which", "why", "when",
    }
    words = [w.strip("?.,!") for w in question.lower().split()]
    keywords = [w for w in words if w and w not in stop_words]

    if not keywords:
        return f"No matches for question: {question}"

    # Try each keyword
    all_results: list[str] = []
    source_globs = ("*.py", "*.ts", "*.js", "*.go", "*.rs")

    for keyword in keywords[:3]:  # Limit to first 3 keywords
        include_args: list[str] = []
        for glob in source_globs:
            include_args.extend(["--include", glob])

        try:
            result = subprocess.run(
                ["grep", "-rn", *include_args, keyword, str(root)],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue

        if result.returncode == 0 and result.stdout.strip():
            matches = result.stdout.strip().splitlines()[:10]
            all_results.extend(matches)

    if not all_results:
        return f"No matches for question: {question}"

    # Deduplicate
    seen: set[str] = set()
    unique: list[str] = []
    for line in all_results:
        if line not in seen:
            seen.add(line)
            unique.append(line)

    return f"{len(unique)} match(es):\n" + "\n".join(unique[:20])


async def _haiku_fallback(question: str, project: ProjectState) -> str:
    """Use Claude Haiku as a last resort for questions we can't route."""
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"You are a code assistant for a {project.stack.lang} project. "
                        f"Answer concisely:\n\n{question}"
                    ),
                }
            ],
        )
        if message.content:
            block = message.content[0]
            if hasattr(block, "text"):
                return block.text
        return "Unable to get response from Haiku"
    except Exception:
        return "Unable to answer: Anthropic API not configured or unavailable"
