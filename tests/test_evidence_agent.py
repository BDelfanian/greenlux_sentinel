"""Unit tests for evidence_agent.py: draft/retrieve/guardrail wiring via injected fakes -- no
live DB/Azure AI Search/LLM needed. Mirrors test_report_agent.py's patch-the-collaborator style
and reuses its SequentialFakeLLM."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from greenlux_sentinel.agents import evidence_agent

from .test_report_agent import SequentialFakeLLM

_PASSAGES = [
    {"id": "kiid_1_0", "doc_type": "kiid", "content": "The Fund promotes environmental characteristics under SFDR Article 8."},
    {"id": "cssf_faq_0", "doc_type": "cssf_guidance", "content": "CSSF expects consistency between disclosures and holdings."},
]


class TestAnswerWithEvidence:
    def test_happy_path_returns_cited_answer(self):
        conn = MagicMock()
        llm = SequentialFakeLLM(["The Fund is Article 8 [doc:kiid_1_0], consistent with CSSF guidance [doc:cssf_faq_0]."])

        with (
            patch("greenlux_sentinel.agents.evidence_agent.retrieve_evidence", return_value=_PASSAGES),
            patch("greenlux_sentinel.mcp_servers.postgres_server.write_audit_log"),
        ):
            result = evidence_agent.answer_with_evidence(
                "Is this fund Article 8?", conn=conn, llm=llm, precomputed_facts={"name": "Test Fund"}
            )

        assert result["abstained"] is False
        assert {c["id"] for c in result["document_citations"]} == {"kiid_1_0", "cssf_faq_0"}
        assert result["sources_considered"] == 2
        assert not conn.close.called  # caller-owned connection

    def test_no_evidence_retrieved_falls_back_to_abstention_without_raising(self):
        conn = MagicMock()
        # Two attempts, neither cites anything real -- should fall back, not raise.
        llm = SequentialFakeLLM(["Yes, it is Article 8.", "Yes, it is Article 8."])

        with (
            patch("greenlux_sentinel.agents.evidence_agent.retrieve_evidence", return_value=[]),
            patch("greenlux_sentinel.mcp_servers.postgres_server.write_audit_log"),
        ):
            result = evidence_agent.answer_with_evidence("Is this fund Article 8?", conn=conn, llm=llm)

        assert result["abstained"] is True
        assert result["document_citations"] == []
        assert result["sources_considered"] == 0

    def test_explicit_abstention_from_llm_is_recognized(self):
        conn = MagicMock()
        llm = SequentialFakeLLM(["I don't know -- insufficient evidence."])

        with (
            patch("greenlux_sentinel.agents.evidence_agent.retrieve_evidence", return_value=_PASSAGES),
            patch("greenlux_sentinel.mcp_servers.postgres_server.write_audit_log"),
        ):
            result = evidence_agent.answer_with_evidence("Unrelated question?", conn=conn, llm=llm)

        assert result["abstained"] is True

    def test_retry_recovers_on_second_attempt(self):
        conn = MagicMock()
        llm = SequentialFakeLLM(["Unsupported claim with no citation.", "Supported claim [doc:kiid_1_0]."])

        with (
            patch("greenlux_sentinel.agents.evidence_agent.retrieve_evidence", return_value=_PASSAGES),
            patch("greenlux_sentinel.mcp_servers.postgres_server.write_audit_log"),
        ):
            result = evidence_agent.answer_with_evidence("Is this fund Article 8?", conn=conn, llm=llm)

        assert result["abstained"] is False
        assert result["answer"] == "Supported claim [doc:kiid_1_0]."

    def test_fund_id_resolves_isin_and_scopes_retrieval(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = ("IE00BYVJRR92", "Test Fund", "Equity", 5)
        llm = SequentialFakeLLM(["Cited [doc:kiid_1_0]."])

        with (
            patch("greenlux_sentinel.agents.evidence_agent.retrieve_evidence", return_value=_PASSAGES) as m,
            patch("greenlux_sentinel.mcp_servers.postgres_server.write_audit_log"),
        ):
            evidence_agent.answer_with_evidence("Is this fund Article 8?", fund_id="F1", conn=conn, llm=llm)

        m.assert_called_once_with("Is this fund Article 8?", isin="IE00BYVJRR92", search_client=None)

    def test_fact_cited_answer_is_grounded_not_abstained(self):
        # Reproduces the real live finding (docs/PROGRESS_LOG.md's Phase 9c entry): a claim
        # sourced purely from a precomputed fact (no matching document) must be accepted, not
        # forced into an abstention just because it has no [doc:<id>] to attach.
        conn = MagicMock()
        answer = (
            "The composition anomaly score is 47.49 [fact:composition_anomaly_score], "
            "consistent with the KIID's exclusion criteria [doc:kiid_1_0]."
        )
        llm = SequentialFakeLLM([answer])

        with (
            patch("greenlux_sentinel.agents.evidence_agent.retrieve_evidence", return_value=_PASSAGES),
            patch("greenlux_sentinel.mcp_servers.postgres_server.write_audit_log"),
        ):
            result = evidence_agent.answer_with_evidence(
                "Is the score consistent with the KIID?",
                conn=conn,
                llm=llm,
                precomputed_facts={"composition_anomaly_score": 47.49},
            )

        assert result["abstained"] is False
        assert "[fact:composition_anomaly_score]" in result["answer"]

    def test_fact_citation_referencing_an_unsupplied_key_falls_back_to_abstention(self):
        conn = MagicMock()
        llm = SequentialFakeLLM(["The score is 47.49 [fact:made_up_key].", "The score is 47.49 [fact:made_up_key]."])

        with (
            patch("greenlux_sentinel.agents.evidence_agent.retrieve_evidence", return_value=_PASSAGES),
            patch("greenlux_sentinel.mcp_servers.postgres_server.write_audit_log"),
        ):
            result = evidence_agent.answer_with_evidence(
                "Q?", conn=conn, llm=llm, precomputed_facts={"composition_anomaly_score": 47.49}
            )

        assert result["abstained"] is True

    def test_numeric_facts_are_collected_as_citations(self):
        conn = MagicMock()
        llm = SequentialFakeLLM(["Cited [doc:kiid_1_0]."])

        with (
            patch("greenlux_sentinel.agents.evidence_agent.retrieve_evidence", return_value=_PASSAGES),
            patch("greenlux_sentinel.mcp_servers.postgres_server.write_audit_log"),
        ):
            result = evidence_agent.answer_with_evidence(
                "Q?", conn=conn, llm=llm, precomputed_facts={"name": "Test Fund", "sustainability_rating": 5}
            )

        assert result["numeric_citations"] == [5]


    def test_document_citations_are_persisted(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        llm = SequentialFakeLLM(["Cited [doc:kiid_1_0] and [doc:cssf_faq_0]."])

        with (
            patch("greenlux_sentinel.agents.evidence_agent.retrieve_evidence", return_value=_PASSAGES),
            patch("greenlux_sentinel.mcp_servers.postgres_server.write_audit_log"),
        ):
            evidence_agent.answer_with_evidence("Q?", fund_id="F1", conn=conn, llm=llm, precomputed_facts={"isin": None})

        insert_calls = [c for c in cur.execute.call_args_list if "INSERT INTO document_citations" in c.args[0]]
        assert len(insert_calls) == 2
        assert {c.args[1][1] for c in insert_calls} == {"kiid_1_0", "cssf_faq_0"}
        assert conn.commit.called

    def test_abstained_answer_writes_no_citation_rows(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        llm = SequentialFakeLLM(["I don't know -- insufficient evidence."])

        with (
            patch("greenlux_sentinel.agents.evidence_agent.retrieve_evidence", return_value=_PASSAGES),
            patch("greenlux_sentinel.mcp_servers.postgres_server.write_audit_log"),
        ):
            evidence_agent.answer_with_evidence("Q?", conn=conn, llm=llm)

        insert_calls = [c for c in cur.execute.call_args_list if "INSERT INTO document_citations" in c.args[0]]
        assert insert_calls == []


class TestRetrieveEvidence:
    def test_delegates_to_search_server_hybrid_search(self):
        with patch("greenlux_sentinel.mcp_servers.search_server.hybrid_search", return_value=_PASSAGES) as m:
            result = evidence_agent.retrieve_evidence("question", isin="IE1")

        assert result == _PASSAGES
        m.assert_called_once_with("question", filters={"isin": "IE1"}, client=None)
