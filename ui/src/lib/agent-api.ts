// Server-only client for the FastAPI agent API (src/greenlux_sentinel/api/app.py). Never imported
// from a Client Component -- AGENT_API_TOKEN must not reach the browser bundle.

export class AgentApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "AgentApiError";
  }
}

async function callAgentApi<T>(path: string, body?: unknown): Promise<T> {
  const baseUrl = process.env.AGENT_API_URL;
  if (!baseUrl) {
    throw new AgentApiError(0, "AGENT_API_URL is not configured (see .env.local.example)");
  }

  const token = process.env.AGENT_API_TOKEN;
  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body ?? {}),
    cache: "no-store",
  });

  const text = await response.text();
  const data = text ? JSON.parse(text) : {};

  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : response.statusText;
    throw new AgentApiError(response.status, detail);
  }

  return data as T;
}

// Mirrors evidence_agent.answer_with_evidence()'s return shape.
export type DocumentCitation = {
  id: string;
  doc_type: "kiid" | "prospectus" | "regulation" | "cssf_guidance";
  content?: string;
  source_url?: string | null;
};

export type EvidenceResultData = {
  answer: string;
  document_citations: DocumentCitation[];
  numeric_citations: number[];
  abstained: boolean;
  sources_considered: number;
};

// Mirrors supervisor.SupervisorState in agents/supervisor.py -- Phase 8c added the multi_hop-only
// fields (plan/hop_results/hop_errors/trace/final_answer), only populated when route === "multi_hop".
export type AskResult = {
  request: string;
  fund_id?: string | null;
  route?: "sql" | "risk" | "query_optimizer" | "dashboard" | "report" | "evidence" | "multi_hop";
  result?: Record<string, unknown>;
  error?: string;
  plan?: string[];
  hop_results?: Record<string, Record<string, unknown>>;
  hop_errors?: Record<string, string>;
  trace?: { hop: string; status: "ok" | "error"; error?: string }[];
  final_answer?: EvidenceResultData;
};

export function ask(question: string, fundId: string | null): Promise<AskResult> {
  return callAgentApi<AskResult>("/ask", { question, fund_id: fundId || null });
}

export function approveIndexProposal(proposalId: string, actor: string): Promise<{ status: string }> {
  return callAgentApi(`/query-optimizer/${encodeURIComponent(proposalId)}/approve`, { actor });
}

export function rejectIndexProposal(proposalId: string, actor: string): Promise<{ status: string }> {
  return callAgentApi(`/query-optimizer/${encodeURIComponent(proposalId)}/reject`, { actor });
}

export function publishReport(reportId: string, actor: string): Promise<{ status: string }> {
  return callAgentApi(`/report/${encodeURIComponent(reportId)}/publish`, { actor });
}

export function rejectReport(reportId: string, actor: string): Promise<{ status: string }> {
  return callAgentApi(`/report/${encodeURIComponent(reportId)}/reject`, { actor });
}
