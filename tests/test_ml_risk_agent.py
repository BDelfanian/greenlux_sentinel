"""Unit tests for ml_risk_agent.py: DB/model wiring via injected fakes (MagicMock), matching the
pattern in test_risk_agent.py. ml.greenwashing_risk_model.score()/load_model() are patched so
these tests don't depend on a real trained artifact existing on disk."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from greenlux_sentinel.agents import ml_risk_agent


@pytest.fixture(autouse=True)
def _reset_model_cache():
    ml_risk_agent._cached_model = None
    yield
    ml_risk_agent._cached_model = None


_SCORE_RESULT = {
    "predicted_rating_bucket": "High",
    "actual_rating_bucket": "High",
    "composition_anomaly_score": 14.82,
    "composition_anomaly_tier": "Low",
    "model_version": "tier1-composition-anomaly-v1",
    "caveat": "...",
}


class TestScoreFundComposition:
    def _conn_with_row(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = ("F1", "IE00TEST0001", 5.0, *([0.0] * len(ml_risk_agent.model.FEATURE_COLUMNS)))
        cur.description = [SimpleNamespace(name=c) for c in ml_risk_agent._SELECT_COLUMNS]
        return conn, cur

    def test_raises_when_fund_not_found(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        with pytest.raises(ValueError, match="not found"):
            ml_risk_agent.score_fund_composition("UNKNOWN", conn=conn)

    def test_scores_persists_and_audit_logs(self):
        conn, cur = self._conn_with_row()
        with (
            patch("greenlux_sentinel.ml.greenwashing_risk_model.load_model", return_value="fake-bundle") as load,
            patch("greenlux_sentinel.ml.greenwashing_risk_model.score", return_value=dict(_SCORE_RESULT)) as score,
            patch("greenlux_sentinel.mcp_servers.postgres_server.write_audit_log") as audit,
        ):
            result = ml_risk_agent.score_fund_composition("F1", conn=conn)

        assert result == _SCORE_RESULT
        load.assert_called_once()
        score.assert_called_once()
        assert score.call_args.args[0] == "fake-bundle"

        insert_calls = [c for c in cur.execute.call_args_list if "INSERT INTO fund_sustainability_anomaly_scores" in c.args[0]]
        assert len(insert_calls) == 1
        assert insert_calls[0].args[1][:3] == ("F1", "High", "High")

        audit.assert_called_once()
        assert audit.call_args.kwargs["conn"] is conn
        assert audit.call_args.kwargs["agent_name"] == "ml_risk_agent"
        conn.commit.assert_called_once()

    def test_does_not_close_caller_owned_connection(self):
        conn, _ = self._conn_with_row()
        with (
            patch("greenlux_sentinel.ml.greenwashing_risk_model.load_model", return_value="fake-bundle"),
            patch("greenlux_sentinel.ml.greenwashing_risk_model.score", return_value=dict(_SCORE_RESULT)),
            patch("greenlux_sentinel.mcp_servers.postgres_server.write_audit_log"),
        ):
            ml_risk_agent.score_fund_composition("F1", conn=conn)
        assert not conn.close.called

    def test_model_loaded_once_and_cached_across_calls(self):
        conn, _ = self._conn_with_row()
        with (
            patch("greenlux_sentinel.ml.greenwashing_risk_model.load_model", return_value="fake-bundle") as load,
            patch("greenlux_sentinel.ml.greenwashing_risk_model.score", return_value=dict(_SCORE_RESULT)),
            patch("greenlux_sentinel.mcp_servers.postgres_server.write_audit_log"),
        ):
            ml_risk_agent.score_fund_composition("F1", conn=conn)
            ml_risk_agent.score_fund_composition("F1", conn=conn)
        load.assert_called_once()
