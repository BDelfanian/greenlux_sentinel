"""Report Agent — compiles a final, cited, multilingual (EN/FR/DE) fund report.

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Pulls the greenwashing risk score + explanation (risk_agent) and basic fund facts
    (sql_agent), drafts a report body in English, French, and German (see
    docs/DATA.md#multilingual-layer — this text is agent-generated, not sourced
    pre-translated data), and appends the methodology caveat from
    docs/DATA.md#ground-truth-methodology (hand-translated per language, not LLM-translated —
    too important to let drift).

    Every numeric claim in the draft must trace back to a tool call result from this run
    (docs/RESPONSIBLE_AI.md#principles, guardrail #2) — enforced by
    guardrails.validators.tool_sourced_numbers() before a draft is returned; one retry with a
    stricter prompt is attempted on a guardrail failure before raising.

HUMAN-IN-THE-LOOP GATE (docs/RESPONSIBLE_AI.md#human-in-the-loop-gates):
    draft_report() only ever writes status='draft' rows. publish_report() is the one path that
    flips them to 'published', and only after re-checking every language row is still 'draft'
    (same non-bypassable re-check pattern as query_optimizer_agent.apply_approved() — see that
    module's docstring for why "Phase 2/3/4 has no UI for this" means the human side is a direct
    function call, not a simulated approval). reject_report() is the symmetric rejection path,
    parallel to query_optimizer_agent.reject_proposal() — RESPONSIBLE_AI.md requires gate
    outcomes (approved/rejected) to be audit-logged, not just the approved path.

Persistence: one row per (report_id, language) in the `fund_reports` table (db/schema.sql).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from greenlux_sentinel.agents.risk_agent import CAVEAT as _CAVEAT_EN
from greenlux_sentinel.guardrails import validators

if TYPE_CHECKING:
    import psycopg
    from azure.cosmos import ContainerProxy
    from langchain_core.language_models import BaseChatModel

_CAVEAT_FR = (
    "Ce score est un indicateur de substitution fonde sur les donnees, comparant la notation de "
    "durabilite revendiquee par Morningstar au profil ESG moyen pondere des avoirs reellement "
    "detenus par le fonds. Il ne constitue pas une constatation de non-conformite SFDR ni "
    "aucune autre conclusion reglementaire ou juridique."
)
_CAVEAT_DE = (
    "Dieser Wert ist ein datengestuetzter Naeherungsindikator, der die von Morningstar "
    "angegebene Nachhaltigkeitsbewertung mit dem gewichteten durchschnittlichen ESG-Profil der "
    "tatsaechlich gehaltenen Wertpapiere des Fonds vergleicht. Er stellt keine Feststellung "
    "eines Verstosses gegen die SFDR oder eine sonstige regulatorische oder rechtliche "
    "Einschaetzung dar."
)
_CAVEATS = {"en": _CAVEAT_EN, "fr": _CAVEAT_FR, "de": _CAVEAT_DE}
_LANGUAGE_NAMES = {"en": "English", "fr": "French", "de": "German"}

_DRAFT_SYSTEM_PROMPT = """You are drafting a short {language_name} summary for an institutional \
fund report. Use ONLY the facts and numbers listed below -- do not invent, estimate, round \
differently, or add any number that is not explicitly listed. Two to four sentences, plain text \
only, no markdown, no headers. Do NOT include a compliance disclaimer -- one is appended \
separately.

