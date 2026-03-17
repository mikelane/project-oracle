"""Shared formatting utilities for Project Oracle."""

from __future__ import annotations


def format_elapsed(seconds: int) -> str:
    """Format elapsed seconds as a human-readable string (e.g. '5s', '2m', '1h')."""
    if seconds >= 3600:
        return f"{seconds // 3600}h"
    if seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"
