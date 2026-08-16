"""Supervisor agent — routes an analyst request to the right specialist agent(s).

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Entry point of the LangGraph graph. Decides, per incoming request, whether it needs
    the NL2SQL agent, the greenwashing-risk agent, the dashboard agent, the report agent,
    the evidence agent, or a multi-hop chain of several of these, then merges their outputs
    into one response.

No human-in-the-loop gate here — routing itself is read-only. Gates live on the
query-optimizer and report agents (see docs/RESPONSIBLE_AI.md#human-in-the-loop-gates).

Phase 4 scope wired the five original read-only-or-single-gate specialists — sql_agent,
risk_agent, query_optimizer_agent, dashboard_agent, report_agent — each a single-hop leaf route
straight to END. Phase 8b added a sixth single-hop leaf, evidence_agent. Phase 8c (this revision)
adds a seventh route, "multi_hop", that does NOT go straight to a single specialist: a planner
node LLM-picks an ordered subset of _PLANNABLE_HOPS, a dispatch node runs them one at a
time (each hop's own try/except-and-record-not-raise contract, same as every run_*() below),
then a synthesize node calls evidence_agent.answer_with_evidence() with the gathered hop results
as precomputed_facts to produce one final cited-or-abstaining answer. The six original single-hop
routes are completely untouched by this — same nodes, same edges straight to END — so a request
that already knows which one specialist it needs (or the five dedicated REST endpoints in
api/app.py, which call agent functions directly and never touch this graph at all) is unaffected.

Phase 9b added a fourth plannable hop, "ml_risk" (`agents/ml_risk_agent.score_fund_composition`) —
the Phase 9 Tier 1 composition-anomaly ML signal, alongside "risk"'s Tier 2 holdings-based gap.
Deliberately a plannable *hop*, not a new top-level single-hop route/REST endpoint (out of scope
for what prompted it — see docs/PROGRESS_LOG.md's Phase 9b entry): its value is specifically in
`synthesize()` combining it with document evidence, and it's already reachable that way. Unlike
"risk" (5 issuer-verified ETFs only), "ml_risk" works for any fund with a claimed rating and
Tier 1 composition data once Postgres is backfilled (~41k funds) — the planner can include both
for the 4 funds that have both signals, or just "ml_risk" for everything else. The two signals are
kept in distinctly-named facts (never merged into one number) so `evidence_agent`'s LLM prompt —
and the final synthesized answer — cannot conflate them (CLAUDE.md decision #8).

report_agent's route only calls draft_report() — never publish_report()/reject_report(). The
human-approval gate (docs/RESPONSIBLE_AI.md#human-in-the-loop-gates) is a decision made outside
the graph, the same way query_optimizer_agent.apply_approved()/reject_proposal() are called
directly rather than being routable — a supervisor route would let the router itself decide to
publish, which defeats the gate. etl_agent is real (see its own module) but still not a graph
node — ingestion is a distinct on-demand operation, not something a question gets "routed" to.

Known simplification: the router only classifies which specialist (or plan) handles the request
from the free-text question; it does not do entity extraction. A "risk"/"report"/"evidence"
request must pass `fund_id` directly in the initial state (no agent here resolves "which fund is
this about" from conversation) — see route_request()'s docstring. The multi-hop planner has the
same limitation: it picks *which* specialists to run, not what fund they run against.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, TypedDict

from langgraph.graph import END, StateGraph

from greenlux_sentinel.agents import (
    dashboard_agent,
    evidence_agent,
    ml_risk_agent,
    query_optimizer_agent,
    report_agent,
    risk_agent,
    sql_agent,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

_ROUTES = ("sql", "risk", "query_optimizer", "dashboard", "report", "evidence", "multi_hop")

_ROUTER_SYSTEM_PROMPT = """Classify the analyst's request into exactly one route. Reply with \
ONLY the route word, nothing else.

Routes:
- sql: a question answerable by querying the fund database (counts, comparisons, listings, lookups).
- risk: a request specifically for a fund's Greenwashing Risk Score or its explanation, and \
nothing else.
- query_optimizer: a request to analyze/optimize a specific slow SQL query's performance.
- dashboard: a request to update/refresh a Power BI dashboard view for a question.
- report: a request to draft a multilingual fund report.
- evidence: a question that needs document evidence (fund disclosures, SFDR/CSSF regulatory \
text) to answer, but doesn't also need combining several other specialists' output first.
- multi_hop: a complex question that needs combining structured data (SQL and/or risk score(s)) \
*with* document evidence to produce one synthesized, cited answer.

