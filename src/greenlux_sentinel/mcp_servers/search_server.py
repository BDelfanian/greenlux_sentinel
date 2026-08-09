"""Azure AI Search MCP server -- document-evidence retrieval for the evidence agent (Phase 8b).

Tools exposed (docs/ARCHITECTURE.md#mcp-servers):
    hybrid_search(query, filters, top_k)   -> vector + keyword search over the document corpus
    get_document(doc_id)                   -> one indexed chunk by id

Read-only surface -- the evidence agent is the only consumer.

Same two-layer shape as postgres_server.py/cosmos_server.py: the plain functions below are what
agents import and call in-process (with an optional injected SearchClient, for shared clients and
for the existing unit tests against a MagicMock client); the @mcp.tool()-decorated wrappers are
the standalone-server entrypoints, each opening its own client per call since MCP tool arguments
must be plain JSON, never a live SearchClient.

Phase 8b status: implemented against the real Azure AI Search SDK surface (query embedding via
the Azure OpenAI embedding deployment, an OData filter built from a fixed field whitelist), unit
tested against an injected fake client -- NOT live-verified, no Azure AI Search resource is
provisioned yet (see infra/README.md's Phase 8 note). Same "implemented, not live-verified"
status mcp_servers/powerbi_server.py already carries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from azure.search.documents import SearchClient

mcp = FastMCP("search_server")

# Only these fields may be filtered on -- keeps hybrid_search from turning caller-supplied keys
# into an arbitrary/injectable OData filter (same whitelist idea as cosmos_server.py's
# _ALLOWED_FILTER_FIELDS).
_ALLOWED_FILTER_FIELDS = {"isin", "doc_type"}

_DEFAULT_TOP_K = 5


def _connect() -> SearchClient:
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    from greenlux_sentinel.config import get_settings

    settings = get_settings()
    return SearchClient(
        endpoint=settings.azure_search_endpoint,
        index_name=settings.azure_search_index_name,
        credential=AzureKeyCredential(settings.azure_search_query_key),
    )


def _embed_query(query: str) -> list[float]:
    from openai import AzureOpenAI

    from greenlux_sentinel.config import get_settings

    settings = get_settings()
    client = AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )
    response = client.embeddings.create(input=[query], model=settings.azure_openai_embedding_deployment)
    return response.data[0].embedding


def _build_filter(filters: dict[str, Any]) -> str | None:
    """A fund-specific question must retrieve both that fund's own documents AND the general
    regulatory corpus (doc_type in ('regulation', 'cssf_guidance')) simultaneously -- an OR
    across those two, not a strict single-field equality filter. If no isin is given, no filter
    is applied at all (a general question can match anything in the index)."""
    unknown = set(filters) - _ALLOWED_FILTER_FIELDS
    if unknown:
        raise ValueError(f"unsupported filter field(s): {sorted(unknown)}")

    isin = filters.get("isin")
    doc_type = filters.get("doc_type")

    if doc_type is not None:
        clause = f"doc_type eq '{doc_type}'"
        return f"isin eq '{isin}' or ({clause})" if isin else clause
    if isin:
        # Azure AI Search's OData dialect doesn't support SQL-style "field in (...)" -- it needs
        # the search.in() function (confirmed live: the SQL-style form raises "unsupported OData
        # language feature" against the real service; a MagicMock client never would have caught
        # this, since it doesn't validate filter syntax).
        return f"isin eq '{isin}' or search.in(doc_type, 'regulation,cssf_guidance', ',')"
    return None


def hybrid_search(
    query: str, filters: dict[str, Any] | None = None, top_k: int = _DEFAULT_TOP_K, client: SearchClient | None = None
) -> list[dict[str, Any]]:
    """Vector + keyword hybrid search over the document-evidence index. filters supports "isin"
    and/or "doc_type" (see _build_filter for how they combine)."""
    from azure.search.documents.models import VectorizedQuery

    client = client or _connect()
    odata_filter = _build_filter(filters or {})
    vector_query = VectorizedQuery(vector=_embed_query(query), k_nearest_neighbors=top_k, fields="content_vector")

    results = client.search(
        search_text=query,
        vector_queries=[vector_query],
        filter=odata_filter,
        top=top_k,
    )
    return [dict(r) for r in results]


def get_document(doc_id: str, client: SearchClient | None = None) -> dict[str, Any] | None:
    """Look up one indexed chunk by id. Returns None if not found."""
    from azure.core.exceptions import ResourceNotFoundError

    client = client or _connect()
    try:
        return dict(client.get_document(key=doc_id))
    except ResourceNotFoundError:
        return None


@mcp.tool(name="hybrid_search")
def _hybrid_search_tool(query: str, filters: dict[str, Any] | None = None, top_k: int = _DEFAULT_TOP_K) -> list[dict[str, Any]]:
    """Vector + keyword hybrid search over the document-evidence index."""
    return hybrid_search(query, filters, top_k)


@mcp.tool(name="get_document")
def _get_document_tool(doc_id: str) -> dict[str, Any] | None:
    """Look up one indexed document chunk by id."""
    return get_document(doc_id)


def serve() -> None:
    """Start the MCP server process (stdio transport)."""
    mcp.run()
