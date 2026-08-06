"""Unit tests for risk_agent.py: pure scoring/explanation logic, plus the DB/Cosmos wiring via
injected fakes (MagicMock), matching the pattern in test_etl_load.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from greenlux_sentinel.agents import risk_agent


class TestComputeGap:
    def test_claim_matches_holdings_yields_zero(self):
        # 5 globes -> 100 claimed quality; holdings score at the population max -> 100 quality.
        assert risk_agent.compute_gap(5, 1536) == pytest.approx(0.0)

    def test_overclaiming_yields_positive_risk(self):
        # 5 globes (100 claimed quality) but holdings score at the population floor (0 quality).
        assert risk_agent.compute_gap(5, 600) == pytest.approx(100.0)

    def test_holdings_better_than_claimed_clamps_to_zero_not_negative(self):
        # 1 globe (0 claimed quality) but holdings score at the population max (100 quality) —
        # a positive surprise, not a "negative risk".
        assert risk_agent.compute_gap(1, 1536) == pytest.approx(0.0)

    def test_midpoint_claim_and_holdings(self):
        # 3 globes -> 50 claimed quality; holdings score at the dataset midpoint (600+1536)/2=1068
        # -> 50 holdings quality. Gap should be ~0.
        assert risk_agent.compute_gap(3, 1068) == pytest.approx(0.0, abs=0.1)


class TestExplain:
    def _holding(self, ticker, weight_pct, total_esg_score):
        return {"ticker": ticker, "weight_pct": weight_pct, "esg": {"total_esg_score": total_esg_score}}

    def test_no_matched_holdings_returns_placeholder(self):
        assert "unavailable" in risk_agent.explain([{"ticker": "X", "weight_pct": 1.0, "esg": None}])

    def test_lists_below_median_holdings_by_weight_descending(self):
        holdings = [
            self._holding("HIGH1", 10.0, 1500),
            self._holding("HIGH2", 9.0, 1400),
            self._holding("LOWBIG", 8.0, 700),
            self._holding("LOWSMALL", 1.0, 650),
        ]
        text = risk_agent.explain(holdings, top_n=5)
        assert "LOWBIG" in text
        # LOWBIG (bigger weight) should be listed before LOWSMALL
        assert text.index("LOWBIG") < text.index("LOWSMALL")
        assert "HIGH1" not in text  # above median, not a laggard

    def test_all_above_median_or_equal_returns_placeholder(self):
        holdings = [self._holding("A", 5.0, 1000), self._holding("B", 5.0, 1000)]
        assert "No below-median" in risk_agent.explain(holdings)


class TestScoreByIsin:
    def _fake_doc(self, holdings_implied_esg_score=1000.0):
        return {
            "isin": "IE00TEST0001",
            "holdings_implied_esg_score": holdings_implied_esg_score,
            "holdings": [
                {"ticker": "MSFT", "weight_pct": 7.0, "esg": {"total_esg_score": 1400}},
                {"ticker": "ZZZZ", "weight_pct": 2.0, "esg": None},
            ],
        }

    def test_raises_when_no_verified_doc(self):
        conn, container = MagicMock(), MagicMock()
        container.query_items.return_value = []
        with pytest.raises(ValueError, match="no verified Tier 2"):
            risk_agent.score_by_isin("IE00MISSING", conn, container)

    def test_raises_when_no_matched_holdings_score(self):
        conn, container = MagicMock(), MagicMock()
        container.query_items.return_value = [self._fake_doc(holdings_implied_esg_score=None)]
        with pytest.raises(ValueError, match="no matched holdings"):
            risk_agent.score_by_isin("IE00TEST0001", conn, container)

    def test_raises_when_no_tier1_claim(self):
        conn, container = MagicMock(), MagicMock()
        container.query_items.return_value = [self._fake_doc()]
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        with pytest.raises(ValueError, match="no Tier 1 sustainability rating"):
            risk_agent.score_by_isin("IE00TEST0001", conn, container)

    def test_one_result_per_share_class(self):
        conn, container = MagicMock(), MagicMock()
        container.query_items.return_value = [self._fake_doc()]
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [("FUND_A", 5), ("FUND_B", 5)]

        results = risk_agent.score_by_isin("IE00TEST0001", conn, container)

        assert {r["fund_id"] for r in results} == {"FUND_A", "FUND_B"}
        assert all(r["isin"] == "IE00TEST0001" for r in results)
        assert all(r["caveat"] == risk_agent.CAVEAT for r in results)


class TestPersist:
    def test_writes_one_row_per_result_and_audit_logs(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        results = [
            {"fund_id": "F1", "isin": "IE00X", "risk_score": 10.0, "holdings_implied_esg": 1000.0, "explanation": "e"},
            {"fund_id": "F2", "isin": "IE00X", "risk_score": 10.0, "holdings_implied_esg": 1000.0, "explanation": "e"},
        ]

        risk_agent.persist(results, conn)

        insert_calls = [c for c in cur.execute.call_args_list if "INSERT INTO fund_risk_scores" in c.args[0]]
        assert len(insert_calls) == 2
        audit_calls = [c for c in cur.execute.call_args_list if "audit_log" in c.args[0]]
        assert len(audit_calls) == 1


class TestScoreFund:
    def test_not_found_raises(self):
        conn, container = MagicMock(), MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        with pytest.raises(ValueError, match="not found"):
            risk_agent.score_fund("UNKNOWN", conn=conn, container=container)

    def test_does_not_close_caller_owned_connection(self):
        conn, container = MagicMock(), MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = ("IE00TEST0001",)
        cur.fetchall.return_value = [("FUND_A", 5)]
        container.query_items.return_value = [
            {
                "isin": "IE00TEST0001",
                "holdings_implied_esg_score": 1000.0,
                "holdings": [{"ticker": "MSFT", "weight_pct": 7.0, "esg": {"total_esg_score": 1400}}],
            }
        ]

        result = risk_agent.score_fund("FUND_A", conn=conn, container=container)

        assert set(result.keys()) == {"risk_score", "explanation", "caveat"}
        assert not conn.close.called
