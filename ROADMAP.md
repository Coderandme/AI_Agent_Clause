# Clause — Incremental Roadmap

**Companion to SPEC.md** · Version 0.1 · 2026-07-14 · Status: Proposed, awaiting sign-off

SPEC.md specifies the finished product. This document specifies the *order we build it in*, the
*infrastructure it runs on at zero cost*, and — most importantly — the set of decisions we make on
day 1 so that no later version requires re-architecting an earlier one.

Where this document contradicts SPEC.md, it says so explicitly and states why.

**Cost position:** every piece of infrastructure is free tier. OpenAI tokens are the only thing that
costs money, and that is accepted. The spend ceiling from SPEC.md §7.2 still ships — but as *abuse
protection on a public URL*, not as a budget constraint. Strangers should not be able to run the
bill up; you should be able to.

---

## 1. The one place this contradicts the spec

SPEC.md §3.1 says: *"Hosting | Vercel (web) · Fly.io (api + worker) · Neon (Postgres) | All have
usable free tiers."*

That is no longer true of Fly.io — it withdrew its free allowance and now bills from the first
machine. Neon and Vercel are unaffected. So one row of that table changes, and nothing else does:
the API is a Docker container running FastAPI, and it can run anywhere that will run a Docker
container for free.

Everything else in §3 — Postgres as the only datastore, the Postgres job queue, local embeddings,
the hand-rolled loop — is *unchanged*, and in fact each of those choices is what makes a zero-cost
deployment possible at all. A design that needed Redis, Pinecone, and Celery would need three more
free tiers stitched together, and would fall over on the first one that expired.

---

## 2. Target architecture (all versions)

```
                        ┌──────────────────────────────┐
   browser ────────────►│  Vercel (Hobby, free)        │
                        │  Next.js 15 App Router       │
                        │                              │
                        │  Server components read      │
                        │  Neon DIRECTLY for:          │
                        │   · demo contracts           │
                        │   · finished analyses        │
                        │   · findings, key terms      │
                        │   · memo markdown            │
                        └───────┬──────────────────────┘
                                │ (SQL over TLS)
      ┌─────────────────────────┼───────────────────────────────┐
      │                         ▼                               │
      │              ┌────────────────────────┐                 │
      │              │  Neon Postgres (free)  │                 │
      │              │  + pgvector            │                 │
      │              │  documents, pages,     │◄────────────┐   │
      │              │  chunks, analyses,     │             │   │
      │              │  findings, absences,   │             │   │
      │              │  key_terms,            │             │   │
      │              │  agent_events, jobs,   │             │   │
      │              │  usage_ledger          │             │   │
      │              └────────────────────────┘             │   │
      │                                                     │   │
      │  browser ──── multipart upload ────────────────┐    │   │
      │  browser ──── SSE: /events, /ask ──────────┐   │    │   │
      │                                            ▼   ▼    │   │
      │                        ┌───────────────────────────────┐│
      │                        │  Docker container (free host) ││
      │                        │                               ││
      │                        │  uvicorn ── FastAPI routes    ││
      │                        │      │                        ││
      │                        │      ├─ ingest (PyMuPDF)      ││
      │                        │      └─ signals ──┐           ││
      │                        │                   ▼           ││
      │                        │  worker ── claims jobs        ││
      │                        │      ├─ agent loop (OpenAI)   ││
      │                        │      ├─ quote verification    ││
      │                        │      ├─ fastembed (local)     ││
      │                        │      └─ memo render           ││
      │                        └───────────┬───────────────────┘│
      │                                    │                    │
      │                                    ▼                    │
      │                        ┌────────────────────────┐       │
      │                        │  Cloudflare R2 (free)  │       │
      │                        │  uploaded PDFs         │       │
      │                        │  rendered memo PDFs    │       │
      │                        └────────────────────────┘       │
      └─────────────────────────────────────────────────────────┘

                   Only line item that costs money: OpenAI tokens.
                   Demo mode never touches it.
```

### 2.1 Why the browser talks to the API directly

The SSE endpoints (`/api/analyses/{id}/events`, `/api/analyses/{id}/ask`) are held open for
40–70 seconds. Proxying them through a Vercel function would put them under Vercel's function
duration ceiling for no benefit. Instead the browser opens the EventSource against the Python API's
own origin, with CORS locked to the Vercel domain. Vercel functions are then needed for
approximately nothing, which is the point — the Hobby plan's limits stop being a design constraint
rather than something we engineer around.

Reads of *finished* data (demo contracts, completed analyses, findings, memo markdown) go straight
from Next.js server components to Neon. This means **the entire demo path works even when the Python
API is asleep**, which matters more than it sounds like — see §5.2.

### 2.2 Free-tier inventory

