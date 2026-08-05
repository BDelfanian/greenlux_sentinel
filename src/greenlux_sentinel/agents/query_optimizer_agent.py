"""Query-Optimizer Agent — reads EXPLAIN ANALYZE output, proposes indexes/schema changes.

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Runs EXPLAIN ANALYZE on slow queries (flagged by the NL2SQL agent or a threshold),
    proposes a DDL change (e.g. CREATE INDEX), and estimates the before/after cost —
    but does NOT apply it directly.

HUMAN-IN-THE-LOOP GATE (docs/RESPONSIBLE_AI.md#human-in-the-loop-gates):
    The proposed DDL is queued for human review. Only an explicit approval applies it
    against the real database. Do not remove this gate — schema changes are the one
    genuinely destructive-adjacent action this agent can take.

TODO(Phase 2):
    - Implement propose_index() calling Postgres MCP's explain_query + propose_index tools
    - Implement apply_approved() that only runs after an external approval record exists
    - Audit-log both the proposal and the approval/rejection decision
"""

from __future__ import annotations


def propose_index(slow_query_sql: str) -> dict:
    """Return {"ddl": str, "estimated_improvement": str}, queued for approval. Not yet implemented."""
    raise NotImplementedError("Phase 2 — see docs/ROADMAP.md")


def apply_approved(proposal_id: str, approved_by: str) -> None:
    """Apply a previously human-approved DDL proposal. Not yet implemented."""
    raise NotImplementedError("Phase 2 — see docs/ROADMAP.md")
