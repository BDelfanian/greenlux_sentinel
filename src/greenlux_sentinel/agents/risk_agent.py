"""Greenwashing-Risk Agent — computes and explains the per-fund Greenwashing Risk Score.

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Reads Tier 2 data (ETF holdings + company ESG ratings from Cosmos DB) and the fund's
    own Morningstar Sustainability Rating (Postgres), computes the consistency gap, and
    produces an explanation of which holdings drive the score.

    IMPORTANT: this score is a data-driven proxy indicator, not a determination of legal
    SFDR non-compliance. See docs/DATA.md#ground-truth-methodology — do not present it as
    a compliance finding anywhere downstream (dashboard, report).

Real Tier 2 coverage is the five issuer-verified UCITS ETFs from
docs/DATA.md#tier-2-verified-holdings-phase-2-correction (source="issuer_verified" documents in
Cosmos, joined back to Tier 1 by ISIN) — NOT the original Top 100 Kaggle set, which has no fund
in Tier 1 and can't feed this formula (see that module, load_esg_cosmos.py). One of the five
(IE00B5BMR087, a plain S&P 500 tracker) has no sustainability claim of its own and is excluded
from scoring — see score_all_verified().

Read-only except for writing its own output table (fund_risk_scores) — no human-in-the-loop gate.

Phase 3: the Cosmos lookup (_fetch_verified_doc) and the audit-log write (persist) now go
through `mcp_servers.cosmos_server`/`mcp_servers.postgres_server` respectively, per
ARCHITECTURE.md's documented tool surface. The isin/claims Postgres reads (_fetch_claims, the
fund_id->isin lookup in score_fund) and the fund_risk_scores INSERT stay direct psycopg calls —
they're this agent's own hardcoded, non-analyst-facing reads/writes, not the dynamic
LLM-generated SQL that run_readonly_query is for (see mcp_servers/postgres_server.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import psycopg
    from azure.cosmos import ContainerProxy

# Population bounds observed in data/raw/public_company_esg_ratings.csv (722 companies) — used to
# rescale the raw ~600-1536 total_esg_score onto a comparable 0-100 "quality" scale. Not a
# theoretical min/max; re-derive if the ESG ratings source dataset changes.
_ESG_SCORE_MIN = 600.0
_ESG_SCORE_MAX = 1536.0

CAVEAT = (
    "This score is a data-driven proxy comparing Morningstar's claimed Sustainability Rating "
    "against the weighted-average ESG profile of the fund's real disclosed holdings. It is not "
    "a determination of SFDR non-compliance or any other regulatory/legal finding."
)

# ISINs with a real Tier 1 sustainability claim to compare against (excludes the CSPX control,
# which has none) — see docs/DATA.md#tier-2-verified-holdings-phase-2-correction.
SCORABLE_ISINS = ["IE00BYVJRR92", "IE00BFNM3G45", "IE00BDZZTM54", "IE00BKVL7331"]


def _rescale_globes_to_quality(rating: float) -> float:
    """1-5 Morningstar globes -> 0-100 "claimed quality" (higher = more sustainable claim)."""
    return (rating - 1) / 4 * 100


def _rescale_holdings_score_to_quality(raw_score: float) -> float:
    """Raw ~600-1536 weighted company-ESG score -> 0-100 (higher = better), clipped to the
    observed population range in public_company_esg_ratings.csv."""
    clipped = min(max(raw_score, _ESG_SCORE_MIN), _ESG_SCORE_MAX)
    return (clipped - _ESG_SCORE_MIN) / (_ESG_SCORE_MAX - _ESG_SCORE_MIN) * 100


def compute_gap(claimed_rating: float, holdings_implied_score: float) -> float:
    """Core formula: risk_score(fund) = f(claimed_sustainability_rating, holdings_implied_esg).

    Positive => fund claims better sustainability than its real holdings imply (greenwashing
    risk). Clamped to [0, 100]: a fund whose holdings imply better ESG than claimed scores 0,
    not negative — a positive surprise isn't a risk.
    """
    claimed_quality = _rescale_globes_to_quality(claimed_rating)
    holdings_quality = _rescale_holdings_score_to_quality(holdings_implied_score)
    return round(max(0.0, claimed_quality - holdings_quality), 2)


def explain(holdings: list[dict[str, Any]], top_n: int = 5) -> str:
    """Plain-language explanation of which real holdings drive the score — the biggest-weight
    positions with a below-population-median ESG score."""
    scored = [h for h in holdings if h.get("esg") and h["esg"].get("total_esg_score") is not None]
    if not scored:
        return "No matched holdings had an ESG score; explanation unavailable."

    scores = sorted(h["esg"]["total_esg_score"] for h in scored)
    median_score = scores[len(scores) // 2]
    laggards = sorted(
        (h for h in scored if h["esg"]["total_esg_score"] < median_score),
        key=lambda h: h["weight_pct"],
        reverse=True,
    )[:top_n]
    if not laggards:
        return "No below-median-ESG holdings found among the matched, weighted constituents."

    parts = [
        f"{h['ticker']} ({h['weight_pct']:.2f}% weight, ESG score {h['esg']['total_esg_score']})"
        for h in laggards
    ]
    return "Below-median ESG holdings driving this score: " + "; ".join(parts) + "."


def _fetch_verified_doc(isin: str, container: ContainerProxy) -> dict[str, Any] | None:
    from greenlux_sentinel.mcp_servers import cosmos_server

    docs = cosmos_server.query_esg_documents({"isin": isin, "source": "issuer_verified"}, container=container)
    return docs[0] if docs else None


def _fetch_claims(isin: str, conn: psycopg.Connection) -> list[tuple[str, float]]:
    """All Tier 1 fund_ids (share classes) sharing this ISIN, with their sustainability_rating."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT fund_id, sustainability_rating FROM funds "
            "WHERE isin = %s AND sustainability_rating IS NOT NULL",
            (isin,),
        )
        return cur.fetchall()


