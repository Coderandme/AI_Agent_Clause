/** Upload your own contract, and get it analysed. SPEC.md §2.5, §9.2. Protected: login required.
 *
 * The flow: upload → the server ingests the PDF and schedules the agent → we poll GET /api/analyses
 * /{id} until it flips to `complete` (or `failed`) → render the findings with the same cards the
 * demo uses. The analysis takes ~40-70s, so "upload" returns almost immediately and the waiting
 * happens here, against a running agent (analysis/service.py).
 *
 * The invite-only gate is visible here: the page shows what's left of your grant, and when the
 * server refuses (403 grant spent, 402 ceiling) it renders the server's message verbatim.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { api, ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { ErrorNote } from "@/components/Form";
import { FindingCard } from "@/components/FindingCard";
import { KeyTermsTable } from "@/components/KeyTermsTable";
import type { Analysis } from "@/types";

export function Analyse() {
  const { user, refresh } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Poll the analysis until it settles. Restarts whenever a new upload sets a fresh analysisId.
  useEffect(() => {
    if (!analysisId) return;
    let active = true;

    const poll = async () => {
      try {
        const a = await api.getAnalysis(analysisId);
        if (!active) return;
        setAnalysis(a);
        if (a.status === "complete" || a.status === "failed") {
          void refresh(); // a completed analysis spent part of the grant — re-read it
          return;
        }
        timer.current = setTimeout(poll, 3000);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Lost contact with the analysis.");
      }
    };
    void poll();

    return () => {
      active = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [analysisId, refresh]);

  const reset = useCallback(() => {
    setFile(null);
    setAnalysisId(null);
    setAnalysis(null);
    setError(null);
  }, []);

  if (!user) return null; // ProtectedRoute guarantees this; satisfies the type checker.

  const unlimited = user.uploads_remaining === null;
  const exhausted = !unlimited && (user.uploads_remaining ?? 0) <= 0;
  const running =
    analysisId !== null && (analysis === null || analysis.status === "queued" || analysis.status === "running");

  function onPick(e: ChangeEvent<HTMLInputElement>) {
    setFile(e.target.files?.[0] ?? null);
    setError(null);
  }

  async function onUpload() {
    if (!file) return;
    setUploading(true);
    setError(null);
    setAnalysis(null);
    setAnalysisId(null);
    try {
      const res = await api.upload(file);
      setAnalysisId(res.analysis_id); // starts the polling effect
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
      void refresh();
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <header>
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">Analyse a contract</h1>
        <p className="mt-1 text-sm text-slate-600">
          PDF, up to 10 MB and 40 pages. Your file is stored only to run the analysis and is deleted
          24 hours later.
        </p>
      </header>

      <GrantBanner
        unlimited={unlimited}
        remaining={user.uploads_remaining}
        grant={user.upload_grant}
        used={user.uploads_used}
      />

      {/* Upload form — hidden once an analysis is under way or shown, to keep focus on the result. */}
      {analysisId === null && (
        <section className="rounded-md border border-slate-200 bg-white p-4">
          <input
            type="file"
            accept="application/pdf,.pdf"
            onChange={onPick}
            disabled={exhausted || uploading}
            className="block w-full text-sm text-slate-600 file:mr-3 file:cursor-pointer file:rounded file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-slate-700 hover:file:bg-slate-200 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={onUpload}
            disabled={!file || uploading || exhausted}
            className="mt-3 rounded bg-accent-600 px-3 py-2 text-sm font-medium text-white hover:bg-accent-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {uploading ? "Uploading…" : "Analyse"}
          </button>
          {error && <div className="mt-3">{<ErrorNote>{error}</ErrorNote>}</div>}
        </section>
      )}

      {running && <Running filename={analysis?.filename} />}

      {analysis?.status === "failed" && (
        <section className="space-y-3">
          <ErrorNote>{analysis.error ?? "The analysis failed."}</ErrorNote>
          <button
            type="button"
            onClick={reset}
            className="text-sm text-accent-700 underline underline-offset-2"
          >
            Try another contract
          </button>
        </section>
      )}

      {analysis?.status === "complete" && <Result analysis={analysis} onReset={reset} />}
    </div>
  );
}

