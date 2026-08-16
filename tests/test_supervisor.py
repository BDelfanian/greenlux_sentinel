"""Unit tests for supervisor.py: routing logic and the compiled graph, via a fake LLM and
patched specialist agents (no live DB/LLM needed)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from greenlux_sentinel.agents import supervisor

from .test_report_agent import SequentialFakeLLM


class FakeLLM:
    def __init__(self, content: str):
        self.content = content

    def invoke(self, messages):
        return SimpleNamespace(content=self.content)


class TestRouteRequest:
    @pytest.mark.parametrize("route", ["sql", "risk", "query_optimizer", "dashboard", "report", "evidence", "multi_hop"])
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


class TestRunMlRisk:
    def test_missing_fund_id_returns_error(self):
        result = supervisor.dispatch({"request": "q", "plan": ["ml_risk"], "hop_results": {}, "hop_errors": {}, "trace": []})
        assert "fund_id" in result["hop_errors"]["ml_risk"]

    def test_returns_result_on_success(self):
        ml_result = {"composition_anomaly_score": 14.82, "composition_anomaly_tier": "Low"}
        with patch("greenlux_sentinel.agents.ml_risk_agent.score_fund_composition", return_value=ml_result) as m:
            result = supervisor.dispatch(
                {"request": "q", "fund_id": "F1", "plan": ["ml_risk"], "hop_results": {}, "hop_errors": {}, "trace": []}
            )
        assert result["hop_results"]["ml_risk"] == ml_result
        m.assert_called_once_with("F1")

    def test_failure_becomes_hop_error_not_raise(self):
        with patch("greenlux_sentinel.agents.ml_risk_agent.score_fund_composition", side_effect=ValueError("boom")):
            result = supervisor.dispatch(
                {"request": "q", "fund_id": "F1", "plan": ["ml_risk"], "hop_results": {}, "hop_errors": {}, "trace": []}
            )
        assert result["hop_errors"]["ml_risk"] == "boom"


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


class TestRunEvidence:
    def test_returns_result_on_success(self):
        result = {"answer": "cited [doc:1]", "abstained": False}
        with patch("greenlux_sentinel.agents.evidence_agent.answer_with_evidence", return_value=result) as m:
            state_result = supervisor.run_evidence({"request": "q", "fund_id": "F1"})
        assert state_result == {"result": result}
        m.assert_called_once_with("q", fund_id="F1")

    def test_returns_error_on_failure_without_raising(self):
        with patch("greenlux_sentinel.agents.evidence_agent.answer_with_evidence", side_effect=ValueError("boom")):
            result = supervisor.run_evidence({"request": "q"})
        assert result["result"] == {}
        assert result["error"] == "boom"


class TestParsePlan:
    def test_valid_plan_passes_through(self):
        assert supervisor._parse_plan('["sql", "risk", "evidence"]') == ["sql", "risk", "evidence"]

    def test_unknown_hop_names_filtered_out(self):
        assert supervisor._parse_plan('["sql", "bogus", "evidence"]') == ["sql", "evidence"]

    def test_unparseable_reply_falls_back_to_default(self):
        assert supervisor._parse_plan("not json at all") == supervisor._DEFAULT_PLAN

    def test_empty_plan_after_filtering_falls_back_to_default(self):
        assert supervisor._parse_plan('["bogus1", "bogus2"]') == supervisor._DEFAULT_PLAN

    def test_plan_capped_at_max_hops(self):
        oversized = json.dumps(["sql", "risk", "evidence"] * 3)
        assert len(supervisor._parse_plan(oversized)) <= supervisor._MAX_HOPS


class TestPlanRequest:
    def test_parses_llm_plan_and_resets_hop_state(self):
        result = supervisor.plan_request({"request": "q"}, llm=FakeLLM('["sql", "evidence"]'))
        assert result == {"plan": ["sql", "evidence"], "hop_results": {}, "hop_errors": {}, "trace": []}


class TestFactsFromHops:
    def test_extracts_risk_score_and_explanation(self):
        facts = supervisor._facts_from_hops({"risk": {"risk_score": 42.5, "explanation": "..."}})
        assert facts == {"greenwashing_risk_score": 42.5, "risk_explanation": "..."}

    def test_extracts_ml_risk_facts_under_distinct_keys(self):
        facts = supervisor._facts_from_hops(
            {"ml_risk": {"composition_anomaly_score": 14.82, "composition_anomaly_tier": "Low", "predicted_rating_bucket": "High"}}
        )
        assert facts == {
            "composition_anomaly_score": 14.82,
            "composition_anomaly_tier": "Low",
            "ml_predicted_rating_bucket": "High",
        }

    def test_risk_and_ml_risk_facts_coexist_without_colliding(self):
        facts = supervisor._facts_from_hops(
            {
                "risk": {"risk_score": 53.03, "explanation": "..."},
                "ml_risk": {"composition_anomaly_score": 14.82, "composition_anomaly_tier": "Low"},
            }
        )
        assert facts["greenwashing_risk_score"] == 53.03
        assert facts["composition_anomaly_score"] == 14.82

    def test_extracts_scalar_fields_from_first_sql_row(self):
        facts = supervisor._facts_from_hops({"sql": {"rows": [{"name": "Fund One", "total_net_assets": 100.0}]}})
        assert facts == {"name": "Fund One", "total_net_assets": 100.0}

    def test_empty_hop_results_returns_empty_facts(self):
        assert supervisor._facts_from_hops({}) == {}


class TestDispatch:
    def test_runs_next_unrun_hop_sql(self):
        with patch("greenlux_sentinel.agents.sql_agent.ask", return_value={"sql": "SELECT 1", "rows": []}):
            result = supervisor.dispatch({"request": "q", "plan": ["sql", "evidence"], "hop_results": {}, "hop_errors": {}, "trace": []})
        assert result["hop_results"]["sql"] == {"sql": "SELECT 1", "rows": []}
        assert result["trace"] == [{"hop": "sql", "status": "ok"}]

    def test_risk_hop_without_fund_id_records_error_not_raise(self):
        result = supervisor.dispatch({"request": "q", "plan": ["risk"], "hop_results": {}, "hop_errors": {}, "trace": []})
        assert "fund_id" in result["hop_errors"]["risk"]
        assert result["trace"][0]["status"] == "error"

    def test_skips_already_completed_hops(self):
        with patch("greenlux_sentinel.agents.risk_agent.score_fund", return_value={"risk_score": 1.0}) as m:
            result = supervisor.dispatch(
                {
                    "request": "q",
                    "fund_id": "F1",
                    "plan": ["sql", "risk"],
                    "hop_results": {"sql": {"rows": []}},
                    "hop_errors": {},
                    "trace": [],
                }
            )
        m.assert_called_once_with("F1")
        assert result["hop_results"]["risk"] == {"risk_score": 1.0}

    def test_no_remaining_hops_returns_empty_dict(self):
        result = supervisor.dispatch({"plan": ["sql"], "hop_results": {"sql": {}}, "hop_errors": {}, "trace": []})
        assert result == {}


class TestNextDispatchStep:
    def test_pending_hop_routes_to_dispatch(self):
        state = {"plan": ["sql", "evidence"], "hop_results": {"sql": {}}, "hop_errors": {}}
        assert supervisor._next_dispatch_step(state) == "dispatch"

    def test_all_hops_resolved_routes_to_synthesize(self):
        state = {"plan": ["sql", "evidence"], "hop_results": {"sql": {}}, "hop_errors": {"evidence": "boom"}}
        assert supervisor._next_dispatch_step(state) == "synthesize"


class TestSynthesize:
    def test_reuses_evidence_hop_result_directly(self):
        evidence_result = {"answer": "cited [doc:1]", "abstained": False}
        result = supervisor.synthesize({"hop_results": {"evidence": evidence_result}})
        assert result == {"final_answer": evidence_result, "result": evidence_result}

    def test_calls_evidence_agent_with_facts_from_other_hops_when_no_evidence_hop(self):
        final = {"answer": "synthesized", "abstained": False}
        with patch("greenlux_sentinel.agents.evidence_agent.answer_with_evidence", return_value=final) as m:
            result = supervisor.synthesize(
                {"request": "q", "fund_id": "F1", "hop_results": {"risk": {"risk_score": 42.5}}}
            )
        assert result == {"final_answer": final, "result": final}
        m.assert_called_once_with("q", fund_id="F1", precomputed_facts={"greenwashing_risk_score": 42.5})

    def test_evidence_agent_failure_becomes_error_not_raise(self):
        with patch("greenlux_sentinel.agents.evidence_agent.answer_with_evidence", side_effect=ValueError("boom")):
            result = supervisor.synthesize({"request": "q", "hop_results": {}})
        assert result["final_answer"] == {}
        assert result["error"] == "boom"


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

    def test_evidence_route_end_to_end(self):
        result = {"answer": "cited [doc:1]", "abstained": False}
        with patch("greenlux_sentinel.agents.evidence_agent.answer_with_evidence", return_value=result):
            graph = supervisor.build_graph(llm=FakeLLM("evidence"))
            final_state = graph.invoke({"request": "does this fund's KIID say Article 8?", "fund_id": "F1"})
        assert final_state["route"] == "evidence"
        assert final_state["result"] == result

    def test_multi_hop_route_chains_sql_then_evidence_and_synthesizes(self):
        # Router call ("multi_hop"), then planner call (the JSON plan) -- SequentialFakeLLM
        # feeds one reply per invoke(), in order.
        llm = SequentialFakeLLM(["multi_hop", '["sql", "evidence"]'])
        sql_result = {"sql": "SELECT name FROM funds WHERE fund_id = 'F1'", "rows": [{"name": "Test Fund"}]}
        evidence_result = {"answer": "Test Fund is Article 8 [doc:kiid_1_0].", "abstained": False}

        with (
            patch("greenlux_sentinel.agents.sql_agent.ask", return_value=sql_result),
            patch("greenlux_sentinel.agents.evidence_agent.answer_with_evidence", return_value=evidence_result) as m,
        ):
            graph = supervisor.build_graph(llm=llm)
            final_state = graph.invoke({"request": "Is Test Fund Article 8, per its disclosures?", "fund_id": "F1"})

        assert final_state["route"] == "multi_hop"
        assert final_state["plan"] == ["sql", "evidence"]
        assert final_state["hop_results"]["sql"] == sql_result
        assert final_state["hop_results"]["evidence"] == evidence_result
        assert final_state["final_answer"] == evidence_result
        assert final_state["result"] == evidence_result
        # evidence was already run as a plannable hop -- synthesize() must reuse it, not call twice.
        m.assert_called_once()

    def test_multi_hop_route_combines_risk_and_ml_risk_facts_for_synthesize(self):
        # Both quantitative signals present (the 4 funds that have both) -- synthesize() must pass
        # BOTH under their own distinct keys, not merge or drop either (CLAUDE.md decision #8).
        llm = SequentialFakeLLM(["multi_hop", '["risk", "ml_risk"]'])
        risk_result = {"risk_score": 53.03, "explanation": "..."}
        ml_risk_result = {"composition_anomaly_score": 14.82, "composition_anomaly_tier": "Low"}
        final_answer = {"answer": "synthesized [doc:kiid_1_0].", "abstained": False}

        with (
            patch("greenlux_sentinel.agents.risk_agent.score_fund", return_value=risk_result),
            patch("greenlux_sentinel.agents.ml_risk_agent.score_fund_composition", return_value=ml_risk_result),
            patch("greenlux_sentinel.agents.evidence_agent.answer_with_evidence", return_value=final_answer) as m,
        ):
            graph = supervisor.build_graph(llm=llm)
            graph.invoke({"request": "Give me the fullest risk picture with evidence.", "fund_id": "F1"})

        m.assert_called_once_with(
            "Give me the fullest risk picture with evidence.",
            fund_id="F1",
            precomputed_facts={
                "greenwashing_risk_score": 53.03,
                "risk_explanation": "...",
                "composition_anomaly_score": 14.82,
                "composition_anomaly_tier": "Low",
            },
        )

    def test_multi_hop_route_chains_ml_risk_then_evidence(self):
        llm = SequentialFakeLLM(["multi_hop", '["ml_risk", "evidence"]'])
        ml_risk_result = {"composition_anomaly_score": 14.82, "composition_anomaly_tier": "Low", "predicted_rating_bucket": "High"}
        evidence_result = {"answer": "Composition looks typical for its claim [doc:kiid_1_0].", "abstained": False}

        with (
            patch("greenlux_sentinel.agents.ml_risk_agent.score_fund_composition", return_value=ml_risk_result),
            patch("greenlux_sentinel.agents.evidence_agent.answer_with_evidence", return_value=evidence_result) as m,
        ):
            graph = supervisor.build_graph(llm=llm)
            final_state = graph.invoke(
                {"request": "Is this fund's disclosed strategy consistent with its rating?", "fund_id": "F1"}
            )

        assert final_state["plan"] == ["ml_risk", "evidence"]
        assert final_state["hop_results"]["ml_risk"] == ml_risk_result
        assert final_state["final_answer"] == evidence_result
        # evidence was run as a plannable hop directly -- synthesize() must reuse it, not re-call.
        m.assert_called_once()

    def test_multi_hop_route_without_evidence_hop_still_synthesizes(self):
        llm = SequentialFakeLLM(["multi_hop", '["risk"]'])
        risk_result = {"risk_score": 42.5, "explanation": "..."}
        final_answer = {"answer": "synthesized from risk score [doc:kiid_1_0].", "abstained": False}

        with (
            patch("greenlux_sentinel.agents.risk_agent.score_fund", return_value=risk_result),
            patch("greenlux_sentinel.agents.evidence_agent.answer_with_evidence", return_value=final_answer) as m,
        ):
            graph = supervisor.build_graph(llm=llm)
            final_state = graph.invoke({"request": "Is the risk score consistent with disclosures?", "fund_id": "F1"})

        assert final_state["hop_results"] == {"risk": risk_result}
        assert final_state["final_answer"] == final_answer
        m.assert_called_once_with(
            "Is the risk score consistent with disclosures?",
            fund_id="F1",
            precomputed_facts={"greenwashing_risk_score": 42.5, "risk_explanation": "..."},
        )
