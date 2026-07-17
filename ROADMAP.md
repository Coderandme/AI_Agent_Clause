# Clause — Incremental Roadmap

**Companion to SPEC.md** · Version 0.5 · 2026-07-17 · Status: **V1 DEPLOYED — next up: V2 (RAG Q&A)**

SPEC.md specifies the finished product. This document specifies the *order we build it in*, the
*infrastructure it runs on at zero cost*, and — most importantly — the set of decisions we make on
day 1 so that no later version requires re-architecting an earlier one.

Where this document contradicts SPEC.md, it says so explicitly and states why.

> **v0.2 (2026-07-15) — MVP reframe.** The project sprawled faster than it shipped, so V1 is
> re-cut around one runnable product: **a real login, and the agent you already have behind it.**
> The AI core — the hand-rolled loop, the 15 rules, and the quote-verification guard — is *built and
> tested already*; what V1 adds is the product shell that makes it usable by a named person. The
> eval harness (also already built) moves out of the featured MVP path; retrieval/Q&A, the memo, and
> Stripe move to later versions. See §3 for the new cut and §9 for what changed from v0.1.
>
> **v0.3 (2026-07-15) — invite-only access.** On the point that this is a portfolio tool shown to a
> few prospects, not a public SaaS: the self-serve free tier and the Upgrade/Stripe flow are
> *removed.* Running the agent is invite-only — a client signs up with a single-use **access code**
> you hand out, which sets a per-account upload grant; you (admin) are unlimited on a protected
> reserve. This makes the set of people who can spend your OpenAI budget exactly the set you invited.
> Accounts and JWT stay (they are the login-page artifact and the spend gate). See the updated §3 V1
> table and §9.
>
> **v0.4 (2026-07-17) — V1 is built; hosting moved again.** Shipped since v0.3: JWT auth and
> invite-only access codes, the Vite/React SPA (with the demo bundled as static JSON and a PDF
> cross-check), **upload → agent → verified findings** end-to-end, and the 24-hour deletion job.
> Verified on a real run: 15 findings, 15/15 quotes verified, $0.42, ceiling armed. Hosting moved to
> **Render** after Hugging Face withdrew its free CPU tier in July 2026 — the second host to do so
> (§2.3). Two sections were found describing a jobs-table worker we never built and have been
> corrected to say what actually runs (§2.4, §5.1).
>
> **v0.5 (2026-07-17) — V1 is LIVE.** Deployed to Render from the committed `render.yaml`:
> `clause-web` (static SPA + bundled demo) and `clause-api` (Docker). Verified in production: a
> 17-page real contract (tearlab, SEC EDGAR) uploaded through the site, analysed, findings rendered,
> spend recorded to the ledger. **V1 is done by its own definition.**
>
> ── **IF YOU ARE PICKING THIS PROJECT UP: START HERE** ──────────────────────────────
> The next version is **V2 — RAG Q&A** (§3, "Version 2"): chunking, local-or-API embeddings,
> `pgvector` hybrid search, the `search_document` tool, and the Ask tab. Before writing code, read:
> `ARCHITECTURE.md` (the map of what exists), §2.4 here (what the async story actually is — there is
> NO jobs-table worker), and §2.3's RAM warning (Render free = 512 MB; local ONNX embeddings likely
> do not fit — SPEC §3.3 pre-authorises switching to OpenAI's embedding API, ~$0.0006/contract).
> Smaller debts that can ride along with V2, in value order: live SSE trace streaming for uploads
> (events already recorded in `agent_events`), showing the uploaded PDF with page-jump on the
> Analyse page (needs R2 configured — local disk on Render is ephemeral), and a reaper for analyses
> stuck at `running` after a container restart.

**Cost position:** every piece of infrastructure is free tier. OpenAI tokens are the only thing that
costs money, and that is accepted. The spend ceiling from SPEC.md §7.2 still ships — but as *abuse
protection on a public URL*, not as a budget constraint. Strangers should not be able to run the
bill up; you should be able to.

---

## 1. The one place this contradicts the spec

SPEC.md §3.1 says: *"Hosting | Vercel (web) · Fly.io (api + worker) · Neon (Postgres) | All have
usable free tiers."*

**Only the Neon half of that survived.** Fly.io withdrew its free allowance and bills from the first
machine. We moved to Hugging Face Spaces; HF then withdrew its free CPU tier too (§2.3). We now run
**both halves on Render** — the API as a Docker web service, the SPA as a static site — which also
retires the Vercel row, not because Vercel is unfit for a static build (it is fine) but because one
platform and one committed `render.yaml` beats two dashboards.

