"""Tool handler for oracle_stats — adoption visibility and token savings stats."""

from __future__ import annotations

from oracle.storage.store import OracleStore


def _format_hit_rate_section(session_id: str, store: OracleStore) -> str:
    session_stats = store.get_session_stats(session_id)
    oracle_calls = _count_oracle_calls(session_id, store)
    hits = session_stats["total_cache_hits"]
    tokens_saved = session_stats["total_tokens_saved"]

    hit_pct = round(hits / oracle_calls * 100) if oracle_calls > 0 else 0

    return (
        f"Cache Performance:\n"
        f"  Hit rate: {hit_pct}% ({hits}/{oracle_calls} oracle calls)\n"
        f"  Tokens saved: {tokens_saved:,} this session"
    )


def _count_oracle_calls(session_id: str, store: OracleStore) -> int:
    breakdown = store.get_tool_breakdown(session_id=session_id)
    return sum(row["count"] for row in breakdown if row["tool_name"].startswith("oracle_"))


def _format_adoption_section(session_id: str, store: OracleStore) -> str:
    rates = store.get_adoption_rates(session_id=session_id)
    if not rates:
        return ""

    lines = ["Adoption (oracle vs built-in):"]
    for category in ["read", "grep", "run"]:
        if category not in rates:
            continue
        data = rates[category]
        oracle_count = data["oracle"]
        builtin_count = data["builtin"]
        total = oracle_count + builtin_count
        pct = round(oracle_count / total * 100) if total > 0 else 0
        suffix = "  <-- never used" if oracle_count == 0 and builtin_count > 0 else ""
        line = (
            f"  {category}:  {pct}% oracle"
            f" ({oracle_count} oracle / {builtin_count} built-in)"
            f"{suffix}"
        )
        lines.append(line)

    return "\n".join(lines)


def _format_trend_section(session_id: str, store: OracleStore) -> str:
    comparison = store.get_session_comparison(session_id)
    if comparison["trend"] == "stable" and comparison["avg_hit_rate"] == 0.0:
        return ""

    current_hit = round(comparison["current_hit_rate"] * 100)
    avg_hit = round(comparison["avg_hit_rate"] * 100)
    hit_diff = current_hit - avg_hit
    hit_sign = "+" if hit_diff >= 0 else ""

    current_adopt = round(comparison["current_adoption_rate"] * 100)
    avg_adopt = round(comparison["avg_adoption_rate"] * 100)
    adopt_diff = current_adopt - avg_adopt
    adopt_sign = "+" if adopt_diff >= 0 else ""

    return (
        f"Trend vs recent sessions:\n"
        f"  Hit rate:  {current_hit}% now vs {avg_hit}% avg ({hit_sign}{hit_diff}%)\n"
        f"  Adoption:  {current_adopt}% now vs {avg_adopt}% avg ({adopt_sign}{adopt_diff}%)"
    )


def _format_cumulative_section(store: OracleStore) -> str:
    cumulative_stats = store.get_cumulative_stats()
    breakdown = store.get_tool_breakdown()

    oracle_calls = sum(row["count"] for row in breakdown if row["tool_name"].startswith("oracle_"))
    builtin_calls = sum(
        row["count"] for row in breakdown if row["tool_name"].startswith("builtin_")
    )

    total = oracle_calls + builtin_calls
    adoption_pct = round(oracle_calls / total * 100) if total > 0 else 0
    total_hits = cumulative_stats["total_cache_hits"]
    hit_rate_pct = round(total_hits / oracle_calls * 100) if oracle_calls > 0 else 0
    total_tokens = cumulative_stats["total_tokens_saved"]

    return (
        f"=== Cumulative ===\n"
        f"Oracle calls: {oracle_calls} | Built-in calls: {builtin_calls}\n"
        f"Overall adoption: {adoption_pct}% | Cache hit rate: {hit_rate_pct}%\n"
        f"Tokens saved: {total_tokens:,}"
    )


def handle_oracle_stats(session_id: str, store: OracleStore) -> str:
    """Return formatted adoption visibility and token savings stats."""
    sections = [f"=== Oracle Health (session {session_id}) ==="]

    sections.append(_format_hit_rate_section(session_id, store))

    adoption = _format_adoption_section(session_id, store)
    if adoption:
        sections.append(adoption)

    trend = _format_trend_section(session_id, store)
    if trend:
        sections.append(trend)

    sections.append(_format_cumulative_section(store))

    return "\n\n".join(sections)
