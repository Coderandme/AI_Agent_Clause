# Clause — Architecture & Code Map (developer notes)

**This file is for you, the developer, not for users.** It explains how the project is laid out, what
each major file does, and how a request flows through the system. It is a living document — when the
code moves, move this with it. `SPEC.md` is *what* we're building and *why*; this is *where each piece
lives*. If you ever want it out of the shipped repo, add `ARCHITECTURE.md` to `.gitignore`; nothing
in the app depends on it.

Status: **backend auth is built and verified; the React frontend is the next iteration.** Sections
below mark ✅ built / 🟡 partial / ⬜ not yet.

---

## 1. The big picture

Clause is two programs that talk over HTTP, plus a database and a file store:

```
   Browser
     │
     ├── (static files) ────►  React SPA            ✅ (TypeScript, in web/)
     │                          the pages you see: landing, login, signup, analysis view
     │                          the DEMO is baked into it as static JSON — no server needed
     │
     └── (HTTP + JWT) ──────►  FastAPI backend      ✅ (Python, in api/)
                                 everything dynamic: signup, login, upload, run the agent
                                    │           │
                                    ▼           ▼
                          Neon Postgres     Cloudflare R2
                          (users, docs,     (uploaded PDFs;
                           analyses, …)      local disk in dev)
                                    │
                                    ▼
                          OpenAI API  ← the only thing that costs money
```

Two ideas do most of the explaining:

1. **The backend is the only thing that can spend money.** Every request that could call OpenAI goes
   through it, and it checks *who you are* (a JWT) and *whether you're allowed* (your grant) first.
2. **Access is invite-only** (`SPEC.md` §2.5). The public demo needs no account. Uploading your own
   contract needs an account, and an account needs an **access code** you handed out. So the set of
   people who can spend your OpenAI budget is exactly the set you invited.

### The three kinds of user

| Who | How they get in | What they can do |
|---|---|---|
| **Anonymous** | nothing | View the demo (free, static). Cannot upload. |
| **Invited client** | signs up with an access code | Upload + analyse, up to the code's grant (e.g. 3). |
| **Admin (you)** | `is_admin` flag set by hand in the DB | Unlimited uploads. |

---

## 2. Repository map

Only the parts that matter. `✅/🟡/⬜` = built / partial / not yet.

