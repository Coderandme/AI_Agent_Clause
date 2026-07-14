-- Split the usage ledger into two pools. ROADMAP.md, and clause/guard.py for the reasoning.
--
-- A single global spend ceiling protects the wallet by breaking the demo at the worst possible
-- moment: a bot drains the budget on Tuesday, and on Thursday the author opens their own project in
-- an interview and it says "uploads disabled".
--
-- So the budget is split. Strangers draw from `anonymous`, which is small and expendable. Anyone
-- with an access code draws from `reserved`, which strangers cannot reach. A bot can empty the
-- first. It cannot touch the second.

ALTER TABLE usage_ledger ADD COLUMN pool text NOT NULL DEFAULT 'anonymous'
  CHECK (pool IN ('anonymous', 'reserved'));

-- The primary key must now include the pool: one IP can legitimately appear in both, on the same
-- day, if the visitor enters an access code partway through.
ALTER TABLE usage_ledger DROP CONSTRAINT usage_ledger_pkey;
ALTER TABLE usage_ledger ADD PRIMARY KEY (day, ip_hash, pool);

CREATE INDEX ON usage_ledger (day, pool);
