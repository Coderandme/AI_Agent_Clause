-- Make grant accounting durable, so the 24-hour deletion job cannot refund it. SPEC.md §2.5, §7.2.
--
-- THE BUG THIS FIXES. Usage was computed by COUNTING rows in `documents`:
--
--     used = SELECT count(*) FROM documents WHERE owner_user_id = $1
--
-- That was fine while nothing ever deleted a document. But SPEC.md §7.2 promises uploads are deleted
-- 24 hours after upload, and the moment that job runs, the count drops back to zero and every user's
-- grant silently refills. A client with grant=1 could upload one contract a day, forever — the exact
-- thing the invite-only cap exists to prevent. The privacy feature would have become a spend exploit.
--
-- So usage becomes a COUNTER that is incremented when a document is created and never decremented.
-- "You consumed 2 analyses" is a fact about the past; it must outlive the contract text we delete.
--
-- The trade is deliberate: a counter can theoretically drift from the rows, whereas a count cannot.
-- But drift is the lesser evil — here the rows are *designed* to disappear, so counting them was
-- measuring the wrong thing in the first place.

ALTER TABLE users ADD COLUMN uploads_used int NOT NULL DEFAULT 0;

-- Backfill from the documents that still exist, so accounts created before this migration keep the
-- usage they have already had. Nothing has been deleted yet, so at this moment the count IS correct.
UPDATE users u
SET uploads_used = (
  SELECT count(*) FROM documents d WHERE d.owner_user_id = u.id
);
