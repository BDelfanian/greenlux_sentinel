"use server";

import {
  AgentApiError,
  approveIndexProposal,
  ask,
  publishReport,
  rejectIndexProposal,
  rejectReport,
  type AskResult,
} from "@/lib/agent-api";

export type AskFormState = {
  data?: AskResult;
  error?: string;
};

export async function askQuestion(_prevState: AskFormState, formData: FormData): Promise<AskFormState> {
  const question = String(formData.get("question") ?? "").trim();
  const fundId = String(formData.get("fund_id") ?? "").trim();

  if (!question) {
    return { error: "Enter a question." };
  }

  try {
    const data = await ask(question, fundId || null);
    return { data };
  } catch (err) {
    return { error: err instanceof AgentApiError ? err.message : "Request failed." };
  }
}

export type GateActionState = {
  status?: string;
  error?: string;
};

async function runGateAction(action: () => Promise<{ status: string }>): Promise<GateActionState> {
  try {
    const result = await action();
    return { status: result.status };
  } catch (err) {
    return { error: err instanceof AgentApiError ? err.message : "Request failed." };
  }
}

export async function approveIndex(
  proposalId: string,
  _prevState: GateActionState,
  formData: FormData,
): Promise<GateActionState> {
  const actor = String(formData.get("actor") ?? "").trim();
  if (!actor) return { error: "Enter your name to approve this." };
  return runGateAction(() => approveIndexProposal(proposalId, actor));
}

export async function rejectIndex(
  proposalId: string,
  _prevState: GateActionState,
  formData: FormData,
): Promise<GateActionState> {
  const actor = String(formData.get("actor") ?? "").trim();
  if (!actor) return { error: "Enter your name to reject this." };
  return runGateAction(() => rejectIndexProposal(proposalId, actor));
}

export async function publishReportAction(
  reportId: string,
  _prevState: GateActionState,
  formData: FormData,
): Promise<GateActionState> {
  const actor = String(formData.get("actor") ?? "").trim();
  if (!actor) return { error: "Enter your name to publish this." };
  return runGateAction(() => publishReport(reportId, actor));
}

export async function rejectReportAction(
  reportId: string,
  _prevState: GateActionState,
  formData: FormData,
): Promise<GateActionState> {
  const actor = String(formData.get("actor") ?? "").trim();
  if (!actor) return { error: "Enter your name to reject this." };
  return runGateAction(() => rejectReport(reportId, actor));
}
