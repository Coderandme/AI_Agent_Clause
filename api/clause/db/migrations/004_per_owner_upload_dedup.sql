-- Per-owner deduplication for uploads. SPEC.md §2.5.
--
-- The original UNIQUE (sha256, source) made an uploaded file globally unique: if user A uploaded a
-- contract, user B uploading the SAME bytes would be deduplicated onto A's row. Under the anonymous
-- single-pool model that was harmless. Under accounts it is two bugs at once:
--
--   * Privacy: B would be handed a document row owned by A, and could read A's analysis by its id.
--   * Grant accounting: B's upload would not create a row B owns, so it would never count against
--     B's grant — a free analysis that the invite-only cap is specifically meant to prevent.
--
-- So uploads are deduplicated PER OWNER instead: the same user re-uploading the same file still
-- collapses onto their existing row (no double-charge), but two different accounts get their own
-- rows. Demo documents remain globally unique — they belong to nobody and are seeded once.

ALTER TABLE documents DROP CONSTRAINT documents_sha256_source_key;

-- Demo documents: one row per file, globally. (owner_user_id is always NULL here.)
CREATE UNIQUE INDEX documents_demo_sha_key
  ON documents (sha256) WHERE source = 'demo';

-- Uploads: one row per (file, owner). Two accounts may each hold the same contract; one account
-- may not hold it twice. Rows with a NULL owner (legacy anonymous uploads) are exempt, since NULLs
-- are distinct in a unique index — which is the correct behaviour for pre-accounts data.
CREATE UNIQUE INDEX documents_upload_owner_sha_key
  ON documents (sha256, owner_user_id) WHERE source = 'upload';
