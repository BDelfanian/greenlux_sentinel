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
   other project's core mechanism. **Correction (Phase 8):** the user explicitly overrode this —
   wanting the tool to answer complex questions by combining structured fund data with real
   document evidence (fund disclosures, SFDR/CSSF regulatory text), synthesizing one answer, and
   explicitly abstaining ("I don't know") when evidence is missing, which a structured-summary
   layer alone can't do. The user chose the heaviest, most literal option — Azure AI Search, the
   same service named in this decision — and to include general SFDR/CSSF text alongside
   fund-specific documents, so there is now real document-corpus overlap with agentic-rag-lu, not
   just mechanism overlap; differentiation no longer rests on "we don't touch this kind of data."
   What still differentiates the two: **mechanism of use**, not the document set.
   agentic-rag-lu answers open-ended questions via full GraphRAG (Microsoft's library was
   evaluated and dropped — real Windows/Rust packaging blocker, and independently judged
   overkill for an ~11-document corpus with no hidden entity structure to discover — replaced by
   lightweight LLM entity tagging, see `etl/extract_document_entities.py`'s docstring) plus a
   hand-rolled Cosmos DB **Gremlin** graph (that project's own actual implementation, confirmed by
   reading it directly — also not the graphrag package) and free-form conversational RAG chat.
   This project fuses that document evidence with structured quantitative fund analytics
   (Postgres/Cosmos Tier 1/Tier 2 data) into **one synthesized, cited-or-abstaining answer**,
   delivered through the fixed multi-hop LangGraph pipeline in decision #6, not a chat interface —
   consistent with decision #3's Cosmos-stays-NoSQL/Core boundary (the new document index lives in
   Azure AI Search, Cosmos usage here is untouched) and decision #5's existing framing of this
   project's UI as a thin client over fixed specialist agents, never free-form chat. New agent:
   `agents/evidence_agent.py`. New guardrail: `guardrails/grounding.py`
   (docs/RESPONSIBLE_AI.md#principles, Principle 5). Full detail: docs/PROGRESS_LOG.md's
   Phase 8a/8b/8c entries.

5. **Operator UI: Next.js app calling the Agent API.** Originally "no chat frontend" (the concern
   was duplicating agentic-rag-lu's Next.js chat app over RAG). **Correction (Phase 7):** the user
   explicitly overrode this — direct HTTP calls to the Agent API were too inconvenient for
   day-to-day use, and asked for a Next.js UI where a question goes in and the full result (route
   taken, generated SQL/DAX, risk score + explanation, multilingual report, citations, audit
   trail) comes back on one page. This is still not the same product as agentic-rag-lu: that one
   answers open-ended questions over regulatory PDF text via RAG + graph traversal; this one is a
   thin client over the five fixed, schema-constrained specialist agents (sql/risk/dashboard/
   query_optimizer/report) — no free-form chat history, no RAG, one request in, one structured
   result out. Lives in `ui/` (see that directory's own notes for the stack). Power BI + the
   generated report remain the primary *analyst-facing* deliverable; this UI is for
   driving/inspecting the agents directly, which is a different audience (developer/operator).
   **Update (Phase 8b/8c):** two more routes joined the original five —
   `evidence` (single-hop, `agents/evidence_agent.py`) and `multi_hop` (a supervisor-planned chain
   of several specialists, see decision #6) — still no free-form chat, still one request in, one
   structured result out, just a richer result shape for these two routes (`ResultView.tsx`'s
   `EvidenceResult`/`MultiHopResult`).

6. **Orchestration is LangGraph/LangChain/LangSmith,** not native OpenAI function-calling (which
   agentic-rag-lu uses). This is a hard project requirement, not a style preference.
   **Update (Phase 8c):** `supervisor.py`'s graph gained a `multi_hop` route — a planner node
   LLM-picks an ordered subset of `{sql, risk, evidence}`, a dispatch node runs them one at a
   time (each hop's own try/except-and-record contract, never raising), then a synthesize node
   calls `evidence_agent.answer_with_evidence()` with the gathered facts to produce one final
   answer. This is supervisor-*planned* multi-hop orchestration, not free-form agent-to-agent
   messaging (evaluated and explicitly rejected in favor of this — a planned pipeline keeps the
   human-in-the-loop gates and audit trail in decision #7 exactly as tractable as the original
   single-hop design). The six original single-hop routes/edges are completely untouched.

7. **Human-in-the-loop gates:** required before (a) the report agent finalizes/publishes a
   report, and (b) the query-optimizer agent applies a schema change (e.g. creating an index) in
   Postgres. Read-only agent actions (analysis, dashboard queries) run autonomously. Don't remove
   these gates for convenience — see [docs/RESPONSIBLE_AI.md](docs/RESPONSIBLE_AI.md).

8. **`ml/greenwashing_risk_model.py` is a real, trained classical ML model (Phase 9) — the first
   non-LLM learned model in the system,** not the unimplemented stub it was through Phase 8. It
   predicts a fund's own REAL, existing claimed `sustainability_rating` bucket (Low/Medium/High)
   from 41 OBJECTIVE Tier 1 portfolio-composition columns (sector/asset-class/market-cap/
   credit-quality/controversial-business-involvement — newly loaded onto `funds`, see
   `etl/load_funds_postgres.COMPOSITION_COLUMNS`), deliberately excluding the claimed-side E/S/G
   subscores to avoid circularity. Its own `predict_proba` gives a
   `composition_anomaly_score`/tier signal, written to the new `fund_sustainability_anomaly_scores`
   table. **This still respects decision #1** — it predicts a real Morningstar field, not a
   fabricated greenwashing/SFDR label. **It is a different, coarser signal from decision #2's Tier
   2 `compute_gap()`, not a replacement for it** — Tier 1 breadth (~41k funds, population-relative
   composition normality) vs. Tier 2 depth (4 funds, real security-level holdings-vs-claim gap);
   the two are not expected to agree, and a worked example where they don't is documented in
   [docs/DATA.md](docs/DATA.md#tier-1-composition-anomaly-model-ml) and
   `notebooks/02_ml_model_worked_example.ipynb`. Not wired into `etl_agent.run_ingestion()`, a new
   LangGraph agent node, or a new API route this pass — deliberately scoped down; see
   docs/PROGRESS_LOG.md's Phase 9 entry. Not live-Postgres-verified as of Phase 9 (no Azure
   Postgres credentials available in that session) — trained/evaluated against the local
   `data/raw/*.csv` files only.

## Repo map

- `src/greenlux_sentinel/agents/` — LangGraph agent nodes (supervisor + specialists, incl.
  `evidence_agent.py` since Phase 8b)
- `src/greenlux_sentinel/mcp_servers/` — MCP tool servers (Postgres, Cosmos, Power BI, GLEIF,
  `search_server.py`/Azure AI Search since Phase 8b)
- `src/greenlux_sentinel/etl/` — ingestion scripts (Kaggle CSVs/JSON → Postgres/Cosmos; document
  corpus fetch/tag/index → Azure AI Search since Phase 8a)
- `src/greenlux_sentinel/ml/` — greenwashing-risk scoring model. Since Phase 9:
  `greenwashing_risk_model.py` (the real trained classifier + scoring logic),
  `train_greenwashing_risk_model.py` (runnable training entry point), `artifacts/` (gitignored
  model artifact, train-on-demand)
- `src/greenlux_sentinel/guardrails/` — output validators, PII redaction, tool-sourced-numbers
  enforcement, document-citation grounding (`grounding.py` since Phase 8b)
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
