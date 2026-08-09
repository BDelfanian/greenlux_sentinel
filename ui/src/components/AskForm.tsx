"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { askQuestion, type AskFormState } from "@/app/actions";
import { ResultView } from "./ResultView";

const initialState: AskFormState = {};

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

  return (
    <div className="space-y-6">
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
            placeholder="e.g. Which 5 Luxembourg-domiciled funds have a sustainability_rating of 5, ordered by total_net_assets?"
            className="w-full rounded border border-black/15 bg-transparent p-2 text-sm dark:border-white/20"
          />
        </div>
        <div>
          <label htmlFor="fund_id" className="mb-1 block text-sm font-medium">
            Fund ID <span className="font-normal text-black/50 dark:text-white/50">(only needed for risk score / report requests)</span>
          </label>
          <input
            id="fund_id"
            name="fund_id"
            type="text"
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
