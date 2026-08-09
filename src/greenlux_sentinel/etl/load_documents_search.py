"""Loads document chunk records (extract_document_entities.build_document_records' output) into
the Azure AI Search index backing the evidence agent (mcp_servers/search_server.py). Mirrors
every other etl/load_*.py module's inject-or-open-your-own client pattern (see
load_verified_holdings_cosmos.py).

Embeds each chunk's content via the Azure OpenAI embedding deployment (config.py's
azure_openai_embedding_deployment) before upload -- the index's content_vector field is what
search_server.hybrid_search() queries against.

Phase 8a status: implemented against the real Azure AI Search SDK surface, unit-tested against an
injected fake SearchClient -- NOT live-verified, no Azure AI Search resource is provisioned yet
(see infra/README.md's Phase 8 note). Same "implemented, not live-verified" status
mcp_servers/powerbi_server.py already carries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from azure.search.documents import SearchClient
    from openai import AzureOpenAI


def _default_search_client() -> SearchClient:
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    from greenlux_sentinel.config import get_settings

    settings = get_settings()
    return SearchClient(
        endpoint=settings.azure_search_endpoint,
        index_name=settings.azure_search_index_name,
        credential=AzureKeyCredential(settings.azure_search_admin_key),
    )


def _default_embedding_client() -> AzureOpenAI:
    from openai import AzureOpenAI

    from greenlux_sentinel.config import get_settings

    settings = get_settings()
    return AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


def _embed(texts: list[str], embedding_client: AzureOpenAI) -> list[list[float]]:
    from greenlux_sentinel.config import get_settings

    response = embedding_client.embeddings.create(
        input=texts, model=get_settings().azure_openai_embedding_deployment
    )
    return [item.embedding for item in response.data]


def load(
    records: list[dict[str, Any]],
    search_client: SearchClient | None = None,
    embedding_client: AzureOpenAI | None = None,
) -> int:
    """Embed and upload every chunk record into the search index. Returns the number of
    documents uploaded. Uploads in batches of 16 to keep each embeddings.create() call and each
    Azure AI Search upload_documents() call a reasonable size for this corpus's ~11 documents."""
    search_client = search_client or _default_search_client()
    embedding_client = embedding_client or _default_embedding_client()

    batch_size = 16
    uploaded = 0
    for start in range(0, len(records), batch_size):
        batch = records[start : start + batch_size]
        vectors = _embed([r["content"] for r in batch], embedding_client)
        documents = [{**record, "content_vector": vector} for record, vector in zip(batch, vectors, strict=True)]
        search_client.upload_documents(documents=documents)
        uploaded += len(documents)
    return uploaded
