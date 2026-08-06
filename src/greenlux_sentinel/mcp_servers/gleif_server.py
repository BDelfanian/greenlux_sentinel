"""GLEIF MCP server -- live Luxembourg legal-entity data, no API key required.

Tools exposed (docs/ARCHITECTURE.md#mcp-servers):
    lookup_lei(name_or_lei)        -> resolve a fund/management-company name or LEI to its record
    search_lu_entities(entity_type) -> search Luxembourg-registered entities

This is the project's "at least one dynamic external API" requirement (see
docs/REQUIREMENTS_TRACEABILITY.md, row 14) -- ultimately meant for the ETL Agent to ground fund
domicile claims against a real, live public register. etl_agent.py is still an unimplemented
stub (see docs/ROADMAP.md), so nothing calls these functions yet this phase; they were
live-verified directly against https://api.gleif.org during implementation (real HTTP calls via
curl -- see docs/PROGRESS_LOG.md), and the unit tests below replay that shape through
httpx.MockTransport so they don't depend on network access.

Response shape (confirmed live 2026-08-06): GET /lei-records/{lei} returns {"data": {...}} (one
record); GET /lei-records?filter[...]=... returns {"data": [...]} (a list). Both share the same
attributes.{lei, entity.{legalName.name, legalForm.id, status, legalAddress.country}} shape,
summarized by _summarize() below. entity.category ('FUND', 'GENERAL', 'BRANCH', ...) is GLEIF's
own coarse entity-type field -- used for search_lu_entities(entity_type), not the more granular
(and code-based, not human-readable) legalForm.id.

No auth needed; a single httpx.Client per call is enough load for this project's read-only
"grounding lookup" use case, so no connection pooling beyond httpx's own defaults.
"""

from __future__ import annotations

from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("gleif_server")

_LEI_LENGTH = 20


def _base_url() -> str:
    from greenlux_sentinel.config import get_settings

    return get_settings().gleif_api_base_url.rstrip("/")


def _summarize(record: dict[str, Any]) -> dict[str, Any]:
    attributes = record["attributes"]
    entity = attributes["entity"]
    return {
        "lei": attributes["lei"],
        "legal_name": entity["legalName"]["name"],
        "entity_legal_form": entity.get("legalForm", {}).get("id"),
        "entity_status": entity.get("status"),
        "country": entity.get("legalAddress", {}).get("country"),
    }


def lookup_lei(name_or_lei: str, client: httpx.Client | None = None) -> dict[str, Any] | None:
    """Resolve a fund/management-company name or a 20-character LEI to its GLEIF record's key
    fields (see _summarize). Returns None if nothing matched. On a name, returns the first
    (most relevant, per GLEIF's own ranking) match."""
    owns_client = client is None
    client = client or httpx.Client(base_url=_base_url(), timeout=10.0)
    try:
        if len(name_or_lei) == _LEI_LENGTH and name_or_lei.isalnum():
            response = client.get(f"/lei-records/{name_or_lei}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            record = response.json()["data"]
        else:
            response = client.get(
                "/lei-records", params={"filter[entity.legalName]": name_or_lei, "page[size]": 1}
            )
            response.raise_for_status()
            matches = response.json()["data"]
            if not matches:
                return None
            record = matches[0]
        return _summarize(record)
    finally:
        if owns_client:
            client.close()


def search_lu_entities(
    entity_type: str | None = None, limit: int = 20, client: httpx.Client | None = None
) -> list[dict[str, Any]]:
    """Search Luxembourg-registered legal entities, optionally filtered by GLEIF's
    entity.category (e.g. 'FUND'), returning up to `limit` summarized records."""
    owns_client = client is None
    client = client or httpx.Client(base_url=_base_url(), timeout=10.0)
    try:
        params: dict[str, Any] = {
            "filter[entity.legalAddress.country]": "LU",
            "page[size]": limit,
        }
        if entity_type:
            params["filter[entity.category]"] = entity_type
        response = client.get("/lei-records", params=params)
        response.raise_for_status()
        return [_summarize(record) for record in response.json()["data"]]
    finally:
        if owns_client:
            client.close()


@mcp.tool(name="lookup_lei")
def _lookup_lei_tool(name_or_lei: str) -> dict[str, Any] | None:
    """Resolve a fund/management-company name or LEI to its GLEIF legal-entity record."""
    return lookup_lei(name_or_lei)


@mcp.tool(name="search_lu_entities")
def _search_lu_entities_tool(entity_type: str | None = None) -> list[dict[str, Any]]:
    """Search Luxembourg-registered legal entities, optionally filtered by entity category
    (e.g. 'FUND')."""
    return search_lu_entities(entity_type)


def serve() -> None:
    """Start the MCP server process (stdio transport)."""
    mcp.run()
