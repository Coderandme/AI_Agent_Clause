/** The shapes that cross the wire, and the shape of the pre-computed demo files.
 *
 * These mirror the backend's Pydantic models (api/clause/auth/schemas.py) and the JSON written by
 * `python -m clause.demo`. They are hand-written rather than generated: the surface is small, and a
 * codegen step for six types would cost more than it saves.
 */

export type Severity = "critical" | "high" | "medium" | "low";
export type Confidence = "high" | "medium" | "low";

/** A user, as the API returns them. Note there is no password field — by construction. */
export interface User {
  id: string;
  email: string;
  is_admin: boolean;
  upload_grant: number;
  uploads_used: number;
  /** null means unlimited (admin). */
  uploads_remaining: number | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

/** One risk finding. Everything from `matched_text` down is DERIVED by quote verification on the
 * server (SPEC.md §4.5) — the agent never supplies a page number, because it cannot be trusted to. */
export interface Finding {
  rule_id: string;
  severity: Severity;
  title: string;
  exposure: string;
  recommendation: string;
  quoted_text: string;
  confidence: Confidence;
  verified: boolean;
  matched_text: string | null;
  char_start: number | null;
  char_end: number | null;
  page_number: number | null;
}

/** A rule that was checked and did NOT fire. This is what separates a tool that looks thorough from
 * one that is (SPEC.md §9.2). */
export interface Absence {
  rule_id: string;
  rationale: string;
}

export type TraceEvent =
  | { at: number; kind: "tool_call"; name: string; input: Record<string, unknown> }
  | { at: number; kind: "tool_result"; name: string; output: unknown }
  | { at: number; kind: "usage"; input_tokens: number; cached_input_tokens: number; output_tokens: number }
  | { at: number; kind: "reasoning" | "text"; text?: string };

export interface KeyTerms {
  parties?: string[] | null;
  effective_date?: string | null;
  initial_term?: string | null;
  renewal?: string | null;
  notice_period?: string | null;
  payment_terms?: string | null;
  liability_cap?: string | null;
  governing_law?: string | null;
  termination?: string | null;
  [key: string]: unknown;
}

/** A pre-computed demo analysis: the whole thing, frozen to JSON, replayed at zero cost. */
export interface DemoAnalysis {
  slug: string;
  filename: string;
  blurb: string;
  page_count: number;
  char_count: number;
  scan_model: string;
  rule_library_version: string;
  prompt_version: string;
  summary: string;
  findings: Finding[];
  unverified_count: number;
  absences: Absence[];
  key_terms: KeyTerms | null;
  trace: TraceEvent[];
  usage: { input_tokens: number; cached_input_tokens: number; output_tokens: number } | null;
  seconds: number;
}

/** One retrieved excerpt backing a Q&A answer. Sent by the server BEFORE the answer streams, so
 * every [n] the model cites is already resolvable. The span is a verbatim slice of the document —
 * the chunker's invariant — which is why a citation can carry a page number worth trusting. */
export interface Citation {
  n: number;
  section_label: string | null;
  page: number | null;
  char_start: number;
  char_end: number;
  preview: string;
}

/** What POST /api/documents returns: the document is stored and an analysis has been scheduled.
 * The `analysis_id` is what the SPA then polls. */
export interface UploadResult {
  document_id: string;
  analysis_id: string;
  page_count: number;
  char_count: number;
  deduplicated: boolean;
}

export type AnalysisStatus = "queued" | "running" | "complete" | "failed";

/** A live analysis, as GET /api/analyses/{id} returns it. Deliberately the same shape the demo
 * uses (DemoAnalysis) so the Analyse page renders it with the same finding cards, so while it runs
 * the findings/absences/key_terms are empty and `status` says why. */
export interface Analysis {
  id: string;
  status: AnalysisStatus;
  error: string | null;
  filename: string;
  page_count: number;
  scan_model: string | null;
  summary: string | null;
  unverified_count: number;
  cost_microdollars: number | null;
  seconds: number | null;
  findings: Finding[];
  absences: Absence[];
  key_terms: KeyTerms | null;
}
