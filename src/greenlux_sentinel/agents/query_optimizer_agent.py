"""Query-Optimizer Agent — reads EXPLAIN ANALYZE output, proposes indexes/schema changes.

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Runs EXPLAIN ANALYZE on slow queries (flagged by the NL2SQL agent or a threshold),
    proposes a DDL change (e.g. CREATE INDEX), and estimates the before/after cost —
    but does NOT apply it directly.

HUMAN-IN-THE-LOOP GATE (docs/RESPONSIBLE_AI.md#human-in-the-loop-gates):
    The proposed DDL is queued for human review (as a `pending` row in `audit_log`, reusing its
    `required_approval`/`approval_status` columns rather than a new table). Only apply_approved()
    — called after an external approval — runs the DDL against the real database. Phase 2 has no
    UI for that review step, so the "human" side is a direct function call (reject_proposal() /
    apply_approved()) rather than a real reviewer; the gate itself (queue -> explicit decision ->
    apply) is real and not bypassable — apply_approved() re-checks the row is still `pending`
    before doing anything. Do not remove this gate — schema changes are the one genuinely
    destructive-adjacent action this agent can take.

Both the proposal and the approval/rejection decision are audit-logged as separate rows, per
RESPONSIBLE_AI.md's "outcomes are themselves audit-logged."

Phase 3: explain_query()'s EXPLAIN ANALYZE and propose_index()'s pending-row insert now run
through `mcp_servers.postgres_server` (per ARCHITECTURE.md's postgres_server tool surface).
_existing_indexed_columns()'s pg_indexes introspection, _fetch_pending_proposal(), and
apply_approved()'s DDL execution stay direct psycopg calls -- they're this agent's own internal
bookkeeping (catalog introspection, the human-gate's state machine, the one deliberately
non-tool-surfaced DDL apply step), not part of the documented MCP tool surface.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from greenlux_sentinel.agents.sql_agent import validate as validate_select
from greenlux_sentinel.mcp_servers import postgres_server

if TYPE_CHECKING:
    import psycopg

# Naive but effective for this schema: WHERE/JOIN equality/IN predicates on a bare column name.
# Good enough to flag "no index backs this filter" — not a full SQL parser.
_PREDICATE_COLUMN = re.compile(r"\b(\w+)\s*(?:=|IN\s*\()", re.IGNORECASE)
_FROM_TABLE = re.compile(r"\bFROM\s+(\w+)", re.IGNORECASE)


def explain_query(sql: str, conn: psycopg.Connection) -> str:
    """Run EXPLAIN ANALYZE on a read-only query and return the plan text."""
    validate_select(sql)
    return postgres_server.explain_query(sql, conn=conn)


def _existing_indexed_columns(table: str, conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename = %s", (table,))
        indexdefs = [row[0] for row in cur.fetchall()]
    conn.rollback()
    columns = set()
    for indexdef in indexdefs:
        match = re.search(r"\(([^)]+)\)", indexdef)
        if match:
            columns.update(c.strip() for c in match.group(1).split(","))
    return columns


def _candidate_index(slow_query_sql: str, conn: psycopg.Connection) -> tuple[str, str] | None:
    """Return (table, column) for the first predicate column with no covering index, or None."""
    table_match = _FROM_TABLE.search(slow_query_sql)
    if not table_match:
        return None
    table = table_match.group(1)
    indexed = _existing_indexed_columns(table, conn)

    for match in _PREDICATE_COLUMN.finditer(slow_query_sql):
        column = match.group(1)
        if column.lower() == table.lower():
            continue  # matched the table name itself, not a column
        if column not in indexed:
            return table, column
    return None


def propose_index(slow_query_sql: str, conn: psycopg.Connection | None = None) -> dict[str, Any]:
    """Analyze slow_query_sql and queue a CREATE INDEX proposal for human review.

    Returns {"proposal_id", "ddl", "estimated_improvement"}. Raises ValueError if no un-indexed
    predicate column is found (nothing to propose).
    """
    validate_select(slow_query_sql)

    owns_conn = conn is None
    if owns_conn:
        import psycopg

        from greenlux_sentinel.config import get_settings

        conn = psycopg.connect(get_settings().postgres_dsn)

    try:
        plan = explain_query(slow_query_sql, conn)
        candidate = _candidate_index(slow_query_sql, conn)
        if candidate is None:
            raise ValueError("no un-indexed predicate column found; nothing to propose")
        table, column = candidate

        ddl = f"CREATE INDEX IF NOT EXISTS idx_{table}_{column} ON {table} ({column})"
        seq_scan_rows = re.search(r"Seq Scan.*?rows=(\d+)", plan)
        estimated_improvement = (
            f"Sequential scan over {seq_scan_rows.group(1)} rows detected on `{table}`; "
            f"an index on `{column}` should let this query use an index scan instead."
            if seq_scan_rows
            else f"No sequential scan detected in the current plan, but `{column}` is filtered "
            f"on with no covering index — proposing one defensively."
        )

        proposal_id = postgres_server.propose_index(ddl, slow_query_sql, conn=conn)
    finally:
        if owns_conn:
            conn.close()

    return {"proposal_id": proposal_id, "ddl": ddl, "estimated_improvement": estimated_improvement}


def _fetch_pending_proposal(proposal_id: str, conn: psycopg.Connection) -> tuple[str, str] | None:
    """Return (ddl, approval_status) for the given proposal, or None if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT output_summary, approval_status FROM audit_log "
            "WHERE id = %s AND tool_name = 'propose_index'",
            (int(proposal_id),),
        )
        row = cur.fetchone()
    conn.rollback()
    return row


