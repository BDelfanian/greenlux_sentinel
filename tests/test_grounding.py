"""Unit tests for guardrails/grounding.py: pure text-processing logic, no DB/LLM needed. Mirrors
test_validators.py's style for the sibling guardrail module."""

from __future__ import annotations

from greenlux_sentinel.guardrails import grounding


class TestDocumentGroundedOrAbstained:
    def test_all_citations_point_at_retrieved_docs_passes(self):
        text = "The fund is Article 8 [doc:kiid_1_0]. It has an SRI mandate [doc:kiid_1_1]."
        assert grounding.document_grounded_or_abstained(text, {"kiid_1_0", "kiid_1_1"}) is True

    def test_citation_pointing_at_unretrieved_doc_fails(self):
        text = "The fund is Article 8 [doc:kiid_1_0]."
        assert grounding.document_grounded_or_abstained(text, {"other_doc"}) is False

    def test_no_citations_and_not_abstention_fails(self):
        text = "The fund is Article 8."
        assert grounding.document_grounded_or_abstained(text, {"kiid_1_0"}) is False

    def test_abstention_marker_passes_regardless_of_retrieved_docs(self):
        text = "I don't know -- insufficient evidence."
        assert grounding.document_grounded_or_abstained(text, set()) is True

    def test_abstention_marker_passes_even_with_no_retrieved_docs_and_empty_text_around(self):
        assert grounding.document_grounded_or_abstained("I don't know", set()) is True

    def test_partial_match_of_marker_without_citation_still_fails(self):
        text = "I don't really know how to explain this without a citation."
        assert grounding.document_grounded_or_abstained(text, {"kiid_1_0"}) is False

    def test_fact_citation_pointing_at_a_known_fact_key_passes(self):
        text = "The composition anomaly score is 47.49 [fact:composition_anomaly_score]."
        assert grounding.document_grounded_or_abstained(text, set(), {"composition_anomaly_score"}) is True

    def test_fact_citation_pointing_at_an_unknown_key_fails(self):
        text = "The score is 47.49 [fact:made_up_key]."
        assert grounding.document_grounded_or_abstained(text, set(), {"composition_anomaly_score"}) is False

    def test_mixed_doc_and_fact_citations_both_valid_passes(self):
        text = (
            "The KIID discloses exclusions [doc:kiid_1_0], and the composition anomaly score is "
            "47.49 [fact:composition_anomaly_score]."
        )
        assert (
            grounding.document_grounded_or_abstained(text, {"kiid_1_0"}, {"composition_anomaly_score"})
            is True
        )

    def test_mixed_citations_one_invalid_fails(self):
        text = "Cited [doc:kiid_1_0] and [fact:made_up_key]."
        assert (
            grounding.document_grounded_or_abstained(text, {"kiid_1_0"}, {"composition_anomaly_score"})
            is False
        )

    def test_no_known_fact_keys_argument_defaults_to_no_fact_support(self):
        # Backward compatibility: a caller that never passes known_fact_keys gets the exact prior
        # behavior -- a bare [fact:...] marker is not a valid doc citation and has no known keys.
        text = "The score is 47.49 [fact:composition_anomaly_score]."
        assert grounding.document_grounded_or_abstained(text, {"kiid_1_0"}) is False
