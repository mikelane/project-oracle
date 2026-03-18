"""Keyword-based intent classifier for oracle_ask routing.

Routes natural-language questions to the correct handler without an LLM.
"""

from __future__ import annotations

from enum import Enum, auto


class Intent(Enum):
    GIT_STATUS = auto()
    READINESS = auto()
    TEST_STATUS = auto()
    PROJECT_STRUCTURE = auto()
    CODE_UNDERSTANDING = auto()
    UNKNOWN = auto()


_PATTERNS: list[tuple[Intent, tuple[str, ...]]] = [
    (Intent.GIT_STATUS, ("changed", "modified", "dirty", "status", "uncommitted")),
    (Intent.READINESS, ("ready", "push", "merge", "ci", "ship")),
    (Intent.TEST_STATUS, ("test", "passing", "failing", "coverage", "pytest", "spec")),
    (Intent.PROJECT_STRUCTURE, ("structure", "stack", "overview", "what is this", "tech")),
    (
        Intent.CODE_UNDERSTANDING,
        (
            "import",
            "find",
            "where",
            "how",
            "explain",
            "what",
            "function",
            "class",
            "method",
            "module",
            "handler",
            "auth",
            "database",
            "connection",
            "config",
            "logic",
        ),
    ),
]


def classify_intent(question: str) -> Intent:
    """Classify a natural-language question into an intent.  No LLM needed."""
    q = question.lower()
    for intent, keywords in _PATTERNS:
        if any(kw in q for kw in keywords):
            return intent
    return Intent.UNKNOWN
