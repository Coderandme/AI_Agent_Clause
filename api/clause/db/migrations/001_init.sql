-- Clause — initial schema. SPEC.md §5.
--
-- This migration ships the COMPLETE data model, including tables and columns that V1 never writes
-- to. That is deliberate, and it is the single decision that keeps V1 -> V2 from being a rewrite
-- (ROADMAP.md §4):
--
--   * `chunks` ships with its vector(384) column and its HNSW index, and stays empty until V2 adds
--     retrieval. Shipping an unused table costs nothing. Adding a vector column and an HNSW index
--     to a populated production table costs an outage.
--   * `eval_runs` likewise: `make eval` writes to it from V1, and the Evaluations page reads it in
--     V3 without a migration.
--
-- PDFs are never stored in Postgres. `documents.storage_key` points at object storage (R2).

CREATE EXTENSION IF NOT EXISTS vector;

-- ── Documents and their text ─────────────────────────────────────────────────────────────────────

CREATE TABLE documents (
  id              uuid PRIMARY KEY,
  sha256          text NOT NULL,
  filename        text NOT NULL,
  source          text NOT NULL CHECK (source IN ('demo', 'upload')),
  page_count      int  NOT NULL,
  char_count      int  NOT NULL,
  -- Set at ingest by character density (char_count / page_count < 100). Because we pass extracted
  -- text and not page images (SPEC.md §3.2), a scanned PDF yields nothing to analyse — so v1
  -- rejects it at upload. The column exists so that rejection is data rather than a special case,
  -- and so that adding OCR later is a feature and not a schema change.
  is_scanned      bool NOT NULL DEFAULT false,
  storage_key     text NOT NULL,
  full_text       text NOT NULL,
  -- Anonymous cookie. NULL for demo documents, which belong to nobody.
  owner_session   text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  -- Uploads: now() + 24h, enforced by the deletion job. Demo documents: NULL, they are permanent.
  -- The 24-hour promise is stated inline on the dropzone (SPEC.md §7.2) because a person about to
  -- hand a contract to a stranger's website wants to read exactly that sentence.
  expires_at      timestamptz,
  UNIQUE (sha256, source)
);
CREATE INDEX ON documents (expires_at) WHERE expires_at IS NOT NULL;

-- Maps a character offset in documents.full_text to a page. This is what turns a verified quote
-- into a page number and a highlight (SPEC.md §4.5, §9.3).
CREATE TABLE pages (
  document_id     uuid NOT NULL REFERENCES documents ON DELETE CASCADE,
  page_number     int  NOT NULL,           -- 1-indexed
  char_start      int  NOT NULL,           -- offset into documents.full_text
  char_end        int  NOT NULL,
  PRIMARY KEY (document_id, page_number)
);

