"""Dashboard Agent — turns an analyst question into a live Power BI update.

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Composes a DAX/Power BI query from the analyst's request and calls the Power BI MCP
    server (run_dax_query) so the dashboard reflects the question just asked — this is the
    "dynamic, not static" requirement: no fixed pre-built report.

Read-only against the dataset (a query, not a schema/report-definition change) — no
human-in-the-loop gate.

Template selection mirrors sql_agent.py's generate_sql()/ask() split: an LLM classifies the
question into one of bi/dax_templates.py's two templates (+ any parameter), rather than
free-generating DAX text — keeps the query surface small and auditable, same reasoning as
sql_agent's schema-constrained SQL generation.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from greenlux_sentinel.bi import dax_templates

if TYPE_CHECKING:
    import httpx
    import psycopg
    from langchain_core.language_models import BaseChatModel

_SYSTEM_PROMPT = """Classify the analyst's dashboard question into exactly one DAX template and \
extract any parameter it needs. Reply with ONLY a JSON object, nothing else -- no markdown, no \
explanation.

Templates:
- risk_by_category: average greenwashing risk score grouped by fund category. No parameters.
- top_n_high_risk: the N funds with the highest greenwashing risk score. Optional "n" (integer).

Reply format examples:
{"template": "risk_by_category"}
{"template": "top_n_high_risk", "n": 10}
"""

_DEFAULT_TOP_N = 10
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


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


def _parse_template_choice(text: str) -> dict[str, Any]:
    match = _JSON_RE.search(text.strip())
    if not match:
        raise ValueError(f"model did not return a JSON template choice: {text[:80]!r}")
    return json.loads(match.group(0))


def build_dax(question: str, llm: BaseChatModel | None = None) -> str:
    """Question -> a filled-in DAX template. Split out from update_dashboard() so template
    selection can be tested against a fake llm without a live Power BI dataset."""
    llm = llm or _default_llm()
    response = llm.invoke([("system", _SYSTEM_PROMPT), ("human", question)])
    choice = _parse_template_choice(str(response.content))

    template = choice.get("template")
    if template == "risk_by_category":
        return dax_templates.RISK_SCORE_BY_CATEGORY
    if template == "top_n_high_risk":
        n = int(choice.get("n") or _DEFAULT_TOP_N)
        return dax_templates.TOP_N_HIGH_RISK_FUNDS.format(n=n)
    raise ValueError(f"unrecognized dashboard template: {template!r}")


def update_dashboard(
    question: str,
    conn: psycopg.Connection | None = None,
    llm: BaseChatModel | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Return {"dax": str, "dataset_id": str, "rows": list[dict]}."""
    from greenlux_sentinel.config import get_settings
    from greenlux_sentinel.mcp_servers import postgres_server, powerbi_server

    dax = build_dax(question, llm=llm)
    dataset_id = get_settings().powerbi_dataset_id
    rows = powerbi_server.run_dax_query(dataset_id, dax, client=client)

    owns_conn = conn is None
    if owns_conn:
        import psycopg

        conn = psycopg.connect(get_settings().postgres_dsn)

    try:
        postgres_server.write_audit_log(
            conn=conn,
            agent_name="dashboard_agent",
            tool_name="update_dashboard",
            input_summary=question,
            output_summary=f"dax={dax!r}, {len(rows)} rows",
        )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()

    return {"dax": dax, "dataset_id": dataset_id, "rows": rows}
