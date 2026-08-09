"""One-time setup: creates the Azure AI Search index `search_server.py`/`load_documents_search.py`
read/write against (config.py's azure_search_index_name, default "greenlux-docs"). The Bicep
module (infra/modules/ai-search.bicep) provisions the *service*; the index schema itself isn't
something Bicep manages, hence this separate script -- same reason `db/schema.sql` is applied
outside Bicep too.

Idempotent: create_or_update_index() replaces the index definition if it already exists with the
same name, so re-running this after a schema change is safe.

Vector field uses text-embedding-3-small's real output dimension (1536) and a plain HNSW/cosine
profile -- no need for anything fancier at this corpus's scale (~11 documents, ~400 chunks).
"""

from __future__ import annotations

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

from greenlux_sentinel.config import get_settings

_EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small


def build_index(index_name: str) -> SearchIndex:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=_EMBEDDING_DIMENSIONS,
            vector_search_profile_name="default-vector-profile",
        ),
        SimpleField(name="doc_id", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="doc_type", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="isin", type=SearchFieldDataType.String, filterable=True),
        SearchField(
            name="entity_names",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            searchable=True,
            filterable=True,
        ),
        SimpleField(name="source_url", type=SearchFieldDataType.String),
        SimpleField(name="chunk_index", type=SearchFieldDataType.Int32),
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="default-hnsw")],
        profiles=[VectorSearchProfile(name="default-vector-profile", algorithm_configuration_name="default-hnsw")],
    )
    return SearchIndex(name=index_name, fields=fields, vector_search=vector_search)


def create_or_update() -> str:
    settings = get_settings()
    client = SearchIndexClient(endpoint=settings.azure_search_endpoint, credential=AzureKeyCredential(settings.azure_search_admin_key))
    index = build_index(settings.azure_search_index_name)
    result = client.create_or_update_index(index)
    return result.name


if __name__ == "__main__":
    name = create_or_update()
    print(f"index ready: {name}")
