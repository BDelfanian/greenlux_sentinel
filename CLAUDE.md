# CLAUDE.md — persistent context for this repo

This file is the entry point for any AI-assisted session (Claude Code or otherwise) working in
this repository. Read it before making changes. It captures decisions that were made deliberately
and should not be silently "improved" back to a more generic default.

## What this project is

**GreenLux Sentinel** — a portfolio project for Luxembourg finance-industry job applications. A
multi-agent system that computes a **Greenwashing Risk Score** per investment fund: the gap
between a fund's claimed sustainability profile (Morningstar Sustainability Rating) and the
actual ESG profile implied by its real holdings. Wrapped in agentic ETL, agentic SQL/BI, and a
multilingual report-writing agent, with Responsible-AI guardrails throughout.

Full requirement list and how each is satisfied: [docs/REQUIREMENTS_TRACEABILITY.md](docs/REQUIREMENTS_TRACEABILITY.md).

## Decisions that must not be quietly reverted

These were chosen for specific reasons during project planning — don't "simplify" them away
without checking with the user first.

1. **Ground-truth signal is "Morningstar Sustainability Rating vs. holdings-implied ESG profile,"
   not a literal SFDR Article 6/8/9 column.** No free dataset was confirmed to carry the legal
   SFDR label. Don't invent or fabricate an SFDR-article column — the risk score is a data-driven
   proxy, explicitly documented as such, not a claim of regulatory non-compliance. See
   [docs/DATA.md](docs/DATA.md#ground-truth-methodology).

2. **Two-tier data architecture, not a single flat join.** The Morningstar fund dataset
   (~67k funds) only has sector/asset-class allocation, not security-level holdings. The
   greenwashing-risk model runs on a *narrower* subset (Top-100 ETF holdings joined to company-
   level ESG ratings) where real holdings data exists. The broad fund universe powers BI/agentic-
   SQL; the narrow subset powers the risk model. Don't collapse these into one dataset or pretend
   the full 67k funds all have holdings-level ESG linkage.

3. **Cosmos DB uses the NoSQL/Core (SQL) API, not Gremlin.** The sibling project
   ([agentic-rag-lu](https://github.com/BDelfanian/agentic-rag-lu)) already uses Cosmos DB
   Gremlin for graph traversal. Using the same API here would erase the intended differentiation.
   Keep Cosmos DB usage here strictly document-store (nested JSON ESG records).

4. **No RAG / vector search over regulatory PDFs.** That's the core of agentic-rag-lu
   (CSSF FAQs, EUR-Lex documents via Azure AI Search + GraphRAG). This project's multilingual
   layer (EN/FR/DE) is **agent-generated structured summaries**, not a retrieval corpus. Don't
   add a vector store or start ingesting regulatory text corpora here — that would duplicate the
   other project's core mechanism.

5. **No chat frontend.** The primary deliverable surface is the Power BI dashboard and the
   generated report, not a conversational UI (agentic-rag-lu already has a Next.js chat app).
   Keep any operator-facing UI minimal (status/audit log viewer at most).

6. **Orchestration is LangGraph/LangChain/LangSmith,** not native OpenAI function-calling (which
   agentic-rag-lu uses). This is a hard project requirement, not a style preference.

7. **Human-in-the-loop gates:** required before (a) the report agent finalizes/publishes a
   report, and (b) the query-optimizer agent applies a schema change (e.g. creating an index) in
   Postgres. Read-only agent actions (analysis, dashboard queries) run autonomously. Don't remove
   these gates for convenience — see [docs/RESPONSIBLE_AI.md](docs/RESPONSIBLE_AI.md).

## Repo map

- `src/greenlux_sentinel/agents/` — LangGraph agent nodes (supervisor + specialists)
- `src/greenlux_sentinel/mcp_servers/` — MCP tool servers (Postgres, Cosmos, Power BI, GLEIF)
- `src/greenlux_sentinel/etl/` — ingestion scripts (Kaggle CSVs/JSON → Postgres/Cosmos)
- `src/greenlux_sentinel/ml/` — greenwashing-risk scoring model
- `src/greenlux_sentinel/guardrails/` — output validators, PII redaction, tool-sourced-numbers enforcement
- `src/greenlux_sentinel/db/` — SQL schema (fund tables + audit log table)
- `src/greenlux_sentinel/bi/` — DAX/Power BI query templates used by the dashboard agent
- `infra/` — Bicep IaC for the Azure resources
- `docs/` — the documentation set listed in README.md

## Current phase

Scaffolding — see [docs/ROADMAP.md](docs/ROADMAP.md) for the phase checklist. Don't assume any
agent, MCP server, or DB schema in `src/` is implemented beyond its docstring/TODO until the
roadmap says so.