So the hosting row of that table is now wrong twice over, and the lesson is in §2.3: free tiers are a
rental, not a foundation. What makes that survivable is that *nothing in the code knows where it
runs* — the API is a Dockerfile that binds `$PORT`, and it can move to any host that runs a
container.

Everything else in §3 — Postgres as the only datastore, the Postgres job queue, local embeddings,
the hand-rolled loop — is *unchanged*, and in fact each of those choices is what makes a zero-cost
deployment possible at all. A design that needed Redis, Pinecone, and Celery would need three more
free tiers stitched together, and would fall over on the first one that expired.

---

## 2. Target architecture (all versions)

```
   browser
     │
     ├──[static]──►  Vite + React SPA   (Render static site, free)
     │                 · landing (public) · login · signup+code · analysis view
     │                 · DEMO contracts bundled as static JSON ── $0, no backend at all
     │
     ├──[REST + JWT]──►┐
     └──[SSE trace]───►│
                       ▼
        ┌───────────────────────────────┐
        │  Docker container (free host) │
        │  uvicorn ── FastAPI routes    │
        │      ├─ auth  (JWT, bcrypt)   │
        │      ├─ ingest (PyMuPDF)      │
        │      ├─ agent loop (OpenAI)   │
        │      ├─ quote verification    │
        │      └─ (V2: fastembed, RAG)  │
        └───────┬───────────────┬───────┘
                │               │
                ▼               ▼
     ┌────────────────────┐  ┌────────────────────┐
     │ Neon Postgres      │  │ Cloudflare R2      │
     │ + pgvector (free)  │  │ uploaded PDFs      │
     │ users, documents,  │  │ (deleted at 24h)   │
     │ analyses, findings,│  └────────────────────┘
     │ jobs, chunks(V2)…  │
     └────────────────────┘

        Only line item that costs money: OpenAI tokens. Demo mode never touches it.
```

### 2.1 Why the SPA talks to the API for everything dynamic, and to nothing for the demo

A Vite SPA is static files. It cannot hold a database connection, so — unlike the v0.1 Next.js plan
— it does **not** read Neon directly. Every dynamic action (sign up, log in, upload, fetch an
analysis) is an authenticated REST call to the FastAPI container, and the live agent trace is an SSE
stream from that same origin, with CORS locked to the SPA's domain. This is simpler than the old
split: one API owns all reads and writes, and the JWT that gates uploads gates those reads too.

The **demo path touches none of it.** The two sample analyses are baked into the SPA build as static
JSON, so clicking a sample renders instantly from files the browser already downloaded — no API, no
database, no account. That is what keeps the 15-second hook alive even when the free container is
asleep (§5.2), and it is a *better* guarantee than v0.1's "read Neon directly," because now the demo
depends on no running service at all.

### 2.2 Free-tier inventory

| Service | Tier | What it holds | The limit that will actually bite |
|---|---|---|---|
| Render | Free static site | Vite + React SPA + the bundled demo | Bandwidth ceiling. Never sleeps — it is a CDN, not a process, which is why the demo survives the API napping. |
| Neon | Free | All Postgres, `pgvector` | Storage ceiling, and a monthly **compute-hour** allowance. See §5.1. |
| Cloudflare R2 | Free | Uploaded PDFs, rendered memos | Storage ceiling. Uploads are deleted at 24h, so this stays near empty. |
| Render | Free web service | FastAPI + agent + retention sweep | **512 MB / 0.1 vCPU**, and it sleeps after 15 min idle (~50s wake). The RAM is what will bite, at V2. See §2.3. |
| OpenAI | **Paid — accepted** | Nothing. It is the only cost. | Only the abuse ceiling we set ourselves. |

**Verify every one of these against the live pricing page before we rely on it.** Free tiers change,
and the Fly.io row in SPEC.md is the cautionary tale.

### 2.3 The API host — decided: **Render** (free web service)

> **This section has now been wrong twice, and that is the lesson.** v0.1 specced **Fly.io**; Fly
> withdrew its free tier. v0.2 replaced it with **Hugging Face Spaces**; in **July 2026** HF removed
> the free CPU Basic flavour and paywalled the Docker SDK for unpaid accounts, with no notice. Free
> tiers are not a foundation, they are a rental. The response is not to pick a "safer" host — it is
> to make moving cheap: the API is a Dockerfile with no host-specific code, the deployment is a
> committed [`render.yaml`](render.yaml), and the port comes from `$PORT`. Moving again is an
> afternoon.

