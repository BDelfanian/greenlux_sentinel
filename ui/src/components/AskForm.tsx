"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import { askQuestion, type AskFormState } from "@/app/actions";
import { ResultView } from "./ResultView";

const initialState: AskFormState = {};

// Real questions confirmed live against the deployed system (docs/PROGRESS_LOG.md's Phase 9c/9d
// entries) -- picked so a first-time visitor reliably sees a real multi-hop combination instead
// of risking a cold-start abstention. Question *phrasing* measurably affects both the planner's
// hop selection and hybrid_search()'s retrieval quality (confirmed live), so these aren't
// arbitrary -- they're the exact wording known to route and retrieve well.
const EXAMPLES: { label: string; question: string; fundId: string }[] = [
  {
    label: "ML signal + KIID (multi-hop)",
    question:
      "What does this fund's KIID say about ESG exclusions, and is that consistent with its composition-anomaly score from the ml_risk model?",
    fundId: "0P0001EVL3",
  },
  {
    label: "Greenwashing Risk Score",
    question: "What is this fund's greenwashing risk score, and what's driving it?",
    fundId: "0P00018CYB",
  },
  {
    label: "NL2SQL",
    question: "How many LU-domiciled funds are there, and what's their average sustainability rating?",
    fundId: "",
  },
];

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded bg-black px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-black"
    >
      {pending ? "Asking…" : "Ask"}
    </button>
  );
}

export function AskForm() {
  const [state, formAction] = useActionState(askQuestion, initialState);
  const [question, setQuestion] = useState("");
  const [fundId, setFundId] = useState("");

  return (
    <div className="space-y-6">
      <div>
        <span className="mb-1 block text-sm font-medium">Try an example</span>
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((example) => (
            <button
              key={example.label}
              type="button"
              onClick={() => {
                setQuestion(example.question);
                setFundId(example.fundId);
              }}
              className="rounded-full bg-black/5 px-3 py-1 text-xs font-medium hover:bg-black/10 dark:bg-white/10 dark:hover:bg-white/20"
            >
              {example.label}
            </button>
          ))}
        </div>
      </div>

      <form action={formAction} className="space-y-3">
        <div>
          <label htmlFor="question" className="mb-1 block text-sm font-medium">
            Question
          </label>
          <textarea
            id="question"
            name="question"
            rows={3}
            required
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="e.g. Combine this fund's risk score with what its KIID says about business exclusions, and give one synthesized answer"
            className="w-full rounded border border-black/15 bg-transparent p-2 text-sm dark:border-white/20"
          />
        </div>
        <div>
          <label htmlFor="fund_id" className="mb-1 block text-sm font-medium">
            Fund ID <span className="font-normal text-black/50 dark:text-white/50">(needed for risk score / report / evidence / multi-hop requests)</span>
          </label>
          <input
            id="fund_id"
            name="fund_id"
            type="text"
            value={fundId}
            onChange={(e) => setFundId(e.target.value)}
            placeholder="e.g. 0P00018CYB"
            className="w-full rounded border border-black/15 bg-transparent p-2 text-sm dark:border-white/20 sm:w-64"
          />
        </div>
        <SubmitButton />
      </form>

      {state.error && (
        <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-700 dark:text-red-300">
          {state.error}
        </div>
      )}

      {state.data && <ResultView data={state.data} />}
    </div>
  );
}