def score_by_isin(isin: str, conn: psycopg.Connection, container: ContainerProxy) -> list[dict[str, Any]]:
    """Compute (not yet persisted) risk results for every Tier 1 fund_id sharing this ISIN."""
    doc = _fetch_verified_doc(isin, container)
    if doc is None:
        raise ValueError(f"no verified Tier 2 holdings document for isin={isin}")
    if doc.get("holdings_implied_esg_score") is None:
        raise ValueError(f"isin={isin} has no matched holdings to compute an implied ESG score")

    claims = _fetch_claims(isin, conn)
    if not claims:
        raise ValueError(f"isin={isin} has no Tier 1 sustainability rating — no claim to compare against")

    explanation = explain(doc["holdings"])
    holdings_implied_esg = doc["holdings_implied_esg_score"]
    return [
        {
            "fund_id": fund_id,
            "isin": isin,
            "risk_score": compute_gap(float(rating), holdings_implied_esg),
            "holdings_implied_esg": holdings_implied_esg,
            "explanation": explanation,
            "caveat": CAVEAT,
        }
        for fund_id, rating in claims
    ]


def persist(results: list[dict[str, Any]], conn: psycopg.Connection) -> None:
    """Write results to fund_risk_scores and audit-log the write. Caller controls commit.

    The fund_risk_scores INSERT stays a direct psycopg call -- it's this agent's own output
    write, not part of postgres_server's documented tool surface (run_readonly_query/
    explain_query/propose_index/write_audit_log), and there's no generic "write" MCP tool by
    design (see mcp_servers/postgres_server.py's docstring on why apply_approved()'s DDL stays
    off the tool surface too). The audit-log write does go through the MCP tool below, since
    write_audit_log is one of the four documented tools.
    """
    from greenlux_sentinel.mcp_servers import postgres_server

    with conn.cursor() as cur:
        for r in results:
            cur.execute(
                "INSERT INTO fund_risk_scores (fund_id, risk_score, holdings_implied_esg, explanation) "
                "VALUES (%s, %s, %s, %s)",
                (r["fund_id"], r["risk_score"], r["holdings_implied_esg"], r["explanation"]),
            )
    postgres_server.write_audit_log(
        conn=conn,
        agent_name="risk_agent",
        tool_name="score_by_isin",
        input_summary=f"isin={results[0]['isin']}" if results else "",
        output_summary=f"wrote {len(results)} fund_risk_scores rows",
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


def score_fund(
    fund_id: str, conn: psycopg.Connection | None = None, container: ContainerProxy | None = None
) -> dict[str, Any]:
    """Public entry point per ARCHITECTURE.md — compute and persist the risk score for one
    Tier 1 fund_id. Raises if this fund_id's ISIN isn't one of the five verified funds in
    docs/DATA.md#tier-2-verified-holdings-phase-2-correction."""
    owns_connections = conn is None and container is None
    if owns_connections:
        conn, container = _open_connections()

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT isin FROM funds WHERE fund_id = %s", (fund_id,))
            row = cur.fetchone()
        if row is None or row[0] is None:
            raise ValueError(f"fund_id={fund_id} not found or has no ISIN")

        results = score_by_isin(row[0], conn, container)
        result = next(r for r in results if r["fund_id"] == fund_id)
        persist(results, conn)
        conn.commit()
    finally:
        if owns_connections:
            conn.close()

    return {k: v for k, v in result.items() if k in ("risk_score", "explanation", "caveat")}


def score_all_verified(
    conn: psycopg.Connection | None = None, container: ContainerProxy | None = None
) -> list[dict[str, Any]]:
    """Compute and persist risk scores for every Tier 1 fund_id backed by one of the five
    verified Tier 2 funds that also carries a real Tier 1 claim (SCORABLE_ISINS — excludes the
    no-claim CSPX control)."""
    owns_connections = conn is None and container is None
    if owns_connections:
        conn, container = _open_connections()

    try:
        all_results = []
        for isin in SCORABLE_ISINS:
            results = score_by_isin(isin, conn, container)
            persist(results, conn)
            all_results.extend(results)
        conn.commit()
    finally:
        if owns_connections:
            conn.close()

    return all_results
