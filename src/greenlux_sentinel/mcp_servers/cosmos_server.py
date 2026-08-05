"""Cosmos DB MCP server — NoSQL/Core (SQL) API only, NOT Gremlin (see CLAUDE.md, decision #3).

Tools exposed (docs/ARCHITECTURE.md#mcp-servers):
    get_company_esg(ticker)        -> single nested ESG document for one company
    query_esg_documents(filter)    -> filtered read across the ESG holdings container

Read-only surface — the risk agent and report agent are the only consumers.

TODO(Phase 3):
    - Implement using azure-cosmos SDK, Core (SQL) API client
    - Container/document shape defined once Phase 1 data profiling confirms the join keys
      between the ETF holdings dataset and the company ESG ratings dataset
"""

from __future__ import annotations


def serve() -> None:
    """Start the MCP server process. Not yet implemented."""
    raise NotImplementedError("Phase 3 — see docs/ROADMAP.md")
