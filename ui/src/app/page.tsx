import { AskForm } from "@/components/AskForm";

export default function Home() {
  return (
    <div className="flex flex-1 justify-center bg-zinc-50 dark:bg-black">
      <main className="w-full max-w-3xl px-6 py-12">
        <header className="mb-8">
          <h1 className="text-2xl font-semibold">GreenLux Sentinel — Agent Console</h1>
          <p className="mt-1 text-sm text-black/60 dark:text-white/60">
            Ask a question in plain text. It is routed to the specialist agent that can answer it
            (SQL / greenwashing-risk / dashboard / query-optimizer / report) and everything the
            agent produced — the query it ran, the score, the report, the citations — is shown
            below, not just the final number.
          </p>
        </header>
        <AskForm />
      </main>
    </div>
  );
}