**Render, free web service.** 512 MB / 0.1 vCPU, no credit card. It spins down after ~15 minutes idle
and takes ~50s to wake.

**Why the cold start is acceptable now, when §2.3 previously rejected Render *because* of it.** The
old objection was that a 50s wake blew the 15-second demo budget (SPEC §1.2). That assumed the demo
was served by the API. It isn't any more — the demo is pre-computed JSON bundled into the SPA (§2.1),
so it renders with this service asleep. The only people who can wake it are invited account holders
logging in or uploading, and someone who has just dropped a contract on the dropzone is already
waiting 60–80s for the analysis. The objection didn't get weaker; the architecture removed it.

**What we give up, honestly:** 512 MB and a tenth of a CPU. Fine for V1 — the analysis is spent
waiting on OpenAI, not computing. **Not fine for V2's local embeddings**: `fastembed`'s ONNX runtime
plus the model needs a few hundred MB on top of the app, and Render's $7 tier is *also* 512 MB, so
paying wouldn't fix it — 2 GB is ~$25/mo. When V2 lands, the cheaper answer is to drop local
embeddings and call OpenAI's embedding API (~$0.0006 per contract). SPEC §3.3 pre-authorises exactly
that: it says local embeddings were chosen for *fewer dependencies* and that **"cost does not decide
this."** If local starts costing $25/month, the trade flips.

**Rejected: AWS.** Fargate at 0.5 vCPU / 1 GB is ~$18/month, App Runner ~$5/month just to exist, and
neither counts the public IPv4, NAT, CloudWatch, and ALB charges that don't appear on the sticker.
That is 4× the entire OpenAI ceiling to serve it. AWS's free tier is also no longer a free tier: since
July 2025 new accounts get $200 of credits that expire in six months. Paying ~$20/month and then
being surprised by a bill is the wrong shape for a portfolio piece that idles between conversations.
If sleeping ever becomes annoying, the answer is $7 on Render, not $20 on AWS.

Note that OpenAI is *not* a host. It runs the model; it does not run our code. Quote verification, the
agent loop, PyMuPDF, the job queue, and the SSE endpoints are all our code and all need a process to
live in. That process is this container.

Nor can that process be Vercel — and this is structural, not about price. An analysis takes 40–80
seconds and runs as a background task that must outlive the HTTP response; a serverless function is
killed the instant it responds. (Vercel Hobby also caps a function at 60s, and our measured run was
80s, so it would fail twice over.) The SPA has the opposite needs — static files on a CDN — which is
why it lives on Render's static-site type rather than in this container.

Still rejected, for the record:

- **Fly.io** — withdrew its free tier; bills from the first machine.
- **Hugging Face Spaces** — withdrew its free CPU tier in July 2026. Was our choice in v0.2.
- **AWS** — see above. ~$18–36/month for one container, and its "free tier" is now a 6-month credit.
- **Google Cloud Run** — allocates CPU only *during* a request by default, which would freeze the
  background scan the moment we returned 202. Always-on CPU is a paid setting.
- **Koyeb (free).** Genuinely doesn't sleep, which is tempting — but it is one service at 0.1 vCPU /
  512 MB, the same RAM wall as Render, and a smaller company to bet the deployment on. Worth
  revisiting if Render's cold start turns out to annoy in practice.
- **Oracle Cloud always-free ARM VM.** Genuinely always-on, genuinely free, and by far the most
  generous RAM — which would also solve V2's embedding problem. But it is a VM: we would own the OS,
  the TLS certs, the systemd units, and the patching. The best fallback if the free-PaaS well runs
  dry entirely.

The choice is deliberately reversible: the API is a Dockerfile with no host-specific code, the port
comes from `$PORT`, and the deployment is a committed `render.yaml`. Two hosts have already vanished
under this project; the third will not cost us a rewrite.

### 2.4 The worker — what we actually built, and what we didn't

SPEC.md §3.5 specifies "a separate `worker` process polls this [jobs table]" with
`FOR UPDATE SKIP LOCKED`, retries, and crash recovery. **We did not build that, and V1 does not use
the `jobs` table at all.**

What runs instead: the upload route creates a `queued` row in `analyses` and hands the scan to a
**FastAPI background task** in the same process (`analysis/service.py`). It returns 202 with an
`analysis_id` immediately; the SPA polls `GET /api/analyses/{id}` until the row flips to `complete`.

