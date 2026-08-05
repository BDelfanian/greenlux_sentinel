"""Audit log writer — see db/audit_log_schema.sql and docs/RESPONSIBLE_AI.md.

Every agent/pipeline tool call writes one append-only row here. Phase 1 ETL scripts call
this directly with a psycopg connection; from Phase 3 onward, `postgres_server`'s
`write_audit_log` MCP tool becomes the only caller so all write paths go through MCP.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg


def write_audit_log(
    conn: psycopg.Connection,
    *,
    agent_name: str,
    tool_name: str,
    input_summary: str | None = None,
    output_summary: str | None = None,
    langsmith_trace_id: str | None = None,
    required_approval: bool = False,
) -> None:
    """Insert one row into audit_log. Does not commit — caller controls the transaction."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log
                (agent_name, tool_name, input_summary, output_summary,
                 langsmith_trace_id, required_approval)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (agent_name, tool_name, input_summary, output_summary, langsmith_trace_id, required_approval),
        )
