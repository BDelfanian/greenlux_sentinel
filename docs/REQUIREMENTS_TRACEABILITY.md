# Requirements traceability

Every constraint from the original project brief, mapped to where it's satisfied. Use this to
check scope drift — if an implementation choice can't point to a row here, ask whether it belongs.

| # | Requirement | How it's satisfied |
|---|---|---|
| 1 | Agentic theme combining 3+ of {ML, BI, ETL} | Four: agentic ETL (ETL Agent), ML (greenwashing-risk model), agentic BI (Dashboard Agent + dynamic Power BI), agentic query/analytics (NL2SQL + Query-Optimizer agents) |
| 2 | LangChain / LangGraph / LangSmith | Supervisor + specialist agents built as a LangGraph graph; LangChain for tool/chain wiring; LangSmith for tracing every run |
| 3 | MCP implementation | Four MCP servers: Postgres, Cosmos, Power BI, GLEIF — see [ARCHITECTURE.md](ARCHITECTURE.md#mcp-servers) |
| 4 | Deployed on Microsoft Azure | Full service map in [ARCHITECTURE.md](ARCHITECTURE.md#azure-service-map) |
| 5 | Responsible AI: logging, auditability, guardrails | Postgres audit-log table + LangSmith traces + Azure Monitor; output validators enforcing tool-sourced numeric claims — see [RESPONSIBLE_AI.md](RESPONSIBLE_AI.md) |
| 5b | Human-in-the-loop | Approval gate before query-optimizer schema changes and before report publication — see [RESPONSIBLE_AI.md](RESPONSIBLE_AI.md#human-in-the-loop-gates) |
| 6 | PostgreSQL + agentic query creation and optimization | NL2SQL Agent (creation) + Query-Optimizer Agent reading `EXPLAIN ANALYZE` and proposing indexes (optimization) |
| 7 | Power BI dashboards, dynamic/agentic not static | Dashboard Agent composes DAX/Power BI queries at request time via the Power BI MCP server, not a fixed pre-built report |
| 8 | Agent that creates a final report | Report Agent — cites tool-sourced figures, multilingual, gated by human approval |
| 9 | Wide variety of Azure services | 11 distinct services listed in [ARCHITECTURE.md](ARCHITECTURE.md#azure-service-map) |
| 10 | Real-world finance/investment trend, Luxembourg preferred | Greenwashing-risk / SFDR-consistency, tied directly to CSSF's stated 2026 supervisory priorities — see [DATA.md](DATA.md#why-this-topic). The Luxembourg framing is carried by the Tier 1 fund universe as a whole (58% of mutual funds / 33% of ETFs LU-domiciled) and the GLEIF LU legal-entity grounding; the flagship risk-score *demo* itself runs on 5 issuer-verified UCITS ETFs that are Irish-, not Luxembourg-, domiciled — a deliberate, documented data-availability tradeoff, not an oversight, see [DATA.md](DATA.md#tier-2-verified-holdings-phase-2-correction) |
| 11 | GitHub repo, regular pushes | [github.com/BDelfanian/greenlux_sentinel](https://github.com/BDelfanian/greenlux_sentinel) |
| 12 | Real moderate-size Kaggle dataset; relational + NoSQL with different file formats | Morningstar Funds (CSV → Postgres) + ETF holdings/company ESG (CSV/JSON reshaped → Cosmos DB) — see [DATA.md](DATA.md#datasets). Cosmos DB also holds a second, non-Kaggle Tier 2 source that the risk score actually runs on: 5 ETFs' current holdings fetched live from issuer sites — see [DATA.md](DATA.md#tier-2-verified-holdings-phase-2-correction) |
| 13 | Multilingual databases (Luxembourg is multilingual) | EN/FR/DE fund-summary text generated and maintained by the Report Agent — see [DATA.md](DATA.md#multilingual-layer) |
| 14 | At least one API for dynamic external data | GLEIF API — live Luxembourg legal-entity lookups. The issuer-holdings fetch feeding the risk score (`etl/fetch_verified_holdings.py`) is a second live external source, re-pulling current-day holdings rather than a static archive |

## Explicit non-goals (to prevent scope creep back toward the sibling project)

- No vector search / RAG over regulatory PDF text
- No knowledge-graph traversal (Cosmos Gremlin) — that's agentic-rag-lu's territory
- No RAG-style chat as the primary interface — the Phase 7 Next.js operator UI (`ui/`, CLAUDE.md
  decision #5) is a structured request/response client over the five fixed specialist agents, not
  an open-ended conversational surface; Power BI + the generated report remain the primary
  analyst-facing deliverable
- No literal "SFDR Article" column fabricated in any schema
