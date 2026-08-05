"""Supervisor agent — routes an analyst request to the right specialist agent(s).

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Entry point of the LangGraph graph. Decides, per incoming request, whether it needs
    the NL2SQL agent, the greenwashing-risk agent, the dashboard agent, the report agent,
    or some combination, then merges their outputs into one response.

No human-in-the-loop gate here — routing itself is read-only. Gates live on the
query-optimizer and report agents (see docs/RESPONSIBLE_AI.md#human-in-the-loop-gates).

TODO(Phase 2):
    - Build the StateGraph with LangGraph, register each specialist as a node
    - Define the routing/conditional-edge logic
    - Wire LangSmith tracing on the compiled graph
"""

from __future__ import annotations


def build_graph():
    """Return the compiled LangGraph StateGraph. Not yet implemented."""
    raise NotImplementedError("Phase 2 — see docs/ROADMAP.md")
