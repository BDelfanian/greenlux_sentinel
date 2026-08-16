"""Unit tests for sql_agent.py: SQL extraction/validation (pure), plus the DB wiring via an
injected fake LLM and MagicMock connection (no live Azure OpenAI or Postgres needed)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from greenlux_sentinel.agents import sql_agent


class FakeLLM:
    """Minimal stand-in for a langchain chat model -- just enough for generate_sql()/ask()."""

    def __init__(self, content: str):
        self.content = content
        self.received_messages = None

    def invoke(self, messages):
        self.received_messages = messages
        return SimpleNamespace(content=self.content)


class TestExtractSql:
    def test_strips_markdown_fence(self):
        assert sql_agent._extract_sql("```sql\nSELECT 1\n```") == "SELECT 1"

    def test_strips_trailing_semicolon(self):
        assert sql_agent._extract_sql("SELECT 1;") == "SELECT 1"

    def test_plain_text_passthrough(self):
        assert sql_agent._extract_sql("  SELECT 1  ") == "SELECT 1"


class TestValidate:
    def test_accepts_plain_select(self):
        sql_agent.validate("SELECT fund_id FROM funds")  # must not raise

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="empty"):
            sql_agent.validate("")

    def test_rejects_non_select(self):
        with pytest.raises(ValueError, match="only SELECT"):
            sql_agent.validate("DELETE FROM funds")

    def test_rejects_forbidden_keyword_even_inside_a_select(self):
        with pytest.raises(ValueError, match="forbidden keyword"):
            sql_agent.validate("SELECT * FROM funds WHERE fund_id IN (DELETE FROM funds)")

    def test_rejects_multiple_statements(self):
        with pytest.raises(ValueError, match="multiple statements"):
            sql_agent.validate("SELECT 1; SELECT 2")


class TestWithRowLimit:
    def test_adds_limit_when_absent(self):
        assert sql_agent._with_row_limit("SELECT * FROM funds") == "SELECT * FROM funds LIMIT 200"

    def test_leaves_existing_limit_untouched(self):
        sql = "SELECT * FROM funds LIMIT 5"
        assert sql_agent._with_row_limit(sql) == sql


class TestSchemaDDL:
    def test_includes_sustainability_anomaly_scores_table(self):
        # Phase 9: the Tier 1 ML signal must be queryable via NL2SQL without a new agent/route.
        assert "fund_sustainability_anomaly_scores" in sql_agent._SCHEMA_DDL
        assert "composition_anomaly_score" in sql_agent._SCHEMA_DDL


class TestGenerateSql:
    def test_returns_validated_sql_from_llm(self):
        llm = FakeLLM("```sql\nSELECT fund_id FROM funds\n```")
        assert sql_agent.generate_sql("how many funds?", llm=llm) == "SELECT fund_id FROM funds"

    def test_no_query_response_raises(self):
        llm = FakeLLM("NO_QUERY")
        with pytest.raises(ValueError, match="cannot be answered"):
            sql_agent.generate_sql("what's the weather?", llm=llm)

    def test_invalid_llm_output_raises_before_touching_a_db(self):
        llm = FakeLLM("DROP TABLE funds")
        with pytest.raises(ValueError):
            sql_agent.generate_sql("break things", llm=llm)


class TestAsk:
    def test_sets_read_only_then_restores_and_audit_logs(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.description = [SimpleNamespace(name="fund_id"), SimpleNamespace(name="name")]
        cur.fetchall.return_value = [("F1", "Fund One")]
        llm = FakeLLM("SELECT fund_id, name FROM funds")

        result = sql_agent.ask("list funds", conn=conn, llm=llm)

        assert result == {"sql": "SELECT fund_id, name FROM funds", "rows": [{"fund_id": "F1", "name": "Fund One"}]}
        assert conn.read_only is False  # restored after the read-only query
        audit_calls = [c for c in cur.execute.call_args_list if "audit_log" in c.args[0]]
        assert len(audit_calls) == 1
        assert not conn.close.called  # caller-owned connection

    def test_executes_the_row_limited_sql_not_the_raw_sql(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.description = []
        cur.fetchall.return_value = []
        llm = FakeLLM("SELECT fund_id FROM funds")

        sql_agent.ask("list funds", conn=conn, llm=llm)

        executed_sql = cur.execute.call_args_list[0].args[0]
        assert executed_sql == "SELECT fund_id FROM funds LIMIT 200"
