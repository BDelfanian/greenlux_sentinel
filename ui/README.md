# GreenLux Sentinel — Agent Console

Operator UI for the GreenLux Sentinel multi-agent system (CLAUDE.md decision #5). One page: ask a
question in plain text, it's routed by the LangGraph supervisor to whichever specialist agent can
answer it (NL2SQL, greenwashing-risk, Power BI dashboard, query-optimizer, multilingual report,
document-evidence — Phase 8b), or, for a question that needs several combined, planned and chained
automatically across them (`multi_hop` — Phase 8c). The full result — not just a number — is
rendered: the generated SQL/DAX, the risk explanation and caveat, the report body in EN/FR/DE with
citations, the evidence agent's cited-or-abstaining answer with document citations, the multi-hop
plan/trace, plus the human approve/reject actions for the two agents that require one
(query-optimizer, report). A raw-JSON panel is always available for anything the structured view
doesn't surface.

This is **not** a general chat interface — no conversation history, no free-form agent loop, no
open-ended RAG conversation. It's a thin client over seven fixed, schema-constrained agents that
already exist in `src/greenlux_sentinel/agents/`; see CLAUDE.md decision #5 for why that
distinction matters (it's what keeps this different from the sibling project's actual RAG chat
app — see CLAUDE.md decision #4's Phase 8 correction for the fuller differentiation story, since
this project does now retrieve and cite documents too, just not through a chat interface).

## Running locally

Requires the FastAPI Agent API running separately (see the repo root README's "Getting started"):

```powershell
npm install
cp .env.local.example .env.local   # AGENT_API_URL=http://localhost:8000 by default
npm run dev                        # http://localhost:3000
```

`AGENT_API_TOKEN` in `.env.local` only needs a value when pointed at a deployment that has
`api_auth_token` set (the local dev API leaves it blank, so auth is skipped — see
`src/greenlux_sentinel/api/app.py`'s module docstring). It's read server-side only
(`src/lib/agent-api.ts`), inside Server Actions — never sent to the browser.

## Structure

- `src/lib/agent-api.ts` — server-only fetch client for the Agent API's `/ask` and the four
  human-gate endpoints (`/query-optimizer/{id}/approve|reject`, `/report/{id}/publish|reject`)
- `src/app/actions.ts` — the Server Actions the UI calls (`'use server'`)
- `src/components/AskForm.tsx` — the question form
- `src/components/ResultView.tsx` — route-specific rendering, branching on `AskResult.route`
- `src/components/GateAction.tsx` — the reusable approve/reject form used by the two gated routes
