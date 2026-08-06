"""Unit tests for dashboard_agent.py: template selection (pure, via a fake LLM) plus the
Power BI/Postgres wiring via injected fakes -- no live Power BI workspace or DB needed."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from greenlux_sentinel.agents import dashboard_agent
from greenlux_sentinel.bi import dax_templates


class FakeLLM:
    def __init__(self, content: str):
        self.content = content

    def invoke(self, messages):
        return SimpleNamespace(content=self.content)


class TestBuildDax:
    def test_selects_risk_by_category_template(self):
        dax = dashboard_agent.build_dax("what's the average risk by category?", llm=FakeLLM('{"template": "risk_by_category"}'))
        assert dax == dax_templates.RISK_SCORE_BY_CATEGORY

    def test_selects_top_n_template_with_extracted_n(self):
        dax = dashboard_agent.build_dax(
            "show me the top 3 riskiest funds", llm=FakeLLM('{"template": "top_n_high_risk", "n": 3}')
        )
        assert dax == dax_templates.TOP_N_HIGH_RISK_FUNDS.format(n=3)

    def test_top_n_defaults_when_n_missing(self):
        dax = dashboard_agent.build_dax("riskiest funds", llm=FakeLLM('{"template": "top_n_high_risk"}'))
        assert dax == dax_templates.TOP_N_HIGH_RISK_FUNDS.format(n=dashboard_agent._DEFAULT_TOP_N)

    def test_unrecognized_template_raises(self):
        with pytest.raises(ValueError, match="unrecognized dashboard template"):
            dashboard_agent.build_dax("anything", llm=FakeLLM('{"template": "not_a_real_one"}'))

    def test_non_json_reply_raises(self):
        with pytest.raises(ValueError, match="did not return a JSON"):
            dashboard_agent.build_dax("anything", llm=FakeLLM("I don't know"))

    def test_extracts_json_from_surrounding_text(self):
        dax = dashboard_agent.build_dax(
            "riskiest funds", llm=FakeLLM('Sure, here you go: {"template": "risk_by_category"} thanks')
        )
        assert dax == dax_templates.RISK_SCORE_BY_CATEGORY


class TestUpdateDashboard:
    def test_runs_query_and_audit_logs(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        llm = FakeLLM('{"template": "risk_by_category"}')

        with patch(
            "greenlux_sentinel.mcp_servers.powerbi_server.run_dax_query", return_value=[{"category": "Equity", "avg_risk_score": 10.0}]
        ) as run_dax:
            result = dashboard_agent.update_dashboard("average risk by category?", conn=conn, llm=llm)

        run_dax.assert_called_once()
        assert result["dax"] == dax_templates.RISK_SCORE_BY_CATEGORY
        assert result["rows"] == [{"category": "Equity", "avg_risk_score": 10.0}]
        audit_calls = [c for c in cur.execute.call_args_list if "audit_log" in c.args[0]]
        assert len(audit_calls) == 1
        assert not conn.close.called  # caller-owned connection
