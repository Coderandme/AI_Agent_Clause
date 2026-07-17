/** The extracted key terms. SPEC.md §9.2.
 *
 * "Missing values render as an explicit 'Not specified', which for a liability cap is itself the
 * finding." A blank cell looks like the tool forgot to look. "Not specified" says it looked.
 */

import type { KeyTerms } from "@/types";

const LABELS: Record<string, string> = {
  parties: "Parties",
  effective_date: "Effective date",
  initial_term: "Initial term",
  renewal: "Renewal",
  notice_period: "Notice period",
  payment_terms: "Payment terms",
  liability_cap: "Liability cap",
  governing_law: "Governing law",
  termination: "Termination",
};

function render(value: unknown): { text: string; missing: boolean } {
  if (value === null || value === undefined || value === "") {
    return { text: "Not specified", missing: true };
  }
  if (Array.isArray(value)) {
    return value.length
      ? { text: value.join(" · "), missing: false }
      : { text: "Not specified", missing: true };
  }
  return { text: String(value), missing: false };
}

export function KeyTermsTable({ terms }: { terms: KeyTerms | null }) {
  if (!terms) return <p className="text-sm text-slate-500">No key terms were extracted.</p>;

  // Show the known terms in a deliberate order, then anything else the model returned.
  const known = Object.keys(LABELS).filter((k) => k in terms);
  const extra = Object.keys(terms).filter((k) => !(k in LABELS));

  return (
    <dl className="divide-y divide-slate-100 text-sm">
      {[...known, ...extra].map((key) => {
        const { text, missing } = render(terms[key]);
        return (
          <div key={key} className="grid grid-cols-3 gap-3 py-2">
            <dt className="font-medium text-slate-500">{LABELS[key] ?? key}</dt>
            <dd className={`col-span-2 ${missing ? "text-slate-400 italic" : "text-slate-800"}`}>
              {text}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
