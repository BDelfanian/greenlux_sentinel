"""Unit tests for mcp_servers/powerbi_server.py: request shaping only, via an injected
httpx.Client backed by httpx.MockTransport -- no live Power BI workspace exists yet (see the
module docstring), so these never exercise _access_token()/ClientSecretCredential."""

from __future__ import annotations

import httpx

from greenlux_sentinel.mcp_servers import powerbi_server


def _client(handler):
    return httpx.Client(base_url="https://api.powerbi.com/v1.0/myorg", transport=httpx.MockTransport(handler))


class TestRunDaxQuery:
    def test_posts_the_dax_query_and_returns_rows(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1.0/myorg/groups/ws-1/datasets/ds-1/executeQueries"
            body = request.read()
            assert b"EVALUATE" in body
            return httpx.Response(
                200,
                json={"results": [{"tables": [{"rows": [{"[fund_id]": "F1"}]}]}]},
            )

        rows = powerbi_server.run_dax_query(
            "ds-1", "EVALUATE funds", workspace_id="ws-1", client=_client(handler)
        )

        assert rows == [{"[fund_id]": "F1"}]


class TestRefreshDataset:
    def test_posts_a_refresh_request(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1.0/myorg/groups/ws-1/datasets/ds-1/refreshes"
            assert request.method == "POST"
            return httpx.Response(202)

        powerbi_server.refresh_dataset("ds-1", workspace_id="ws-1", client=_client(handler))