```
Rag_Doc/
├── SPEC.md                 the product spec — what & why (source of truth)
├── ROADMAP.md              the build order — V1 / V2 / V3
├── ARCHITECTURE.md         ← you are here (developer map)
├── README.md               public-facing; describes what is BUILT today
├── .env                    secrets (gitignored): OPENAI_API_KEY, DATABASE_URL, …
│
├── api/                    ✅ the FastAPI backend (all the Python)
│   ├── pyproject.toml      dependencies + tool config (ruff, mypy, pytest)
│   ├── .venv/              the virtual environment uv manages (gitignored)
│   └── clause/
│       ├── app.py          ✅ the FastAPI app: startup, CORS, wires routers together
│       ├── config.py       ✅ all settings, read from .env (DB url, JWT secret, limits…)
│       │
│       ├── auth/           ✅ ★ EVERYTHING ABOUT ACCOUNTS lives here
│       │   ├── security.py   password hashing (bcrypt) + JWT sign/verify. Pure, no DB.
│       │   ├── schemas.py    request/response shapes (Pydantic): SignupRequest, UserOut…
│       │   ├── repo.py       the SQL: find user, create-user-with-code, count uploads
│       │   ├── deps.py       "who is calling?" (current_user) + the spend gate (assert_can_upload)
│       │   ├── routes.py     the endpoints: POST /signup, POST /login, GET /me
│       │   └── codes.py      CLI to mint access codes and promote admins
│       │
│       ├── routes/
│       │   ├── documents.py  ✅ POST /api/documents — upload (login-gated) → schedules the analysis
│       │   └── analyses.py   ✅ GET /api/analyses/{id} — status + result the SPA polls
│       │
│       ├── analysis/       ✅ ★ runs the agent on an uploaded doc + persists the result
│       │   └── service.py    the 4 passes → findings/absences/key_terms/trace → record_spend
│       │
│       ├── ingest/         ✅ turn an uploaded PDF into rows
│       │   ├── service.py    validate → hash → store → parse → save (owner-aware)
│       │   ├── parse.py      PyMuPDF: extract text + per-page character offsets
│       │   └── storage.py    save the PDF (Cloudflare R2, or local disk in dev)
│       │
│       ├── agent/          ✅ ★ THE AI. Already built and tested.
│       │   ├── loop.py       the hand-rolled tool-use loop (SPEC §4.3)
│       │   ├── tools.py      the 5 tools the agent may call (strict schemas)
│       │   ├── prompts.py    the frozen system prompt (do not interpolate into it)
│       │   ├── verify.py     ★ the hallucination guard — proves every quote is real (SPEC §4.5)
│       │   └── execute.py    runs a tool call and records the result
│       │
│       ├── analyse.py      ✅ CLI: `python -m clause.analyse file.pdf` → prints findings
│       ├── demo.py         ✅ pre-computes the demo analyses into JSON (zero-cost demo)
│       ├── retention.py    ✅ ★ the 24-hour deletion job — makes the privacy promise true
│       ├── rules.py        ✅ loads rules/v1.yaml (the 15 risk rules)
│       ├── models.py       ✅ model IDs, tiering, pricing — the ONE place a model id appears
│       ├── guard.py        ✅ the spend ledger + the hard monthly $ ceiling, and client_ip
│       ├── text.py         ✅ text normalisation used by quote verification
│       │
│       └── db/
│           ├── pool.py       ✅ the Postgres connection pool + migration runner
│           └── migrations/   ✅ *.sql, applied in order at startup
│               ├── 001_init.sql              the full schema
│               ├── 002_usage_pools.sql       spend-ledger pools
│               ├── 003_accounts.sql          ★ users, access_codes, documents.owner_user_id
│               └── 004_per_owner_upload_dedup.sql   uploads dedupe per owner (privacy + grants)
│
├── rules/v1.yaml           ✅ the 15 risk rules — data, not code. NEVER delete.
├── demo/                   ✅ synthetic sample contracts + their pre-computed analyses
├── evals/                  ✅ real contracts + hand-labelled answer keys (eval harness; V3)
│
├── web/                    ✅ the React SPA (Vite + TypeScript + Tailwind)
│   ├── vite.config.ts        build config; aliases @demo → ../demo/precomputed
│   ├── index.html            the single page everything mounts into
│   └── src/
│       ├── main.tsx          entry point: mounts <App> into #root
│       ├── App.tsx           ★ the routes, and ProtectedRoute (the login gate)
│       ├── types.ts          the shapes crossing the wire (mirrors the Pydantic models)
│       ├── api/client.ts     ★ the ONLY place the SPA calls the backend; attaches the JWT
│       ├── auth/AuthContext.tsx  ★ who is logged in, app-wide; stores the token
│       ├── demo/index.ts     imports the pre-computed demo JSON straight into the bundle
│       ├── pages/
│       │   ├── Landing.tsx     public: the demo — risks, key terms, trace, and the source PDF
│       │   │                   (click a finding's "Page N ↗" to check the quote against the contract)
│       │   ├── Login.tsx       sign in
│       │   ├── Signup.tsx      sign up — requires an access code
│       │   └── Analyse.tsx     protected: upload → poll → real findings + your remaining grant
│       └── components/       Layout (+ disclaimer), FindingCard, Severity, Trace,
│                             KeyTermsTable, Form primitives
├── Dockerfile, DEPLOY.md   deployment: the backend container (HF Spaces, Docker SDK)
└── Makefile                shortcuts: make test / lint / analyse / eval
```

The single most useful thing to internalise: **`auth/` is self-contained.** Six small files, each with
one job. If you want to understand accounts, read those six and nothing else.

---

## 3. How the auth pieces fit (the six files in `auth/`)