def reject_proposal(proposal_id: str, rejected_by: str, conn: psycopg.Connection | None = None) -> None:
    """Record a human rejection of a pending proposal. Does not execute anything."""
    owns_conn = conn is None
    if owns_conn:
        import psycopg

        from greenlux_sentinel.config import get_settings

        conn = psycopg.connect(get_settings().postgres_dsn)

    try:
        row = _fetch_pending_proposal(proposal_id, conn)
        if row is None:
            raise ValueError(f"no such proposal: {proposal_id}")
        _, approval_status = row
        if approval_status != "pending":
            raise ValueError(f"proposal {proposal_id} is not pending (status={approval_status})")

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE audit_log SET approval_status = 'rejected', approved_by = %s, approved_at = now() "
                "WHERE id = %s",
                (rejected_by, int(proposal_id)),
            )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


def apply_approved(proposal_id: str, approved_by: str, conn: psycopg.Connection | None = None) -> None:
    """Record human approval of a pending proposal and apply its DDL. This is the only path that
    ever executes a schema change — re-checks the proposal is still `pending` first, so a
    proposal can't be applied twice or after being rejected."""
    owns_conn = conn is None
    if owns_conn:
        import psycopg

        from greenlux_sentinel.config import get_settings

        conn = psycopg.connect(get_settings().postgres_dsn)

    try:
        row = _fetch_pending_proposal(proposal_id, conn)
        if row is None:
            raise ValueError(f"no such proposal: {proposal_id}")
        ddl, approval_status = row
        if approval_status != "pending":
            raise ValueError(f"proposal {proposal_id} is not pending (status={approval_status})")

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE audit_log SET approval_status = 'approved', approved_by = %s, approved_at = now() "
                "WHERE id = %s",
                (approved_by, int(proposal_id)),
            )
            cur.execute(ddl)  # deliberately direct -- see module docstring on why apply_approved()
            # is the one place DDL execution stays off the MCP tool surface
        postgres_server.write_audit_log(
            conn=conn,
            agent_name="query_optimizer_agent",
            tool_name="apply_approved",
            input_summary=f"proposal_id={proposal_id}",
            output_summary=f"executed: {ddl}",
            required_approval=False,  # this row logs the mechanical execution of an already-approved decision
        )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()
