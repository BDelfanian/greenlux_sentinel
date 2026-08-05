# Roadmap

Phased so each milestone produces something runnable/demoable, not a big-bang integration at the
end. Check items off as they land; don't mark a phase done until its own checklist is clean.

## Phase 0 — Scaffolding (current)

- [x] Local repo + folder structure
- [x] Documentation set (this file and its siblings)
- [x] GitHub remote created and pushed
- [x] `pyproject.toml` dependencies pinned to real versions

## Phase 1 — Data profiling & ingestion

- [x] Download all three Kaggle datasets, confirm actual columns against [DATA.md](DATA.md)
      (real files in `data/raw/`, profiled in `notebooks/01_data_profiling.ipynb` — see
      [DATA.md](DATA.md#first-milestone-data-profiling) for what changed vs. the original
      best-guess schema)
- [x] Profile ticker overlap between ETF holdings and company ESG ratings datasets
      (real overlap: ~14% of unique holding tickers, 0–90.3% per-ETF, median 16% — much lower
      than the ~79% used in early synthetic fixtures; see DATA.md)
- [x] Finalize Postgres schema (`db/schema.sql`) based on confirmed columns — reconciled
      against the real Morningstar export (dropped sharpe/treynor/alpha/beta, which don't
      exist in the real data; added domicile/management_company derivation + E/S/G subscores,
      which do)
- [x] ETL Agent: load Morningstar funds → Postgres (`etl/load_funds_postgres.py`, transform
      logic unit-tested and smoke-tested against the full real 67k-row export; upsert path
      unit-tested via injected connection — not yet run against a live Postgres instance)
- [x] ETL Agent: reshape + load ETF holdings/company ESG → Cosmos DB
      (`etl/load_esg_cosmos.py`, same caveat — unit- and smoke-tested against the full real
      132k-row holdings file, not yet run against live Cosmos DB)
- [x] Audit log table live and being written to from the first ETL run (`db/audit.py`,
      called from both loaders; verified via unit test, not a live DB)

**Still open before Phase 1 is fully done:** an actual Postgres/Cosmos instance (local emulator
or Azure) to run `load()` against for real, rather than just unit/smoke-testing the transform
logic. No Docker was available in the dev environment used so far — see Phase 2 below.

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
