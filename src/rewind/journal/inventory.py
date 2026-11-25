"""Canonical phase 1 schema inventory.

``transactions`` and ``proxy_sessions`` are proposed names. The written
baseline requires nine tables but names seven of them. The four index names
are also proposed. See docs/schema.md.
"""

from __future__ import annotations

EXPECTED_TABLES = frozenset(
    {
        "schema_meta",
        "proxy_leases",
        "transactions",
        "proxy_sessions",
        "tool_calls",
        "journal_events",
        "compensation_calls",
        "compensation_adjustments",
        "operator_resolutions",
    }
)

EXPECTED_TRIGGERS = frozenset(
    {
        "validate_comp_adjustment_insert",
        "prevent_compensation_snapshot_update",
        "prevent_journal_events_update",
        "prevent_journal_events_delete",
        "prevent_comp_adjustments_update",
        "prevent_comp_adjustments_delete",
        "prevent_operator_resolutions_update",
        "prevent_operator_resolutions_delete",
    }
)

EXPECTED_INDEXES = frozenset(
    {
        "idx_journal_events_call",
        "idx_compensation_adjustments_parent",
        "idx_operator_resolutions_call",
        "idx_tool_calls_business_key",
    }
)

PROPOSED_TABLES = frozenset({"transactions", "proxy_sessions"})
PROPOSED_INDEXES = EXPECTED_INDEXES

TERMINAL_COMPENSATION_STATES = frozenset({"COMPENSATION_FAILED", "COMPENSATION_COMPLETE"})
NONTERMINAL_COMPENSATION_STATES = frozenset({"COMPENSATION_PLANNED", "COMPENSATION_PARTIAL", "COMPENSATION_IN_DOUBT"})


def is_terminal_compensation(state: str) -> bool:
    """COMPENSATION_IN_DOUBT is unresolved and is not a terminal state."""

    return state in TERMINAL_COMPENSATION_STATES
