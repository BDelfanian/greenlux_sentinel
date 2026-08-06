"""Power BI MCP server.

Tools exposed (docs/ARCHITECTURE.md#mcp-servers):
    run_dax_query(dataset_id, dax)   -> executes a DAX query against a published dataset
    refresh_dataset(dataset_id)      -> triggers a dataset refresh via the Power BI REST API

Used only by the Dashboard Agent, to keep the dashboard "dynamic, not static" -- every call
here is meant to be driven by an analyst's natural-language question at request time.

Phase 3 status: implemented against the real Power BI REST API surface (service-principal auth
via azure-identity's ClientSecretCredential -- no new dependency needed, azure-identity is
already used for Key Vault), but NOT live-verified -- no Power BI workspace/service principal is
provisioned yet (that's Phase 4's "Power BI dataset connected to Postgres/Cosmos outputs", see
docs/ROADMAP.md). Unit tests exercise the request shaping via httpx.MockTransport. dashboard_
agent.py is still an unimplemented stub, so nothing calls these functions yet either.

run_dax_query uses POST /groups/{workspace}/datasets/{dataset}/executeQueries -- the REST API's
supported way to run a DAX query without standing up an XMLA endpoint connection.
"""

from __future__ import annotations

from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("powerbi_server")

_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
_BASE_URL = "https://api.powerbi.com/v1.0/myorg"


def _access_token() -> str:
    from azure.identity import ClientSecretCredential

    from greenlux_sentinel.config import get_settings

    settings = get_settings()
    credential = ClientSecretCredential(
        tenant_id=settings.powerbi_tenant_id,
        client_id=settings.powerbi_client_id,
        client_secret=settings.powerbi_client_secret,
    )
    return credential.get_token(_SCOPE).token


def _resolve_client(client: httpx.Client | None) -> tuple[httpx.Client, bool]:
    if client is not None:
        return client, False
    return (
        httpx.Client(base_url=_BASE_URL, headers={"Authorization": f"Bearer {_access_token()}"}, timeout=30.0),
        True,
    )


def run_dax_query(
    dataset_id: str, dax: str, workspace_id: str | None = None, client: httpx.Client | None = None
) -> list[dict[str, Any]]:
    """Execute a DAX query against a published dataset, return the result rows."""
    from greenlux_sentinel.config import get_settings

    workspace_id = workspace_id or get_settings().powerbi_workspace_id
    http_client, owns_client = _resolve_client(client)
    try:
        response = http_client.post(
            f"/groups/{workspace_id}/datasets/{dataset_id}/executeQueries",
            json={"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}},
        )
        response.raise_for_status()
        return response.json()["results"][0]["tables"][0]["rows"]
    finally:
        if owns_client:
            http_client.close()


def refresh_dataset(
    dataset_id: str, workspace_id: str | None = None, client: httpx.Client | None = None
) -> None:
    """Trigger an on-demand dataset refresh. Fire-and-forget -- Power BI processes refreshes
    asynchronously; nothing here polls for completion since no consumer needs that yet
    (dashboard_agent.py is still an unimplemented stub)."""
    from greenlux_sentinel.config import get_settings

    workspace_id = workspace_id or get_settings().powerbi_workspace_id
    http_client, owns_client = _resolve_client(client)
    try:
        response = http_client.post(f"/groups/{workspace_id}/datasets/{dataset_id}/refreshes")
        response.raise_for_status()
    finally:
        if owns_client:
            http_client.close()


@mcp.tool(name="run_dax_query")
def _run_dax_query_tool(dataset_id: str, dax: str) -> list[dict[str, Any]]:
    """Execute a DAX query against a published Power BI dataset."""
    return run_dax_query(dataset_id, dax)


@mcp.tool(name="refresh_dataset")
def _refresh_dataset_tool(dataset_id: str) -> None:
    """Trigger a Power BI dataset refresh."""
    refresh_dataset(dataset_id)


def serve() -> None:
    """Start the MCP server process (stdio transport)."""
    mcp.run()
