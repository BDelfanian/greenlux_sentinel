# Architecture

## Agent graph (LangGraph)

A single supervisor graph coordinates six specialist agents. All agent-to-tool calls go through
MCP servers (never direct SDK calls from agent code) so tool access is uniform, inspectable, and
swappable.

```mermaid
flowchart LR
    U[Analyst request] --> SUP{{Supervisor Agent}}
    SUP --> ETL[ETL Agent]
    SUP --> RISK[Greenwashing-Risk Agent]
    SUP --> SQL[NL2SQL Agent]
    SUP --> OPT[Query-Optimizer Agent]
    SUP --> DASH[Dashboard Agent]
    SUP --> REP[Report Agent]
    REP -.needs.-> RISK
    REP -.needs.-> SQL
    DASH -.needs.-> SQL
```

| Agent | Responsibility | Tools (via MCP) | Human gate? |
|---|---|---|---|
| Supervisor | Routes analyst requests to the right specialist(s); merges results | none directly | no |
| ETL Agent | Ingests Kaggle sources + GLEIF API, resolves schema drift, writes lineage log | Postgres MCP, Cosmos MCP, GLEIF MCP | no |
| Greenwashing-Risk Agent | Computes the risk score per fund, explains the driving holdings | Postgres MCP, Cosmos MCP | no (read-only) |
| NL2SQL Agent | Translates analyst questions into SQL against the fund schema | Postgres MCP | no (read-only) |
| Query-Optimizer Agent | Reads `EXPLAIN ANALYZE` output, proposes/creates indexes | Postgres MCP (DDL) | **yes** — schema changes require approval |
| Dashboard Agent | Turns an analyst question into a DAX/Power BI query, updates the live dashboard | Power BI MCP | no (read-only refresh) |
| Report Agent | Compiles risk score + SQL findings into a cited, multilingual report | Postgres MCP, Cosmos MCP | **yes** — publishing requires approval |

## MCP servers

Each server wraps one system and exposes a small, explicit tool surface — no server should
expose raw query execution without validation.

- **`postgres_server`** — tools: `run_readonly_query(sql)`, `explain_query(sql)`,
  `propose_index(ddl)` (queued for approval, not auto-applied), `write_audit_log(entry)`
- **`cosmos_server`** — tools: `get_company_esg(ticker)`, `query_esg_documents(filter)`
- **`powerbi_server`** — tools: `run_dax_query(dataset_id, dax)`, `refresh_dataset(dataset_id)`
- **`gleif_server`** — tools: `lookup_lei(name_or_lei)`, `search_lu_entities(entity_type)`

## Agent API

`src/greenlux_sentinel/api/app.py` — the HTTP surface Container Apps hosts and API Management
fronts. One REST route per specialist agent (not a single endpoint wrapping `supervisor.py`'s LLM
router): a direct caller should be able to hit a specific agent without depending on free-text
intent classification. Auth is a single shared bearer token (`api_auth_token` — empty/unset means
auth is skipped, the local-dev default); there's no per-caller identity or scoping beyond that —
a documented portfolio-scope simplification, not a production auth design.

| Route | Agent call |
|---|---|
| `POST /sql` | `sql_agent.ask(question)` |
| `POST /risk/{fund_id}` | `risk_agent.score_fund(fund_id)` |
| `POST /dashboard` | `dashboard_agent.update_dashboard(question)` |
| `POST /query-optimizer/propose` | `query_optimizer_agent.propose_index(sql)` |
| `POST /query-optimizer/{id}/approve`, `/reject` | the query-optimizer human-approval gate |
| `POST /report/draft/{fund_id}` | `report_agent.draft_report(fund_id)` |
| `POST /report/{id}/publish`, `/reject` | the report human-approval gate |
| `POST /etl/run` | `etl_agent.run_ingestion()` (also runs on `function_app.py`'s daily timer trigger) |
| `GET /healthz` | unauthenticated liveness/readiness probe |

The two human-in-the-loop gates (docs/RESPONSIBLE_AI.md#human-in-the-loop-gates) are their own
endpoints, not folded into the propose/draft response — a human decision has to be an explicit,
separate call.

## Data layer

See [DATA.md](DATA.md) for the full dataset breakdown. In short:

- **Azure Database for PostgreSQL Flexible Server** — the ~67k-row Morningstar European Funds
  table (breadth: BI + agentic SQL live here) plus the audit-log table.
- **Azure Cosmos DB (NoSQL/Core API)** — nested JSON documents: ETF holdings joined to
  company-level ESG ratings (depth: the risk model runs here). **Not** the Gremlin API — see
  [CLAUDE.md](../CLAUDE.md) for why that distinction matters.

## Azure service map

| Service | Role |
|---|---|
| Azure Database for PostgreSQL Flexible Server | Relational fund data + audit log |
| Azure Cosmos DB (NoSQL API) | ESG holdings documents |
| Azure Blob Storage / ADLS Gen2 | Raw Kaggle files, landing zone before ETL |
| Azure Functions (Consumption, Python, timer-triggered) | Scheduled ETL orchestration — resolved in favor of Functions over Data Factory in Phase 5 (`infra/modules/functions.bicep`): Python-native, matches `etl/*.py` directly with no pipeline-JSON translation layer, and Consumption pricing suits this project's once-a-day/on-demand run cadence |
| Azure AI Foundry (Azure OpenAI models) | LLM backing all agents |
| Azure Container Registry | Hosts the built agent API image (`Dockerfile`) that Container Apps pulls, passwordless via managed identity |
| Azure Container Apps | Hosts the agent API (`api/app.py`) |
| Azure API Management | Fronts the agent API |
| Azure Key Vault | Secrets: DB connection strings, API keys, PBI service principal |
| Azure Monitor + Log Analytics | Infra/app logging, feeds the audit trail alongside LangSmith |
| Microsoft Entra ID | Auth for the operator-facing surface and service principals |
| Power BI Service | Hosts the dynamic dashboard; agent talks to it via the Power BI REST API/XMLA |
| GitHub Actions | CI/CD (lint, test, deploy on merge) |

## Differentiation from agentic-rag-lu

See [CLAUDE.md](../CLAUDE.md#decisions-that-must-not-be-quietly-reverted) for the definitive list
of "don't rebuild this" boundaries. Summary table:

| | agentic-rag-lu | GreenLux Sentinel |
|---|---|---|
| Method | GraphRAG + vector RAG over regulatory text | Quantitative multi-agent analytics over structured data |
| Orchestration | OpenAI Responses API, native function-calling | LangGraph + LangChain + LangSmith |
| Cosmos DB API | Gremlin (graph) | NoSQL/Core (document) |
| Question shape | "Which sub-funds are Article 8, what does CSSF guidance say?" | "Is this fund's claim consistent with its holdings?" |
| Surface | Next.js chat UI + graph visualization, open-ended RAG conversation | Power BI dashboard + generated report (analyst-facing); a Next.js operator UI (`ui/`) that drives the five fixed specialist agents and shows the full result (query, score, report, citations) — not a chat, no RAG, no conversation history |
| MCP | Not used | Core requirement |

## Guardrails and human-in-the-loop

Detailed in [RESPONSIBLE_AI.md](RESPONSIBLE_AI.md). The short version: every agent tool call is
logged (Postgres audit table + LangSmith trace); numeric claims in the report must trace back to
a tool call result, not free-generated text; and the two write-capable agents (query-optimizer,
report) stop for human approval before their output takes effect.