| Service | Tier | What it holds | The limit that will actually bite |
|---|---|---|---|
| Vercel | Hobby | Next.js frontend | Non-commercial use only. A portfolio qualifies. |
| Neon | Free | All Postgres, `pgvector` | Storage ceiling, and a monthly **compute-hour** allowance. See §5.1. |
| Cloudflare R2 | Free | Uploaded PDFs, rendered memos | Storage ceiling. Uploads are deleted at 24h, so this stays near empty. |
| Hugging Face Spaces | Free CPU (Docker) | FastAPI + worker + fastembed | Sleeps after ~48h idle. See §2.3. |
| OpenAI | **Paid — accepted** | Nothing. It is the only cost. | Only the abuse ceiling we set ourselves. |

**Verify every one of these against the live pricing page before we rely on it.** Free tiers change,
and the Fly.io row in SPEC.md is the cautionary tale.

### 2.3 The API host — decided: Hugging Face Spaces

**Hugging Face Spaces, Docker SDK, free CPU tier.** 2 vCPU / 16 GB RAM, no sleep until roughly 48
hours of inactivity, and it will run `uvicorn` plus a worker task without complaint. The RAM headroom
makes `fastembed`'s ONNX runtime a non-issue when V2 lands.

Note that OpenAI is *not* a host. It runs the model; it does not run our code. Quote verification, the
agent loop, PyMuPDF, the job queue, and the SSE endpoints are all our code and all need a process to
live in. That process is this container.

Nor can that process be Vercel. An analysis takes 40–70 seconds and must outlive the HTTP request
that started it — serverless functions exist to serve a request and then die, leaving nothing behind
to claim jobs from a queue. The whole §3.5 design assumes a process that keeps running.

Rejected, for the record:

- **Render (free web service).** Spins down after 15 minutes idle with a ~50s cold start, landing
  directly on top of the "90 seconds to a memo" target. Its *background worker* type is paid-only.
- **Oracle Cloud always-free ARM VM.** Genuinely always-on and genuinely free, but it is a VM — we
  would own the OS, the TLS certs, and the systemd units.

The choice is deliberately reversible: the API is a Dockerfile with no host-specific code in it.

### 2.4 The worker, and how it differs from the spec

SPEC.md §3.5 specifies "a separate `worker` process polls this [jobs table]". On a free tier we get
one container, so V1 runs the worker as an asyncio task **inside the API container**.

This is not a compromise of the design. The Postgres queue, `FOR UPDATE SKIP LOCKED`, the retry
semantics, and the crash-recovery story are all exactly as specced; the only thing that changes is
which OS process the claim loop runs in. The day this needs to scale, `worker.py` gets its own
container and *no other code changes*, because the queue was never in-process to begin with.

One thing does have to change, though, and it is a good example of a free tier reaching back into
the design: **the worker must not poll the jobs table on a timer.** See §5.1.

---

## 3. The versions

Each version ends deployed to a public URL and demonstrable to a stranger. None of them ends with
"the parser is done."

### Version 1 — MVP: *"It reads the contract, and every quote it shows you is provably real."*

The thesis of the entire project, with nothing around it. A visitor lands, clicks a sample, and
watches an agent work through a real contract and produce findings anchored to verbatim text.

**In scope**

| Area | What ships |
|---|---|
| Ingest | PDF upload → validate → hash → R2 → PyMuPDF parse → full text + per-page char offsets. Scanned-PDF rejection by character density. |
| Rule library | `rules/v1.yaml`, all 15 rules, all 4 families, hashed into `analyses.rule_library_version`. |
| **The agent** | Hand-rolled loop (§4.3). Four rule-family passes. Prompt caching with the frozen prefix (§4.2). **Five** tools: `get_rule_detail`, `record_finding`, `record_key_terms`, `note_absence`, `finalize`. |
| **Quote verification** | The full guard (§4.5): normalise → exact match → rapidfuzz fallback → char range → page number. Unverified findings never render. |
| Async + trace | Postgres job queue. `agent_events` written as the analysis runs. SSE endpoint that streams live *and* replays when complete. |
| Frontend | Landing page. Document view, split pane. PDF viewer. **Risks tab.** Key-terms summary strip. **Agent trace drawer.** Disclaimer everywhere. |
| Highlighting | **Page-level only.** Click a finding → the PDF jumps to that page and outlines it. |
| Memo | Rendered as **Markdown**, previewed in the UI, "Copy Markdown". |
| Demo mode | **Two** pre-baked samples (SaaS MSA, mutual NDA) with real recorded traces. Zero API calls. |
| Abuse control | Per-document caps, per-IP daily cap, global monthly ceiling, 24h deletion job. |
| Evidence | A **3-contract** hand-labelled eval set (real contracts, from SEC EDGAR — see §6) and the **model-tier sweep** (§8.1). |

