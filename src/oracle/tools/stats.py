"""Tool handler for oracle_stats — token savings stats."""

from __future__ import annotations

from oracle.storage.store import OracleStore


def handle_oracle_stats(session_id: str, store: OracleStore) -> str:
    """Return formatted token savings stats for the current session and all sessions."""
    session_stats = store.get_session_stats(session_id)
    session_calls = store.get_session_call_count(session_id)
    cumulative_stats = store.get_cumulative_stats()
    cumulative_calls = store.get_cumulative_call_count()

    return (
        f"Session ({session_id}):\n"
        f"  Tool calls: {session_calls}\n"
        f"  Cache hits: {session_stats['total_cache_hits']}\n"
        f"  Tokens saved: {session_stats['total_tokens_saved']:,}\n"
        f"\n"
        f"All sessions:\n"
        f"  Tool calls: {cumulative_calls}\n"
        f"  Cache hits: {cumulative_stats['total_cache_hits']}\n"
        f"  Tokens saved: {cumulative_stats['total_tokens_saved']:,}"
    )
