/** Ask questions about an analysed contract. V2 — the part that makes "chatbot" literally true.
 *
 * The stream arrives citations-first (the excerpt map), then answer tokens. Every [n] the model
 * writes is rendered as a chip resolving to a real excerpt with its section and page — the server
 * guarantees the excerpts are verbatim document slices, so a citation can never point at nothing.
 *
 * Honesty in the UI: uploads are deleted after 24 hours, and Q&A dies with the document. The panel
 * says so up front instead of letting tomorrow's visitor find a dead question box.
 */

import { useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { api } from "@/api/client";
import type { Citation } from "@/types";

interface Exchange {
  question: string;
  answer: string;
  citations: Citation[];
  costMicrodollars: number | null;
  error: string | null;
  streaming: boolean;
}

export function AskPanel({ analysisId }: { analysisId: string }) {
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (q.length < 3 || busy) return;
    setQuestion("");
    setBusy(true);

    // Append a fresh exchange and stream into it. Updates go through the setter with an index so
    // React re-renders on every delta — which is the whole point of streaming.
    const idx = exchanges.length;
    const patch = (p: Partial<Exchange>) =>
      setExchanges((xs) => xs.map((x, i) => (i === idx ? { ...x, ...p } : x)));
    setExchanges((xs) => [
      ...xs,
      { question: q, answer: "", citations: [], costMicrodollars: null, error: null, streaming: true },
    ]);

    let answer = "";
    await api.askStream(analysisId, q, {
      onCitations: (citations) => patch({ citations }),
      onDelta: (text) => {
        answer += text;
        patch({ answer });
        bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      },
      onDone: (cost) => patch({ costMicrodollars: cost, streaming: false }),
      onError: (message) => patch({ error: message, streaming: false }),
    });
    setBusy(false);
  }

  return (
    <section className="rounded-md border border-slate-200 bg-white p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">Ask about this contract</h3>
        <p className="text-[11px] text-slate-500">
          Answers come only from the document, with citations. Available for 24 hours — then the
          contract is deleted, and the answers go with it.
        </p>
      </header>

      <div className="mt-3 space-y-4">
        {exchanges.map((x, i) => (
          <ExchangeView key={i} x={x} />
        ))}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={onSubmit} className="mt-3 flex gap-2">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder='e.g. "What happens if we terminate early?"'
          maxLength={500}
          disabled={busy}
          className="w-full rounded border border-slate-300 px-2.5 py-1.5 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-accent-600 focus:ring-1 focus:ring-accent-600 disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={busy || question.trim().length < 3}
          className="shrink-0 rounded bg-accent-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? "Answering…" : "Ask"}
        </button>
      </form>
    </section>
  );
}

function ExchangeView({ x }: { x: Exchange }) {
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-slate-900">
        <span className="mr-1.5 text-slate-400">Q</span>
        {x.question}
      </p>

      {x.error ? (
        <p className="rounded border border-sev-high/30 bg-sev-high-bg px-3 py-2 text-xs text-sev-high">
          {x.error}
        </p>
      ) : (
        <div className="rounded border border-slate-100 bg-slate-50 px-3 py-2">
          <p className="text-sm leading-relaxed whitespace-pre-wrap text-slate-800">
            {renderWithCitations(x.answer, x.citations)}
            {x.streaming && <span className="ml-0.5 animate-pulse text-accent-600">▋</span>}
          </p>

          {x.citations.length > 0 && !x.streaming && (
            <details className="mt-2 border-t border-slate-200 pt-2">
              <summary className="text-[11px] font-medium text-slate-500">
                Sources ({x.citations.length} excerpts retrieved)
              </summary>
              <ul className="mt-1.5 space-y-1.5">
                {x.citations.map((c) => (
                  <li key={c.n} className="text-[11px] leading-snug text-slate-600">
                    <CitationChip c={c} /> <span className="text-slate-400">“{c.preview}…”</span>
                  </li>
                ))}
              </ul>
            </details>
          )}

          {x.costMicrodollars !== null && (
            <p className="mt-1.5 text-right text-[10px] text-slate-400">
              ${(x.costMicrodollars / 1e6).toFixed(4)}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/** Turn "[2]" in the streamed answer into an inline chip resolving to its excerpt. Plain text
 * otherwise — the model writes prose, not markup. */
function renderWithCitations(answer: string, citations: Citation[]): ReactNode[] {
  const byN = new Map(citations.map((c) => [c.n, c]));
  return answer.split(/(\[\d+\])/g).map((part, i) => {
    const m = /^\[(\d+)\]$/.exec(part);
    const c = m ? byN.get(Number(m[1])) : undefined;
    if (!c) return <span key={i}>{part}</span>;
    return <CitationChip key={i} c={c} />;
  });
}

function CitationChip({ c }: { c: Citation }) {
  const where = [c.section_label && `§${c.section_label}`, c.page && `p. ${c.page}`]
    .filter(Boolean)
    .join(" · ");
  return (
    <span
      className="mx-0.5 inline-flex items-center gap-1 rounded border border-accent-600/30 bg-accent-50 px-1 py-px align-baseline text-[10px] font-medium text-accent-700"
      title={`${where || "excerpt"} — “${c.preview}…”`}
    >
      [{c.n}]{where && <span className="text-accent-700/70">{where}</span>}
    </span>
  );
}