**Why the queue didn't earn its place yet.** Everything the durable queue buys — claim semantics,
retries, recovery of an orphaned job — is insurance against a crash mid-analysis. The premium is a
claim loop, a poller, and a second process. At invite-only volume the uninsured loss is: one analysis
is lost, the row stays `running`, and the user uploads again. That is a worse product than the specced
design and a much better trade than building the machinery before anything depends on it.

**What it costs us, stated plainly:** a restart mid-scan loses that scan silently (the row sits at
`running` forever — there is no reaper). That is the honest bug in V1's async story, and the fix is
the specced queue, on the day it matters.

**What keeps the door open:** the `jobs` table ships in migration 001, unused. The agent loop never
knew who called it — the CLI, the demo pre-baker, and the web path all drive the same `run_pass`. So
the queue is additive when it arrives; nothing gets rewritten to accept it.

---

## 3. The versions

Each version ends deployed to a public URL and demonstrable to a stranger. None of them ends with
"the parser is done."

### Version 1 — MVP: *"Log in, upload your contract, and every quote the agent shows you is provably real."*

The agent that reads a contract and proves its quotations — **which already exists and passes its
tests** — put behind a real product shell: a public demo anyone can watch, a login, and a single
gated upload of your own document. V1 is almost entirely *product plumbing around a finished
engine*; the hard AI work is done.

**In scope**