Think of a request as passing through these in order:

```
  HTTP request
      │
  schemas.py   ── validates the JSON body (is this a real email? is the password long enough?)
      │
  routes.py    ── the handler: decides what to do (sign up? log in?)
      │
  repo.py      ── talks to Postgres (create the user, look them up, count their uploads)
      │
  security.py  ── hashes the password / signs the token (the crypto)
      │
  deps.py      ── on PROTECTED routes, runs FIRST: reads the token, loads the user, checks the grant
```

- **`security.py`** is the vault. `hash_password` / `verify_password` (bcrypt), and `issue_token` /
  `decode_token` (JWT). It imports no database and no web framework, so it's easy to test in isolation
  — which is exactly what `tests/test_auth.py` does.
- **`schemas.py`** is the contract for the API's shape. Because `UserOut` has no `password_hash`
  field, it is *impossible* to accidentally leak a hash in a response — Pydantic only serialises what's
  declared.
- **`repo.py`** is the only file with SQL for accounts. `create_user_with_code` is the interesting one:
  it redeems the code and creates the user **in one transaction**, so a code can't be half-used.
- **`deps.py`** holds the two guards. `current_user` turns a token into a user (or 401). 
  `assert_can_upload` is the money gate: admins pass; everyone else must be under their grant *and*
  under the global monthly ceiling.
- **`routes.py`** wires the above into three endpoints.
- **`codes.py`** is the little admin tool you run from the terminal to create codes and admins.

---

## 4. Code flows (follow the arrows)

### 4.1 Signup ✅  — "a client you invited creates their account"

```
Browser: POST /api/auth/signup { email, password, access_code }
   │
routes.signup
   │  1. security.hash_password(password)            → a bcrypt hash (never the plaintext)
   │  2. repo.create_user_with_code(...)             → in ONE transaction:
   │        • lock the code row (must exist & be unclaimed)   else → 400 "code invalid/used"
   │        • INSERT the user with upload_grant = code.grant  else → 409 "email taken"
   │        • mark the code claimed
   │  3. security.issue_token(user)                  → a JWT
   └─► 201 { access_token, user }   ← the browser stores the token and is now logged in
```

### 4.2 Login ✅ — "come back later"

```
Browser: POST /api/auth/login { email, password }
   │
routes.login
   │  1. repo.get_user_by_email(email)
   │  2. security.verify_password(password, user.password_hash)
   │       (if the user doesn't exist OR the password is wrong → the SAME 401,
   │        so you can't tell which accounts exist)
   │  3. security.issue_token(user)
   └─► 200 { access_token, user }
```

### 4.3 Any protected request ✅ — "how the backend knows who you are"

Every request to a protected endpoint carries the token in a header:
`Authorization: Bearer <jwt>`.

```
deps.current_user  (runs before the handler)
   │  1. read the Bearer token from the header        (none → 401)
   │  2. security.decode_token(token)                 (bad/expired signature → 401)
   │  3. repo.get_user_by_id(claims.user_id)          (deleted since issued → 401)
   └─► hands the handler a fully-loaded AuthUser
```

There is **no session table.** The token itself carries the identity; we just verify its signature.
That's what "stateless auth" means, and it's why the secret in `config.jwt_secret` matters so much —
anyone who has it can mint a token for anyone.

### 4.4 Upload → analyse → poll ✅ — "the one expensive door"

```
Browser: POST /api/documents  (multipart PDF)  + Bearer token
   │
deps.current_user            → must be logged in            (else 401)
   │
routes.upload
   │  assert_can_upload(conn, user)      ← THE GATE, before any work:
   │     • not admin & used >= grant     → 403 "you've used your N analyses"
   │     • month spend >= hard ceiling   → 402 "budget spent, demos still work"
   │  ingest(...) owner_user_id=user.id  → validate, parse, store, save rows
   │  analysis.create_analysis(...)      → a 'queued' row
   │  background.add_task(run_and_store)  → the agent runs AFTER the response
   └─► 202 { document_id, analysis_id, … }
   │
   │   ~40-70s later, in the background (analysis/service.py):
   │     run the 4 rule-family passes → verify every quote → write findings,
   │     absences, key_terms, trace → guard.record_spend()  ← arms the ceiling
   │
Browser: polls GET /api/analyses/{id} every 3s
   └─► status: queued → running → complete  (then it renders the findings)
```

