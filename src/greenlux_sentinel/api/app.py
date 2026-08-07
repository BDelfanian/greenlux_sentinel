"""Agent API — HTTP surface for the LangGraph specialists, hosted on Container Apps
(docs/ARCHITECTURE.md#azure-service-map: "Container Apps hosts the LangGraph service + MCP
servers"; "API Management fronts the agent API").

One route per specialist agent (not a single generic /invoke wrapping supervisor.py's LLM
router) — a direct API consumer (Power BI, a future UI) should be able to call a specific agent
without depending on free-text intent classification. supervisor.py's router stays what it is:
the entry point for natural-language requests that don't already know which specialist they
need — not something this API wraps.

Auth: a single shared bearer token (settings.api_auth_token, Key Vault-backed in prod —
config.py, infra/modules/key-vault.bicep). This is a deliberate portfolio-scope simplification,
not a production-grade auth design — there's no per-caller identity and no scoping (e.g. a
read-only caller vs. one allowed to hit the two human-approval-gate endpoints), just "did the
caller present the shared secret." Documented here so it isn't mistaken for more than it is. If
api_auth_token is unset (the local-dev default), auth is skipped entirely so `uvicorn` works out
of the box without extra setup.

The two human-in-the-loop gates (docs/RESPONSIBLE_AI.md#human-in-the-loop-gates) are exposed as
their own endpoints (POST .../approve, POST .../reject) rather than folded into the
propose/draft response — same reasoning supervisor.py's docstring gives for keeping
publish_report()/apply_approved() out of the LangGraph routes: a human decision should be an
explicit, separate call, never something a single route can trigger on its own.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from greenlux_sentinel.agents import (
    dashboard_agent,
    etl_agent,
    query_optimizer_agent,
    report_agent,
    risk_agent,
    sql_agent,
)
from greenlux_sentinel.config import get_settings

app = FastAPI(title="GreenLux Sentinel Agent API")


def require_auth(authorization: Annotated[str | None, Header()] = None) -> None:
    token = get_settings().api_auth_token
    if not token:
        return  # local dev: auth disabled when no token is configured, see module docstring
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")


_AUTH = Depends(require_auth)


def _call(fn: Callable[..., Any], *args: Any) -> Any:
    """Run an agent function, turning its ValueError (this codebase's convention for a
    caller-fixable input problem — bad fund_id, non-pending proposal, etc.) into a 400 instead
    of an unhandled 500."""
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class SqlRequest(BaseModel):
    question: str


class DashboardRequest(BaseModel):
    question: str


class ProposeIndexRequest(BaseModel):
    sql: str


class ApprovalRequest(BaseModel):
    actor: str


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Unauthenticated — Container Apps liveness/readiness probe target."""
    return {"status": "ok"}


@app.post("/etl/run", dependencies=[_AUTH])
def post_etl_run() -> dict[str, Any]:
    """Manual/on-demand trigger for the same full ingestion the Functions timer trigger runs
    on a schedule (functions/function_app.py) — synchronous, so this can take a while on a full
    data_dir; there's no async job-status pattern here, by portfolio-project scope choice."""
    return _call(etl_agent.run_ingestion)


@app.post("/sql", dependencies=[_AUTH])
def post_sql(body: SqlRequest) -> dict[str, Any]:
    return _call(sql_agent.ask, body.question)


@app.post("/risk/{fund_id}", dependencies=[_AUTH])
def post_risk(fund_id: str) -> dict[str, Any]:
    return _call(risk_agent.score_fund, fund_id)


@app.post("/dashboard", dependencies=[_AUTH])
def post_dashboard(body: DashboardRequest) -> dict[str, Any]:
    return _call(dashboard_agent.update_dashboard, body.question)


@app.post("/query-optimizer/propose", dependencies=[_AUTH])
def post_propose_index(body: ProposeIndexRequest) -> dict[str, Any]:
    return _call(query_optimizer_agent.propose_index, body.sql)


@app.post("/query-optimizer/{proposal_id}/approve", dependencies=[_AUTH])
def post_approve_index(proposal_id: str, body: ApprovalRequest) -> dict[str, str]:
    _call(query_optimizer_agent.apply_approved, proposal_id, body.actor)
    return {"status": "approved"}


@app.post("/query-optimizer/{proposal_id}/reject", dependencies=[_AUTH])
def post_reject_index(proposal_id: str, body: ApprovalRequest) -> dict[str, str]:
    _call(query_optimizer_agent.reject_proposal, proposal_id, body.actor)
    return {"status": "rejected"}


@app.post("/report/draft/{fund_id}", dependencies=[_AUTH])
def post_draft_report(fund_id: str) -> dict[str, Any]:
    return _call(report_agent.draft_report, fund_id)


@app.post("/report/{report_id}/publish", dependencies=[_AUTH])
def post_publish_report(report_id: str, body: ApprovalRequest) -> dict[str, str]:
    _call(report_agent.publish_report, report_id, body.actor)
    return {"status": "published"}


@app.post("/report/{report_id}/reject", dependencies=[_AUTH])
def post_reject_report(report_id: str, body: ApprovalRequest) -> dict[str, str]:
    _call(report_agent.reject_report, report_id, body.actor)
    return {"status": "rejected"}
