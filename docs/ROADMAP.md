# Roadmap

Phased so each milestone produces something runnable/demoable, not a big-bang integration at the
end. Check items off as they land; don't mark a phase done until its own checklist is clean.

## Phase 0 — Scaffolding (current)

- [x] Local repo + folder structure
- [x] Documentation set (this file and its siblings)
- [ ] GitHub remote created and pushed
- [ ] `pyproject.toml` dependencies pinned to real versions

## Phase 1 — Data profiling & ingestion

- [ ] Download all three Kaggle datasets, confirm actual columns against [DATA.md](DATA.md)
- [ ] Profile ticker overlap between ETF holdings and company ESG ratings datasets
- [ ] Finalize Postgres schema (`db/schema.sql`) based on confirmed columns
- [ ] ETL Agent: load Morningstar funds → Postgres
- [ ] ETL Agent: reshape + load ETF holdings/company ESG → Cosmos DB
- [ ] Audit log table live and being written to from the first ETL run

## Phase 2 — Core agents (no cloud yet, local Postgres/Cosmos emulator)

- [ ] NL2SQL Agent against local Postgres
- [ ] Query-Optimizer Agent + human-approval gate (local, mocked approval)
- [ ] Greenwashing-Risk Agent producing a real score on the Tier 2 subset
- [ ] LangGraph supervisor wiring all agents together
- [ ] LangSmith tracing enabled end to end

## Phase 3 — MCP servers

- [ ] `postgres_server`, `cosmos_server` implemented and swapped in for direct SDK calls
- [ ] `gleif_server` — live API integration
- [ ] `powerbi_server` — stubbed against a dev Power BI workspace

## Phase 4 — BI + reporting

- [ ] Power BI dataset connected to Postgres/Cosmos outputs
- [ ] Dashboard Agent: NL question → DAX query → live dashboard update
- [ ] Report Agent: multilingual (EN/FR/DE) draft generation + citation trail
- [ ] Report human-approval gate wired to a real "publish" action

## Phase 5 — Azure deployment

- [ ] Bicep IaC for the full service map in [ARCHITECTURE.md](ARCHITECTURE.md#azure-service-map)
- [ ] CI/CD via GitHub Actions
- [ ] Secrets in Key Vault, no local `.env` in any deployed path
- [ ] Azure Monitor/Log Analytics wired alongside the Postgres audit log

## Phase 6 — Polish for portfolio presentation

- [ ] README architecture diagram matches what's actually built
- [ ] Short demo video/GIF
- [ ] Sanity pass on [REQUIREMENTS_TRACEABILITY.md](REQUIREMENTS_TRACEABILITY.md) — every row still true
