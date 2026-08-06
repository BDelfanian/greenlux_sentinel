"""Unit tests for query_optimizer_agent.py, via injected MagicMock connections (no live DB)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from greenlux_sentinel.agents import query_optimizer_agent as qoa


def _mock_conn():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    return conn, cur


class TestCandidateIndex:
    def test_finds_unindexed_predicate_column(self):
        conn, cur = _mock_conn()
        cur.fetchall.return_value = [("CREATE UNIQUE INDEX funds_pkey ON public.funds USING btree (fund_id)",)]

        result = qoa._candidate_index("SELECT * FROM funds WHERE category = 'Equity'", conn)

        assert result == ("funds", "category")

    def test_returns_none_when_column_already_indexed(self):
        conn, cur = _mock_conn()
        cur.fetchall.return_value = [("CREATE INDEX idx_funds_category ON public.funds USING btree (category)",)]

        result = qoa._candidate_index("SELECT * FROM funds WHERE category = 'Equity'", conn)

        assert result is None

    def test_returns_none_when_no_from_clause_matched(self):
        conn, _cur = _mock_conn()
        assert qoa._candidate_index("SELECT 1", conn) is None


class TestProposeIndex:
    def test_rejects_non_select_input(self):
        conn = MagicMock()
        with pytest.raises(ValueError, match="only SELECT"):
            qoa.propose_index("DELETE FROM funds", conn=conn)

    def test_raises_when_nothing_to_propose(self):
        conn, cur = _mock_conn()
        cur.fetchall.side_effect = [
            [("Seq Scan on funds  (rows=67098)",)],  # EXPLAIN ANALYZE
            [("CREATE INDEX idx_funds_category ON public.funds USING btree (category)",)],  # pg_indexes
        ]
        with pytest.raises(ValueError, match="nothing to propose"):
            qoa.propose_index("SELECT * FROM funds WHERE category = 'Equity'", conn=conn)

    def test_queues_a_pending_proposal_and_returns_ddl(self):
        conn, cur = _mock_conn()
        cur.fetchall.side_effect = [
            [("Seq Scan on funds  (cost=0.00..1934.00 rows=67098 width=120)",)],  # EXPLAIN ANALYZE
            [("CREATE UNIQUE INDEX funds_pkey ON public.funds USING btree (fund_id)",)],  # pg_indexes
        ]
        cur.fetchone.return_value = (42,)

        result = qoa.propose_index("SELECT * FROM funds WHERE category = 'Equity'", conn=conn)

        assert result["proposal_id"] == "42"
        assert result["ddl"] == "CREATE INDEX IF NOT EXISTS idx_funds_category ON funds (category)"
        assert "67098 rows" in result["estimated_improvement"]

        insert_call = next(c for c in cur.execute.call_args_list if "INSERT INTO audit_log" in c.args[0])
        assert insert_call.args[1][-1] == "pending"
        assert conn.commit.called


class TestApplyApproved:
    def test_raises_when_proposal_not_found(self):
        conn, cur = _mock_conn()
        cur.fetchone.return_value = None
        with pytest.raises(ValueError, match="no such proposal"):
            qoa.apply_approved("42", "alice", conn=conn)

    def test_raises_when_not_pending(self):
        conn, cur = _mock_conn()
        cur.fetchone.return_value = ("CREATE INDEX idx_x ON funds (category)", "rejected")
        with pytest.raises(ValueError, match="not pending"):
            qoa.apply_approved("42", "alice", conn=conn)

    def test_executes_ddl_and_audit_logs_when_pending(self):
        conn, cur = _mock_conn()
        cur.fetchone.return_value = ("CREATE INDEX idx_funds_category ON funds (category)", "pending")

        qoa.apply_approved("42", "alice", conn=conn)

        ddl_calls = [c for c in cur.execute.call_args_list if "CREATE INDEX" in c.args[0]]
        assert len(ddl_calls) == 1
        approve_calls = [c for c in cur.execute.call_args_list if "approval_status = 'approved'" in c.args[0]]
        assert len(approve_calls) == 1
        audit_calls = [c for c in cur.execute.call_args_list if "audit_log" in c.args[0] and "INSERT" in c.args[0]]
        assert len(audit_calls) == 1
        assert conn.commit.called


class TestRejectProposal:
    def test_raises_when_not_pending(self):
        conn, cur = _mock_conn()
        cur.fetchone.return_value = ("CREATE INDEX idx_x ON funds (category)", "approved")
        with pytest.raises(ValueError, match="not pending"):
            qoa.reject_proposal("42", "alice", conn=conn)

    def test_marks_rejected_without_executing_ddl(self):
        conn, cur = _mock_conn()
        cur.fetchone.return_value = ("CREATE INDEX idx_funds_category ON funds (category)", "pending")

        qoa.reject_proposal("42", "alice", conn=conn)

        ddl_calls = [c for c in cur.execute.call_args_list if "CREATE INDEX" in c.args[0]]
        assert len(ddl_calls) == 0
        reject_calls = [c for c in cur.execute.call_args_list if "approval_status = 'rejected'" in c.args[0]]
        assert len(reject_calls) == 1
        assert conn.commit.called
