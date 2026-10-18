interface Example {
  question: string;
  /** Drives the dot color only — never rendered as text. The outcome should reveal
   * itself when the example runs, not spoil it with a "this one fails" label. Verified
   * live against the running backend before being hardcoded here (see the plan this was
   * built from) — these aren't hypothetical, they're the actual behavior. */
  kind: "cited" | "abstain";
}

// One per thing the corpus covers: obligations, an annex, official guidance, the 2026
// amendment, the AI Act/GDPR interplay, and an honest abstention.
const EXAMPLES: Example[] = [
  { question: "What are the requirements for high-risk AI systems under the EU AI Act?", kind: "cited" },
  { question: "Is AI used to decide who gets a loan considered high-risk?", kind: "cited" },
  { question: "According to the EDPB, when is a company 'aware' of a personal data breach?", kind: "cited" },
  { question: "Have the AI Act's deadlines for high-risk AI systems been postponed?", kind: "cited" },
  {
    question: "If my AI system is also a GDPR data processor, does the AI Act override my GDPR breach notification deadline?",
    kind: "cited",
  },
  { question: "What does the California Consumer Privacy Act say about deleting data?", kind: "abstain" },
];

export function ExampleQuestions({ onAsk }: { onAsk: (question: string) => void }) {
  return (
    <div>
      <p className="font-mono text-[11px] tracking-wide text-ink/50 uppercase">
        try it — no need to write your own question
      </p>
      <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
        {EXAMPLES.map((example) => (
          <button
            key={example.question}
            type="button"
            onClick={() => onAsk(example.question)}
            className="border-rule hover:border-ink flex items-start gap-3 border px-4 py-3 text-left transition-colors"
          >
            <span
              aria-hidden="true"
              className={`mt-2 h-1.5 w-1.5 shrink-0 rounded-full ${example.kind === "cited" ? "bg-citation" : "bg-abstain"}`}
            />
            <span className="font-serif text-sm leading-snug text-ink">{example.question}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
