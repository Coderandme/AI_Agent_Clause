/** The agent trace. SPEC.md §2.3: "not a debug panel. It is a feature."
 *
 * Watching it call get_rule_detail("auto_renewal"), then record_finding, is what makes this legibly
 * *agentic* rather than a single prompt with a spinner in front of it. The events below are the real
 * ones, recorded while the agent actually worked — not a re-enactment.
 */

import type { TraceEvent } from "@/types";

function summarise(event: TraceEvent): { label: string; detail: string } | null {
  switch (event.kind) {
    case "tool_call": {
      const args = Object.entries(event.input)
        .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
        .join(", ");
      return { label: `${event.name}(${args})`, detail: "" };
    }
    case "tool_result": {
      const out = event.output as Record<string, unknown> | null;
      // record_finding answers {verified, page} — the most interesting thing in the whole trace,
      // because it is the moment a quote is accepted or thrown away.
      if (out && typeof out === "object" && "verified" in out) {
        const ok = Boolean(out["verified"]);
        return {
          label: `→ ${ok ? "verified" : "REJECTED — quote not found in document"}`,
          detail: ok && out["page"] != null ? `page ${String(out["page"])}` : "",
        };
      }
      return null;
    }
    case "usage":
      return {
        label: "→ tokens",
        detail: `${event.input_tokens} in (${event.cached_input_tokens} cached) · ${event.output_tokens} out`,
      };
    default:
      return null;
  }
}

export function Trace({ events }: { events: TraceEvent[] }) {
  const rows = events.map((e) => ({ event: e, view: summarise(e) })).filter((r) => r.view !== null);

  return (
    <div className="space-y-1 font-mono text-[12px] leading-relaxed">
      {rows.map(({ event, view }, i) => {
        const isCall = event.kind === "tool_call";
        const rejected = view!.label.includes("REJECTED");
        return (
          <div key={i} className="flex gap-2">
            <span className="w-10 shrink-0 text-right text-slate-400 tabular-nums">
              {event.at.toFixed(0)}s
            </span>
            <span
              className={
                isCall
                  ? "text-slate-800"
                  : rejected
                    ? "font-semibold text-sev-critical"
                    : "text-slate-500"
              }
            >
              {view!.label}
              {view!.detail && <span className="ml-2 text-slate-400">{view!.detail}</span>}
            </span>
          </div>
        );
      })}
    </div>
  );
}
