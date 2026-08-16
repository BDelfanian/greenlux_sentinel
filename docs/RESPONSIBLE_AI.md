# Responsible AI

## Principles

1. **Every agent action is logged.** Tool calls, prompts, and responses are written to a Postgres
   `audit_log` table (who/what agent, what tool, what input, what output, timestamp, LangSmith
   trace ID) and separately traced in LangSmith. The two logs must cross-reference by trace ID so
   either can be used to reconstruct a decision after the fact.
2. **Numeric claims must be tool-sourced.** The Report Agent and Dashboard Agent are not allowed
   to state a number that didn't come from a tool call result in the same run. Enforced by an
   output validator in `guardrails/validators.py` that checks generated text against the set of
   values actually returned by tool calls in that run's trace, rejecting/regenerating on mismatch.
3. **The risk score is presented as a proxy indicator, never as a compliance finding.** Every
   surface that shows the Greenwashing Risk Score (dashboard, report) must carry the methodology
   caveat from [DATA.md](DATA.md#ground-truth-methodology). This is a guardrail on the *content*,
   not just the *process*. **Since Phase 9**, this also covers `ml/greenwashing_risk_model.py`'s
   composition-anomaly score — a different, ML-based signal from the same-named risk score, with
   its own `CAVEAT` string carrying the equivalent framing ("data-driven proxy... not a
   determination of greenwashing, SFDR non-compliance, or any other regulatory/legal finding") and
   an explicit note that it's a coarser, population-relative signal, not a substitute for the
   holdings-based one. Unlike Principle 2's black-box LLM outputs, this model is **interpretable
   by construction** — `train()` returns real feature importances and a full held-out metrics
   report (accuracy, macro-F1, per-class precision/recall, confusion matrix), not just a score —
   so its behavior can be audited directly, not just its outputs validated after the fact.
   **Since Phase 9b**, this score can also flow into a `multi_hop` synthesized answer via
   `agents/ml_risk_agent.py` — Principle 5's grounding guardrail still applies to that answer's
   *document* citations, and the composition-anomaly value is passed to the drafting LLM under its
   own distinct fact key (never merged with Tier 2's `risk_score`), so a synthesized answer can't
   misattribute one signal's number to the other.
4. **PII redaction.** Any free-text fields ingested (e.g. company descriptions) pass through a
   redaction step before being stored or surfaced, even though the datasets in use are
   company/fund-level, not individual-level — defensive by default.
5. **Grounded claims must cite their source or abstain.** The Evidence Agent (Phase 8b) is not
   allowed to answer a question without either citing a real source for every claim, or explicitly
   answering "I don't know" when nothing it has actually supports an answer. Two distinct citation
   forms, not one conflated marker: `[doc:<id>]` for a claim sourced from a real, retrieved
   document passage, `[fact:<key>]` (Phase 9c) for a claim sourced from a precomputed
   tool-sourced fact (e.g. `composition_anomaly_score`) that has no document to cite. Enforced by
   `guardrails/grounding.py`'s `document_grounded_or_abstained()`, the same reject/regenerate
   pattern as Principle 2, extended from *numeric* tool-sourcing to *citation-marker* tool-sourcing
   for both forms. Like Principle 3's risk-score caveat, this is a citation-validity check, not
   full semantic/entailment verification — it confirms a cited document was actually retrieved (or
   a cited fact actually supplied) this run, not that the source truly supports the specific claim
   made about it. **Phase 9c correction**: the original single-marker design required a `[doc:<id>]`
   on every claim including numeric facts, which had no document to cite — live testing found this
   made the model abstain even when it had a real, tool-sourced number to state (see
   docs/PROGRESS_LOG.md's Phase 9c entry for the live transcript that surfaced it). The two-marker
   design fixes that without weakening the guardrail: a `[fact:<key>]` is still checked against the
   real facts actually supplied, not accepted on trust.

## Human-in-the-loop gates

Two, and only two, agent actions require a human approval step before taking effect. Read-only
analysis (SQL queries, dashboard refreshes, risk-score computation) runs autonomously — gating
everything would make the "agentic" framing meaningless.

| Action | Agent | Gate |
|---|---|---|
| Applying a proposed index/schema change | Query-Optimizer Agent | Proposal is queued; a human reviews the DDL and the `EXPLAIN ANALYZE` before/after estimate, then approves or rejects |
| Publishing the final report | Report Agent | Draft is generated and shown with its full citation trail; a human marks it "approved" before it's exposed as final output |

Both gates and their outcomes (approved/rejected/edited) are themselves audit-logged.

## Audit log schema (see `src/greenlux_sentinel/db/audit_log_schema.sql`)

Minimum columns: `id`, `timestamp`, `agent_name`, `tool_name`, `input_summary`, `output_summary`,
`langsmith_trace_id`, `required_approval` (bool), `approval_status`, `approved_by`,
`approved_at`.

## What this project is not claiming

This is a portfolio-scale demonstration of Responsible AI patterns (logging, tool-sourced
grounding, human approval gates), not a production compliance system and not a legal
determination of greenwashing or SFDR non-compliance for any real fund. Say this explicitly in
the README and in the generated report template.

The Phase 9 composition-anomaly model is a portfolio-scope evaluation, not a governed production
ML system: no drift monitoring, no scheduled retraining pipeline, and (as of Phase 9) no live
Postgres run — trained and evaluated against the local `data/raw/*.csv` files only.