**Deliberately out of scope for V1, and why**

- **Chunks, embeddings, `pgvector`, hybrid search, `search_document`.** SPEC.md §4.1 is explicit
  that retrieval exists for Q&A, *not* for the risk scan — the scan reads the whole document. So
  retrieval is not load-bearing for the MVP's marquee feature, and cutting it takes ONNX,
  `fastembed`, and the HNSW index off the V1 critical path entirely. The `chunks` table still ships
  in the V1 migration, empty. See §4.
- **The Ask tab.** SPEC.md §10.1 names it as the first thing to cut if the schedule slips. We are
  taking that advice before the schedule forces us to.
- **Span-precise highlighting.** SPEC.md §9.3 calls it "the hardest piece of frontend work in the
  project" and §10.1 pre-authorises the page-level fallback. Building the fallback *first* and the
  precision *second* means the overlay can never sink a version.
- **Memo PDF export.** WeasyPrint and its font stack, deferred one version.
- **DOCX ingest.** PDF only.

**Done when:** a stranger opens the public URL, clicks "SaaS MSA", watches a real recorded agent
trace replay, reads six findings each carrying a verbatim quote and a page number, clicks one and
lands on that page of the PDF — and then uploads their own contract and gets the same thing in under
ninety seconds.

**Why the eval is in V1 and not V3.** SPEC.md §7.3 calls the model-tier sweep "the single
highest-leverage experiment in the project", and it decides which model the scan runs on — which is
a decision baked into every version after it. Three labelled contracts is enough to run that sweep
honestly. The full ten-contract harness with CI gates is a V3 concern; *knowing which model to use*
is not.

---

### Version 2 — *"Ask it anything, and take the memo with you."*

V1 proves the agent works. V2 makes the thing usable and gives the visitor an artifact to leave with.
This is also where RAG lands — and it lands *for the reason the spec gives*, which is a considerably
better story than building it reflexively in V1 and then using it for nothing.

**In scope**

| Area | What ships |
|---|---|
| Retrieval | Chunking (numbered-section regex → ~800-token packs, 100-token overlap, `section_label` carried forward). `fastembed` + `bge-small-en-v1.5`, local, batched. `pgvector` HNSW index. The hybrid SQL query from §3.4. |
| Sixth tool | `search_document` joins the agent's tool surface, so it can re-locate a clause in order to quote it precisely. |
| Ask tab | Grounded Q&A over hybrid retrieval, streamed, with inline citations that jump to the source span. |
| Memo | Jinja2 → Markdown → **WeasyPrint → PDF**. Download works. The artifact is good enough to send to someone. |
| Highlight overlay | **Span-precise.** Walk the pdf.js text layer, resolve the char window to a DOM range, paint rectangles behind it. Page-level remains the fallback when a span won't resolve. |
| Key Terms tab | The full two-column table, "Not specified" rendering, CSV/JSON export. |
| Absences | The "Checked and not found" list renders beneath the findings. |
| Demo mode | Expanded to **four** samples (adds the office lease and the freelance agreement). |
| Retrieval tuning | The `0.7 / 0.3` semantic/lexical weights tuned against the eval corpus rather than guessed. |

**Done when:** the visitor can ask "what happens if we terminate early?", get a streamed answer with
a citation that jumps to the exact highlighted clause, and download a PDF memo they would be willing
to forward to their actual lawyer.

**Cost:** embeddings are local, so all of retrieval adds **zero** marginal API cost. Q&A adds roughly
$0.007 per question.

---

### Version 3 — *"And here is the proof that it works."*

The version that separates a demo from an engineering artifact, and the one an engineering leader
evaluating the repo will actually read. Everything here is about *measurement* and about *not
silently regressing*.

**In scope**

| Area | What ships |
|---|---|
| Eval harness | The full **10-contract** hand-labelled corpus. `make eval` prints the §8 table: recall (critical+high), recall (all), precision, citation-verification rate, anchor accuracy, cost/doc, wall-clock/doc. |
| The gates | Recall ≥ 0.80 critical/high · precision ≥ 0.75 · verification rate ≥ 0.85 · anchor accuracy ≥ 0.90 · `unverified_count / total_findings` ≤ 0.15. A build that misses them fails. |
| The two silent-failure tests | (1) The second pass of an analysis reports a **non-zero cached-token count** — zero means a cache invalidator has crept into the prefix and we are paying ~10× for nothing, with no error anywhere. (2) A deliberately corrupted quote **never** reaches `verified = true`. |
| CI | Three of the ten contracts run on every change to the system prompt or the rule library. The full ten run nightly. |
| Observability | Structured JSON logs. `token_usage` and `cost_microdollars` populated per analysis. `/api/health` reports db, queue depth, and spend headroom. |
| DOCX ingest | The second half of `type ∈ {pdf, docx}`. |
| README | Architecture diagram, the **tier-sweep table**, the eval numbers, a demo GIF, and an honest note that the sample contracts are synthetic. |

