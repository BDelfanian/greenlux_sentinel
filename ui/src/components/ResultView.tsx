"use client";

import { useState } from "react";
import type { AskResult, DocumentCitation } from "@/lib/agent-api";
import { approveIndex, publishReportAction, rejectIndex, rejectReportAction } from "@/app/actions";
import { GateAction } from "./GateAction";

function RowsTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-black/60 dark:text-white/60">No rows returned.</p>;
  }
  const columns = Object.keys(rows[0]);
  return (
    <div className="overflow-x-auto rounded border border-black/10 dark:border-white/15">
      <table className="w-full min-w-max text-left text-sm">
        <thead className="bg-black/5 dark:bg-white/10">
          <tr>
            {columns.map((col) => (
              <th key={col} className="px-3 py-2 font-medium whitespace-nowrap">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-black/10 dark:border-white/10">
              {columns.map((col) => (
                <td key={col} className="px-3 py-2 whitespace-nowrap">
                  {String(row[col] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="overflow-x-auto rounded bg-black/5 p-3 text-sm dark:bg-white/10">
      <code>{children}</code>
    </pre>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold tracking-wide text-black/60 uppercase dark:text-white/50">{title}</h3>
      {children}
    </div>
  );
}

function SqlResult({ result }: { result: Record<string, unknown> }) {
  const sql = String(result.sql ?? "");
  const rows = (result.rows as Record<string, unknown>[]) ?? [];
  return (
    <div className="space-y-4">
      <Section title="Generated SQL">
        <CodeBlock>{sql}</CodeBlock>
      </Section>
      <Section title={`Rows (${rows.length})`}>
        <RowsTable rows={rows} />
      </Section>
    </div>
  );
}

function RiskResult({ result }: { result: Record<string, unknown> }) {
  return (
    <div className="space-y-4">
      <Section title="Greenwashing Risk Score">
        <div className="text-4xl font-bold">{String(result.risk_score ?? "-")}</div>
        <p className="text-xs text-black/50 dark:text-white/50">0-100, higher = bigger gap between claim and holdings</p>
      </Section>
      <Section title="Explanation">
        <p className="text-sm">{String(result.explanation ?? "")}</p>
      </Section>
      <Section title="Caveat">
        <p className="text-sm text-black/60 italic dark:text-white/60">{String(result.caveat ?? "")}</p>
      </Section>
    </div>
  );
}

function DashboardResult({ result }: { result: Record<string, unknown> }) {
  const dax = String(result.dax ?? "");
  const rows = (result.rows as Record<string, unknown>[]) ?? [];
  return (
    <div className="space-y-4">
      <Section title={`DAX Query (dataset ${String(result.dataset_id ?? "")})`}>
        <CodeBlock>{dax}</CodeBlock>
      </Section>
      <Section title={`Rows (${rows.length})`}>
        <RowsTable rows={rows} />
      </Section>
    </div>
  );
}

function QueryOptimizerResult({ result }: { result: Record<string, unknown> }) {
  const proposalId = String(result.proposal_id ?? "");
  return (
    <div className="space-y-4">
      <Section title="Proposed DDL">
        <CodeBlock>{String(result.ddl ?? "")}</CodeBlock>
      </Section>
      <Section title="Estimated improvement">
        <p className="text-sm">{String(result.estimated_improvement ?? "")}</p>
      </Section>
      <Section title={`Human approval required (proposal ${proposalId})`}>
        <div className="flex flex-wrap gap-3">
          <GateAction label="Approve & apply" tone="approve" action={approveIndex.bind(null, proposalId)} />
          <GateAction label="Reject" tone="reject" action={rejectIndex.bind(null, proposalId)} />
        </div>
      </Section>
    </div>
  );
}

const LANGUAGES = [
  { key: "en", label: "English" },
  { key: "fr", label: "Francais" },
  { key: "de", label: "Deutsch" },
] as const;

function ReportResult({ result }: { result: Record<string, unknown> }) {
  const [lang, setLang] = useState<(typeof LANGUAGES)[number]["key"]>("en");
  const reportId = String(result.report_id ?? "");
  const citations = (result.citations as number[]) ?? [];

  return (
    <div className="space-y-4">
      <Section title={`Draft report (${reportId})`}>
        <div className="flex gap-1">
          {LANGUAGES.map((l) => (
            <button
              key={l.key}
              onClick={() => setLang(l.key)}
              className={`rounded px-3 py-1 text-sm ${
                lang === l.key
                  ? "bg-black text-white dark:bg-white dark:text-black"
                  : "bg-black/5 hover:bg-black/10 dark:bg-white/10 dark:hover:bg-white/15"
              }`}
            >
              {l.label}
            </button>
          ))}
        </div>
        <p className="rounded border border-black/10 p-3 text-sm whitespace-pre-wrap dark:border-white/15">
          {String(result[lang] ?? "")}
        </p>
      </Section>
      <Section title="Citations (tool-sourced numbers this draft is allowed to use)">
        <p className="font-mono text-sm">{citations.join(", ") || "none"}</p>
      </Section>
      <Section title="Human approval required before this is final">
        <div className="flex flex-wrap gap-3">
          <GateAction label="Publish" tone="approve" action={publishReportAction.bind(null, reportId)} />
          <GateAction label="Reject" tone="reject" action={rejectReportAction.bind(null, reportId)} />
        </div>
      </Section>
    </div>
  );
}

const DOC_TYPE_LABELS: Record<string, string> = {
  kiid: "KIID",
  prospectus: "Prospectus",
  regulation: "Regulation",
  cssf_guidance: "CSSF Guidance",
};

function EvidenceResult({ result }: { result: Record<string, unknown> }) {
  const answer = String(result.answer ?? "");
  const abstained = Boolean(result.abstained);
  const documentCitations = (result.document_citations as DocumentCitation[]) ?? [];
  const numericCitations = (result.numeric_citations as number[]) ?? [];
  const sourcesConsidered = Number(result.sources_considered ?? 0);

  return (
    <div className="space-y-4">
      <Section title="Answer">
        {abstained && (
          <span className="mb-2 inline-block rounded-full bg-amber-500/15 px-3 py-1 text-xs font-medium text-amber-700 dark:text-amber-400">
            Abstained — insufficient evidence
          </span>
        )}
        <p className="rounded border border-black/10 p-3 text-sm whitespace-pre-wrap dark:border-white/15">{answer}</p>
      </Section>
      <Section title={`Document citations (${documentCitations.length} of ${sourcesConsidered} retrieved)`}>
        {documentCitations.length === 0 ? (
          <p className="text-sm text-black/60 dark:text-white/60">None.</p>
        ) : (
          <ul className="space-y-2">
            {documentCitations.map((c) => (
              <li key={c.id} className="rounded border border-black/10 p-2 text-sm dark:border-white/15">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs font-medium uppercase dark:bg-white/10">
                    {DOC_TYPE_LABELS[c.doc_type] ?? c.doc_type}
                  </span>
                  <span className="font-mono text-xs text-black/60 dark:text-white/60">{c.id}</span>
                  {c.source_url && (
                    <a href={c.source_url} target="_blank" rel="noreferrer" className="text-xs underline">
                      source
                    </a>
                  )}
                </div>
                {c.content && <p className="mt-1 text-black/70 dark:text-white/70">{c.content}</p>}
              </li>
            ))}
          </ul>
        )}
      </Section>
      {numericCitations.length > 0 && (
        <Section title="Numeric citations">
          <p className="font-mono text-sm">{numericCitations.join(", ")}</p>
        </Section>
      )}
    </div>
  );
}

function MultiHopResult({ data }: { data: AskResult }) {
  const plan = data.plan ?? [];
  const trace = data.trace ?? [];
  const finalResult = data.result ?? {};

  return (
    <div className="space-y-4">
      <Section title="Plan">
        <div className="flex flex-wrap gap-2">
          {plan.map((hop) => {
            const step = trace.find((t) => t.hop === hop);
            const status = step?.status ?? "pending";
            const tone =
              status === "ok"
                ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
                : status === "error"
                  ? "bg-red-500/15 text-red-700 dark:text-red-400"
                  : "bg-black/5 text-black/50 dark:bg-white/10 dark:text-white/50";
            return (
              <span key={hop} className={`rounded-full px-3 py-1 text-xs font-medium ${tone}`}>
                {hop} {status === "ok" ? "✓" : status === "error" ? "✗" : "…"}
              </span>
            );
          })}
        </div>
        {trace.some((t) => t.status === "error") && (
          <ul className="mt-2 space-y-1 text-xs text-red-700 dark:text-red-400">
            {trace
              .filter((t) => t.status === "error")
              .map((t) => (
                <li key={t.hop}>
                  {t.hop}: {t.error}
                </li>
              ))}
          </ul>
        )}
      </Section>
      <div className="space-y-2">
        <h3 className="text-sm font-semibold tracking-wide text-black/60 uppercase dark:text-white/50">
          Synthesized answer
        </h3>
        <EvidenceResult result={finalResult} />
      </div>
    </div>
  );
}

const ROUTE_LABELS: Record<string, string> = {
  sql: "NL2SQL agent",
  risk: "Greenwashing-Risk agent",
  dashboard: "Dashboard agent",
  query_optimizer: "Query-Optimizer agent",
  report: "Report agent",
  evidence: "Evidence agent",
  multi_hop: "Multi-hop (supervisor-planned)",
};

export function ResultView({ data }: { data: AskResult }) {
  const { route, result, error } = data;

  return (
    <div className="space-y-4 rounded-lg border border-black/10 p-4 dark:border-white/15">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="rounded-full bg-black/5 px-3 py-1 text-xs font-medium tracking-wide uppercase dark:bg-white/10">
          Routed to: {route ? (ROUTE_LABELS[route] ?? route) : "unknown"}
        </span>
      </div>

      {error && (
        <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {!error && result && route === "sql" && <SqlResult result={result} />}
      {!error && result && route === "risk" && <RiskResult result={result} />}
      {!error && result && route === "dashboard" && <DashboardResult result={result} />}
      {!error && result && route === "query_optimizer" && <QueryOptimizerResult result={result} />}
      {!error && result && route === "report" && <ReportResult result={result} />}
      {!error && result && route === "evidence" && <EvidenceResult result={result} />}
      {route === "multi_hop" && <MultiHopResult data={data} />}

      <details className="text-sm">
        <summary className="cursor-pointer text-black/50 select-none dark:text-white/50">Raw response</summary>
        <pre className="mt-2 overflow-x-auto rounded bg-black/5 p-3 dark:bg-white/10">
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </div>
  );
}
