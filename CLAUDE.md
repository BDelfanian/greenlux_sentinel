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
   greenwashing-risk model runs on a *narrower* subset where real holdings data exists. The broad
   fund universe powers BI/agentic-SQL; the narrow subset powers the risk model. Don't collapse
   these into one dataset or pretend the full 67k funds all have holdings-level ESG linkage.
   **Correction (Phase 2):** the original "Top-100 ETF holdings" subset turned out to have zero
   overlap with the Tier 1 fund table (different market entirely) and no sustainability claim of
   its own, so it could never feed the risk model as originally planned. The risk model's real
   Tier 2 subset is now five issuer-verified UCITS ETFs that *are* in Tier 1 — see
   [docs/DATA.md](docs/DATA.md#tier-2-verified-holdings-phase-2-correction). The Top-100 set is
   kept only as a separate, clearly-unlinked descriptive dataset.

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

See [docs/PROGRESS_LOG.md](docs/PROGRESS_LOG.md) (newest entry first) for exactly what's been
done and what's next — read it before starting new work, alongside [docs/ROADMAP.md](docs/ROADMAP.md)
for the phase checklist. Don't assume any agent, MCP server, or DB schema in `src/` is implemented
beyond its docstring/TODO until the roadmap and progress log say so.

## Session continuity — keep the progress log current

At the end of each roadmap phase (or any substantial chunk of work, even mid-phase), append a new
entry to the **top** of [docs/PROGRESS_LOG.md](docs/PROGRESS_LOG.md) — don't rewrite past entries.
Each entry covers:

1. **Done** — what was actually completed, concretely (files touched, what was verified and how).
2. **Deviations from the original plan** — anywhere the real implementation diverged from what
   CLAUDE.md/ROADMAP.md/DATA.md/ARCHITECTURE.md originally assumed, and why. This is the most
   important part: it's what stops a fresh session from re-deriving (or contradicting) a decision
   already made for a reason.
3. **Next step** — the concrete next action, specific enough that a new chat with no other context
   could start there.

Also update `docs/ROADMAP.md` checkboxes in the same pass — the log explains *why/what changed*,
the roadmap tracks *what's checked off*. If a deviation changes a decision recorded elsewhere
(e.g. a schema assumption in DATA.md turns out wrong), update that doc directly too; don't leave
the correction only in the log.
