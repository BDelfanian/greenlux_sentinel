"""Document-grounding guardrail (docs/RESPONSIBLE_AI.md#principles, Principle 5) -- kept in its
own module rather than added to validators.py, matching that module's own stated philosophy of
"kept separate so each is independently testable." Gates the Evidence Agent before its answer is
shown, the same way validators.tool_sourced_numbers() gates the Report Agent.

This is a citation-validity check, not true NLI/entailment faithfulness checking -- it verifies
every citation marker in a draft answer points at a document the retrieval step actually
returned (or, since Phase 9c, a precomputed fact the caller actually supplied), not that the
answer's claims are semantically supported by that document's text. An honestly-scoped
substitute, consistent with how this project already frames the risk score as a data-driven
proxy rather than a compliance finding (docs/DATA.md#ground-truth-methodology).

Phase 9c: two distinct citation forms, not one conflated marker -- `[doc:<id>]` for a claim
sourced from a retrieved document passage, `[fact:<key>]` for a claim sourced from the
`precomputed_facts`/Tier-1-facts dict `evidence_agent.answer_with_evidence()` already builds (a
quantitative signal like `composition_anomaly_score` has no document id to cite, so forcing it
through `[doc:<id>]` made the model abstain on questions it actually had the facts to answer --
confirmed live, see docs/PROGRESS_LOG.md's Phase 9c entry). Keeping the two forms separate (rather
than accepting a bare fact name with no prefix) matters for the same reason CLAUDE.md decision #8
keeps `risk_score`/`composition_anomaly_score` under distinct keys: a reader of the final answer
should be able to tell a document-grounded claim from a tool-sourced-number claim at a glance.
"""

from __future__ import annotations

import re

_CITATION_RE = re.compile(r"\[doc:([^\]]+)\]")
_FACT_CITATION_RE = re.compile(r"\[fact:([^\]]+)\]")

DEFAULT_ABSTENTION_MARKER = "I don't know"


def document_grounded_or_abstained(
    draft_text: str,
    retrieved_doc_ids: set[str],
    known_fact_keys: set[str] | None = None,
    abstention_marker: str = DEFAULT_ABSTENTION_MARKER,
) -> bool:
    """Return True if draft_text is the abstention marker (or starts with it), or if every
    [doc:<id>] citation marker points at a real, retrieved document id AND every [fact:<key>]
    marker points at a real, supplied fact key -- and it contains at least one such marker
    (either form, or a mix of both). A draft with zero citation markers and no abstention marker
    fails: an answer must be either grounded or an explicit "don't know," never bare assertion.

    `known_fact_keys` defaults to none (no fact-citation support) -- existing callers that only
    ever pass `retrieved_doc_ids` keep their exact prior behavior unchanged."""
    stripped = draft_text.strip()
    if stripped.startswith(abstention_marker):
        return True

    known_fact_keys = known_fact_keys or set()
    cited_doc_ids = _CITATION_RE.findall(draft_text)
    cited_fact_keys = _FACT_CITATION_RE.findall(draft_text)
    if not cited_doc_ids and not cited_fact_keys:
        return False
    return all(doc_id in retrieved_doc_ids for doc_id in cited_doc_ids) and all(
        key in known_fact_keys for key in cited_fact_keys
    )
