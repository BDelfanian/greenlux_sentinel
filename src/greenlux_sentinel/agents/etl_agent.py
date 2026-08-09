"""ETL Agent — ingests Kaggle sources + GLEIF API, resolves schema drift, logs lineage.

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Loads the Morningstar European Funds dataset into Postgres (Tier 1) and the
    ETF-holdings/company-ESG joins into Cosmos DB (Tier 2 — both the descriptive Top-100 set and
    the risk-model-linked verified-holdings set, see docs/DATA.md#two-tier-data-architecture).
    Cross-checks LU-domiciled funds' management companies against the live GLEIF legal-entity
    register.

No human-in-the-loop gate — ingestion is additive/read-source, not a destructive write against
production data.

This module is deliberately thin: the actual transform/load logic already lives in, and is
already unit-tested in, `etl/load_funds_postgres.py`, `etl/load_esg_cosmos.py`,
`etl/load_verified_holdings_cosmos.py`. run_ingestion() is the orchestration + lineage-logging
layer ARCHITECTURE.md assigns to "the ETL Agent" specifically, not a reimplementation of any of
those loaders.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from greenlux_sentinel.db.audit import write_audit_log
from greenlux_sentinel.etl import (
    extract_document_entities,
    fetch_fund_documents,
    load_documents_search,
    load_esg_cosmos,
    load_funds_postgres,
    load_verified_holdings_cosmos,
)

if TYPE_CHECKING:
    import httpx
    import psycopg
    from azure.cosmos import ContainerProxy
    from azure.search.documents import SearchClient
    from azure.storage.blob import ContainerClient
    from langchain_core.language_models import BaseChatModel
    from openai import AzureOpenAI

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"
_LANDING_CONTAINER_NAME = "landing"

# Every file run_ingestion() actually reads -- used to decide whether a data_dir already has
# real data (a dev machine with data/raw/ checked out) or needs fetching from blob storage (a
# deployed Function App/Container App, whose image doesn't include data/ -- it's gitignored).
_REQUIRED_FILES = (
    "morningstar_european_mutual_funds.csv",
    "morningstar_european_etfs.csv",
    "top100_etf_holdings.csv",
    "public_company_esg_ratings.csv",
)


def _resolve_data_dir(data_dir: Path | None, container: ContainerClient | None = None) -> Path:
    """Return a data_dir that actually has the raw files run_ingestion() needs.

    Uses `data_dir` (or the repo's data/raw/ default) unchanged if it already has them. Otherwise
    downloads the whole `landing` container from the ADLS Gen2 landing storage account
    (infra/modules/storage.bicep) into a fresh temp directory and returns that -- the path taken
    by a deployed run, which has no local data/ at all (see infra/README.md's known gaps, now
    closed). Access is via DefaultAzureCredential + the caller's managed identity, no storage key.
    """
    data_dir = data_dir or _DEFAULT_DATA_DIR
    if all((data_dir / name).exists() for name in _REQUIRED_FILES):
        return data_dir

    import tempfile

    owns_container = container is None
    if owns_container:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        from greenlux_sentinel.config import get_settings

        settings = get_settings()
        if not settings.landing_storage_account_name:
            raise FileNotFoundError(
                f"{data_dir} is missing raw data files and LANDING_STORAGE_ACCOUNT_NAME is not "
                "configured -- either populate data_dir locally or set that env var"
            )
        account_url = f"https://{settings.landing_storage_account_name}.blob.core.windows.net"
        service_client = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
        container = service_client.get_container_client(_LANDING_CONTAINER_NAME)

    download_dir = Path(tempfile.mkdtemp(prefix="greenlux-etl-data-"))
    # The landing storage account has ADLS Gen2 hierarchical namespace enabled
    # (infra/modules/storage.bicep), so list_blobs() returns directory placeholder entries
    # (e.g. "verified_holdings" itself, tagged hdi_isfolder=true) alongside real files -- skip
    # them, or a later real file under that "directory" collides trying to mkdir a path that's
    # already been written as a file.
    for blob in container.list_blobs(include=["metadata"]):
        if (blob.metadata or {}).get("hdi_isfolder") == "true":
            continue
        target = download_dir / blob.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(container.download_blob(blob.name).readall())

    return download_dir

# Portfolio-scale cap on how many distinct LU management companies get looked up against GLEIF
# per run — GLEIF's public API has no published rate limit for this volume, this is about
# keeping a demo/CI-scale run fast and bounded, not working around throttling.
_GLEIF_LOOKUP_LIMIT = 25


def _distinct_lu_management_companies(conn: psycopg.Connection, limit: int) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT management_company FROM funds "
            "WHERE domicile_country = 'LU' AND management_company IS NOT NULL "
            "ORDER BY management_company LIMIT %s",
            (limit,),
        )
        return [row[0] for row in cur.fetchall()]


def cross_check_lu_entities(
    conn: psycopg.Connection, client: httpx.Client | None = None, limit: int = _GLEIF_LOOKUP_LIMIT
) -> int:
    """Look up each LU-domiciled fund's management company against the live GLEIF register,
    upserting any match into lu_legal_entities. Returns the number matched.

    Best-effort by design: management_company is itself a heuristic, parsed from the fund name
    (~47% coverage — see load_funds_postgres.py), so a GLEIF miss here just means no grounding
    record for that company, not an ingestion error.
    """
    from greenlux_sentinel.mcp_servers import gleif_server

    owns_client = client is None
    if owns_client:
        import httpx as httpx_module

        from greenlux_sentinel.config import get_settings

        client = httpx_module.Client(base_url=get_settings().gleif_api_base_url.rstrip("/"), timeout=10.0)

    try:
        companies = _distinct_lu_management_companies(conn, limit)
        matched = 0
        for name in companies:
            record = gleif_server.lookup_lei(name, client=client)
            if record is None:
                continue
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO lu_legal_entities "
                    "(lei, legal_name, entity_legal_form, entity_status, country) "
                    "VALUES (%(lei)s, %(legal_name)s, %(entity_legal_form)s, %(entity_status)s, %(country)s) "
                    "ON CONFLICT (lei) DO UPDATE SET "
                    "legal_name = EXCLUDED.legal_name, entity_legal_form = EXCLUDED.entity_legal_form, "
                    "entity_status = EXCLUDED.entity_status, country = EXCLUDED.country, fetched_at = now()",
                    record,
                )
            matched += 1
    finally:
        if owns_client:
            client.close()

    write_audit_log(
        conn,
        agent_name="etl_agent",
        tool_name="cross_check_lu_entities",
        input_summary=f"{len(companies)} LU management companies checked",
        output_summary=f"{matched} matched against GLEIF",
    )
    return matched


def run_ingestion(
    data_dir: Path | None = None,
    conn: psycopg.Connection | None = None,
    container: ContainerProxy | None = None,
) -> dict[str, Any]:
    """Full ETL run: Tier 1 funds, Tier 2 descriptive (Top-100) holdings, Tier 2 verified
    holdings, and a GLEIF cross-check of LU management companies. Returns a lineage summary; each
    stage also writes its own audit_log row via the loader it calls.

    Accepts optional injected connections for testability/DI (same convention as every loader/
    agent this calls); opens (and closes) real ones from config.get_settings() when not
    provided. `data_dir` defaults to this repo's data/raw/ layout, falling back to the ADLS
    landing container (see _resolve_data_dir()) if that layout isn't present locally.
    """
    data_dir = _resolve_data_dir(data_dir)

    owns_connections = conn is None and container is None
    if owns_connections:
        import psycopg
        from azure.cosmos import CosmosClient

        from greenlux_sentinel.config import get_settings

        settings = get_settings()
        conn = psycopg.connect(settings.postgres_dsn)
        client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)
        container = client.get_database_client(settings.cosmos_database).get_container_client(
            settings.cosmos_container
        )

    try:
        funds_loaded = load_funds_postgres.load(
            data_dir / "morningstar_european_mutual_funds.csv",
            data_dir / "morningstar_european_etfs.csv",
            conn=conn,
        )
        top100_holdings_docs = load_esg_cosmos.load(
            data_dir / "top100_etf_holdings.csv",
            data_dir / "public_company_esg_ratings.csv",
            container=container,
        )
        verified_holdings_docs = load_verified_holdings_cosmos.load(
            data_dir / "verified_holdings",
            data_dir / "public_company_esg_ratings.csv",
            container=container,
        )
        gleif_matched = cross_check_lu_entities(conn)

        summary = {
            "funds_loaded": funds_loaded,
            "top100_holdings_docs": top100_holdings_docs,
            "verified_holdings_docs": verified_holdings_docs,
            "gleif_matched": gleif_matched,
        }
        write_audit_log(
            conn,
            agent_name="etl_agent",
            tool_name="run_ingestion",
            input_summary=str(data_dir),
            output_summary=str(summary),
        )
        conn.commit()
    finally:
        if owns_connections:
            conn.close()

    return summary


_DEFAULT_DOCUMENT_CORPUS_DIR = Path(__file__).resolve().parents[3] / "data" / "raw" / "document_corpus"


def run_document_ingestion(
    corpus_dir: Path | None = None,
    conn: psycopg.Connection | None = None,
    search_client: SearchClient | None = None,
    embedding_client: AzureOpenAI | None = None,
    llm: BaseChatModel | None = None,
) -> dict[str, Any]:
    """Fetch + tag + index the Phase 8 document corpus (fetch_fund_documents.FUND_DOCUMENTS):
    KIIDs/prospectuses for the 5 issuer-verified UCITS ETFs plus general SFDR/CSSF regulatory
    PDFs. Same thin-orchestrator-over-real-loaders shape as run_ingestion() above -- the actual
    fetch/extract/load logic lives in, and is unit-tested in, etl/fetch_fund_documents.py,
    etl/extract_document_entities.py, etl/load_documents_search.py.

    Manual-trigger only (no scheduled Functions timer -- see docs/PROGRESS_LOG.md's Phase 8a
    entry): this corpus is near-static, unlike the daily Morningstar/GLEIF data run_ingestion()
    refreshes. Returns a lineage summary; writes its own audit_log row (no per-stage loader here
    writes its own the way run_ingestion()'s loaders do, since fetch/extract/load don't touch
    Postgres individually).
    """
    corpus_dir = corpus_dir or _DEFAULT_DOCUMENT_CORPUS_DIR
    documents = fetch_fund_documents.FUND_DOCUMENTS

    owns_conn = conn is None
    if owns_conn:
        import psycopg

        from greenlux_sentinel.config import get_settings

        conn = psycopg.connect(get_settings().postgres_dsn)

    try:
        fetch_fund_documents.fetch_all(corpus_dir)
        records = extract_document_entities.build_document_records(corpus_dir, documents, llm=llm)
        chunks_indexed = load_documents_search.load(records, search_client=search_client, embedding_client=embedding_client)

        summary = {
            "documents_fetched": len(documents),
            "chunks_indexed": chunks_indexed,
        }
        write_audit_log(
            conn,
            agent_name="etl_agent",
            tool_name="run_document_ingestion",
            input_summary=str(corpus_dir),
            output_summary=str(summary),
        )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()

    return summary
