/** One risk finding. SPEC.md §9.2.
 *
 * The quoted clause is the point of the whole product, so it gets the most visual weight after the
 * title: a verbatim block with its page number attached. That page number was DERIVED by the server
 * from the quote (SPEC.md §4.5) — the agent never supplied it — which is exactly why it can be
 * trusted enough to print.
 */

import { SeverityBadge } from "./Severity";
import type { Finding } from "@/types";

/** `onViewPage`, when provided, turns the page number into a button that opens the source PDF at
 * that page — so a reader can check the quote against the actual contract. Optional because the same
 * card renders in contexts with no PDF to open (e.g. a future uploaded-doc view before the viewer
 * exists). */
export function FindingCard({
  finding,
  onViewPage,
}: {
  finding: Finding;
  onViewPage?: (page: number) => void;
}) {
  const page = finding.page_number;
  return (
    <article className="rounded-md border border-slate-200 bg-white p-4 shadow-xs">
      <header className="flex items-start justify-between gap-3">
        <h3 className="text-[15px] leading-snug font-semibold text-slate-900">{finding.title}</h3>
        <SeverityBadge severity={finding.severity} />
      </header>

      <p className="mt-2 text-sm leading-relaxed text-slate-600">{finding.exposure}</p>

      <figure className="mt-3">
        <blockquote className="clause-quote">{finding.quoted_text}</blockquote>
        <figcaption className="mt-1.5 flex items-center gap-2 text-[11px] text-slate-500">
          {page !== null &&
            (onViewPage ? (
              <button
                type="button"
                onClick={() => onViewPage(page)}
                className="font-medium text-accent-700 underline underline-offset-2 hover:text-accent-600"
                title="Open the contract at this page and check the quote yourself"
              >
                Page {page} ↗
              </button>
            ) : (
              <span className="font-medium text-slate-600">Page {page}</span>
            ))}
          <span className="inline-flex items-center gap-1 text-emerald-700" title="This exact text was located in your document before the finding was allowed to exist.">
            <span aria-hidden="true">✓</span> quote verified
          </span>
          <span className="text-slate-400">·</span>
          <span>{finding.rule_id}</span>
          <span className="text-slate-400">·</span>
          <span>{finding.confidence} confidence</span>
        </figcaption>
      </figure>

      <div className="mt-3 border-t border-slate-100 pt-3">
        <p className="text-sm leading-relaxed text-slate-700">
          <span className="font-semibold text-slate-900">Ask for: </span>
          {finding.recommendation}
        </p>
      </div>
    </article>
  );
}
