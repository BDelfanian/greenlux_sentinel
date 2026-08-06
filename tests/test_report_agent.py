"""Unit tests for report_agent.py: draft/publish/reject wiring via injected fakes -- no live
DB/Cosmos/LLM needed. Mirrors the patch-the-collaborator style test_supervisor.py uses for
cross-agent calls (risk_agent.score_fund, sql_agent.ask)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from greenlux_sentinel.agents import report_agent


class SequentialFakeLLM:
    """Returns each content in `replies` in turn, one per invoke() call."""

    def __init__(self, replies: list[str]):
        self._replies = list(replies)
        self.calls = 0

    def invoke(self, messages):
        content = self._replies[min(self.calls, len(self._replies) - 1)]
        self.calls += 1
        return SimpleNamespace(content=content)


_RISK_RESULT = {"risk_score": 42.5, "explanation": "driven by laggard holdings", "caveat": "unused"}
_SQL_RESULT = {"sql": "SELECT name, category FROM funds WHERE fund_id = 'F1'", "rows": [{"name": "Fund One", "category": "Equity"}]}


class TestDraftReport:
    def test_happy_path_writes_three_rows_and_returns_bodies(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        container = MagicMock()
        llm = SequentialFakeLLM(["en body 42.5", "fr body 42.5", "de body 42.5"])

        with (
            patch("greenlux_sentinel.agents.risk_agent.score_fund", return_value=_RISK_RESULT),
            patch("greenlux_sentinel.agents.sql_agent.ask", return_value=_SQL_RESULT),
        ):
            result = report_agent.draft_report("F1", conn=conn, container=container, llm=llm)

        assert set(result.keys()) == {"report_id", "en", "fr", "de", "citations"}
        assert 42.5 in result["citations"]
        insert_calls = [c for c in cur.execute.call_args_list if "INSERT INTO fund_reports" in c.args[0]]
        assert len(insert_calls) == 3
        languages_inserted = {c.args[1][2] for c in insert_calls}
        assert languages_inserted == {"en", "fr", "de"}
        audit_calls = [c for c in cur.execute.call_args_list if "audit_log" in c.args[0]]
        assert len(audit_calls) == 1
        assert not conn.close.called  # caller-owned connections

    def test_retries_once_then_raises_if_still_unsourced(self):
        conn = MagicMock()
        container = MagicMock()
        # en: first attempt has an unsourced number, retry also unsourced -> should raise.
        llm = SequentialFakeLLM(["the fund scores 999"])

        with (
            patch("greenlux_sentinel.agents.risk_agent.score_fund", return_value=_RISK_RESULT),
            patch("greenlux_sentinel.agents.sql_agent.ask", return_value=_SQL_RESULT),
            pytest.raises(ValueError, match="tool-sourced-numbers guardrail"),
        ):
            report_agent.draft_report("F1", conn=conn, container=container, llm=llm)

    def test_retry_recovers_on_second_attempt(self):
        conn = MagicMock()
        container = MagicMock()
        # First call (en) fails, second call (en retry) passes, then fr/de each pass first try.
        llm = SequentialFakeLLM(["unsourced 999", "the score is 42.5", "fr 42.5", "de 42.5"])

        with (
            patch("greenlux_sentinel.agents.risk_agent.score_fund", return_value=_RISK_RESULT),
            patch("greenlux_sentinel.agents.sql_agent.ask", return_value=_SQL_RESULT),
        ):
            result = report_agent.draft_report("F1", conn=conn, container=container, llm=llm)

        assert result["en"] == "the score is 42.5"

    def test_fund_not_found_via_sql_raises(self):
        conn = MagicMock()
        container = MagicMock()
        llm = SequentialFakeLLM(["body"])

        with (
            patch("greenlux_sentinel.agents.risk_agent.score_fund", return_value=_RISK_RESULT),
            patch("greenlux_sentinel.agents.sql_agent.ask", return_value={"sql": "SELECT 1", "rows": []}),
            pytest.raises(ValueError, match="not found via sql_agent"),
        ):
            report_agent.draft_report("F1", conn=conn, container=container, llm=llm)


class TestPublishReport:
    def test_publishes_when_fully_draft(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (3, 3)

        report_agent.publish_report("R1", "reviewer@example.com", conn=conn)

        update_calls = [c for c in cur.execute.call_args_list if "UPDATE fund_reports" in c.args[0]]
        assert len(update_calls) == 1
        assert update_calls[0].args[1][0] == "published"
        assert conn.commit.called

    def test_raises_when_report_missing(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (0, 0)

        with pytest.raises(ValueError, match="no such report"):
            report_agent.publish_report("MISSING", "reviewer", conn=conn)

    def test_raises_when_not_fully_draft(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (3, 1)  # only 1 of 3 language rows still draft

        with pytest.raises(ValueError, match="not fully in draft status"):
            report_agent.publish_report("R1", "reviewer", conn=conn)


class TestRejectReport:
    def test_rejects_when_fully_draft(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (3, 3)

        report_agent.reject_report("R1", "reviewer", conn=conn)

        update_calls = [c for c in cur.execute.call_args_list if "UPDATE fund_reports" in c.args[0]]
        assert update_calls[0].args[1][0] == "rejected"
