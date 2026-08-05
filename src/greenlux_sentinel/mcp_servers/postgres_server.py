"""Postgres MCP server.

Tools exposed (docs/ARCHITECTURE.md#mcp-servers):
    run_readonly_query(sql)   -> rejects anything that isn't a SELECT
    explain_query(sql)        -> EXPLAIN ANALYZE, used by the query-optimizer agent
    propose_index(ddl)        -> queues a DDL proposal for human approval; never auto-applies
    write_audit_log(entry)    -> append-only insert into the audit_log table

No tool here executes arbitrary write/DDL directly — propose_index only queues; the actual
apply step lives behind query_optimizer_agent.apply_approved(), gated on human approval
(docs/RESPONSIBLE_AI.md#human-in-the-loop-gates).

TODO(Phase 3):
    - Implement using the official `mcp` Python SDK server scaffolding
    - Connection pooling via psycopg
"""

from __future__ import annotations


def serve() -> None:
    """Start the MCP server process. Not yet implemented."""
    raise NotImplementedError("Phase 3 — see docs/ROADMAP.md")
