import { AskForm } from "@/components/AskForm";

export default function Home() {
  return (
    <div className="flex flex-1 justify-center bg-zinc-50 dark:bg-black">
      <main className="w-full max-w-3xl px-6 py-12">
        <header className="mb-8">
          <h1 className="text-2xl font-semibold">GreenLux Sentinel — Agent Console</h1>
          <p className="mt-1 text-sm text-black/60 dark:text-white/60">
            Ask a question in plain text. It is routed to the specialist agent that can answer it
            (SQL / greenwashing-risk / dashboard / query-optimizer / report / document-evidence),
            or — for a question that needs several of these combined — planned and chained
            automatically across them, synthesizing one cited answer (or an explicit
            &quot;I don&apos;t know&quot; if the evidence doesn&apos;t support one). Everything the
            agent(s) produced — the query, the score, the report, the citations, the hop-by-hop
            plan — is shown below, not just the final number.
          </p>
        </header>
        <AskForm />
      </main>
    </div>
  );
}