-- V2. Empty in V1 — the risk scan reads the whole document and does not retrieve (SPEC.md §4.1).
-- Retrieval exists for Q&A, and Q&A ships in V2.
CREATE TABLE chunks (
  id              uuid PRIMARY KEY,
  document_id     uuid NOT NULL REFERENCES documents ON DELETE CASCADE,
  ordinal         int  NOT NULL,
  section_label   text,                    -- "9.2", "Schedule A", when detectable
  char_start      int  NOT NULL,
  char_end        int  NOT NULL,
  text            text NOT NULL,
  embedding       vector(384),             -- bge-small-en-v1.5, local. See models.EMBEDDING_DIM.
  tsv             tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON chunks USING gin (tsv);
CREATE INDEX ON chunks (document_id, ordinal);

-- ── Analyses and their output ────────────────────────────────────────────────────────────────────

CREATE TABLE analyses (
  id                   uuid PRIMARY KEY,
  document_id          uuid NOT NULL REFERENCES documents ON DELETE CASCADE,
  status               text NOT NULL CHECK (status IN ('queued','running','complete','failed')),
  scan_model           text NOT NULL,      -- the resolved model ID, not the tier name
  extract_model        text NOT NULL,
  rule_library_version text NOT NULL,      -- hash of rules/v1.yaml, so old analyses stay explicable
  summary              text,
  turns_used           int,
  unverified_count     int  NOT NULL DEFAULT 0,
  token_usage          jsonb,              -- per-model, including cached-token counts
  cost_microdollars    bigint,
  error                text,               -- refusal, truncation, or exception. Surfaced honestly.
  started_at           timestamptz,
  completed_at         timestamptz
);
CREATE INDEX ON analyses (document_id);

CREATE TABLE findings (
  id              uuid PRIMARY KEY,
  analysis_id     uuid NOT NULL REFERENCES analyses ON DELETE CASCADE,
  rule_id         text NOT NULL,
  severity        text NOT NULL CHECK (severity IN ('critical','high','medium','low')),
  title           text NOT NULL,
  exposure        text NOT NULL,
  recommendation  text NOT NULL,
  quoted_text     text NOT NULL,           -- as the agent supplied it
  -- Everything below is DERIVED by quote verification (SPEC.md §4.5), never supplied by the agent.
  -- The agent cannot be trusted to produce a character offset, so it is not asked to.
  matched_text    text,                    -- as actually found in the source
  char_start      int,
  char_end        int,
  page_number     int,
  -- The hallucination guard. A finding with verified = false is NOT rendered in the UI and NOT
  -- included in the memo. It exists only so the agent can be told it misquoted, and so that
  -- analyses.unverified_count can be counted against the 0.15 eval gate.
  verified        bool NOT NULL,
  confidence      text NOT NULL CHECK (confidence IN ('high','medium','low')),
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON findings (analysis_id, severity);

-- Rules checked and NOT triggered. This is what lets the memo say "we checked for X and found
-- none", which is what separates a tool that looks thorough from one that is. It also gives the
-- eval harness its true-negative signal, which is why SPEC.md §10.1 says keep RECORDING these even
-- if the UI stops rendering them.
CREATE TABLE absences (
  analysis_id     uuid NOT NULL REFERENCES analyses ON DELETE CASCADE,
  rule_id         text NOT NULL,
  rationale       text NOT NULL,
  PRIMARY KEY (analysis_id, rule_id)
);

CREATE TABLE key_terms (
  analysis_id     uuid PRIMARY KEY REFERENCES analyses ON DELETE CASCADE,
  -- Validated by the KeyTerms Pydantic model before it lands here. Nulls are legal and MEANINGFUL:
  -- "no liability cap present" is itself a finding, and the UI renders it as "Not specified".
  payload         jsonb NOT NULL
);

-- The agent trace. Not a debug panel — a feature (SPEC.md §2.3). Persisting it means the trace
-- survives a page refresh, replays for a finished analysis, and lets demo documents ship with a
-- REAL recorded trace that replays at a plausible speed with zero API calls.
CREATE TABLE agent_events (
  analysis_id     uuid NOT NULL REFERENCES analyses ON DELETE CASCADE,
  seq             int  NOT NULL,
  kind            text NOT NULL CHECK (kind IN ('status','reasoning','text','tool_call','tool_result','finding','usage')),
  payload         jsonb NOT NULL,
  at              timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (analysis_id, seq)
);

-- ── Queue ────────────────────────────────────────────────────────────────────────────────────────

-- SPEC.md §3.5. No Redis, no Celery. Claimed with FOR UPDATE SKIP LOCKED.
--
-- NOTE (ROADMAP.md §5.1): the worker must NOT poll this table on a timer. Neon's free tier meters
-- compute-hours and suspends when idle; a 5-second poll keeps the database awake 24/7 and burns the
-- monthly allowance while doing no work. The API signals the worker directly on enqueue; polling is
-- reserved for boot-time recovery of orphaned jobs and for while a job is in flight.
CREATE TABLE jobs (
  id              uuid PRIMARY KEY,
  kind            text NOT NULL,
  payload         jsonb NOT NULL,
  status          text NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','running','complete','failed')),
  attempts        int  NOT NULL DEFAULT 0,
  last_error      text,
  run_after       timestamptz NOT NULL DEFAULT now(),
  locked_at       timestamptz,
  locked_by       text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON jobs (status, run_after) WHERE status = 'queued';

-- ── Cost control ─────────────────────────────────────────────────────────────────────────────────

-- SPEC.md §7.2. The raw IP is NEVER stored — only HMAC(ip, secret).
CREATE TABLE usage_ledger (
  day               date NOT NULL,
  ip_hash           text NOT NULL,
  analyses          int  NOT NULL DEFAULT 0,
  cost_microdollars bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (day, ip_hash)
);

-- ── Evaluation ───────────────────────────────────────────────────────────────────────────────────

-- SPEC.md §8. Written by `make eval`, which runs OFFLINE against the checked-in corpus and answer
-- keys in evals/. It is a test suite, not a product feature: the corpus is frozen and versioned in
-- git, because a recall number is only meaningful when compared across runs against the SAME exam.
--
-- The Evaluations page (V3) READS this table and renders the scorecard — including the misses and
-- the false alarms. It never triggers a run.
CREATE TABLE eval_runs (
  id                   uuid PRIMARY KEY,
  at                   timestamptz NOT NULL DEFAULT now(),
  git_sha              text,
  scan_model           text NOT NULL,      -- which tier this row is for; the §8.1 sweep writes one row per tier
  rule_library_version text NOT NULL,
  prompt_version       text NOT NULL,      -- hash of the frozen system prompt
  -- The §8 scorecard: recall_critical_high, recall_all, precision, verification_rate,
  -- anchor_accuracy, cost_per_doc_microdollars, wall_clock_seconds.
  metrics              jsonb NOT NULL,
  -- Per-contract, per-finding detail: hits, misses (false negatives), false alarms (false
  -- positives), with the clause text. This is what the Evaluations page renders, and publishing
  -- our own misses is a stronger signal than publishing only the headline number.
  detail               jsonb NOT NULL
);
CREATE INDEX ON eval_runs (at DESC);
