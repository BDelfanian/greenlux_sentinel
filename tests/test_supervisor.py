"""Unit tests for supervisor.py: routing logic and the compiled graph, via a fake LLM and
patched specialist agents (no live DB/LLM needed)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from greenlux_sentinel.agents import supervisor


class FakeLLM:
    def __init__(self, content: str):
        self.content = content

    def invoke(self, messages):
        return SimpleNamespace(content=self.content)


class TestRouteRequest:
    @pytest.mark.parametrize("route", ["sql", "risk", "query_optimizer", "dashboard", "report"])
    def test_recognized_route_passes_through(self, route):
        result = supervisor.route_request({"request": "anything"}, llm=FakeLLM(route))
        assert result == {"route": route}

    def test_unrecognized_reply_falls_back_to_sql(self):
        result = supervisor.route_request({"request": "anything"}, llm=FakeLLM("nonsense"))
        assert result == {"route": "sql"}

    def test_reply_is_case_and_whitespace_insensitive(self):
        result = supervisor.route_request({"request": "anything"}, llm=FakeLLM("  RISK  \n"))
        assert result == {"route": "risk"}


class TestRunSql:
    def test_returns_result_on_success(self):
        with patch("greenlux_sentinel.agents.sql_agent.ask", return_value={"sql": "SELECT 1", "rows": []}):
            assert supervisor.run_sql({"request": "q"}) == {"result": {"sql": "SELECT 1", "rows": []}}

    def test_returns_error_on_failure_without_raising(self):
        with patch("greenlux_sentinel.agents.sql_agent.ask", side_effect=ValueError("boom")):
            result = supervisor.run_sql({"request": "q"})
        assert result["result"] == {}
        assert result["error"] == "boom"


class TestRunRisk:
    def test_missing_fund_id_returns_error(self):
        result = supervisor.run_risk({"request": "q"})
        assert "fund_id" in result["error"]

    def test_returns_result_on_success(self):
        with patch("greenlux_sentinel.agents.risk_agent.score_fund", return_value={"risk_score": 50.0}):
            result = supervisor.run_risk({"request": "q", "fund_id": "F1"})
        assert result == {"result": {"risk_score": 50.0}}


class TestRunQueryOptimizer:
    def test_returns_result_on_success(self):
        with patch("greenlux_sentinel.agents.query_optimizer_agent.propose_index", return_value={"proposal_id": "1"}):
            result = supervisor.run_query_optimizer({"request": "SELECT 1"})
        assert result == {"result": {"proposal_id": "1"}}


class TestRunDashboard:
    def test_returns_result_on_success(self):
        with patch(
            "greenlux_sentinel.agents.dashboard_agent.update_dashboard",
            return_value={"dax": "EVALUATE x", "dataset_id": "ds-1", "rows": []},
        ):
            result = supervisor.run_dashboard({"request": "average risk by category?"})
        assert result == {"result": {"dax": "EVALUATE x", "dataset_id": "ds-1", "rows": []}}

    def test_returns_error_on_failure_without_raising(self):
        with patch("greenlux_sentinel.agents.dashboard_agent.update_dashboard", side_effect=ValueError("boom")):
            result = supervisor.run_dashboard({"request": "q"})
        assert result["result"] == {}
        assert result["error"] == "boom"


class TestRunReport:
    def test_missing_fund_id_returns_error(self):
        result = supervisor.run_report({"request": "q"})
        assert "fund_id" in result["error"]

    def test_returns_result_on_success(self):
        draft = {"report_id": "R1", "en": "...", "fr": "...", "de": "...", "citations": [42.5]}
        with patch("greenlux_sentinel.agents.report_agent.draft_report", return_value=draft):
            result = supervisor.run_report({"request": "q", "fund_id": "F1"})
        assert result == {"result": draft}


class TestBuildGraph:
    def test_sql_route_end_to_end(self):
        with patch("greenlux_sentinel.agents.sql_agent.ask", return_value={"sql": "SELECT 1", "rows": [{"a": 1}]}):
            graph = supervisor.build_graph(llm=FakeLLM("sql"))
            final_state = graph.invoke({"request": "how many funds are there?"})
        assert final_state["route"] == "sql"
        assert final_state["result"] == {"sql": "SELECT 1", "rows": [{"a": 1}]}

    def test_risk_route_end_to_end(self):
        with patch("greenlux_sentinel.agents.risk_agent.score_fund", return_value={"risk_score": 53.03}):
            graph = supervisor.build_graph(llm=FakeLLM("risk"))
            final_state = graph.invoke({"request": "what's the risk score?", "fund_id": "0P00018CYB"})
        assert final_state["route"] == "risk"
        assert final_state["result"] == {"risk_score": 53.03}

    def test_query_optimizer_route_end_to_end(self):
        with patch(
            "greenlux_sentinel.agents.query_optimizer_agent.propose_index",
            return_value={"proposal_id": "7", "ddl": "CREATE INDEX ..."},
        ):
            graph = supervisor.build_graph(llm=FakeLLM("query_optimizer"))
            final_state = graph.invoke({"request": "SELECT * FROM funds WHERE category = 'x'"})
        assert final_state["route"] == "query_optimizer"
        assert final_state["result"]["proposal_id"] == "7"

    def test_dashboard_route_end_to_end(self):
        with patch(
            "greenlux_sentinel.agents.dashboard_agent.update_dashboard",
            return_value={"dax": "EVALUATE x", "dataset_id": "ds-1", "rows": [{"category": "Equity"}]},
        ):
            graph = supervisor.build_graph(llm=FakeLLM("dashboard"))
            final_state = graph.invoke({"request": "average risk by category?"})
        assert final_state["route"] == "dashboard"
        assert final_state["result"]["rows"] == [{"category": "Equity"}]

    def test_report_route_end_to_end(self):
        draft = {"report_id": "R1", "en": "...", "fr": "...", "de": "...", "citations": [53.03]}
        with patch("greenlux_sentinel.agents.report_agent.draft_report", return_value=draft):
            graph = supervisor.build_graph(llm=FakeLLM("report"))
            final_state = graph.invoke({"request": "draft a report", "fund_id": "0P00018CYB"})
        assert final_state["route"] == "report"
        assert final_state["result"] == draft
