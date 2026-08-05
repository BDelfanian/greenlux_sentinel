"""GLEIF MCP server — live Luxembourg legal-entity data, no API key required.

Tools exposed (docs/ARCHITECTURE.md#mcp-servers):
    lookup_lei(name_or_lei)        -> resolve a fund/management-company name or LEI to its record
    search_lu_entities(entity_type) -> search Luxembourg-registered entities (SICAV, FCP, ...)

This is the project's "at least one dynamic external API" requirement (see
docs/REQUIREMENTS_TRACEABILITY.md, row 14) — used by the ETL Agent to ground fund
domicile claims against a real, live public register rather than a static snapshot.

TODO(Phase 3):
    - Thin httpx wrapper over GLEIF_API_BASE_URL (see .env.example)
    - No auth needed; rate-limit politely regardless
"""

from __future__ import annotations


def serve() -> None:
    """Start the MCP server process. Not yet implemented."""
    raise NotImplementedError("Phase 3 — see docs/ROADMAP.md")