**Done when:** `make eval` produces the table from §8 of the spec, CI enforces it, and the README
contains a number rather than an adjective for every claim it makes.

---

### Beyond V3 — explicitly not now (SPEC.md §1.3)

OCR for scanned PDFs · cross-document comparison · user accounts · a 16th rule · redline generation.
The schema already anticipates the first two. None of them ships until the first three versions are
done and deployed.

---

## 4. How we get from V1 to V3 without rewriting anything

This is the part of the plan that actually matters, and it reduces to one principle:

> **Ship the full data model and the full deployment topology in V1. Add only code paths after that.**

Five things are therefore fixed on day 1 and never revisited:

1. **The entire schema from SPEC.md §5 ships in the V1 migration** — including `chunks`, its
   `vector(384)` column, its HNSW index, and its `tsvector`. V1 simply never writes to it. The cost
   of shipping an unused table is zero. The cost of adding a vector column and an HNSW index to a
   populated production table is not.
2. **The tool registry is a list.** V2 adds `search_document` by appending one entry; the loop, the
   dispatcher, and the SSE adapter never learn how many tools there are. (Per the caching discipline
   in §4.2, tools serialise **sorted by name** — so adding one invalidates the cached prefix only
   from `search_document` onward, and only on the deploy that adds it.)
3. **The SSE vocabulary from §6.2 is frozen in V1.** The frontend never sees an OpenAI type name;
   one adapter normalises them. V2's Ask tab reuses that vocabulary rather than inventing a second.
4. **The deployment topology is the final one from day 1.** Vercel + Neon + R2 + a Docker API. V2 and
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

### 5.1 Neon meters *compute-hours*, so the worker must not poll on a timer

Neon's free tier suspends the compute after a few minutes of inactivity, and the monthly allowance is
consumed only while it is awake. A worker running `SELECT … FOR UPDATE SKIP LOCKED` every five
seconds keeps the database awake around the clock — **720 compute-hours a month for an idle site**,
exhausting the allowance while doing no work at all.

So the claim loop is *event-driven, with polling only as a safety net*:

- The API enqueues to the `jobs` table (durable, exactly as specced) **and** signals the in-container
  worker directly. The worker wakes and claims immediately.
- The worker polls the table **only** at container boot — to recover jobs orphaned by a crash — and
  while at least one job is in flight.
- An idle site issues zero queries, Neon suspends, and the meter stops.

This costs nothing in correctness. The jobs table is still the source of truth and still the unit of
crash recovery; the signal is an optimisation over polling, not a replacement for the queue. When the
worker eventually moves to its own container, the signal becomes `LISTEN/NOTIFY` and the design is
otherwise unchanged.

### 5.2 The demo path must not depend on the API being awake

Free container hosts sleep. Whichever we pick, some visitor is eventually going to be the first
request after an idle period, and they will wait for a cold start.

That visitor must not be waiting on the *demo*, because the demo is the primary call to action and
its fifteen-second budget (SPEC.md §1.2) has no room in it for a container boot. Hence the
architecture in §2.1: demo contracts, findings, key terms, traces, and memos are read by Next.js
**directly from Neon**, and the Python API is not in that path at all. The API is needed only when
someone uploads — and a person who has just dragged their own contract onto a dropzone will tolerate
a few seconds of "waking up" far better than a person still deciding whether the site is worth their
attention.

---

## 6. The two corpora

A distinction SPEC.md leaves implicit, and getting it wrong would quietly invalidate every number in
§8. **There are two separate sets of contracts, and they exist for opposite reasons.**

| | Demo corpus | Eval corpus |
|---|---|---|
| **Purpose** | Persuade a visitor in 15 seconds | Measure whether the agent actually works |
| **Count** | 4 (2 in V1) | 3 in V1, up to 10 by V3 |
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

Then: three labelled contracts for V1 — enough to run the model-tier sweep (§8.1) honestly — and a
decision at V3 about whether to grind out the remaining seven or fall back to a Claude-drafted key
that the author corrects. The fallback is weaker evidence and the README would say so plainly.

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

1. **The abuse ceiling.** Token cost is accepted, so this is only about what a *stranger* can spend.
   Proposed: per-IP cap stays at 3 analyses/day, and the global monthly ceiling is set to whatever
   figure would be annoying-but-survivable if a bot found the upload endpoint. Needed before M7.
2. **The eval labels.** Needed at the *end* of V1, not the start — see §6.2.
