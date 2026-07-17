/** The landing page and the demo. SPEC.md §9.2, §7.1.
 *
 * This is the primary call to action, and it is deliberately the cheapest page in the product: no
 * login, no API call, no cold start. A visitor clicks a sample and watches a real recorded agent
 * trace with verified quotes, instantly, for $0.00. Most visitors will never do anything else, and
 * they will still have seen the product work.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { DEMOS, DEMO_PDFS } from "@/demo";
import { FindingCard } from "@/components/FindingCard";
import { KeyTermsTable } from "@/components/KeyTermsTable";
import { Trace } from "@/components/Trace";
import { SEVERITY_ORDER } from "@/components/Severity";
import type { DemoAnalysis } from "@/types";

type Tab = "risks" | "terms" | "trace" | "contract";

export function Landing() {
  const [slug, setSlug] = useState(DEMOS[0]?.slug ?? "");
  const [tab, setTab] = useState<Tab>("risks");
  const [pdfPage, setPdfPage] = useState(1);
  const demo = DEMOS.find((d) => d.slug === slug) ?? DEMOS[0];

  function pickSlug(next: string) {
    setSlug(next);
    setTab("risks");
    setPdfPage(1);
  }

  // Clicking a finding's page number jumps to that page of the source PDF — the cross-check that
  // makes the "every quote is real" claim something a visitor can verify rather than trust.
  function viewPage(page: number) {
    setPdfPage(page);
    setTab("contract");
  }

  if (!demo) return <p className="text-slate-500">No demo contracts are bundled.</p>;

  return (
    <div className="space-y-6">
      <section className="max-w-3xl">
        <h1 className="text-2xl leading-tight font-semibold tracking-tight text-slate-900">
          An agent reads your contract, flags the risks, and{" "}
          <span className="underline decoration-accent-600 decoration-2 underline-offset-4">
            proves every quotation it shows you exists in the document.
          </span>
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-slate-600">
          Not a chatbot. It works through a library of 15 risk rules on its own — loading a rule,
          checking a clause, recording a finding. Every quote is verified against the source before
          it is allowed to reach you, so a quotation the agent invents is structurally unable to be
          displayed.
        </p>
      </section>

      <SamplePicker demos={DEMOS} slug={slug} onPick={pickSlug} />

      <AnalysisHeader demo={demo} />

      <div className="border-b border-slate-200">
        <nav className="-mb-px flex gap-6">
          {(
            [
              ["risks", `Risks (${demo.findings.length})`],
              ["terms", "Key terms"],
              ["trace", `Agent trace (${demo.trace.length})`],
              ["contract", "Contract"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={`border-b-2 px-1 pb-2 text-sm ${
                tab === key
                  ? "border-accent-600 font-semibold text-slate-900"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              {label}
            </button>
          ))}
        </nav>
      </div>

      {tab === "risks" && <Risks demo={demo} onViewPage={viewPage} />}
      {tab === "terms" && (
        <div className="max-w-2xl rounded-md border border-slate-200 bg-white p-4">
          <KeyTermsTable terms={demo.key_terms} />
        </div>
      )}
      {tab === "trace" && (
        <div className="rounded-md border border-slate-200 bg-white p-4">
          <p className="mb-3 text-xs text-slate-500">
            What the agent actually did, in order. This is not a log — it is the product. Recorded
            while it worked; replayed here at zero cost.
          </p>
          <Trace events={demo.trace} />
        </div>
      )}
      {tab === "contract" && <ContractView demo={demo} page={pdfPage} />}

      <section className="rounded-md border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Want it run on your own contract?</h2>
        <p className="mt-1 text-sm text-slate-600">
          That part is invite-only — it costs real money to run, so it is limited to people I have
          given an access code to.{" "}
          <Link to="/signup" className="text-accent-700 underline underline-offset-2">
            Sign up with a code
          </Link>{" "}
          or{" "}
          <Link to="/login" className="text-accent-700 underline underline-offset-2">
            sign in
          </Link>
          .
        </p>
      </section>
    </div>
  );
}

function SamplePicker({
  demos,
  slug,
  onPick,
}: {
  demos: DemoAnalysis[];
  slug: string;
  onPick: (slug: string) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {demos.map((d) => {
        const worst = [...d.findings].sort(
          (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
        )[0];
        const active = d.slug === slug;
        return (
          <button
            key={d.slug}
            type="button"
            onClick={() => onPick(d.slug)}
            className={`rounded-md border p-3 text-left transition ${
              active
                ? "border-accent-600 bg-accent-50"
                : "border-slate-200 bg-white hover:border-slate-300"
            }`}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-semibold text-slate-900">{d.filename}</span>
              <span className="text-[11px] text-slate-500">
                {d.page_count} pages · {d.findings.length} findings
              </span>
            </div>
            <p className="mt-1 line-clamp-2 text-xs text-slate-500">{d.blurb}</p>
            {worst && (
              <p className="mt-2 truncate text-xs text-slate-700">
                <span className="font-medium">Worst: </span>
                {worst.title}
              </p>
            )}
          </button>
        );
      })}
    </div>
  );
}

function AnalysisHeader({ demo }: { demo: DemoAnalysis }) {
  return (
    <section className="rounded-md border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-slate-900">{demo.filename}</h2>
        <p className="text-[11px] text-slate-500">
          Pre-computed · <span className="font-semibold text-emerald-700">$0.00</span> · no API calls
          · {demo.scan_model} · {demo.seconds.toFixed(0)}s when it ran
        </p>
      </div>
      <p className="mt-2 text-sm leading-relaxed text-slate-700">{demo.summary}</p>
      <p className="mt-2 text-xs text-slate-500">
        {demo.findings.length} findings shown · quote verification{" "}
        <span className="font-medium text-slate-700">
          {demo.findings.length}/{demo.findings.length + demo.unverified_count}
        </span>
        {demo.unverified_count > 0 && (
          <> · {demo.unverified_count} unverified and therefore not displayed</>
        )}
      </p>
    </section>
  );
}

function Risks({ demo, onViewPage }: { demo: DemoAnalysis; onViewPage: (page: number) => void }) {
  const sorted = [...demo.findings].sort(
    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
  );
  return (
    <div className="space-y-3">
      {sorted.map((f, i) => (
        <FindingCard key={`${f.rule_id}-${i}`} finding={f} onViewPage={onViewPage} />
      ))}

      {demo.absences.length > 0 && (
        <details className="rounded-md border border-slate-200 bg-white p-4">
          <summary className="cursor-pointer text-sm font-medium text-slate-700">
            Checked and not found ({demo.absences.length})
          </summary>
          <p className="mt-1 text-xs text-slate-500">
            Rules the agent checked and decided did not fire. This is the difference between a tool
            that looks thorough and one that is.
          </p>
          <ul className="mt-3 space-y-2">
            {demo.absences.map((a) => (
              <li key={a.rule_id} className="text-sm">
                <span className="font-mono text-xs text-slate-500">{a.rule_id}</span>
                <span className="mx-2 text-slate-300">—</span>
                <span className="text-slate-600">{a.rationale}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** The source contract, rendered in the browser's own PDF viewer. Deliberately an <iframe>, not
 * react-pdf: for the demo we only need "open it to the right page and let the visitor check the
 * quote", and the browser viewer does that with `#page=N` and zero dependencies. The span-precise
 * highlight overlay (SPEC.md §9.3) is the real product feature and a later version — this is the
 * blessed page-level fallback (§10.1), which for a cross-check is plenty.
 *
 * The iframe is keyed by page so that navigating from a different finding re-fires the `#page` jump;
 * without the remount the browser ignores a hash change on an already-loaded document. */
function ContractView({ demo, page }: { demo: DemoAnalysis; page: number }) {
  const url = DEMO_PDFS[demo.slug];
  if (!url) {
    return (
      <p className="rounded-md border border-slate-200 bg-white p-4 text-sm text-slate-500">
        The source PDF for this sample isn't bundled.
      </p>
    );
  }
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span>
          The exact contract the agent read. Click <span className="font-medium">Page N ↗</span> on
          any finding to jump here and check the quote against the source yourself.
        </span>
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="shrink-0 text-accent-700 underline underline-offset-2"
        >
          Open in a new tab ↗
        </a>
      </div>
      <iframe
        key={page}
        src={`${url}#page=${page}`}
        title={`${demo.filename} — page ${page}`}
        className="h-[75vh] w-full rounded border border-slate-200 bg-slate-100"
      />
    </div>
  );
}