function Running({ filename }: { filename?: string }) {
  return (
    <section className="rounded-md border border-slate-200 bg-white p-6 text-center">
      <div className="mx-auto mb-3 h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-accent-600" />
      <p className="text-sm font-medium text-slate-800">
        The agent is reading {filename ?? "your contract"}…
      </p>
      <p className="mt-1 text-xs text-slate-500">
        It works through all 15 rules and verifies every quote against the source. About 40–70
        seconds — this page updates itself.
      </p>
    </section>
  );
}

function Result({ analysis, onReset }: { analysis: Analysis; onReset: () => void }) {
  return (
    <div className="space-y-4">
      <section className="rounded-md border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-base font-semibold text-slate-900">{analysis.filename}</h2>
          <p className="text-[11px] text-slate-500">
            {analysis.findings.length} findings · quote verification{" "}
            <span className="font-medium text-slate-700">
              {analysis.findings.length}/{analysis.findings.length + analysis.unverified_count}
            </span>
            {analysis.scan_model && <> · {analysis.scan_model}</>}
            {analysis.seconds != null && <> · {analysis.seconds.toFixed(0)}s</>}
          </p>
        </div>
        {analysis.summary && (
          <p className="mt-2 text-sm leading-relaxed text-slate-700">{analysis.summary}</p>
        )}
      </section>

      {analysis.findings.length === 0 ? (
        <p className="rounded-md border border-slate-200 bg-white p-4 text-sm text-slate-600">
          No risks fired against the 15 rules. That is a real result, not an empty one — see the
          "checked and not found" list below.
        </p>
      ) : (
        <div className="space-y-3">
          {analysis.findings.map((f, i) => (
            <FindingCard key={`${f.rule_id}-${i}`} finding={f} />
          ))}
        </div>
      )}

      {analysis.key_terms && (
        <section className="rounded-md border border-slate-200 bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-900">Key terms</h3>
          <KeyTermsTable terms={analysis.key_terms} />
        </section>
      )}

      {analysis.absences.length > 0 && (
        <details className="rounded-md border border-slate-200 bg-white p-4">
          <summary className="cursor-pointer text-sm font-medium text-slate-700">
            Checked and not found ({analysis.absences.length})
          </summary>
          <ul className="mt-3 space-y-2">
            {analysis.absences.map((a) => (
              <li key={a.rule_id} className="text-sm">
                <span className="font-mono text-xs text-slate-500">{a.rule_id}</span>
                <span className="mx-2 text-slate-300">—</span>
                <span className="text-slate-600">{a.rationale}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <button
        type="button"
        onClick={onReset}
        className="text-sm text-accent-700 underline underline-offset-2"
      >
        Analyse another contract
      </button>
    </div>
  );
}

function GrantBanner({
  unlimited,
  remaining,
  grant,
  used,
}: {
  unlimited: boolean;
  remaining: number | null;
  grant: number;
  used: number;
}) {
  if (unlimited) {
    return (
      <p className="rounded border border-slate-800/20 bg-slate-800 px-3 py-2 text-xs text-white">
        <strong className="font-semibold">Admin.</strong> Unlimited analyses.
      </p>
    );
  }
  const left = remaining ?? 0;
  if (left <= 0) {
    return (
      <p className="rounded border border-sev-high/30 bg-sev-high-bg px-3 py-2 text-xs text-sev-high">
        <strong className="font-semibold">You've used all {grant} of your analyses.</strong> Contact
        the admin for more access.
      </p>
    );
  }
  return (
    <p className="rounded border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
      <strong className="font-semibold text-slate-900">
        {left} of {grant} {grant === 1 ? "analysis" : "analyses"} remaining
      </strong>{" "}
      on your access code ({used} used).
    </p>
  );
}
