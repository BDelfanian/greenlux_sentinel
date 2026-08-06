"""Unit tests for mcp_servers/cosmos_server.py, via a MagicMock ContainerProxy (no live Cosmos
needed) -- same pattern as test_risk_agent.py, which exercises these through the risk agent."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from greenlux_sentinel.mcp_servers import cosmos_server


class TestQueryEsgDocuments:
    def test_builds_a_conditioned_query_from_the_filter(self):
        container = MagicMock()
        container.query_items.return_value = [{"isin": "IE00X", "source": "issuer_verified"}]

        docs = cosmos_server.query_esg_documents({"isin": "IE00X", "source": "issuer_verified"}, container=container)

        assert docs == [{"isin": "IE00X", "source": "issuer_verified"}]
        call = container.query_items.call_args
        assert "c.isin = @isin" in call.kwargs["query"]
        assert "c.source = @source" in call.kwargs["query"]
        assert call.kwargs["enable_cross_partition_query"] is True

    def test_no_filter_selects_everything(self):
        container = MagicMock()
        container.query_items.return_value = []

        cosmos_server.query_esg_documents({}, container=container)

        assert container.query_items.call_args.kwargs["query"] == "SELECT * FROM c"

    def test_rejects_unsupported_filter_field(self):
        with pytest.raises(ValueError, match="unsupported filter field"):
            cosmos_server.query_esg_documents({"holdings_count": 5}, container=MagicMock())


class TestGetCompanyEsg:
    def test_returns_flattened_esg_record_for_first_match(self):
        container = MagicMock()
        container.query_items.return_value = [
            {"ticker": "MSFT", "name": "Microsoft Corp", "esg": {"total_esg_score": 1400, "sector": "Technology"}}
        ]

        result = cosmos_server.get_company_esg("msft", container=container)

        assert result == {"ticker": "MSFT", "name": "Microsoft Corp", "total_esg_score": 1400, "sector": "Technology"}
        params = container.query_items.call_args.kwargs["parameters"]
        assert {"name": "@ticker", "value": "MSFT"} in params  # uppercased before querying

    def test_returns_none_when_no_holding_matches(self):
        container = MagicMock()
        container.query_items.return_value = []

        assert cosmos_server.get_company_esg("ZZZZ", container=container) is None