| Area | What ships |
|---|---|
| **Auth** | FastAPI + Pydantic + **JWT** (bcrypt-hashed passwords). `users` and `access_codes` tables on Neon. **Signup requires a valid access code**; login issues the JWT, verified per request, no session store. `is_admin` set by hand in the DB. (SPEC §2.5.) |
| **Access control (invite-only)** | Public demo needs no account. Uploading requires an account, and an account requires a code you handed out. A code carries a grant (e.g. 3 analyses) → `users.upload_grant`; the check before an analysis is `is_admin OR users.uploads_used < upload_grant`. Grant spent → inline "contact the admin", **no** Upgrade page. Admin = unlimited. **`uploads_used` is a counter, not `COUNT(documents)`** — the 24h deletion job removes those rows, and counting them would refund every grant nightly (migration 005). |
| Frontend | **Vite + React SPA** (TypeScript, Tailwind). Screens: Landing (public), Login, Sign up (with access-code field), Analysis view (upload → trace → risk cards). Disclaimer everywhere. No Upgrade page. |
| Ingest | PDF upload → validate → hash → R2 → PyMuPDF parse → full text + per-page char offsets. Scanned-PDF rejection by character density. *(Built.)* |
| Rule library | `rules/v1.yaml`, all 15 rules, all 4 families, hashed into `analyses.rule_library_version`. *(Built.)* |
| **The agent** | Hand-rolled loop (§4.3), four rule-family passes, prompt caching, five strict tools. *(Built — wired behind the authenticated upload endpoint.)* |
| **Quote verification** | The full guard (§4.5): normalise → exact match → rapidfuzz locate → ordered token check → char range → page number. Unverified findings never render. *(Built.)* |
| Risk UI | Severity-ranked risk cards, each with a verbatim quote and a page number. Demo: the agent trace replays, and "Page N ↗" opens the source PDF at that page so a visitor can check a quote against the contract themselves. Uploads render the same cards (trace is recorded but not yet shown — see out of scope). |
| Demo mode | The **two** pre-baked samples (SaaS MSA, mutual NDA) shipped as **static JSON bundled into the SPA** — the demo renders with *no backend at all*: zero API calls, zero cold-start, works even when the API is asleep. (This replaces v0.1's Next.js-server-components-read-Neon plan — see §5.2.) |
| Abuse control | The invite gate is the primary control: no code, no account, no spend. Behind it, the hard monthly ceiling — **armed**, since every completed analysis records its cost to `usage_ledger` (`analysis/service.py`). |
| Retention | The **24h deletion job** (`clause/retention.py`) — sweeps at boot and hourly, deleting the PDF and every row derived from it (findings and the trace quote the contract verbatim, so they go too). *(Built.)* |

**Deliberately out of scope for V1, and why**

- **The eval harness in the featured path.** It is *built* and stays in the repo (`evals/`, `make
  eval`) — this is a resequencing, not a deletion. It simply is not on the MVP's critical path or in
  the UI. The model-tier sweep already told us what it can on one contract (see the README): `sol`
  stays as the default and the corpus is too small to license a cheaper choice. Expanding to more
  labelled contracts and wiring CI gates is a later version (§3, V3).
- **Retrieval / Ask / RAG.** SPEC §4.1: retrieval exists for Q&A, not the risk scan. Cut from V1
  entirely (no ONNX, no `fastembed`, no HNSW on the critical path). The `chunks` table still ships in
  the V1 migration, empty. This is the **next** thing we build — see V2.
- **Durable job queue + live SSE streaming.** V1 runs the analysis for the logged-in uploader and
  the trace **replays** as it does today. The Postgres queue and live streaming are a hardening step,
  deferred; the schema (`jobs`, `agent_events`) still ships so nothing needs re-architecting.
- **Memo generation, span-precise highlighting, DOCX ingest, Stripe.** All later versions.

**Done when:** a stranger opens the public URL and watches the SaaS MSA demo replay with real
findings and verbatim quotes — *without logging in*. Someone you gave a code signs up with it,
uploads their own contract, and gets the same analysis; once their grant is spent the upload is
refused with an honest message. A stranger with no code cannot create a spending account at all.
Signed in as admin, uploads are unlimited.

---

### Version 2 — *"Ask it anything."* — RAG Q&A

The next step after the MVP, and the one Bijeeta flagged as the natural follow-on. This is where
retrieval lands — *for the reason the spec gives* (narrow questions, asked many times), which is a
better story than building RAG reflexively in V1 and using it for nothing. This is also the version
where "chatbot" becomes literally true: a grounded chat over the uploaded document.

**In scope**

| Area | What ships |
|---|---|
| Retrieval | Chunking (numbered-section regex → ~800-token packs, 100-token overlap, `section_label` carried forward). `fastembed` + `bge-small-en-v1.5`, local, batched. `pgvector` HNSW index. The hybrid SQL query from §3.4. |
| Sixth tool | `search_document` joins the agent's tool surface, so it can re-locate a clause in order to quote it precisely. |
| Ask tab | **Grounded Q&A** over hybrid retrieval, streamed, with inline citations that jump to the source span. This is the conversational chat, deferred out of the MVP on purpose. |
| Key Terms tab | The full two-column table, "Not specified" rendering, CSV/JSON export. |
| Absences | The "Checked and not found" list renders beneath the findings. |
| Demo mode | Expanded to **four** samples (adds the office lease and the freelance agreement). |

**Done when:** a signed-in user can ask "what happens if we terminate early?" and get a streamed
answer with a citation that jumps to the exact clause.

**Cost:** embeddings are local, so retrieval adds **zero** marginal API cost. Q&A adds ~$0.007/question.

---

### Version 3 — *"Take the memo with you, and here is the proof it works."*

The artifact and the evidence. The memo is what a prospective client forwards to their lawyer; the
eval numbers are what an engineering leader reads. Both were built or half-built already — this
version finishes and features them.

**In scope**

| Area | What ships |
|---|---|
| Memo | Jinja2 → Markdown → **WeasyPrint → PDF**. Download works. The artifact is good enough to send to someone. |
| Highlight overlay | **Span-precise.** Walk the pdf.js text layer, resolve the char window to a DOM range, paint rectangles behind it. Page-level remains the fallback. |
| Eval harness | The full **10-contract** hand-labelled corpus, featured. `make eval` prints the §8 table. |
| The gates | Recall ≥ 0.80 critical/high · precision ≥ 0.75 · verification rate ≥ 0.85 · anchor accuracy ≥ 0.90 · `unverified_count / total_findings` ≤ 0.15. A build that misses them fails. |
| The two silent-failure tests | (1) The second pass reports a **non-zero cached-token count** — zero means a cache invalidator crept into the prefix. (2) A deliberately corrupted quote **never** reaches `verified = true`. |
| CI | Three of the ten contracts run on every prompt/rule change. The full ten run nightly. |
| Observability | Structured JSON logs. `token_usage` and `cost_microdollars` per analysis. `/api/health` reports db, queue depth, spend headroom. |
| Durable async | The Postgres job queue and live SSE streaming of the trace (deferred from V1), if not already pulled forward. |
| DOCX ingest | The second half of `type ∈ {pdf, docx}`. |
| README | Architecture diagram, the tier-sweep table, the eval numbers, a demo GIF, the synthetic-corpus note. |

**Done when:** `make eval` produces the §8 table, CI enforces it, the memo downloads as a PDF, and
the README contains a number rather than an adjective for every claim it makes.

---

### Beyond V3 — explicitly not now (SPEC.md §1.3)

**A self-serve product** — public signup, a paid tier, Stripe, an Upgrade page — *if this ever
stops being a portfolio piece and becomes a real SaaS.* It is not one today, which is why invite-only
codes replaced all of that (§9). Also: OCR for scanned PDFs · cross-document comparison · a 16th
rule · redline generation. The schema already anticipates several. None ships until the first three
versions are done and deployed.

---

## 4. How we get from V1 to V3 without rewriting anything

This is the part of the plan that actually matters, and it reduces to one principle:

> **Ship the full data model and the full deployment topology in V1. Add only code paths after that.**

Five things are therefore fixed on day 1 and never revisited:

1. **The entire schema from SPEC.md §5 ships in the V1 migration** — the `users`, `access_codes`, and
   `documents.owner_user_id` that the invite-only access control needs *and* the tables V1 never writes to yet,
   including `chunks`, its `vector(384)` column, its HNSW index, and its `tsvector`. The cost of
   shipping an unused table is zero. The cost of adding a vector column and an HNSW index to a
   populated production table is not.
2. **The tool registry is a list.** V2 adds `search_document` by appending one entry; the loop, the
   dispatcher, and the SSE adapter never learn how many tools there are. (Per the caching discipline
   in §4.2, tools serialise **sorted by name** — so adding one invalidates the cached prefix only
   from `search_document` onward, and only on the deploy that adds it.)
3. **The SSE vocabulary from §6.2 is frozen in V1.** The frontend never sees an OpenAI type name;
   one adapter normalises them. V2's Ask tab reuses that vocabulary rather than inventing a second.
4. **The deployment topology is the final one from day 1.** Render (static SPA + Docker API) + Neon +
   R2. Note the caveat §2.3 earned the hard way: the *shape* is final (a static frontend, a
   long-lived container, one Postgres), but the *hosts* are rented — two have already withdrawn their
   free tiers under us. Nothing in the code knows where it runs, which is what makes that survivable.
   V2 and
   V3 add no infrastructure whatsoever. There is no "and then we move it to real hosting" step,
   because the free tier *is* the hosting.
5. **`models.py` is the only place a model ID appears**, pinned from the live API reference on day 1
   per SPEC.md §3.2. The V1 tier sweep will likely change the value in it. Nothing else moves.

The only thing V2 changes about V1's runtime is that the ingest path grows two steps (chunk, embed)
and the container grows ~150 MB for the ONNX runtime. Both were sized for in §2.3.

---

## 5. Free-tier constraints that reach back into the design

Two places where "it's free" is not merely an accounting fact but an engineering one. Both are worth
knowing before we write code rather than after.

### 5.1 Neon meters *compute-hours*, so nothing may poll on a tight timer

Neon's free tier suspends the compute after a few minutes of inactivity, and the monthly allowance is
consumed only while it is awake. Anything that touches Postgres on a timer keeps it awake: a five-
second poll would cost **720 compute-hours a month for an idle site**, exhausting the allowance while
doing no work at all.

This constraint has outlived the design it was written for. It was aimed at the jobs-table worker,
which we didn't build (§2.4) — nothing claims jobs, so nothing polls them. But it lands on the one
timer we *do* have, the retention sweep (`clause/retention.py`), and it is why that sweep is hourly
rather than every few minutes:

- **Hourly:** ~24 wakes a day, a couple of compute-hours — and a file is deleted within an hour of its
  24-hour deadline, which honours the promise without lying about the precision.
- **At boot, always.** The free API sleeps after 15 minutes idle, and a sleeping process deletes
  nothing. Sweeping the moment it wakes is what stops a nap becoming a retention hole.
- **An idle site is genuinely idle:** the SPA serves the demo from a CDN and never calls the API, so
  when nobody is logged in, Neon suspends and the meter stops.

The rule generalises past this one job: **before adding anything that runs on a timer, price it in
compute-hours first.** That is the whole reason this section exists.

### 5.2 The demo path must not depend on the API being awake

Free container hosts sleep. Whichever we pick, some visitor is eventually going to be the first
request after an idle period, and they will wait for a cold start.

That visitor must not be waiting on the *demo*, because the demo is the primary call to action and
its fifteen-second budget (SPEC.md §1.2) has no room in it for a container boot. Hence the
architecture in §2.1: the two demo analyses — findings, quotes, traces — are **bundled into the SPA
as static JSON at build time**, so the demo renders from files the browser already has, with no API
and no database in the path at all. (v0.1 achieved this by having Next.js server components read Neon
directly; the Vite SPA can't hold a DB connection, so we bake the data in instead — a stronger
guarantee, since the demo now depends on no running service whatsoever.) The API is needed only when
someone logs in and uploads — and a person who has just dragged their own contract onto a dropzone
will tolerate a few seconds of "waking up" far better than a person still deciding whether the site
is worth their attention.

---

## 6. The two corpora

A distinction SPEC.md leaves implicit, and getting it wrong would quietly invalidate every number in
§8. **There are two separate sets of contracts, and they exist for opposite reasons.**

| | Demo corpus | Eval corpus |
|---|---|---|
| **Purpose** | Persuade a visitor in 15 seconds | Measure whether the agent actually works |
| **Count** | 4 (2 in V1) | 1 labelled today; expands toward 10 by V3. Not featured in the MVP — see §3. |
| **Source** | **Synthetic — generated for this project** | **Real — SEC EDGAR filed commercial agreements** |
| **Wanted property** | Dramatic, legible findings | Messy, realistic, clauses buried in cross-references |
| **Authored by** | Claude | Nobody — they already exist, we download them |
| **Labelled?** | No | **Yes — by the author, by hand** |
| **Where it lives** | `demo/` | `evals/corpus/` + `evals/labels/` |

The reason the eval corpus must be *real* is the whole point of the exercise: an agent graded on
contracts written to be catchable proves nothing. A finding planted at a known offset in a document
I wrote is not evidence that the agent can find a liability carve-out buried on page 31 of a filed
MSA. SEC EDGAR publishes thousands of genuine commercial agreements as exhibits. They are free,
public, and exactly as unpleasant to read as real contracts are, which is the property we want.

### 6.1 What labelling is — and what it is not

**It is not training.** Nothing in this project trains, fine-tunes, or teaches the model anything.
The model arrives from OpenAI already trained and stays frozen. The labels are never shown to it. If
the agent could see the answer key, the measurement would be worthless — same as a student who has
seen the exam paper.

**It is an answer key.** For each eval contract, the author reads it, works through the 15 rules,
and records which rules *should* fire and which clause is the evidence for each. `make eval` then
runs the agent and compares its output to that key. Every number in SPEC.md §8 falls out of that
comparison:

- **Recall** — of the rules the key says should fire, how many did the agent catch?
- **Precision** — of the rules it fired, how many were real?
- **Anchor accuracy** — did the span it quoted overlap the clause the key points at, or did it flag
  the right rule off the wrong sentence?

The closest familiar analogue is a unit test, not a machine-learning pipeline. `assert add(2,2) == 4`
does not teach the function to add. It checks whether it does.

**Why this is worth hours of a human's time.** An AI system that is silently 40% accurate looks
*identical* to one that is 90% accurate — both emit confident, professional-looking findings with
severities and quotes. There is no way to tell them apart by looking. The answer key is the only
instrument that distinguishes them, and the §8 table is consequently the most persuasive artifact in
the repository: the evidence that the author knows the system works rather than hoping it does.

**Why the author labels and Claude does not.** If Claude writes the contract, plants the clauses,
writes the answer key, *and* builds the agent, the eval measures nothing but Claude's internal
consistency. The specific trap is subtle: a clause the agent is constitutionally bad at spotting
would also be missed by Claude when drafting the key — so it never appears as a miss, and recall
comes out looking excellent. The measurement launders the bug. Independence of the answer key is not
a formality; it is the entire source of the number's value.

### 6.2 The labelling plan

Label **one** contract together, first, before committing to any number. Roughly half an hour will
establish whether this is tedious-but-fine or genuinely miserable, and that is a much better basis
for deciding about the other nine than a guess made now.

Labelling is **no longer on the MVP path** (v0.2 moved the eval harness to V3), so there is no rush.
The one already-labelled contract and the two downloaded-but-unlabelled ones stay in `evals/`. When
V3 comes, the decision is whether to grind out the remaining contracts by hand or fall back to a
Claude-drafted key that the author corrects — weaker evidence, and the README would say so plainly.

---

## 7. Model IDs and pricing — pinned 2026-07-14, verified against the live API

SPEC.md §3.2 instructs us to pin model IDs from the live API reference rather than trust the
document. Done, on day 1, by listing `/v1/models` against the project's own key. **The spec's IDs are
correct and current**, and all three tiers the §8.1 sweep asks for exist:

| Role | Model | Input | Cached input | Output |
|---|---|---|---|---|
| Risk scan (specced default) | `gpt-5.6-sol` | $5.00 | $0.50 | $30.00 |
| Sweep candidate, mid tier | `gpt-5.6-terra` | $2.50 | $0.25 | $15.00 |
| Extraction · Q&A · memo summary | `gpt-5.4-mini` | $0.75 | $0.075 | $4.50 |

Per-million-token, standard tier, verified against the pricing page on 2026-07-14. These match
SPEC.md §7.3 exactly, so its cost model stands: **≈ $0.68 per uploaded document** on sol, and the
tier sweep remains the highest-leverage experiment in the project.

Also available and worth knowing about, though not specced: `gpt-5.6-luna` ($1.00 / $0.10 / $6.00)
sits between terra and mini, and `gpt-5.4-nano` ($0.20 / $0.02 / $1.25) sits below mini. If the sweep
shows sol is overkill but mini is not quite enough, luna is the obvious fourth column to add.

All of these live in `api/clause/models.py` and nowhere else.

## 8. Still open

1. **The global monthly ceiling figure.** The ultimate backstop even against invited clients: whatever
   total monthly spend is annoying-but-survivable. (v0.3's invite-only gate removed the old
   "free-account abuse" worry — a stranger with no code can't create a spending account at all.)
2. **Code issuance ergonomics.** How you mint and hand out codes. Simplest MVP: a one-line script or
   `psql` `INSERT` into `access_codes`. A tiny admin screen to generate them is a nice-to-have, not V1.
3. **Admin provisioning.** `is_admin` is set by hand in the DB (SPEC §2.5). Fine for one admin (the
   author). If that ever needs to be more than a manual `UPDATE`, it becomes a real feature — not now.
4. **The eval labels.** No longer on the MVP path — see §6.2. Needed only when V3's harness is built.

---

## 9. What changed in v0.2 (2026-07-15)

The reframe that produced this version. v0.1 sequenced the *full spec* into three versions; v0.2
re-cut them around a shippable MVP (the project had more spec than product, and the AI engine was
already built); v0.3 then made access invite-only after clarifying this is a portfolio tool, not a
public SaaS. The table shows v0.1 against where we landed (v0.2–0.3).

| Area | v0.1 | now (v0.2–0.3) |
|---|---|---|
| **V1 thesis** | The agent + trace + risk cards, no accounts | The agent behind a **login**, with public demo + one gated upload |
| **Accounts** | None (SPEC §1.3 non-goal) | JWT auth, `users` + `access_codes`, invite-only + admin (SPEC §2.5) |
| **Who can spend** | Anonymous: 3/IP/day, two-pool budget | **Only people you gave a code.** Grant = N analyses/account; admin unlimited |
| **Upgrade page / Stripe** | — | **Removed.** Grant spent → "contact the author". Self-serve/Stripe is "beyond V3, if ever" |
| **Frontend** | Next.js 15 (App Router) | **Vite + React SPA** |
| **Demo delivery** | Next.js server components read Neon directly | **Static JSON bundled in the SPA** — no backend at all |
| **Eval harness** | Featured in V1 (3 contracts + tier sweep) | Built already; **moved to V3**, off the MVP path |
| **RAG / Ask** | V2 | **V2** (unchanged — the explicit next step) |
| **Memo** | V2 (PDF) | **V3** |
| **Job queue + live SSE** | V1 | Deferred; V1 replays the trace as today. Schema still ships. |

What did **not** change: the agent, the quote-verification guard, the 15-rule library, the
single-Postgres design, local embeddings (when they land in V2), the free-tier hosting topology, and
`models.py` as the one home for model IDs. The engine is the same; v0.2 only changes the order the
shell is built in and puts a door with a lock on the front of it.


Note to myself -
cd api
uv run python -m clause.auth.codes new --grant 3     # → CLAUSE-XXXX-XXXX
--grant N = how many analyses that code is worth. Change the number per client (--grant 1 for a taster, --grant 5 for a serious prospect). It writes straight into Neon — nothing to do in the Neon console.

The other two commands:


uv run python -m clause.auth.codes list                    # who claimed what
uv run python -m clause.auth.codes make-admin you@x.com    # unlimited, after you sign up
Remember the two numbers are different things: the code's grant_count (3) never changes — it's the coupon's face value. Your allowance is copied to users.upload_grant at signup, and usage is counted on your user row.