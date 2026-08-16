"""NL2SQL Agent — translates an analyst's natural-language question into SQL.

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Generates SQL against the Tier 1 Postgres fund schema, executes it read-only, and returns
    tabular results plus the SQL used (so the report/dashboard agents can cite it and guardrails
    can verify numeric claims trace back to this call).

Read-only — no human-in-the-loop gate. Must never execute DDL/DML; enforced two ways: (1) the
generated text is validated to be a single SELECT statement with no forbidden keywords before
it ever reaches the database, and (2) the connection itself is put into Postgres's native
read-only transaction mode for the query, so even a validation bypass can't write. The actual
execution and audit-log write go through `mcp_servers.postgres_server`'s `run_readonly_query`/
`write_audit_log` (Phase 3, per ARCHITECTURE.md) — validation itself stays here, unchanged.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import psycopg
    from langchain_core.language_models import BaseChatModel

# Kept in sync by hand with db/schema.sql -- only the tables an analyst should be able to query.
# audit_log is deliberately excluded (internal bookkeeping, not an analyst-facing table).
_SCHEMA_DDL = """
CREATE TABLE funds (
    fund_id TEXT PRIMARY KEY, isin TEXT, name TEXT NOT NULL, fund_type TEXT NOT NULL,
    management_company TEXT, domicile_country TEXT, category TEXT, currency TEXT,
    total_net_assets NUMERIC, ongoing_cost NUMERIC, sustainability_rating NUMERIC,
    sustainability_score NUMERIC, environmental_score NUMERIC, social_score NUMERIC,
    governance_score NUMERIC, return_ytd NUMERIC, return_3y NUMERIC, return_5y NUMERIC,
    return_10y NUMERIC, quarters_up INTEGER, quarters_down INTEGER, ingested_at TIMESTAMPTZ
);
-- sustainability_rating: Morningstar Sustainability Rating, 1-5 globes (claimed profile).
-- fund_type is 'mutual_fund' or 'etf'.
-- domicile_country is a 2-letter ISO country code (e.g. 'LU', 'IE', 'GB'), not a country name.

CREATE TABLE fund_risk_scores (
    fund_id TEXT REFERENCES funds(fund_id), risk_score NUMERIC NOT NULL,
    holdings_implied_esg NUMERIC NOT NULL, explanation TEXT, computed_at TIMESTAMPTZ
);
-- Greenwashing Risk Score: 0-100, higher = bigger gap between claimed rating and real holdings'
-- ESG profile. Only populated for a small set of funds with verified real holdings data --
-- most rows in `funds` will have no matching row here.

CREATE TABLE fund_sustainability_anomaly_scores (
    fund_id TEXT REFERENCES funds(fund_id), predicted_rating_bucket TEXT NOT NULL,
    actual_rating_bucket TEXT NOT NULL, composition_anomaly_score NUMERIC NOT NULL,
    composition_anomaly_tier TEXT NOT NULL, model_version TEXT NOT NULL, computed_at TIMESTAMPTZ
);
-- A different, ML-based signal from fund_risk_scores above -- NOT the same thing and the two
-- need not agree. composition_anomaly_score (0-100, higher = more atypical) compares a fund's
-- claimed sustainability_rating against what a RandomForestClassifier expects from its OBJECTIVE
-- portfolio composition (sector/asset-class/credit-quality/controversial-business-involvement
-- mix), learned from the broad ~41k-fund population -- not from real security-level holdings like
-- fund_risk_scores. predicted_rating_bucket/actual_rating_bucket are 'Low'|'Medium'|'High'.
-- composition_anomaly_tier is the same 'Low'|'Medium'|'High' vocabulary but for the anomaly score
-- itself, not the rating.

CREATE TABLE lu_legal_entities (
    lei TEXT PRIMARY KEY, legal_name TEXT NOT NULL, entity_legal_form TEXT,
    entity_status TEXT, country TEXT, fetched_at TIMESTAMPTZ
);

CREATE TABLE fund_reports (
    report_id UUID, fund_id TEXT REFERENCES funds(fund_id), language TEXT NOT NULL,
    content TEXT NOT NULL, citations JSONB, status TEXT NOT NULL, created_at TIMESTAMPTZ,
    approved_by TEXT, approved_at TIMESTAMPTZ
);
-- status: 'draft' | 'approved' | 'published' | 'rejected'. language: 'en' | 'fr' | 'de'.
""".strip()

_SYSTEM_PROMPT = f"""You are a PostgreSQL expert. Given a question, write ONE read-only SQL query \
that answers it, using only the tables and columns below. Output ONLY the raw SQL statement -- \
no markdown code fences, no explanation, no trailing semicolon.

Rules:
- Exactly one SELECT statement. Never INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/etc.
- Only reference the tables/columns defined below.
- If the question cannot be answered with these tables, return exactly: NO_QUERY

Schema:
{_SCHEMA_DDL}
"""

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|MERGE|COPY|CALL|VACUUM)\b",
    re.IGNORECASE,
)
_DEFAULT_ROW_LIMIT = 200


def _extract_sql(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        text = match.group(1)
    return text.strip().rstrip(";").strip()


def validate(sql: str) -> None:
    """Raise ValueError unless sql is a single, plain SELECT statement."""
    if not sql:
        raise ValueError("model returned an empty query")
    if ";" in sql:
        raise ValueError("multiple statements are not allowed")
    if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        raise ValueError(f"only SELECT statements are allowed, got: {sql[:80]!r}")
    if _FORBIDDEN.search(sql):
        raise ValueError(f"query contains a forbidden keyword: {sql[:80]!r}")


def _with_row_limit(sql: str, limit: int = _DEFAULT_ROW_LIMIT) -> str:
    if re.search(r"\bLIMIT\s+\d+\s*$", sql, re.IGNORECASE):
        return sql
    return f"{sql} LIMIT {limit}"


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


def generate_sql(question: str, llm: BaseChatModel | None = None) -> str:
    """Question -> validated SQL text. Split out from ask() so validation/extraction can be
    tested against a fake llm without a live DB."""
    llm = llm or _default_llm()
    response = llm.invoke([("system", _SYSTEM_PROMPT), ("human", question)])
    sql = _extract_sql(response.content)
    if sql.upper() == "NO_QUERY":
        raise ValueError("question cannot be answered from the available schema")
    validate(sql)
    return sql


def ask(question: str, conn: psycopg.Connection | None = None, llm: BaseChatModel | None = None) -> dict[str, Any]:
    """Return {"sql": str, "rows": list[dict]}."""
    from greenlux_sentinel.mcp_servers import postgres_server

    sql = generate_sql(question, llm=llm)
    limited_sql = _with_row_limit(sql)

    owns_conn = conn is None
    if owns_conn:
        import psycopg

        from greenlux_sentinel.config import get_settings

        conn = psycopg.connect(get_settings().postgres_dsn)

    try:
        rows = postgres_server.run_readonly_query(limited_sql, conn=conn)

        postgres_server.write_audit_log(
            conn=conn,
            agent_name="sql_agent",
            tool_name="ask",
            input_summary=question,
            output_summary=f"sql={sql!r}, {len(rows)} rows",
        )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()

    return {"sql": sql, "rows": rows}