Reply with exactly one of: sql, risk, query_optimizer, dashboard, report, evidence, multi_hop
"""

# The four specialists a multi-hop plan may chain -- deliberately excludes query_optimizer
# (write-side/gated, not a fact-gathering step) and dashboard/report (presentational/gated
# finalization, not evidence-gathering either). evidence_agent.answer_with_evidence() is also
# always the synthesis step at the end (see synthesize()), so including "evidence" as one of the
# *plannable* hops lets a plan front-load it (e.g. ["evidence"] alone, or ["sql", "evidence"]) --
# synthesize() just reuses that result rather than calling it twice. "risk" and "ml_risk" (Phase
# 9b) are two DIFFERENT quantitative signals, not alternatives of each other -- see this module's
# docstring and CLAUDE.md decision #8.
_PLANNABLE_HOPS = ("sql", "risk", "ml_risk", "evidence")
_MAX_HOPS = 5  # portfolio-scale cap, same spirit as etl_agent._GLEIF_LOOKUP_LIMIT
_DEFAULT_PLAN = ["evidence"]

_PLANNER_SYSTEM_PROMPT = """The analyst's request needs multiple steps to answer. Decide which \
specialists to run, in order, from: sql, risk, ml_risk, evidence. Reply with ONLY a JSON array of \
specialist names, nothing else -- no markdown, no explanation.

- sql: pull supporting facts/rows from the fund database.
- risk: compute the fund's Tier 2 Greenwashing Risk Score, from its real security-level holdings \
vs. its claim (requires a fund_id; only works for the small set of funds with verified holdings \
data -- if unsure whether a fund has this, include ml_risk too as a fallback).
- ml_risk: compute the fund's Tier 1 composition-anomaly score, a different ML-based signal for \
whether the fund's claimed sustainability rating looks typical for its objective portfolio \
composition (requires a fund_id; works for far more funds than risk). Not a replacement for risk \
-- include both when the question calls for the fullest possible risk picture.
- evidence: retrieve and cite document evidence, and produce the final synthesized answer -- \
almost always include this, usually last.

Example: ["sql", "risk", "ml_risk", "evidence"]
If unsure, reply with: ["evidence"]
"""

_PLAN_JSON_RE = re.compile(r"\[.*\]", re.DOTALL)


class SupervisorState(TypedDict, total=False):
    request: str
    fund_id: str | None
    route: str
    result: dict[str, Any]
    error: str
    # multi_hop-only fields (route == "multi_hop"):
    plan: list[str]
    hop_results: dict[str, Any]
    hop_errors: dict[str, str]
    trace: list[dict[str, Any]]
    final_answer: dict[str, Any]


def _default_llm() -> BaseChatModel:
    from langchain_openai import AzureChatOpenAI

    from greenlux_sentinel.config import get_settings

    settings = get_settings()
    return AzureChatOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        azure_deployment=settings.azure_openai_deployment,
        api_version=settings.azure_openai_api_version,
    )


def route_request(state: SupervisorState, llm: BaseChatModel | None = None) -> dict[str, Any]:
    """LLM-classify state["request"] into one of _ROUTES. Falls back to "sql" on an
    unrecognized reply rather than failing the whole request."""
    llm = llm or _default_llm()
    response = llm.invoke([("system", _ROUTER_SYSTEM_PROMPT), ("human", state["request"])])
    route = str(response.content).strip().lower()
    return {"route": route if route in _ROUTES else "sql"}


def run_sql(state: SupervisorState) -> dict[str, Any]:
    try:
        return {"result": sql_agent.ask(state["request"])}
    except Exception as e:  # noqa: BLE001 -- surfaced to the caller as state["error"], not swallowed
        return {"result": {}, "error": str(e)}


def run_risk(state: SupervisorState) -> dict[str, Any]:
    fund_id = state.get("fund_id")
    if not fund_id:
        return {"result": {}, "error": "risk route requires a fund_id in the initial state"}
    try:
        return {"result": risk_agent.score_fund(fund_id)}
    except Exception as e:  # noqa: BLE001
        return {"result": {}, "error": str(e)}


def run_query_optimizer(state: SupervisorState) -> dict[str, Any]:
    try:
        return {"result": query_optimizer_agent.propose_index(state["request"])}
    except Exception as e:  # noqa: BLE001
        return {"result": {}, "error": str(e)}


def run_dashboard(state: SupervisorState) -> dict[str, Any]:
    try:
        return {"result": dashboard_agent.update_dashboard(state["request"])}
    except Exception as e:  # noqa: BLE001
        return {"result": {}, "error": str(e)}


def run_report(state: SupervisorState) -> dict[str, Any]:
    fund_id = state.get("fund_id")
    if not fund_id:
        return {"result": {}, "error": "report route requires a fund_id in the initial state"}
    try:
        return {"result": report_agent.draft_report(fund_id)}
    except Exception as e:  # noqa: BLE001
        return {"result": {}, "error": str(e)}


def run_evidence(state: SupervisorState) -> dict[str, Any]:
    try:
        return {"result": evidence_agent.answer_with_evidence(state["request"], fund_id=state.get("fund_id"))}
    except Exception as e:  # noqa: BLE001
        return {"result": {}, "error": str(e)}


def _parse_plan(text: str) -> list[str]:
    match = _PLAN_JSON_RE.search(text.strip())
    if not match:
        return list(_DEFAULT_PLAN)
    try:
        hops = json.loads(match.group(0))
    except json.JSONDecodeError:
        return list(_DEFAULT_PLAN)
    valid = [h for h in hops if isinstance(h, str) and h in _PLANNABLE_HOPS][:_MAX_HOPS]
    return valid or list(_DEFAULT_PLAN)


def plan_request(state: SupervisorState, llm: BaseChatModel | None = None) -> dict[str, Any]:
    """LLM-plan an ordered list of hops (subset of _PLANNABLE_HOPS) for a multi_hop request.
    Falls back to _DEFAULT_PLAN on unparseable/empty output -- never raises, same fallback
    philosophy as route_request()'s fallback-to-"sql"."""
    llm = llm or _default_llm()
    response = llm.invoke([("system", _PLANNER_SYSTEM_PROMPT), ("human", state["request"])])
    return {"plan": _parse_plan(str(response.content)), "hop_results": {}, "hop_errors": {}, "trace": []}


