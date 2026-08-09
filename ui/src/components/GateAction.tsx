"use client";

import { useActionState } from "react";
import type { GateActionState } from "@/app/actions";

const initialState: GateActionState = {};

export function GateAction({
  label,
  tone,
  action,
}: {
  label: string;
  tone: "approve" | "reject";
  action: (prevState: GateActionState, formData: FormData) => Promise<GateActionState>;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);

  const toneClasses =
    tone === "approve"
      ? "bg-emerald-600 hover:bg-emerald-500 disabled:bg-emerald-900"
      : "bg-red-600 hover:bg-red-500 disabled:bg-red-900";

  return (
    <form action={formAction} className="flex flex-wrap items-center gap-2">
      <input
        type="text"
        name="actor"
        placeholder="your name"
        required
        className="rounded border border-black/10 bg-transparent px-2 py-1 text-sm dark:border-white/15"
      />
      <button
        type="submit"
        disabled={pending}
        className={`rounded px-3 py-1 text-sm font-medium text-white disabled:cursor-not-allowed ${toneClasses}`}
      >
        {pending ? "Working…" : label}
      </button>
      {state.status && <span className="text-sm text-emerald-600 dark:text-emerald-400">-&gt; {state.status}</span>}
      {state.error && <span className="text-sm text-red-600 dark:text-red-400">{state.error}</span>}
    </form>
  );
}
