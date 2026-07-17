-- Accounts and invite-only access. SPEC.md §2.5, ROADMAP.md v0.3.
--
-- The product is a portfolio tool shown to a handful of prospects, not a public SaaS. So the
-- expensive action — running the agent on your OWN contract — is invite-only:
--
--   * The public demo needs no account and costs nothing (it replays pre-computed analyses).
--   * Uploading requires an account, and an account requires a single-use ACCESS CODE you handed
--     out. The set of people who can spend the OpenAI budget is therefore exactly the set you
--     invited — there is no anonymous upload path to abuse.
--   * A code carries a GRANT (how many analyses it unlocks). It becomes users.upload_grant.
--   * Admins (you) are unlimited, set by hand with the is_admin flag.
--
-- This supersedes the anonymous two-pool model in guard.py as the PRIMARY spend control. The hard
-- global monthly ceiling (usage_ledger, §7.2) still stands behind it as the ultimate backstop.

CREATE TABLE users (
  id             uuid PRIMARY KEY,
  email          text NOT NULL,
  -- Case-insensitive uniqueness: nobody should be able to register "Alice@x.com" when "alice@x.com"
  -- exists. We store the address as typed and enforce uniqueness on its lowercased form.
  email_ci       text GENERATED ALWAYS AS (lower(email)) STORED,
  password_hash  text NOT NULL,             -- bcrypt; the plaintext password is never stored
  is_admin       bool NOT NULL DEFAULT false,
  -- Lifetime number of analyses this account may run. Set from the access code at signup. Admins
  -- ignore it entirely. The check before an analysis is: is_admin OR used < upload_grant.
  upload_grant   int  NOT NULL DEFAULT 0,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_ci_key ON users (email_ci);

-- An access code is a coupon for ACCESS, not for money. Single-use: one code, one client, so clients
-- are distinguishable and individually revocable. Signup consumes an unclaimed code and copies its
-- grant onto the new user. Mint them with `python -m clause.auth.codes new --grant 3` (auth/codes.py).
CREATE TABLE access_codes (
  code         text PRIMARY KEY,
  grant_count  int  NOT NULL CHECK (grant_count >= 0),   -- → users.upload_grant on redemption
  claimed_by   uuid REFERENCES users ON DELETE SET NULL, -- NULL until a signup consumes it
  claimed_at   timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON access_codes (claimed_by);

-- Who uploaded a document. NULL for demo documents (which belong to nobody) and for any legacy
-- anonymous upload predating accounts. The free-tier cap counts a user's uploads through this column.
ALTER TABLE documents ADD COLUMN owner_user_id uuid REFERENCES users ON DELETE SET NULL;
CREATE INDEX ON documents (owner_user_id) WHERE owner_user_id IS NOT NULL;
