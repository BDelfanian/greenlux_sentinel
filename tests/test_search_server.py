"""Unit tests for mcp_servers/search_server.py: filter/query construction against a fake
SearchClient -- no live Azure AI Search resource needed (none is provisioned yet, see
infra/README.md's Phase 8 note). Mirrors test_cosmos_server.py's patch-the-collaborator style."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from greenlux_sentinel.mcp_servers import search_server


class TestBuildFilter:
    def test_no_filters_returns_none(self):
        assert search_server._build_filter({}) is None

    def test_isin_only_ors_with_general_regulatory_doc_types(self):
        result = search_server._build_filter({"isin": "IE00BYVJRR92"})
        assert result == "isin eq 'IE00BYVJRR92' or search.in(doc_type, 'regulation,cssf_guidance', ',')"

    def test_doc_type_only(self):
        assert search_server._build_filter({"doc_type": "kiid"}) == "doc_type eq 'kiid'"

    def test_isin_and_doc_type_combine(self):
        result = search_server._build_filter({"isin": "IE00BYVJRR92", "doc_type": "kiid"})
        assert result == "isin eq 'IE00BYVJRR92' or (doc_type eq 'kiid')"

    def test_unsupported_field_raises(self):
        with pytest.raises(ValueError, match="unsupported filter field"):
            search_server._build_filter({"bogus": "x"})


class TestHybridSearch:
    def test_calls_client_search_with_embedded_vector_and_filter(self):
        client = MagicMock()
        client.search.return_value = [{"id": "doc1_0", "content": "..."}]

        with patch("greenlux_sentinel.mcp_servers.search_server._embed_query", return_value=[0.1, 0.2]):
            results = search_server.hybrid_search("what is the risk score", filters={"isin": "IE1"}, client=client)

        assert results == [{"id": "doc1_0", "content": "..."}]
        client.search.assert_called_once()
        _, kwargs = client.search.call_args
        assert kwargs["search_text"] == "what is the risk score"
        assert kwargs["filter"] == "isin eq 'IE1' or search.in(doc_type, 'regulation,cssf_guidance', ',')"
        assert kwargs["top"] == search_server._DEFAULT_TOP_K


class TestGetDocument:
    def test_found_returns_dict(self):
        client = MagicMock()
        client.get_document.return_value = {"id": "doc1_0", "content": "..."}
        assert search_server.get_document("doc1_0", client=client) == {"id": "doc1_0", "content": "..."}

    def test_not_found_returns_none(self):
        from azure.core.exceptions import ResourceNotFoundError

        client = MagicMock()
        client.get_document.side_effect = ResourceNotFoundError("not found")
        assert search_server.get_document("missing", client=client) is None