Facts:
{facts}
"""

_STRICT_SUFFIX = "\n\nSTRICT: only use the exact numbers listed above; do not introduce any other number."


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return None


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


def _open_connections() -> tuple[psycopg.Connection, ContainerProxy]:
    import psycopg
    from azure.cosmos import CosmosClient

    from greenlux_sentinel.config import get_settings

    settings = get_settings()
    conn = psycopg.connect(settings.postgres_dsn)
    client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)
    container = client.get_database_client(settings.cosmos_database).get_container_client(settings.cosmos_container)
    return conn, container


def _fetch_fund_facts(fund_id: str, conn: psycopg.Connection, llm: BaseChatModel | None) -> dict[str, Any]:
    from greenlux_sentinel.agents import sql_agent

    result = sql_agent.ask(
        f"What are the name, category, currency, and total_net_assets of the fund with "
        f"fund_id = '{fund_id}'?",
        conn=conn,
        llm=llm,
    )
    if not result["rows"]:
        raise ValueError(f"fund_id={fund_id} not found via sql_agent")
    return {"sql": result["sql"], "row": result["rows"][0]}


def _draft_body(language: str, facts_text: str, llm: BaseChatModel) -> str:
    prompt = _DRAFT_SYSTEM_PROMPT.format(language_name=_LANGUAGE_NAMES[language], facts=facts_text)
    response = llm.invoke([("system", prompt), ("human", "Draft the summary.")])
    return str(response.content).strip()


def _draft_validated_body(language: str, facts_text: str, trace_tool_results: list[float], llm: BaseChatModel) -> str:
    body = validators.redact_pii(_draft_body(language, facts_text, llm))
    if validators.tool_sourced_numbers(body, trace_tool_results):
        return body

    body = validators.redact_pii(_draft_body(language, facts_text + _STRICT_SUFFIX, llm))
    if not validators.tool_sourced_numbers(body, trace_tool_results):
        raise ValueError(f"generated {language!r} draft failed the tool-sourced-numbers guardrail after retry")
    return body


def draft_report(
    fund_id: str,
    conn: psycopg.Connection | None = None,
    container: ContainerProxy | None = None,
    llm: BaseChatModel | None = None,
) -> dict[str, Any]:
    """Insert draft rows into fund_reports; return {"report_id": str, "en": str, "fr": str,
    "de": str, "citations": list[float]}."""
    from psycopg.types.json import Json

    from greenlux_sentinel.agents import risk_agent
    from greenlux_sentinel.mcp_servers import postgres_server

    llm = llm or _default_llm()

    owns_connections = conn is None and container is None
    if owns_connections:
        conn, container = _open_connections()

    try:
        risk_result = risk_agent.score_fund(fund_id, conn=conn, container=container)
        facts = _fetch_fund_facts(fund_id, conn, llm)

        citations = [risk_result["risk_score"]]
        # risk_result["explanation"] is itself tool-sourced prose (risk_agent.explain(), built
        # from real Cosmos holdings) and gets included in facts_text below -- its numbers (per-
        # holding weights/ESG scores) must be citable too, or the guardrail rejects them as
        # unsourced even though they're genuine tool output.
        citations.extend(validators.extract_numbers(risk_result["explanation"]))
        citations.extend(v for value in facts["row"].values() if (v := _numeric(value)) is not None)

        facts_text = (
            f"- greenwashing risk score (higher means a bigger gap between the claimed rating and "
            f"the holdings): "
            f"{risk_result['risk_score']}\n"
            f"- risk score explanation: {risk_result['explanation']}\n"
            + "\n".join(f"- {k}: {v}" for k, v in facts["row"].items())
        )

        report_id = str(uuid.uuid4())
        bodies = {language: _draft_validated_body(language, facts_text, citations, llm) for language in _CAVEATS}

        with conn.cursor() as cur:
            for language, body in bodies.items():
                cur.execute(
                    "INSERT INTO fund_reports (report_id, fund_id, language, content, citations, status) "
                    "VALUES (%s, %s, %s, %s, %s, 'draft')",
                    (report_id, fund_id, language, f"{body}\n\n{_CAVEATS[language]}", Json(citations)),
                )
        postgres_server.write_audit_log(
            conn=conn,
            agent_name="report_agent",
            tool_name="draft_report",
            input_summary=f"fund_id={fund_id}",
            output_summary=f"report_id={report_id}, 3 draft rows",
        )
        conn.commit()
    finally:
        if owns_connections:
            conn.close()

    return {"report_id": report_id, **bodies, "citations": citations}


def _report_status_counts(report_id: str, conn: psycopg.Connection) -> tuple[int, int]:
    """Return (total rows, rows still in 'draft' status) for report_id."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*), COUNT(*) FILTER (WHERE status = 'draft') FROM fund_reports WHERE report_id = %s", (report_id,))
        total, draft = cur.fetchone()
    conn.rollback()
    return total, draft


def _finalize_report(report_id: str, actor: str, new_status: str, conn: psycopg.Connection | None) -> None:
    from greenlux_sentinel.mcp_servers import postgres_server

    owns_conn = conn is None
    if owns_conn:
        import psycopg

        from greenlux_sentinel.config import get_settings

        conn = psycopg.connect(get_settings().postgres_dsn)

    try:
        total, draft = _report_status_counts(report_id, conn)
        if total == 0:
            raise ValueError(f"no such report: {report_id}")
        if draft != total:
            raise ValueError(f"report {report_id} is not fully in draft status")

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE fund_reports SET status = %s, approved_by = %s, approved_at = now() WHERE report_id = %s",
                (new_status, actor, report_id),
            )
        postgres_server.write_audit_log(
            conn=conn,
            agent_name="report_agent",
            tool_name="publish_report" if new_status == "published" else "reject_report",
            input_summary=f"report_id={report_id}",
            output_summary=f"status={new_status}, actor={actor}",
            required_approval=False,  # this row logs the outcome of an already-made human decision
        )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


def publish_report(report_id: str, approved_by: str, conn: psycopg.Connection | None = None) -> None:
    """Set fund_reports.status='published' for all languages of report_id, after human
    approval. Re-checks every row is still 'draft' first -- a report can't be published twice
    or after being rejected."""
    _finalize_report(report_id, approved_by, "published", conn)


def reject_report(report_id: str, rejected_by: str, conn: psycopg.Connection | None = None) -> None:
    """Record a human rejection of a draft report. Does not expose it as final output."""
    _finalize_report(report_id, rejected_by, "rejected", conn)
