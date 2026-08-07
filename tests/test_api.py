"""Unit tests for api/app.py: routing + auth wiring via patched collaborators and FastAPI's
TestClient -- no live DB/Cosmos/LLM/network needed. Each agent call itself is already unit-tested
in its own test_*_agent.py; these tests only check the HTTP layer wires requests through to the
right function, translates ValueError to 400, and enforces the bearer-token check.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from greenlux_sentinel.api.app import app

client = TestClient(app)


def _settings(token: str = "") -> SimpleNamespace:
    return SimpleNamespace(api_auth_token=token)


class TestHealthz:
    def test_unauthenticated(self):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestAuth:
    def test_no_token_configured_allows_request(self):
        with (
            patch("greenlux_sentinel.api.app.get_settings", return_value=_settings("")),
            patch("greenlux_sentinel.agents.sql_agent.ask", return_value={"sql": "SELECT 1", "rows": []}),
        ):
            response = client.post("/sql", json={"question": "how many funds?"})
        assert response.status_code == 200

    def test_token_configured_rejects_missing_header(self):
        with patch("greenlux_sentinel.api.app.get_settings", return_value=_settings("secret")):
            response = client.post("/sql", json={"question": "how many funds?"})
        assert response.status_code == 401

    def test_token_configured_rejects_wrong_token(self):
        with patch("greenlux_sentinel.api.app.get_settings", return_value=_settings("secret")):
            response = client.post(
                "/sql", json={"question": "how many funds?"}, headers={"Authorization": "Bearer wrong"}
            )
        assert response.status_code == 401

    def test_token_configured_accepts_correct_token(self):
        with (
            patch("greenlux_sentinel.api.app.get_settings", return_value=_settings("secret")),
            patch("greenlux_sentinel.agents.sql_agent.ask", return_value={"sql": "SELECT 1", "rows": []}),
        ):
            response = client.post(
                "/sql", json={"question": "how many funds?"}, headers={"Authorization": "Bearer secret"}
            )
        assert response.status_code == 200


class TestRoutes:
    def setup_method(self):
        self._settings_patch = patch("greenlux_sentinel.api.app.get_settings", return_value=_settings(""))
        self._settings_patch.start()

    def teardown_method(self):
        self._settings_patch.stop()

    def test_sql(self):
        with patch("greenlux_sentinel.agents.sql_agent.ask", return_value={"sql": "SELECT 1", "rows": [{"n": 1}]}) as m:
            response = client.post("/sql", json={"question": "how many funds?"})
        assert response.status_code == 200
        assert response.json() == {"sql": "SELECT 1", "rows": [{"n": 1}]}
        m.assert_called_once_with("how many funds?")

    def test_risk(self):
        result = {"risk_score": 42.5, "explanation": "...", "caveat": "..."}
        with patch("greenlux_sentinel.agents.risk_agent.score_fund", return_value=result) as m:
            response = client.post("/risk/F1")
        assert response.status_code == 200
        assert response.json() == result
        m.assert_called_once_with("F1")

    def test_risk_value_error_becomes_400(self):
        with patch("greenlux_sentinel.agents.risk_agent.score_fund", side_effect=ValueError("fund_id=F1 not found")):
            response = client.post("/risk/F1")
        assert response.status_code == 400
        assert response.json()["detail"] == "fund_id=F1 not found"

    def test_dashboard(self):
        result = {"dax": "EVALUATE ...", "dataset_id": "ds1", "rows": []}
        with patch("greenlux_sentinel.agents.dashboard_agent.update_dashboard", return_value=result) as m:
            response = client.post("/dashboard", json={"question": "top 10 risky funds"})
        assert response.status_code == 200
        assert response.json() == result
        m.assert_called_once_with("top 10 risky funds")

    def test_query_optimizer_propose(self):
        result = {"proposal_id": "7", "ddl": "CREATE INDEX ...", "estimated_improvement": "..."}
        with patch("greenlux_sentinel.agents.query_optimizer_agent.propose_index", return_value=result) as m:
            response = client.post("/query-optimizer/propose", json={"sql": "SELECT * FROM funds WHERE isin = 'X'"})
        assert response.status_code == 200
        assert response.json() == result
        m.assert_called_once_with("SELECT * FROM funds WHERE isin = 'X'")

    def test_query_optimizer_approve(self):
        with patch("greenlux_sentinel.agents.query_optimizer_agent.apply_approved", return_value=None) as m:
            response = client.post("/query-optimizer/7/approve", json={"actor": "alice"})
        assert response.status_code == 200
        assert response.json() == {"status": "approved"}
        m.assert_called_once_with("7", "alice")

    def test_query_optimizer_reject(self):
        with patch("greenlux_sentinel.agents.query_optimizer_agent.reject_proposal", return_value=None) as m:
            response = client.post("/query-optimizer/7/reject", json={"actor": "alice"})
        assert response.status_code == 200
        assert response.json() == {"status": "rejected"}
        m.assert_called_once_with("7", "alice")

    def test_report_draft(self):
        result = {"report_id": "r1", "en": "...", "fr": "...", "de": "...", "citations": [42.5]}
        with patch("greenlux_sentinel.agents.report_agent.draft_report", return_value=result) as m:
            response = client.post("/report/draft/F1")
        assert response.status_code == 200
        assert response.json() == result
        m.assert_called_once_with("F1")

    def test_report_publish(self):
        with patch("greenlux_sentinel.agents.report_agent.publish_report", return_value=None) as m:
            response = client.post("/report/r1/publish", json={"actor": "alice"})
        assert response.status_code == 200
        assert response.json() == {"status": "published"}
        m.assert_called_once_with("r1", "alice")

    def test_report_reject(self):
        with patch("greenlux_sentinel.agents.report_agent.reject_report", return_value=None) as m:
            response = client.post("/report/r1/reject", json={"actor": "alice"})
        assert response.status_code == 200
        assert response.json() == {"status": "rejected"}
        m.assert_called_once_with("r1", "alice")

    def test_etl_run(self):
        summary = {"funds_loaded": 12, "top100_holdings_docs": 4, "verified_holdings_docs": 5, "gleif_matched": 3}
        with patch("greenlux_sentinel.agents.etl_agent.run_ingestion", return_value=summary) as m:
            response = client.post("/etl/run")
        assert response.status_code == 200
        assert response.json() == summary
        m.assert_called_once_with()
