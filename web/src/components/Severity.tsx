/** The severity scale. SPEC.md §9.1.
 *
 * Severity NEVER relies on colour alone: every badge carries a glyph and the word itself. That is
 * not decoration — it is what keeps the scale legible to a colour-blind reader and in a black-and-
 * white print of the memo. The colour is the third signal, not the only one.
 */

import type { Severity } from "@/types";

const STYLES: Record<Severity, { glyph: string; label: string; className: string }> = {
  critical: {
    glyph: "▲",
    label: "Critical",
    className: "bg-sev-critical-bg text-sev-critical border-sev-critical/30",
  },
  high: {
    glyph: "◆",
    label: "High",
    className: "bg-sev-high-bg text-sev-high border-sev-high/30",
  },
  medium: {
    glyph: "●",
    label: "Medium",
    className: "bg-sev-medium-bg text-sev-medium border-sev-medium/30",
  },
  low: {
    glyph: "○",
    label: "Low",
    className: "bg-sev-low-bg text-sev-low border-sev-low/30",
  },
};

export const SEVERITY_ORDER: Record<Severity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = STYLES[severity];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-[11px] font-semibold tracking-wide uppercase ${s.className}`}
    >
      <span aria-hidden="true">{s.glyph}</span>
      {s.label}
    </span>
  );
}