The scan can't run inside the request — 40-70s is too long to hold an HTTP connection across a
free-tier proxy — so it runs as a background task and the SPA polls. This is the simple in-process
version of the spec's job queue; the durable Postgres queue is still deferred (ROADMAP V1), and the
schema for it (`jobs`, `agent_events`) is already in place.

`used` is `users.uploads_used` — a **counter**, incremented by ingest when a document is created.
Uploading the **same** file twice doesn't charge twice (it deduplicates), but a *second, different*
contract does; once `used` reaches the grant, the gate returns 403. (Verified end-to-end: first
upload → 202, second → 403.)

**Why a counter and not `count(*) FROM documents`?** Because the 24-hour deletion job (§4.7) deletes
those rows. Counting them would hand everyone's grant back every night — a client with grant=1 could
upload one contract a day forever. Usage is a fact about the past and must outlive the content we
delete (migration 005).

### 4.5 The agent ✅ — "what actually reads the contract"

The same agent runs from the CLI (`python -m clause.analyse file.pdf`), from the demo pre-baker, and
now from the web upload (§4.4) — the orchestration lives in `analysis/service.py` for the web path:

```
agent/loop.py  ── a plain for-loop over messages:
   │   ask the model → it calls a tool → run the tool → feed the result back → repeat
   │   tools (agent/tools.py): get_rule_detail, record_finding, record_key_terms,
   │                           note_absence, finalize
   │   every record_finding quote goes through agent/verify.py — if the quote isn't
   │   provably in the document, the finding is DISCARDED (the hallucination guard)
   └─► verified findings, each with a page number
```

**Verified end-to-end** (a real run through the web path): upload → 202 → polled `running` →
`complete` in 80s → **15 findings, quote verification 15/15**, key terms extracted, **$0.423 recorded
to the ledger**, grant exhausted (remaining=0).

**The hard ceiling is now armed.** `analysis/service.py` calls `guard.record_spend` in the same
transaction that writes the findings, so `usage_ledger` fills as analyses complete and
`assert_can_upload`'s month-spend check finally has real numbers to compare against. (Note the timing:
the check reads spend from *prior completed* analyses, so a burst of simultaneous uploads could each
pass the check before any of them records — acceptable at invite-only volume, worth knowing.)

**Still deferred (⬜):** *live* streaming of the trace as it happens (SSE). The trace is recorded to
`agent_events` and returned when the analysis completes, but the web UI shows the result at the end
rather than streaming it turn-by-turn. The durable job queue is deferred too — the background task is
in-process, so a container restart mid-analysis loses that run (the user re-uploads).

### 4.7 The 24-hour deletion job ✅ — "the promise the dropzone makes"

The upload page tells a person *"your file is deleted 24 hours later."* `retention.py` is what makes
that true. It sweeps **at boot and then hourly**, deleting every upload past its `expires_at`:

```
retention.sweep()
   │  SELECT ... FROM documents WHERE expires_at < now()
   │  for each:  storage.delete(pdf)   ← the object FIRST
   │             DELETE FROM documents ← then the row (cascades)
   └─► gone: the PDF, the text, the pages, the analysis, the findings, the trace
```

Object-then-row order is deliberate: delete the row first and a failed object delete would orphan
the file with no pointer to it. This way a failure just leaves the row for the next sweep to retry.

The findings and trace go too, not just the PDF — they quote the contract verbatim, so deleting only
the file would be theatre. What survives is `users.uploads_used` (a fact about consumption, not
content) and `usage_ledger` (a hashed cost total). Demo documents have `expires_at IS NULL` and are
never touched.

