"""Cosmos DB MCP server -- NoSQL/Core (SQL) API only, NOT Gremlin (see CLAUDE.md, decision #3).

Tools exposed (docs/ARCHITECTURE.md#mcp-servers):
    get_company_esg(ticker)        -> nested per-holding ESG data for one company, searched
                                       across every ETF/fund document (there is no standalone
                                       per-company document -- ESG data lives nested under
                                       each document's holdings[], see etl/load_esg_cosmos.py)
    query_esg_documents(filter)    -> filtered read across top-level ETF/fund documents

Read-only surface -- the risk agent is the only consumer so far (report_agent will be the
second once Phase 4 implements it).

Same two-layer shape as postgres_server.py: the plain functions below are what agents import
and call in-process (with an optional injected ContainerProxy, for shared clients and for the
existing unit tests against a MagicMock container); the @mcp.tool()-decorated wrappers are the
standalone-server entrypoints, each opening its own container client per call since MCP tool
arguments must be plain JSON, never a live ContainerProxy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from azure.cosmos import ContainerProxy

mcp = FastMCP("cosmos_server")

# Only these top-level document fields may be filtered on -- keeps query_esg_documents from
# turning caller-supplied keys into an arbitrary/injectable Cosmos SQL query.
_ALLOWED_FILTER_FIELDS = {"id", "isin", "etf_ticker", "source"}


def _connect() -> ContainerProxy:
    from azure.cosmos import CosmosClient

    from greenlux_sentinel.config import get_settings

    settings = get_settings()
    client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)
    return client.get_database_client(settings.cosmos_database).get_container_client(settings.cosmos_container)


def query_esg_documents(
    filter: dict[str, Any], container: ContainerProxy | None = None
) -> list[dict[str, Any]]:
    """Filtered read across top-level ETF/fund documents, e.g.
    {"isin": "IE00...", "source": "issuer_verified"}. Supported keys: id, isin, etf_ticker,
    source (see _ALLOWED_FILTER_FIELDS)."""
    unknown = set(filter) - _ALLOWED_FILTER_FIELDS
    if unknown:
        raise ValueError(f"unsupported filter field(s): {sorted(unknown)}")

    container = container or _connect()
    conditions = " AND ".join(f"c.{key} = @{key}" for key in filter)
    query = f"SELECT * FROM c WHERE {conditions}" if conditions else "SELECT * FROM c"
    parameters = [{"name": f"@{key}", "value": value} for key, value in filter.items()]
    return list(container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))


def get_company_esg(ticker: str, container: ContainerProxy | None = None) -> dict[str, Any] | None:
    """Look up one company's nested ESG record by holding ticker, searched across every
    ETF/fund document. Returns None if no document has a matching, ESG-scored holding."""
    container = container or _connect()
    items = list(
        container.query_items(
            query="SELECT VALUE h FROM c JOIN h IN c.holdings WHERE h.ticker = @ticker AND h.esg != null",
            parameters=[{"name": "@ticker", "value": ticker.upper()}],
            enable_cross_partition_query=True,
        )
    )
    if not items:
        return None
    holding = items[0]
    return {"ticker": holding["ticker"], "name": holding["name"], **holding["esg"]}


@mcp.tool(name="query_esg_documents")
def _query_esg_documents_tool(filter: dict[str, Any]) -> list[dict[str, Any]]:
    """Filtered read across the ESG holdings container's top-level documents. Supported filter
    keys: id, isin, etf_ticker, source."""
    return query_esg_documents(filter)


@mcp.tool(name="get_company_esg")
def _get_company_esg_tool(ticker: str) -> dict[str, Any] | None:
    """Look up one company's ESG rating by its holding ticker."""
    return get_company_esg(ticker)


def serve() -> None:
    """Start the MCP server process (stdio transport)."""
    mcp.run()
