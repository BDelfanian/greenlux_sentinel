"""Evidence Agent — answers a question by combining structured fund facts (Tier 1 Postgres) with
retrieved document evidence (Phase 8's document corpus, via mcp_servers/search_server.py),
citing every claim back to a real retrieved passage or explicitly saying "I don't know" when
nothing retrieved actually supports an answer.

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Given a question and an optional fund_id, looks up that fund's Tier 1 facts (name, category,
    claimed sustainability rating — same funds table read as report_agent._fetch_fund_facts, or
    whatever a multi-hop caller passed as precomputed_facts, e.g. a risk_score/
    composition_anomaly_score from the risk/ml_risk hops — see agents/supervisor.py), retrieves
    matching document passages (that fund's own KIID/prospectus plus the general SFDR/CSSF
    regulatory corpus — see search_server.hybrid_search's OR-shaped filter), and drafts a cited
    answer: a [doc:<id>] marker for a document-sourced claim, a [fact:<key>] marker (Phase 9c) for
    a facts-sourced claim — two distinct forms, not one conflated marker, so a numeric signal like
    composition_anomaly_score never has to masquerade as document-grounded to pass the guardrail.
    Enforced by guardrails/grounding.py's document_grounded_or_abstained()
    (docs/RESPONSIBLE_AI.md#principles, Principle 5) before the answer is returned.

HUMAN-IN-THE-LOOP GATE: none directly — read-only, same autonomy class as sql_agent/risk_agent/
dashboard_agent (docs/RESPONSIBLE_AI.md's "gating everything would make the 'agentic' framing
meaningless"). If an evidence-grounded answer is ever incorporated into a *published* report,
that report still passes through report_agent's existing publish gate — this agent doesn't need
one of its own.

Deliberate divergence from report_agent's guardrail-retry pattern: report_agent raises after one
failed retry (an unsourced number in a report draft is an error to fix). Here, a repeated failure
to produce a fully cited answer falls back to an explicit abstention response instead of raising
— abstaining is this agent's own safe, correct outcome, not a failure state.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from greenlux_sentinel.guardrails import grounding, validators

if TYPE_CHECKING:
    import psycopg
    from azure.search.documents import SearchClient
    from langchain_core.language_models import BaseChatModel

_DRAFT_SYSTEM_PROMPT = """You are answering an analyst's question using ONLY the facts and \
retrieved document passages listed below. For every claim, cite where it came from immediately \
after the claim: a [doc:<id>] marker (matching a passage's exact id) for a claim sourced from a \
retrieved passage, or a [fact:<key>] marker (matching a fact's exact key, e.g. \
[fact:composition_anomaly_score]) for a claim sourced from the Facts list -- a fact is already \
tool-sourced, it does not need a document to cite, but it still needs its own [fact:<key>] \
marker, not a bare number. If the facts and passages below do not contain enough information to \
answer, reply with EXACTLY: I don't know -- insufficient evidence. Do not guess or use outside \
knowledge. Plain text only, no markdown, no headers.

Facts:
{facts}

Retrieved passages:
{passages}
"""

_STRICT_SUFFIX = (
    "\n\nSTRICT: every claim must carry a [doc:<id>] marker citing one of the exact passage ids "
    "listed above, or a [fact:<key>] marker citing one of the exact fact keys listed above; if "
    "you cannot support the answer this way, reply with EXACTLY: I don't know -- insufficient "
    "evidence."
)

_FALLBACK_ABSTENTION = f"{grounding.DEFAULT_ABSTENTION_MARKER} -- unable to produce a fully cited answer."

_CITATION_RE = re.compile(r"\[doc:([^\]]+)\]")


def _default_llm() -> BaseChatModel:
    from langchain_openai import AzureChatOpenAI

    from greenlux_sentinel.config import get_settings

    settings = get_settings()
    return AzureChatOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        azure_deployment=settings.azure_openai_deployment,
        api_version=settings.azure_openai_api_version,
    )


def _fetch_fund_facts(fund_id: str, conn: psycopg.Connection) -> tuple[str | None, dict[str, Any]]:
    """Returns (isin, facts) for fund_id, or (None, {}) if fund_id isn't found."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT isin, name, category, sustainability_rating FROM funds WHERE fund_id = %s",
            (fund_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None, {}
    isin, name, category, rating = row
    facts = {"name": name, "category": category}
    if rating is not None:
        facts["sustainability_rating"] = rating
    return isin, facts


def retrieve_evidence(
    question: str, isin: str | None = None, search_client: SearchClient | None = None
) -> list[dict[str, Any]]:
    """Plain retrieval-only helper — usable standalone or as a future supervisor multi-hop node.
    filters on isin when given (matches that fund's own documents plus the general regulatory
    corpus — see search_server.hybrid_search); an unscoped question searches everything."""
    from greenlux_sentinel.mcp_servers import search_server

    filters = {"isin": isin} if isin else None
    return search_server.hybrid_search(question, filters=filters, client=search_client)


def _draft_answer(question: str, facts_text: str, passages_text: str, llm: BaseChatModel) -> str:
    prompt = _DRAFT_SYSTEM_PROMPT.format(facts=facts_text, passages=passages_text)
    response = llm.invoke([("system", prompt), ("human", question)])
    return str(response.content).strip()


def _draft_validated_answer(
    question: str,
    facts_text: str,
    passages_text: str,
    retrieved_doc_ids: set[str],
    known_fact_keys: set[str],
    llm: BaseChatModel,
) -> str:
    answer = validators.redact_pii(_draft_answer(question, facts_text, passages_text, llm))
    if grounding.document_grounded_or_abstained(answer, retrieved_doc_ids, known_fact_keys):
        return answer

    answer = validators.redact_pii(_draft_answer(question, facts_text, passages_text + _STRICT_SUFFIX, llm))
    if grounding.document_grounded_or_abstained(answer, retrieved_doc_ids, known_fact_keys):
        return answer

    return _FALLBACK_ABSTENTION


def answer_with_evidence(
    question: str,
    fund_id: str | None = None,
    conn: psycopg.Connection | None = None,
    search_client: SearchClient | None = None,
    llm: BaseChatModel | None = None,
    precomputed_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Returns {"answer": str, "document_citations": list[dict], "numeric_citations": list[float],
    "abstained": bool, "sources_considered": int}."""
    from greenlux_sentinel.mcp_servers import postgres_server

    llm = llm or _default_llm()
    owns_conn = conn is None
    if owns_conn:
        import psycopg

        from greenlux_sentinel.config import get_settings

        conn = psycopg.connect(get_settings().postgres_dsn)

    try:
        isin: str | None = None
        facts: dict[str, Any] = {}
        if precomputed_facts is not None:
            facts = precomputed_facts
            isin = facts.pop("isin", None)
        elif fund_id:
            isin, facts = _fetch_fund_facts(fund_id, conn)

        numeric_citations = [v for v in facts.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]

        passages = retrieve_evidence(question, isin=isin, search_client=search_client)
        retrieved_doc_ids = {p["id"] for p in passages}

        facts_text = "\n".join(f"- {k}: {v}" for k, v in facts.items()) or "(no structured facts available)"
        passages_text = (
            "\n".join(f"[doc:{p['id']}] ({p['doc_type']}): {p['content'][:600]}" for p in passages)
            or "(no documents retrieved)"
        )

        answer = _draft_validated_answer(question, facts_text, passages_text, retrieved_doc_ids, set(facts), llm)
        abstained = answer.strip().lower().startswith(grounding.DEFAULT_ABSTENTION_MARKER.lower())
        cited_ids = set(_CITATION_RE.findall(answer))
        document_citations = [p for p in passages if p["id"] in cited_ids]

        # Durable citation trail (RESPONSIBLE_AI.md principle 1: "every agent action is logged")
        # -- report_id stays NULL here; linking into a *published* report is deferred (see
        # db/schema.sql's document_citations comment and docs/PROGRESS_LOG.md's Phase 8b entry).
        with conn.cursor() as cur:
            for citation in document_citations:
                cur.execute(
                    "INSERT INTO document_citations "
                    "(fund_id, doc_id, doc_type, source_url, passage_excerpt, relevance_score) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        fund_id,
                        citation["id"],
                        citation["doc_type"],
                        citation.get("source_url"),
                        citation["content"][:600],
                        citation.get("@search.score"),
                    ),
                )

        postgres_server.write_audit_log(
            conn=conn,
            agent_name="evidence_agent",
            tool_name="answer_with_evidence",
            input_summary=question,
            output_summary=f"abstained={abstained}, {len(document_citations)} doc citation(s), {len(passages)} retrieved",
        )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()

    return {
        "answer": answer,
        "document_citations": document_citations,
        "numeric_citations": numeric_citations,
        "abstained": abstained,
        "sources_considered": len(passages),
    }
