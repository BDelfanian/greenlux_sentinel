"""Postgres MCP server.

Tools exposed (docs/ARCHITECTURE.md#mcp-servers):
    run_readonly_query(sql)   -> executed inside a native Postgres read-only transaction
    explain_query(sql)        -> EXPLAIN ANALYZE, used by the query-optimizer agent
    propose_index(ddl)        -> queues a DDL proposal for human approval; never auto-applies
    write_audit_log(entry)    -> append-only insert into the audit_log table

No tool here executes arbitrary write/DDL directly -- propose_index only queues; the actual
apply step lives behind query_optimizer_agent.apply_approved(), gated on human approval
(docs/RESPONSIBLE_AI.md#human-in-the-loop-gates). apply_approved() deliberately does NOT run
through an MCP tool here -- exposing "run this DDL" as an LLM-callable tool would defeat the
point of the human gate, so that one statement stays a direct psycopg call made only from
inside the already-gated function.

Two layers per tool, same shape for every function below:
  - The plain function (e.g. run_readonly_query) is what agents import and call in-process,
    with an optional injected `conn` -- this is what lets a shared transaction span multiple
    calls (e.g. sql_agent.ask() reads, then audit-logs, then commits once) and what keeps the
    existing agent unit tests working against a MagicMock connection.
  - The `@mcp.tool()`-decorated wrapper is the standalone-server entrypoint used when this
    module runs via serve() -- it owns a fresh connection per call, since MCP tool arguments
    must be plain JSON-serializable values, never a live psycopg.Connection.

Semantic validation (single SELECT, forbidden keywords, schema-scoping) intentionally stays in
agents/sql_agent.py:validate() and agents/query_optimizer_agent.py -- not duplicated here. The
in-process functions trust their caller to have already validated; the MCP-tool wrappers below
re-run that same validation before executing, since ARCHITECTURE.md requires no server here
expose raw query execution without validation of its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    import psycopg

mcp = FastMCP("postgres_server")


def _connect() -> psycopg.Connection:
    import psycopg

    from greenlux_sentinel.config import get_settings

    return psycopg.connect(get_settings().postgres_dsn)


def run_readonly_query(
    sql: str, params: tuple[Any, ...] | None = None, conn: psycopg.Connection | None = None
) -> list[dict[str, Any]]:
    """Execute sql inside a native Postgres read-only transaction, return rows as dicts.

    Enforcement here is mechanical only (Postgres itself rejects any write while
    conn.read_only is set) -- callers validate the SQL themselves first.
    """
    owns_conn = conn is None
    conn = conn or _connect()
    try:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [desc.name for desc in cur.description] if cur.description else []
            rows = [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
        conn.rollback()  # close out the read-only transaction cleanly
        conn.read_only = False
        return rows
    finally:
        if owns_conn:
            conn.close()


def explain_query(sql: str, conn: psycopg.Connection | None = None) -> str:
    """Run EXPLAIN ANALYZE against sql and return the plan text. Caller validates sql is a
    plain SELECT first -- see query_optimizer_agent.explain_query()."""
    owns_conn = conn is None
    conn = conn or _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"EXPLAIN ANALYZE {sql}")
            plan_lines = [row[0] for row in cur.fetchall()]
        conn.rollback()
        return "\n".join(plan_lines)
    finally:
        if owns_conn:
            conn.close()


def propose_index(
    ddl: str, source_sql: str, conn: psycopg.Connection | None = None
) -> str:
    """Queue ddl as a `pending` audit_log row for human review and return the proposal id.
    Never executes ddl -- only query_optimizer_agent.apply_approved() may later do that, and
    only after re-checking the row is still `pending`."""
    owns_conn = conn is None
    conn = conn or _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log "
                "(agent_name, tool_name, input_summary, output_summary, required_approval, approval_status) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                ("query_optimizer_agent", "propose_index", source_sql, ddl, True, "pending"),
            )
            proposal_id = cur.fetchone()[0]
        conn.commit()
        return str(proposal_id)
    finally:
        if owns_conn:
            conn.close()


def write_audit_log(
    *,
    agent_name: str,
    tool_name: str,
    input_summary: str | None = None,
    output_summary: str | None = None,
    langsmith_trace_id: str | None = None,
    required_approval: bool = False,
    conn: psycopg.Connection | None = None,
) -> None:
    """Append-only insert into audit_log. Only commits/closes when it opened the connection
    itself -- an injected conn stays under the caller's transaction control, matching
    db.audit.write_audit_log's existing contract."""
    from greenlux_sentinel.db.audit import write_audit_log as _insert_audit_row

    owns_conn = conn is None
    conn = conn or _connect()
    try:
        _insert_audit_row(
            conn,
            agent_name=agent_name,
            tool_name=tool_name,
            input_summary=input_summary,
            output_summary=output_summary,
            langsmith_trace_id=langsmith_trace_id,
            required_approval=required_approval,
        )
        if owns_conn:
            conn.commit()
    finally:
        if owns_conn:
            conn.close()


@mcp.tool(name="run_readonly_query")
def _run_readonly_query_tool(sql: str) -> list[dict[str, Any]]:
    """Execute a single read-only SELECT statement against the fund schema and return the
    matching rows. Rejected if it isn't a plain SELECT with no forbidden keywords."""
    from greenlux_sentinel.agents.sql_agent import validate

    validate(sql)
    return run_readonly_query(sql)


@mcp.tool(name="explain_query")
def _explain_query_tool(sql: str) -> str:
    """Run EXPLAIN ANALYZE on a read-only SELECT and return the query plan text."""
    from greenlux_sentinel.agents.sql_agent import validate

    validate(sql)
    return explain_query(sql)


@mcp.tool(name="propose_index")
def _propose_index_tool(ddl: str, source_sql: str) -> str:
    """Queue a CREATE INDEX proposal for human review. Returns the proposal id. Never applies
    the DDL -- a separate, human-gated approval step is required for that."""
    return propose_index(ddl, source_sql)


@mcp.tool(name="write_audit_log")
def _write_audit_log_tool(
    agent_name: str,
    tool_name: str,
    input_summary: str | None = None,
    output_summary: str | None = None,
    required_approval: bool = False,
) -> None:
    """Append one row to the audit log."""
    write_audit_log(
        agent_name=agent_name,
        tool_name=tool_name,
        input_summary=input_summary,
        output_summary=output_summary,
        required_approval=required_approval,
    )


def serve() -> None:
    """Start the MCP server process (stdio transport)."""
    mcp.run()