def _facts_from_hops(hop_results: dict[str, Any]) -> dict[str, Any]:
    """Flatten whatever the sql/risk/ml_risk hops produced into the flat scalar-fact shape
    evidence_agent.answer_with_evidence()'s precomputed_facts expects. risk and ml_risk are kept
    under distinctly-named keys -- never merged into one "risk score" -- so the LLM prompt this
    feeds into cannot conflate the two different signals (CLAUDE.md decision #8)."""
    facts: dict[str, Any] = {}
    risk = hop_results.get("risk")
    if risk:
        if "risk_score" in risk:
            facts["greenwashing_risk_score"] = risk["risk_score"]
        if "explanation" in risk:
            facts["risk_explanation"] = risk["explanation"]
    ml_risk = hop_results.get("ml_risk")
    if ml_risk:
        if "composition_anomaly_score" in ml_risk:
            facts["composition_anomaly_score"] = ml_risk["composition_anomaly_score"]
        if "composition_anomaly_tier" in ml_risk:
            facts["composition_anomaly_tier"] = ml_risk["composition_anomaly_tier"]
        if "predicted_rating_bucket" in ml_risk:
            facts["ml_predicted_rating_bucket"] = ml_risk["predicted_rating_bucket"]
    sql = hop_results.get("sql")
    if sql and sql.get("rows"):
        for key, value in sql["rows"][0].items():
            if isinstance(value, (int, float, str)) and not isinstance(value, bool):
                facts[key] = value
    return facts