Hourly rather than a tight poll because Neon meters compute-hours (ROADMAP §5.1). `python -m
clause.retention` runs one sweep for a cron, so the promise doesn't depend on our host.

### 4.6 The demo ⬜(SPA) — "zero-cost, no login"

`demo.py` runs the agent once per sample and freezes the result (findings + the real trace) to JSON in
`demo/precomputed/`. In the SPA these files will be bundled as static assets, so clicking a sample
renders instantly with **no backend and no account** — the always-available front door.

---

## 5. Running it locally

Everything runs inside the **uv-managed virtual environment** at `api/.venv` — no global installs.
(`uv` creates and uses that venv automatically; you don't need to `activate` anything, just prefix
commands with `uv run`.)

```bash
# 1. Install dependencies into api/.venv
cd api && uv sync --extra dev

# 2. Secrets — create ../.env (repo root) with at least:
#      DATABASE_URL=postgresql://…           (Neon works; so does local Postgres)
#      OPENAI_API_KEY=sk-…                   (only needed to actually run the agent)
#      JWT_SECRET=<a long random string>     (python -c "import secrets; print(secrets.token_urlsafe(48))")

# 3. Run the API (applies DB migrations on startup)
uv run uvicorn clause.app:app --reload
#   → http://127.0.0.1:8000    docs at /docs

# 4. Invite yourself: mint a code, sign up in the API docs, then make yourself admin
uv run python -m clause.auth.codes new --grant 3
uv run python -m clause.auth.codes make-admin you@example.com
uv run python -m clause.auth.codes list

# 5. Quality gate (all green today)
uv run ruff check clause tests      # lint
uv run mypy clause/auth             # types (auth is clean; agent/evals have pre-existing findings)
uv run pytest -q                    # 49 tests
```

> **VS Code tip:** if the editor shows "package not installed" squiggles, point it at the venv
> interpreter: Command Palette → *Python: Select Interpreter* → `api/.venv/Scripts/python.exe`.

### The frontend

Two terminals: the API on :8000, the SPA on :5173.

```bash
# terminal 1 — the backend
cd api && uv run uvicorn clause.app:app --reload

# terminal 2 — the SPA
cd web && npm install     # first time only
npm run dev               # → http://localhost:5173
npm run build             # typecheck + production build into web/dist
```

The landing page and its demo work **with the API stopped** — that is the whole point of bundling the
demo (§4.6). Login, signup, and upload need the API running.

> **Two toolchain notes.** (1) `web/` pins **Vite 7**, not 8: Vite 8's bundler needs Node ≥22 and this
> machine runs Node 20.12. Upgrading Node to 20.19+ silences Vite 7's own warning; Vite 8 would need
> 22+. (2) The demo JSON is *aliased*, not copied — `@demo` points at `../demo/precomputed` so the
> backend and frontend share one source of truth. `vite.config.ts` needs `server.fs.allow: [".."]`
> for that, because Vite refuses to serve outside its root by default.

---

## 6. What's next

The MVP loop is now closed end-to-end: a public demo, invite-only accounts, and **upload → agent →
real findings** with the spend ceiling armed. Sensible next steps, roughly in order:

- **Show the uploaded PDF** on the Analyse page, with the same "jump to page N" cross-check the demo
  has — the finding data (`page_number`) is already there; it needs the file served to the browser
  (there's a `GET /api/documents/{id}/file` signed-URL route to build on).
- **Live trace streaming (SSE)** so an uploader watches the agent work instead of waiting on a
  spinner. The events are already recorded to `agent_events`; this is the streaming transport.
- **Deploy.** V1's own "done when" is a stranger opening a public URL. Both halves go to **Render**,
  described by the committed `render.yaml`: the API as a Docker web service (a real process — an
  analysis runs 60-80s as a background task *after* the response, which any serverless host would
  kill), the SPA as a static site. See `DEPLOY.md`.
- Then per `ROADMAP.md`: RAG Q&A (V2); memo PDF and the featured eval harness (V3); Stripe and a
  public self-serve tier only if this ever becomes a real SaaS.
