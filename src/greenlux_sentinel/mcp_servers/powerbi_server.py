"""Power BI MCP server.

Tools exposed (docs/ARCHITECTURE.md#mcp-servers):
    run_dax_query(dataset_id, dax)   -> executes a DAX query against a published dataset
    refresh_dataset(dataset_id)      -> triggers a dataset refresh via the Power BI REST API

Used only by the Dashboard Agent, to keep the dashboard "dynamic, not static" — every
call here is driven by an analyst's natural-language question at request time.

TODO(Phase 3):
    - Auth via service principal (POWERBI_CLIENT_ID/SECRET in .env, Key Vault in prod)
    - Wrap the Power BI REST API (or XMLA endpoint for DAX execution)
"""

from __future__ import annotations


def serve() -> None:
    """Start the MCP server process. Not yet implemented."""
    raise NotImplementedError("Phase 3 — see docs/ROADMAP.md")
