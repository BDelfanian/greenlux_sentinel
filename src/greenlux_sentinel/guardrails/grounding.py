"""Document-grounding guardrail (docs/RESPONSIBLE_AI.md#principles, Principle 5) -- kept in its
own module rather than added to validators.py, matching that module's own stated philosophy of
"kept separate so each is independently testable." Gates the Evidence Agent before its answer is
shown, the same way validators.tool_sourced_numbers() gates the Report Agent.

This is a citation-validity check, not true NLI/entailment faithfulness checking -- it verifies
every citation marker in a draft answer points at a document the retrieval step actually
returned, not that the answer's claims are semantically supported by that document's text. An
honestly-scoped substitute, consistent with how this project already frames the risk score as a
data-driven proxy rather than a compliance finding (docs/DATA.md#ground-truth-methodology).
"""

from __future__ import annotations

import re

_CITATION_RE = re.compile(r"\[doc:([^\]]+)\]")

DEFAULT_ABSTENTION_MARKER = "I don't know"


def document_grounded_or_abstained(
    draft_text: str, retrieved_doc_ids: set[str], abstention_marker: str = DEFAULT_ABSTENTION_MARKER
) -> bool:
    """Return True if draft_text is the abstention marker (or starts with it), or if every
    [doc:<id>] citation marker it contains points at a real, retrieved document id -- and it
    contains at least one such marker. A draft with zero citation markers and no abstention
    marker fails: an answer must be either grounded or an explicit "don't know," never bare
    assertion."""
    stripped = draft_text.strip()
    if stripped.startswith(abstention_marker):
        return True

    cited_ids = _CITATION_RE.findall(draft_text)
    if not cited_ids:
        return False
    return all(doc_id in retrieved_doc_ids for doc_id in cited_ids)
