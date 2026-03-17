"""Tests for intent classifier — keyword-based routing for oracle_ask."""

from __future__ import annotations

import pytest

from oracle.intent import Intent, classify_intent


class DescribeClassifyIntent:
    @pytest.mark.parametrize(
        "question,expected",
        [
            ("what changed?", Intent.GIT_STATUS),
            ("any modified files?", Intent.GIT_STATUS),
            ("git status", Intent.GIT_STATUS),
            ("show me uncommitted changes", Intent.GIT_STATUS),
            ("is the repo dirty?", Intent.GIT_STATUS),
        ],
    )
    def it_classifies_git_status_questions(self, question: str, expected: Intent) -> None:
        assert classify_intent(question) == expected

    @pytest.mark.parametrize(
        "question,expected",
        [
            ("ready to push?", Intent.READINESS),
            ("can I merge this?", Intent.READINESS),
            ("is CI green?", Intent.READINESS),
            ("can we ship it?", Intent.READINESS),
        ],
    )
    def it_classifies_readiness_questions(self, question: str, expected: Intent) -> None:
        assert classify_intent(question) == expected

    @pytest.mark.parametrize(
        "question,expected",
        [
            ("are tests passing?", Intent.TEST_STATUS),
            ("what's failing?", Intent.TEST_STATUS),
            ("test coverage?", Intent.TEST_STATUS),
            ("run pytest", Intent.TEST_STATUS),
            ("any spec failures?", Intent.TEST_STATUS),
        ],
    )
    def it_classifies_test_status_questions(self, question: str, expected: Intent) -> None:
        assert classify_intent(question) == expected

    @pytest.mark.parametrize(
        "question,expected",
        [
            ("what's the project structure?", Intent.PROJECT_STRUCTURE),
            ("what stack is this?", Intent.PROJECT_STRUCTURE),
            ("give me an overview", Intent.PROJECT_STRUCTURE),
            ("what tech does this use?", Intent.PROJECT_STRUCTURE),
            ("what is this project?", Intent.PROJECT_STRUCTURE),
        ],
    )
    def it_classifies_structure_questions(self, question: str, expected: Intent) -> None:
        assert classify_intent(question) == expected

    @pytest.mark.parametrize(
        "question",
        [
            "what imports the User model?",
            "find the auth handler",
            "where is the database connection?",
            "explain the retry logic",
        ],
    )
    def it_defaults_to_code_understanding(self, question: str) -> None:
        assert classify_intent(question) == Intent.CODE_UNDERSTANDING

    @pytest.mark.parametrize(
        "question",
        [
            "hello",
            "greetings",
            "42",
        ],
    )
    def it_returns_unknown_for_unrecognized_questions(self, question: str) -> None:
        assert classify_intent(question) == Intent.UNKNOWN

    def it_is_case_insensitive(self) -> None:
        assert classify_intent("WHAT CHANGED?") == Intent.GIT_STATUS
        assert classify_intent("Ready To Push?") == Intent.READINESS
        assert classify_intent("TEST COVERAGE?") == Intent.TEST_STATUS
        assert classify_intent("PROJECT STRUCTURE?") == Intent.PROJECT_STRUCTURE