def dispatch(state: SupervisorState) -> dict[str, Any]:
    """Run the next un-run hop in state["plan"]. Each hop follows the same try/except-and-record
    contract as every run_*() function above -- a mid-chain failure becomes hop_errors data, not
    a crashed .invoke(). Loop termination: plan is bounded (_MAX_HOPS) and each call resolves
    exactly one hop into hop_results or hop_errors, so the set of un-run hops strictly shrinks."""
    plan = state.get("plan", [])
    hop_results = dict(state.get("hop_results", {}))
    hop_errors = dict(state.get("hop_errors", {}))
    trace = list(state.get("trace", []))

    next_hop = next((h for h in plan if h not in hop_results and h not in hop_errors), None)
    if next_hop is None:
        return {}

    fund_id = state.get("fund_id")
    try:
        if next_hop == "sql":
            result = sql_agent.ask(state["request"])
        elif next_hop == "risk":
            if not fund_id:
                raise ValueError("risk hop requires a fund_id in the initial state")
            result = risk_agent.score_fund(fund_id)
        elif next_hop == "ml_risk":
            if not fund_id:
                raise ValueError("ml_risk hop requires a fund_id in the initial state")
            result = ml_risk_agent.score_fund_composition(fund_id)
        else:  # "evidence" -- the only other _PLANNABLE_HOPS member
            # Pass whatever sql/risk/ml_risk facts already ran earlier in this same plan (dispatch
            # runs hops in plan order) so evidence's OWN drafting call can incorporate them -- not
            # just synthesize()'s later fallback path. Before this fix, a plan like
            # ["ml_risk", "evidence"] ran evidence in total isolation from ml_risk's result: since
            # "evidence" ends up in hop_results either way, synthesize() just reused evidence's own
            # answer verbatim, so a question explicitly asking to combine the two could never
            # succeed -- confirmed live (docs/PROGRESS_LOG.md's Phase 9c entry).
            result = evidence_agent.answer_with_evidence(
                state["request"], fund_id=fund_id, precomputed_facts=_facts_from_hops(hop_results) or None
            )
        hop_results[next_hop] = result
        trace.append({"hop": next_hop, "status": "ok"})
    except Exception as e:  # noqa: BLE001
        hop_errors[next_hop] = str(e)
        trace.append({"hop": next_hop, "status": "error", "error": str(e)})

    return {"hop_results": hop_results, "hop_errors": hop_errors, "trace": trace}


def synthesize(state: SupervisorState) -> dict[str, Any]:
    """Combine every hop's output into one final answer. Reuses the "evidence" hop's own answer
    directly if the plan already included it (avoids a duplicate evidence_agent call); otherwise
    calls evidence_agent.answer_with_evidence() with the other hops' facts pre-supplied."""
    hop_results = state.get("hop_results", {})

    if "evidence" in hop_results:
        final_answer = hop_results["evidence"]
        return {"final_answer": final_answer, "result": final_answer}

    try:
        final_answer = evidence_agent.answer_with_evidence(
            state["request"], fund_id=state.get("fund_id"), precomputed_facts=_facts_from_hops(hop_results) or None
        )
    except Exception as e:  # noqa: BLE001
        return {"final_answer": {}, "result": {}, "error": str(e)}

    return {"final_answer": final_answer, "result": final_answer}


def _select_route(state: SupervisorState) -> str:
    return state["route"]


def _next_dispatch_step(state: SupervisorState) -> str:
    plan = state.get("plan", [])
    hop_results = state.get("hop_results", {})
    hop_errors = state.get("hop_errors", {})
    if any(h not in hop_results and h not in hop_errors for h in plan):
        return "dispatch"
    return "synthesize"


def build_graph(llm: BaseChatModel | None = None):
    """Return the compiled LangGraph StateGraph."""
    graph = StateGraph(SupervisorState)
    graph.add_node("route", lambda state: route_request(state, llm=llm))
    graph.add_node("sql", run_sql)
    graph.add_node("risk", run_risk)
    graph.add_node("query_optimizer", run_query_optimizer)
    graph.add_node("dashboard", run_dashboard)
    graph.add_node("report", run_report)
    graph.add_node("evidence", run_evidence)
    graph.add_node("plan", lambda state: plan_request(state, llm=llm))
    graph.add_node("dispatch", dispatch)
    graph.add_node("synthesize", synthesize)

    graph.set_entry_point("route")
    graph.add_conditional_edges(
        "route",
        _select_route,
        {
            "sql": "sql",
            "risk": "risk",
            "query_optimizer": "query_optimizer",
            "dashboard": "dashboard",
            "report": "report",
            "evidence": "evidence",
            "multi_hop": "plan",
        },
    )
    graph.add_edge("sql", END)
    graph.add_edge("risk", END)
    graph.add_edge("query_optimizer", END)
    graph.add_edge("dashboard", END)
    graph.add_edge("report", END)
    graph.add_edge("evidence", END)
    graph.add_edge("plan", "dispatch")
    graph.add_conditional_edges("dispatch", _next_dispatch_step, {"dispatch": "dispatch", "synthesize": "synthesize"})
    graph.add_edge("synthesize", END)

    return graph.compile()
