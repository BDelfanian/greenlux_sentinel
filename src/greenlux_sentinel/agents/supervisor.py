"""Supervisor agent — routes an analyst request to the right specialist agent(s).

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Entry point of the LangGraph graph. Decides, per incoming request, whether it needs
    the NL2SQL agent, the greenwashing-risk agent, the dashboard agent, the report agent,
    or some combination, then merges their outputs into one response.

No human-in-the-loop gate here — routing itself is read-only. Gates live on the
query-optimizer and report agents (see docs/RESPONSIBLE_AI.md#human-in-the-loop-gates).

Phase 2 scope: wires the three specialist agents actually implemented so far — sql_agent,
risk_agent, query_optimizer_agent. etl_agent/dashboard_agent/report_agent stay
NotImplementedError stubs until Phase 3/4 (see docs/ROADMAP.md) and are not graph nodes yet.

Known simplification: the router only classifies which specialist handles the request from the
free-text question; it does not do entity extraction. A "risk" request must pass `fund_id`
directly in the initial state (the dashboard/report agents that would normally resolve "which
fund is this about" from conversation don't exist yet) — see route_request()'s docstring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

from langgraph.graph import END, StateGraph

from greenlux_sentinel.agents import query_optimizer_agent, risk_agent, sql_agent

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

_ROUTES = ("sql", "risk", "query_optimizer")

_ROUTER_SYSTEM_PROMPT = """Classify the analyst's request into exactly one route. Reply with \
ONLY the route word, nothing else.

Routes:
- sql: a question answerable by querying the fund database (counts, comparisons, listings, lookups).
- risk: a request specifically about a fund's Greenwashing Risk Score or its explanation.
- query_optimizer: a request to analyze/optimize a specific slow SQL query's performance.

Reply with exactly one of: sql, risk, query_optimizer
"""


class SupervisorState(TypedDict, total=False):
    request: str
    fund_id: str | None
    route: str
    result: dict[str, Any]
    error: str


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


def _select_route(state: SupervisorState) -> str:
    return state["route"]


def build_graph(llm: BaseChatModel | None = None):
    """Return the compiled LangGraph StateGraph."""
    graph = StateGraph(SupervisorState)
    graph.add_node("route", lambda state: route_request(state, llm=llm))
    graph.add_node("sql", run_sql)
    graph.add_node("risk", run_risk)
    graph.add_node("query_optimizer", run_query_optimizer)

    graph.set_entry_point("route")
    graph.add_conditional_edges(
        "route", _select_route, {"sql": "sql", "risk": "risk", "query_optimizer": "query_optimizer"}
    )
    graph.add_edge("sql", END)
    graph.add_edge("risk", END)
    graph.add_edge("query_optimizer", END)

    return graph.compile()
