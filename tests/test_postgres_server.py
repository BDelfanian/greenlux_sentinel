"""Unit tests for mcp_servers/postgres_server.py: the conn-injectable functions agents call
in-process, via a MagicMock connection (no live Postgres needed) -- same pattern as
test_sql_agent.py / test_query_optimizer_agent.py, which exercise these through the agents."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from greenlux_sentinel.mcp_servers import postgres_server


def _mock_conn():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    return conn, cur


class TestRunReadonlyQuery:
    def test_returns_rows_as_dicts_and_restores_read_only_flag(self):
        conn, cur = _mock_conn()
        cur.description = [SimpleNamespace(name="fund_id"), SimpleNamespace(name="name")]
        cur.fetchall.return_value = [("F1", "Fund One")]

        rows = postgres_server.run_readonly_query("SELECT fund_id, name FROM funds", conn=conn)

        assert rows == [{"fund_id": "F1", "name": "Fund One"}]
        assert conn.read_only is False
        assert conn.rollback.called
        assert not conn.close.called  # caller-owned connection

    def test_no_description_returns_empty_rows(self):
        conn, cur = _mock_conn()
        cur.description = None
        cur.fetchall.return_value = []

        assert postgres_server.run_readonly_query("SELECT 1", conn=conn) == []

    def test_passes_params_through_to_execute(self):
        conn, cur = _mock_conn()
        cur.description = []
        cur.fetchall.return_value = []

        postgres_server.run_readonly_query("SELECT * FROM funds WHERE isin = %s", ("IE00X",), conn=conn)

        assert cur.execute.call_args.args == ("SELECT * FROM funds WHERE isin = %s", ("IE00X",))


class TestExplainQuery:
    def test_returns_joined_plan_lines_and_rolls_back(self):
        conn, cur = _mock_conn()
        cur.fetchall.return_value = [("Seq Scan on funds  (cost=0.00..1934.00 rows=67098)",), ("Planning Time: 0.1 ms",)]

        plan = postgres_server.explain_query("SELECT * FROM funds", conn=conn)

        assert "Seq Scan on funds" in plan
        assert "Planning Time" in plan
        assert cur.execute.call_args.args[0] == "EXPLAIN ANALYZE SELECT * FROM funds"
        assert conn.rollback.called


class TestProposeIndex:
    def test_inserts_pending_row_and_commits(self):
        conn, cur = _mock_conn()
        cur.fetchone.return_value = (42,)

        proposal_id = postgres_server.propose_index(
            "CREATE INDEX idx_funds_category ON funds (category)",
            "SELECT * FROM funds WHERE category = 'Equity'",
            conn=conn,
        )

        assert proposal_id == "42"
        insert_call = next(c for c in cur.execute.call_args_list if "INSERT INTO audit_log" in c.args[0])
        assert insert_call.args[1][-1] == "pending"
        assert conn.commit.called


class TestWriteAuditLog:
    def test_inserts_row_and_does_not_commit_an_injected_connection(self):
        conn, cur = _mock_conn()

        postgres_server.write_audit_log(
            agent_name="sql_agent", tool_name="ask", input_summary="q", output_summary="ok", conn=conn
        )

        insert_call = next(c for c in cur.execute.call_args_list if "INSERT INTO audit_log" in c.args[0])
        assert insert_call.args[1][0] == "sql_agent"
        assert not conn.commit.called  # caller controls the transaction when conn is injected
        assert not conn.close.called

    def test_commits_and_closes_when_it_owns_the_connection(self):
        conn, _cur = _mock_conn()

        with patch.object(postgres_server, "_connect", return_value=conn):
            postgres_server.write_audit_log(
                agent_name="sql_agent", tool_name="ask", input_summary="q", output_summary="ok"
            )

        assert conn.commit.called
        assert conn.close.called
