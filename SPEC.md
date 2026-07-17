# Clause — Contract Intelligence Agent

**Specification & Implementation Plan**
Version 1.3 · 2026-07-15 · Status: Approved for build

This document is the single source of truth for the project. Any change to scope, architecture, or interface lands here first.

---

## 1. Objective

Build a hosted web application where a user uploads a commercial contract and an **agent** — not a chatbot — reads it, flags risks with verified quotations from the source, extracts the key commercial terms, and produces a downloadable counsel-style review memo.

### 1.1 Why this project

It is a portfolio artifact whose primary job is to convert a prospective client's attention into an inquiry. Everything below serves that. A secondary job is to demonstrate a full production stack end-to-end.

### 1.2 What success looks like


| Criterion                                                   | Target                                     |
| ----------------------------------------------------------- | ------------------------------------------ |
| Time from landing on the page to seeing a real risk finding | Under 15 seconds (via pre-indexed samples) |
| Time from uploading your own contract to a finished memo    | Under 90 seconds for a 30-page document    |
| Findings whose quoted text provably exists in the source    | 100% of displayed findings                 |
| Recall on the hand-labelled eval set                        | ≥ 0.80 on critical/high severity rules     |
| Cost per anonymous analysis                                 | Under $1.00, with a hard monthly ceiling   |
| Cost per demo-mode view                                     | $0.00                                      |




### 1.3 Explicit non-goals

Not a legal-advice product. No contract editing or redline generation (we *recommend* redlines in prose; we do not produce a marked-up document). No jurisdiction-specific legal reasoning beyond what the rule library encodes. No cross-document comparison in v1 — the schema anticipates it, the UI does not ship it.

**No self-serve tier and no payments.** There is no public "free plan" and no Upgrade page. Running the agent on your own contract is **invite-only**: access is granted with a code, not bought (§2.5). Strangers get the public demo, which is free and needs no account. Stripe and paid plans are a *"beyond V3"* concern, only relevant if this ever becomes a real SaaS — which is not what it is.

> **Scope note (v1.3).** This spec originally listed "no user accounts" and "no billing" as non-goals. On 2026-07-15 that was reconsidered twice. First (v1.2): accounts and JWT login were added, so a prospective client could keep an analysis. Then (v1.3), on the observation that this is a **portfolio tool shown to a handful of prospects, not a public SaaS**, the self-serve free tier and the Upgrade/Stripe flow were *removed* and access made **invite-only via access codes** (§2.5). Accounts and JWT stay — they are the point of the login page as a portfolio artifact and the mechanism that gates spend. This document describes the finished product; **`ROADMAP.md` sequences what actually ships in each version, and defers the eval harness, memo, and Q&A out of the MVP.**

### 1.4 Standing constraint: cost

Minimising running cost is a first-class requirement, not an afterthought. It has already shaped three architectural decisions — the model tiering in §3.2, the local embedding model in §3.1, and demo mode in §7.1. Where a decision trades cost against quality, this document states the trade rather than burying it.

---



## 2. Product



### 2.1 Target user

A non-technical commercial buyer — a founder, an ops lead, a procurement manager — who has been handed a vendor agreement and does not have counsel on retainer. They want to know, in ninety seconds, what in this document is going to hurt them.

Secondarily: an engineering leader evaluating whether the author of this repo can build a real agentic system.

### 2.2 The three capabilities

**Risk flagging.** The agent scans the contract against a versioned library of 15 risk rules. Each finding carries a severity, a plain-English explanation of the exposure, a recommended action, and a verbatim quotation anchored to a page and character range in the source document.

**Key-term extraction.** Parties, effective date, initial term, renewal mechanics, notice periods, payment terms, liability cap, governing law, termination rights. This is *not* a headline feature with its own tab — it is an internal capability that populates the memo's key-terms table and a summary strip in the UI. It ships because the memo is incoherent without it.

**Memo generation.** A shareable review memo: executive summary, key-terms table, findings ranked by severity with quotations, and recommended redlines. Rendered as Markdown, exported as PDF. This is the artifact a prospective client remembers.

Plus a supporting capability: **grounded Q&A** over the document, so a user can ask "what happens if we terminate early?" and get an answer with citations.

### 2.3 Core user flow

```
Landing page  (no login required)
  ├── [Primary] Click a pre-indexed sample contract
  │     └── Instant load of cached analysis → full UI, zero cost, zero latency
  │         (served from static precomputed data — no backend, no account)
  │
  └── [Secondary] Drag a PDF onto the dropzone
        ├── Not logged in? → prompt to log in, or sign up with an access code (§2.5)
        ├── Logged in but grant spent? → "you've used your N analyses; contact the author"
        ├── Validation (type, size, page count, spend cap)
        ├── Parse → chunk → embed  (~3s, all local)
        ├── Agent analysis, streamed live  (~40-70s)
        │     └── User watches the agent trace: tools called, findings recorded
        └── Document view

Document view  (split pane)
  ├── Left:  PDF viewer with highlight overlay
  └── Right: tabs
        ├── Risks     — severity-ranked cards; click a card → PDF scrolls and
        │               highlights the exact quoted span
        ├── Key Terms — extracted table, CSV/JSON export
        ├── Ask       — grounded chat with inline citations
        └── Memo      — rendered preview, Download PDF, Copy Markdown
```

The agent trace is not a debug panel. It is a feature. Watching the agent call `get_rule_detail("auto_renewal")`, then `search_document("renewal notice")`, then `record_finding(severity="high", ...)` is what makes this legibly *agentic* rather than a single prompt with a spinner in front of it.

### 2.4 Legal disclaimer

Persistent, unmissable, on every page and in the memo footer:

> Clause is an automated analysis tool. It is not a lawyer and does not provide legal advice. Its output is a starting point for review by qualified counsel, not a substitute for it.

Non-negotiable. Present before the first analysis renders, not buried in a footer link.

### 2.5 Accounts and access control

This is a portfolio tool shown to a handful of prospects, not a public SaaS. So the demo is open to everyone and running the agent on your own contract is **invite-only.** Accounts exist to gate the one expensive action — a real upload — and to demonstrate a genuine auth implementation.

**Tiers.**

| Tier | Who | How they get it | What they can do |
| --- | --- | --- | --- |
| Anonymous | Anyone | — | View demo contracts (static, $0). No account, no upload. |
| Invited client | A prospect you chose | Signs up with an **access code** you gave them | Uploads and analyses, up to the **grant** the code carried (e.g. 3). |
| Admin | The author | `is_admin` flag set by hand in the DB | Unlimited uploads, drawn from a budget reserve strangers cannot touch. |

**No self-serve free tier.** A stranger cannot sign up and spend API budget; there is nothing to sign up *for* without a code. This — not a per-IP counter — is the primary spend control: the set of people who can cost money is exactly the set of people you handed a code.

**Access codes.** A code is a coupon for access, not money. Each code carries a grant (how many analyses it unlocks) and is single-use — one code, one client — so clients are distinguishable and individually revocable. At signup the server checks the code is valid and unclaimed, creates the account with `upload_grant` set from the code, and marks the code claimed. An invalid or spent code fails the signup. (`access_codes` table, §5.)

**The grant is a lifetime count.** An invited client gets `upload_grant` analyses of their own documents, total. The check before an analysis runs is `is_admin OR COUNT(analyses WHERE owner_user_id = $1) < upload_grant`. When the grant is spent, the UI says so plainly — "you've used your N analyses; contact the author for more." There is no Upgrade page and no payment path; access is a conversation with you, not a checkout.

**Auth mechanism.** Email + password, hashed with `bcrypt`. Signup requires a valid access code; login issues a **JWT** — a signed token carrying the user id and admin flag — which the SPA stores and sends as a `Bearer` header on every request. The API verifies the signature per call; there is no server-side session store. Tokens are short-lived; a refresh path is a later concern.

The global monthly ceiling (§7.2) still stands behind all of this as the ultimate backstop: even the sum of every grant cannot exceed it.

---



## 3. Architecture



### 3.1 Stack, and why


| Layer          | Choice                                                                         | Rationale                                                                                                                 |
| -------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| Frontend       | Vite + React 19, TypeScript, Tailwind                                          | A plain single-page app that talks to FastAPI over HTTP. One frontend, one API, no server-side rendering to reason about. (The spec originally named Next.js; simplified to a Vite SPA in v1.2 — see §9.) |
| PDF rendering  | `react-pdf` (pdf.js) with a custom highlight overlay                           | Needs to accept a character range and paint it. Text-layer coordinates come from pdf.js.                                  |
| Backend        | FastAPI, Python 3.12, `uv` for dependency management                           | Async-native, matches the streaming and job-queue shape.                                                                  |
| Auth           | FastAPI + Pydantic, `bcrypt` password hashing, JWT bearer tokens               | Stateless: the token carries the user id and admin flag, verified per request. No session store. See §2.5.               |
| LLM            | OpenAI API, tiered by task                                                     | See §3.2.                                                                                                                 |
| Embeddings     | `fastembed` + `BAAI/bge-small-en-v1.5` (384-dim), local                        | See §3.3.                                                                                                                 |
| Database       | Postgres 16 + `pgvector` + native full-text search                             | One datastore for documents, chunks, embeddings, findings, jobs, and usage. See §3.4.                                     |
| Job queue      | Postgres table + `SELECT … FOR UPDATE SKIP LOCKED`                             | No Redis, no Celery. See §3.5.                                                                                            |
| PDF parsing    | PyMuPDF (`fitz`)                                                               | Fast, gives per-character bounding boxes and page-level char offsets, which the highlight overlay needs.                  |
| Memo rendering | Jinja2 → Markdown → WeasyPrint → PDF                                           | Boring, deterministic, no headless browser.                                                                               |
| Hosting        | Vercel (web) · Fly.io (api + worker) · Neon (Postgres)                         | All have usable free tiers. Neon supports `pgvector`.                                                                     |
| Observability  | Structured JSON logs → Fly log drain; a `token_usage` column on every analysis | No vendor tracing dependency; the trace is already in the database.                                                       |




### 3.2 Model tiering

Output tokens dominate the bill (§7.3). Caching does nothing about them. So the lever is not "cache harder" — it is "use the expensive model only where its output is visible to a human."


| Task                   | Model                      | Why                                                                                                                 |
| ---------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Risk scan              | `gpt-5.6-sol`              | The demo. The only place quality is legible to a prospective client. One call per document.                         |
| Key-term extraction    | `gpt-5.4-mini`             | Filling a table from a document in context is not a reasoning problem. Strict structured output does the enforcing. |
| Grounded Q&A           | `gpt-5.4-mini`             | Narrow questions over retrieved chunks. Users ask several; on the flagship each would cost 30× for no visible gain. |
| Memo executive summary | `gpt-5.4-mini`             | The memo's structure is a Jinja template. The model writes three paragraphs.                                        |
| Embeddings             | local, `bge-small-en-v1.5` | Zero marginal cost, zero network.                                                                                   |


Model IDs live in one config module, never as string literals. **Pin them from the current API reference at M0.** Do not copy them from this document — the tiers move faster than specs do.

Two API behaviours to build around, both easy to get wrong:

**Do not send the PDF.** OpenAI's file input extracts the text *and rasterises every page into an image*, sending both. For a 30-page contract that is thirty images you pay for and do not need. We already run PyMuPDF to get the character offsets that quote verification and the highlight overlay depend on. Pass the extracted plain text.

**Reasoning-model state.** On the Responses API, reasoning items must be carried across tool-call turns or the model re-derives its reasoning each turn. Verify the exact mechanism against the SDK reference at M0. The pseudocode in §4.3 is structurally accurate and lexically indicative — do not copy field names from it.

### 3.3 Why local embeddings, and why cost is not the reason

Embedding a 30-page contract is roughly 28k tokens, once. At any hosted provider's rates that is a fraction of a cent. Cost does not decide this.

What decides it is that **retrieval only powers the Q&A tab**. The risk scan reads the whole document (§4.1). Embedding quality is therefore a low-stakes decision — and low-stakes decisions should be resolved in favour of fewer dependencies, not marginally better benchmark numbers.

`fastembed` runs `bge-small-en-v1.5` through ONNX rather than PyTorch, adding roughly 150MB to the image instead of two gigabytes. Sixty chunks is milliseconds of CPU work in a worker process about to spend seventy seconds waiting on an LLM. It removes an API key, a network hop, a rate limit, and a failure mode from the ingest path.

The vector is 384-dimensional. That is the only downstream consequence: `vector(384)` in the schema, a slightly faster index, nothing else.

### 3.4 Why one database and no vector DB

The application needs semantic search, keyword search, metadata filtering, relational integrity across five entities, and a job queue. Postgres does all five. `pgvector` gives HNSW-indexed cosine similarity; `tsvector` gives lexical search; a single SQL query does hybrid retrieval with a `WHERE document_id = $1` filter that a standalone vector store would make awkward.

A separate vector database would add an operational surface, a synchronisation problem between two sources of truth, and precisely zero capability at this scale. Choosing not to add it is the correct engineering decision and, secondarily, a clearer signal of judgement than reaching for Pinecone would be.

The hybrid query, for reference:

```sql
WITH semantic AS (
  SELECT id, 1 - (embedding <=> $1::vector) AS score
  FROM chunks WHERE document_id = $2
  ORDER BY embedding <=> $1::vector LIMIT 20
),
lexical AS (
  SELECT id, ts_rank_cd(tsv, plainto_tsquery('english', $3)) AS score
  FROM chunks WHERE document_id = $2 AND tsv @@ plainto_tsquery('english', $3)
  ORDER BY score DESC LIMIT 20
)
SELECT c.*, COALESCE(s.score, 0) * 0.7 + COALESCE(l.score, 0) * 0.3 AS score
FROM chunks c
LEFT JOIN semantic s ON s.id = c.id
LEFT JOIN lexical  l ON l.id = c.id
WHERE s.id IS NOT NULL OR l.id IS NOT NULL
ORDER BY score DESC LIMIT 8;
```

Weights `0.7 / 0.3` are a starting point, tuned against the eval set.

### 3.5 Why a Postgres job queue

Analysis takes 40–70 seconds. That cannot happen inside a request. The options were Redis + arq, Celery, or a Postgres table.

`SELECT … FOR UPDATE SKIP LOCKED` gives exactly-once-ish claim semantics, retries, and visibility into the queue from the same `psql` session used for everything else. It is roughly eighty lines of code, adds no infrastructure, and is the right call below a few hundred jobs a minute. We are nowhere near that.

```sql
UPDATE jobs SET status = 'running', locked_at = now(), locked_by = $1, attempts = attempts + 1
WHERE id = (
  SELECT id FROM jobs
  WHERE status = 'queued' AND run_after <= now()
  ORDER BY created_at
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING *;
```

A separate `worker` process polls this. Jobs exceeding `attempts = 3` land in `status = 'failed'` with the exception recorded, and the UI surfaces a real error rather than a spinner that never resolves.

This also settles the durability question that would otherwise argue for an orchestration framework: if the worker dies mid-analysis, the job retries. The unit of recovery is the whole analysis, which costs under a dollar and takes seventy seconds. Paying an abstraction tax to avoid re-running that is a bad trade.

---



## 4. The agent

This is the heart of the project. Everything else is plumbing around it.

### 4.1 The critical design decision: full document, not retrieval

A typical commercial contract is 15,000–50,000 tokens. The context windows in play are hundreds of thousands.

Chunk-based retrieval over a document the model can trivially read in full would *lose* information, not save it. Contract risk is overwhelmingly a property of interactions between clauses: a liability cap in §9 rendered meaningless by a carve-out in §14; an auto-renewal in §3 whose notice period is defined in §17; an indemnity whose scope depends on a definition on page 2. Retrieval fetches the clause and drops the context that makes it dangerous.

So:


| Task                               | Strategy                                                                                               |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Risk scan                          | **Whole document in context**, cached. The agent sees everything.                                      |
| Key-term extraction                | **Whole document in context.**                                                                         |
| Q&A chat                           | **Hybrid retrieval**, because questions are narrow, users ask many, and each should be cheap and fast. |
| Cross-document comparison (future) | Retrieval, necessarily.                                                                                |


Retrieval exists in this system because Q&A needs it and because the future needs it — not because the risk scan does. Building RAG and then deliberately not using it for the marquee feature is the whole point.

### 4.2 Prompt caching

OpenAI caches automatically: the longest previously-seen prefix, above 1,024 tokens, in 128-token increments, at roughly a 90% discount on cached input. There are no `cache_control` annotations to place and no cache-write premium. The cache expires after five to ten minutes of inactivity, which is irrelevant to a seventy-second analysis.

Automatic does not mean free of discipline. Caching is a **prefix match**, so a single byte changed early invalidates everything after it. Render order is `system → tools → messages`, and the prefix must be ordered by stability:

```
system prompt      [ frozen. no dates, no IDs, no conditional sections ]
tool definitions   [ frozen. sorted by name. deterministic serialisation ]
document text      [ stable for the whole analysis ]
── everything above this line is the cached prefix ──
instruction        [ varies per pass: "Analyse rule family: TERMINATION" ]
```

Across a four-pass risk scan, one full-price pass plus three cached ones replaces four full-price passes. Input cost falls by about 70%.

Silent invalidators to audit for, because each costs the entire caching benefit and produces no error:

- Anything time-derived in the system prompt (`datetime.now()`, a build timestamp).
- Session IDs or document IDs interpolated into the system prompt.
- Tool definitions serialised from a `dict` or `set` without a deterministic sort.
- Conditionally-appended system prompt sections.

An integration test asserts that the second pass reports a non-zero cached-token count. If it is zero, caching is silently broken and the build fails.

### 4.3 The loop

Hand-rolled tool-use loop against the OpenAI SDK. Not LangGraph.

The reasoning is threefold. **Reliability:** when an analysis wedges at turn nineteen you want to read a `for` loop and a list of messages, not reason about how a graph checkpointer serialised its state. **Maintainability:** it is one file that will read the same in two years, versus a dependency with a churny API surface, learned in order to express a `while` loop. **Cost:** identical token spend either way — orchestration adds no tokens — except that LangGraph's default state-accumulation patterns make it easy to carry more context forward than intended. A tie at best.

LangGraph earns its place with durable mid-run resume, human-in-the-loop interrupts that block for minutes, or genuinely branching multi-agent topologies. This system has none of those, and §3.5 already provides crash recovery at the correct granularity.

There is a portfolio argument running the same direction. A reviewer who opens `agent/loop.py` and finds forty legible lines learns that the author understands the system. One who finds a `StateGraph` learns that the author can configure someone else's.

```python
messages = [system_msg, document_msg, instruction_msg]

for turn in range(MAX_TURNS):                          # MAX_TURNS = 25
    stream = await client.responses.create(
        model=RISK_SCAN_MODEL,
        input=messages,
        tools=TOOLS,                                   # frozen, sorted
        stream=True,
    )
    async for event in stream:
        await emit_trace(analysis_id, event)           # → SSE → live UI
    response = await stream.get_final_response()

    messages.extend(response.output)                   # incl. reasoning items — see §3.2

    if response.refusal:                               # check BEFORE reading content
        return handle_refusal(analysis_id, response)
    if response.incomplete_reason == "max_output_tokens":
        return handle_truncation(analysis_id, response)

    tool_calls = [b for b in response.output if b.type == "function_call"]
    if not tool_calls:
        break

    results = await asyncio.gather(*[execute_tool(c) for c in tool_calls])
    for call, result in zip(tool_calls, results):
        messages.append({                              # ONE message per call
            "type": "function_call_output",
            "call_id": call.call_id,
            "output": result,
        })
else:
    raise AgentTurnLimitExceeded(analysis_id)
```

> **The field names above are indicative, not authoritative.** Pin them against the SDK reference at M0. The *structure* is what this document specifies; the lexicon belongs to the provider.

Three details that are load-bearing regardless of naming:

- **Append the model's full output**, not just extracted text. On reasoning models, dropping reasoning items forces the model to re-derive its reasoning every turn — you pay for it twice and get worse results.
- **One tool-result message per tool call.** This is the opposite of Anthropic's convention, where all results batch into a single message. Getting it wrong yields a validation error at best and silently suppresses parallel tool calls at worst.
- **A failing tool returns a result describing the failure**, never a dropped message. Every tool call id must have a matching output or the next request is rejected.



### 4.4 Tool surface

Six tools. All `strict: true` with `additionalProperties: false` and every property listed in `required` — optional fields are modelled as nullable unions, not absent keys. This is what strict structured output demands, and it means tool inputs validate exactly.

Tool descriptions are written to be **prescriptive about when to call**, not merely descriptive of what they do. "Call this when…" in the description measurably raises the should-call rate.


| Tool                               | Purpose                                                                                      | Notes                                                                                                                                                      |
| ---------------------------------- | -------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `get_rule_detail(rule_id)`         | Returns the full definition, exposure explanation, and detection guidance for one risk rule. | The system prompt carries only rule *names*; details load on demand. Keeps the cached prefix small.                                                        |
| `search_document(query)`           | Hybrid retrieval over this document's chunks.                                                | Rarely needed during the risk scan (the doc is in context) — it exists for the agent to re-locate a clause it wants to quote precisely, and it powers Q&A. |
| `record_finding(...)`              | Persists one risk finding. **Quote is verified before acceptance.**                          | See §4.5. Returns `{verified: bool, page: int}` so the agent learns immediately if it misquoted.                                                           |
| `record_key_terms(...)`            | Persists the typed extraction record. Called once.                                           | Nulls are legal and meaningful ("no liability cap present").                                                                                               |
| `note_absence(rule_id, rationale)` | Records that a rule was checked and *not* triggered.                                         | Lets the memo say "we checked for X and found none," which is what makes it trustworthy. Also gives the eval harness a true-negative signal.               |
| `finalize(summary)`                | Ends the analysis, writes the executive summary.                                             | Explicit termination beats inferring it from an absent tool call.                                                                                          |


`record_finding` schema:

```python
class RecordFinding(BaseModel):
    rule_id: RuleId                    # enum, from the rule library
    severity: Literal["critical", "high", "medium", "low"]
    title: str                         # ≤ 80 chars, plain English
    exposure: str                      # what goes wrong, and to whom
    recommendation: str                # the redline to ask for
    quoted_text: str                   # VERBATIM from the source. 20-600 chars.
    confidence: Literal["high", "medium", "low"]
```

Note what is *not* in the schema: page number, character offsets. The agent does not supply those, because the agent cannot be trusted to supply those. We derive them.

### 4.5 Quote verification — the hallucination guard

This is the most important mechanism in the system.

There is no citations API here. Nothing in the response tells us where in the source a quoted clause actually lives, or whether it lives there at all. So the agent supplies a verbatim quote in the tool call, and the server verifies it against the extracted document text before the finding is allowed to exist:

```
record_finding(quoted_text="...")
        │
        ├─ normalise: collapse whitespace, unify quote/dash glyphs, casefold
        │
        ├─ exact substring match against normalised document text?
        │     └─ yes → char_start, char_end → page number  → verified
        │
        ├─ no → LOCATE a candidate span: rapidfuzz partial_ratio_alignment ≥ 85
        │     │   (locating only. this score never authorises anything — see below)
        │     │
        │     └─ AUTHORISE it: does every token of the quote appear, in order,
        │         within that span?  the source may carry EXTRA tokens; the quote
        │         may not.
        │           └─ yes → snap to the matched span         → verified
        │
        └─ no → finding.verified = False
                 ├─ NOT rendered in the UI
                 ├─ NOT included in the memo
                 ├─ counted in analysis.unverified_count
                 └─ tool result returns {verified: false} + why, so the agent can retry
```

**Why authorisation is not a similarity threshold.** Version 1.0 of this document specified
`partial_ratio ≥ 95 → verified`. That was implemented, tested against adversarial quotes, and
found to have a hole that would have sunk the product:


|                 |                                                                                                          |
| --------------- | -------------------------------------------------------------------------------------------------------- |
| document        | "…the indemnification obligations … are **not** subject to the limitations of liability in Section 9."   |
| agent           | "…the indemnification obligations … are **fully** subject to the limitations of liability in Section 9." |
| `partial_ratio` | **96.1 — PASSES**                                                                                        |


One word. The clause now means the opposite of what the contract says, and it would have rendered
in the UI with a real page number and a real highlight. That is not a missed finding; it is a
confident, well-anchored lie, and it is precisely the thing this mechanism exists to make
impossible.

No threshold repairs it. A substituted word in a 123-character clause costs about four points of
character similarity, so raising the bar to 98 would still admit substitutions in longer quotes —
while rejecting honest quotes that PDF hyphenation had damaged. The number was not wrong. The
*metric* was: character similarity cannot distinguish text that extraction **damaged** from text
the model **altered**, and those are the two things this guard exists to tell apart.

So fuzzy matching is demoted to what it is genuinely good at — finding *where* in the document to
look — and authorisation rests on an asymmetry:

> **Every token of the quote must appear, in order, in the source span. The source may contain
> extra tokens. The quote may not.**

The asymmetry is derived from what the two kinds of damage actually look like. When a quote spans a
page break it picks up a header, a footer, a page number; when a line wraps, a hyphenated word
splits in two. In every such case the *source* gains junk while the quote's words remain intact and
in order — forgivable, and forgiven. But when a model reconstructs a clause from memory rather than
reading it, the *quote* acquires a word the document never contained. There is no innocent
explanation for that, and a fabrication cannot be expressed any other way. The check therefore
catches it **by construction rather than by calibration**, which is the only basis on which a claim
like the one below can be defended.

This buys three things at once. It makes a fabricated quotation structurally unable to reach the user. It gives us the page and character range for the PDF highlight overlay, which the agent could never reliably produce. And it yields a claim we can put on the landing page and defend: **every quotation you see provably exists in your document.**

If `unverified_count / total_findings` exceeds 0.15 on the eval set, that is a prompt bug, and the eval harness fails the build.

The four substitution cases — flipped negation, reversed parties, swapped number, appended clause —
are pinned as tests (`test_verify.py`). They are the regression suite for the most important claim
the product makes.

### 4.6 System prompt

Frozen, cached, no interpolation. Structure:

1. **Role.** Senior commercial counsel reviewing on behalf of the party receiving the contract. Bias toward the reader's exposure.
2. **Rule library index.** Names and one-line summaries of all 15 rules. Full details via `get_rule_detail`.
3. **Method.** Read the entire document before recording anything. Check every rule. Call `note_absence` for rules that do not trigger. Quote verbatim — never paraphrase into `quoted_text`.
4. **Calibration.** Severity is about *exposure*, not about how unusual the clause is. A standard-but-dangerous term is still high severity.
5. **Autonomy.** Explicit: this runs unattended, the user is not watching in real time, do not ask questions, do not end a turn on a statement of intent.
6. **Output discipline.** No preamble. No progress narration between tool calls beyond a single sentence when direction changes. Otherwise the trace becomes noise.
7. **Boundaries.** Not legal advice. Say when a clause is ambiguous rather than resolving the ambiguity. Do not speculate about jurisdiction-specific enforceability.



### 4.7 Risk rule library

A versioned YAML file, `rules/v1.yaml`, loaded at boot and hashed into `analyses.rule_library_version`. Fifteen rules, chosen because each maps to a concrete financial or operational exposure that a non-lawyer can be made to feel in one sentence.


| `rule_id`                      | Default severity | The exposure, in one sentence                                                                              |
| ------------------------------ | ---------------- | ---------------------------------------------------------------------------------------------------------- |
| `auto_renewal`                 | high             | The contract renews itself and the window to stop it has already closed by the time anyone thinks to look. |
| `uncapped_liability`           | critical         | There is no ceiling on what a single mistake can cost you.                                                 |
| `asymmetric_liability_cap`     | high             | Their exposure is capped; yours is not, or theirs is far lower.                                            |
| `unilateral_termination`       | high             | They can walk away on short notice; you cannot.                                                            |
| `one_sided_indemnity`          | critical         | You cover their legal costs for claims arising from their own conduct.                                     |
| `overbroad_ip_assignment`      | critical         | Work product, improvements, or background IP transfer more broadly than intended.                          |
| `non_compete`                  | high             | Restricts who you may do business with, often after the contract ends.                                     |
| `missing_sla_or_remedy`        | medium           | Performance is promised but nothing happens when it is not delivered.                                      |
| `unilateral_amendment`         | high             | They can change the terms — including price — by posting a new page on their website.                      |
| `unfavorable_forum`            | medium           | Any dispute must be litigated somewhere expensive and far away.                                            |
| `payment_terms`                | medium           | Net-60+, punitive late fees, or no window to dispute an invoice.                                           |
| `missing_data_protection`      | high             | No DPA, no breach-notification duty, no processing limits — with your customers' data.                     |
| `assignment_change_of_control` | medium           | The counterparty can be acquired and the contract transfers to whoever bought them.                        |
| `confidentiality_defect`       | medium           | Perpetual obligations, or none at all, or protection running only one way.                                 |
| `uncapped_price_escalation`    | high             | They may raise the price at renewal without limit.                                                         |


Each rule entry carries: `id`, `title`, `default_severity`, `exposure` (user-facing prose), `detection_guidance` (agent-facing, returned by `get_rule_detail`), `recommended_redline`, and `applies_to` (contract types).

The library is a data file, not code. Adding a rule is a pull request that touches YAML and the eval fixtures — nothing else.

Rules are grouped into four **families** for the multi-pass scan: `LIABILITY`, `TERMINATION`, `COMMERCIAL`, `RIGHTS_AND_DATA`. Each pass shares the cached document prefix and varies only the trailing instruction.

---



## 5. Data model

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE users (
  id              uuid PRIMARY KEY,
  email           text NOT NULL UNIQUE,
  password_hash   text NOT NULL,          -- bcrypt
  is_admin        bool NOT NULL DEFAULT false,
  upload_grant    int  NOT NULL DEFAULT 0, -- lifetime analyses allowed; admin ignores it
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE access_codes (              -- invite codes; a coupon for access, not money
  code            text PRIMARY KEY,
  grant_count     int  NOT NULL,          -- analyses this code unlocks (→ users.upload_grant)
  claimed_by      uuid REFERENCES users,  -- NULL until a signup consumes it; single-use
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE documents (
  id              uuid PRIMARY KEY,
  sha256          text NOT NULL,
  filename        text NOT NULL,
  source          text NOT NULL,          -- 'demo' | 'upload'
  page_count      int  NOT NULL,
  char_count      int  NOT NULL,
  is_scanned      bool NOT NULL DEFAULT false,
  storage_key     text NOT NULL,          -- object storage; PDFs are never in Postgres
  owner_user_id   uuid REFERENCES users,  -- who uploaded it; NULL for demo docs
  created_at      timestamptz NOT NULL DEFAULT now(),
  expires_at      timestamptz,            -- uploads: now() + 24h. demo: NULL.
  UNIQUE (sha256, source)
);

-- The cap is a count over this owner: a non-admin user may run up to
-- users.upload_grant analyses, checked before an analysis runs (§2.5).

CREATE TABLE pages (
  document_id     uuid REFERENCES documents ON DELETE CASCADE,
  page_number     int  NOT NULL,          -- 1-indexed
  char_start      int  NOT NULL,          -- offset into the document's full text
  char_end        int  NOT NULL,
  PRIMARY KEY (document_id, page_number)
);

CREATE TABLE chunks (
  id              uuid PRIMARY KEY,
  document_id     uuid REFERENCES documents ON DELETE CASCADE,
  ordinal         int  NOT NULL,
  section_label   text,                   -- "9.2", "Schedule A", when detectable
  char_start      int  NOT NULL,
  char_end        int  NOT NULL,
  text            text NOT NULL,
  embedding       vector(384),            -- bge-small-en-v1.5
  tsv             tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON chunks USING gin (tsv);
CREATE INDEX ON chunks (document_id, ordinal);

CREATE TABLE analyses (
  id                   uuid PRIMARY KEY,
  document_id          uuid REFERENCES documents ON DELETE CASCADE,
  status               text NOT NULL,     -- queued|running|complete|failed
  scan_model           text NOT NULL,
  extract_model        text NOT NULL,
  rule_library_version text NOT NULL,
  summary              text,
  turns_used           int,
  unverified_count     int  NOT NULL DEFAULT 0,
  token_usage          jsonb,             -- per-model, incl. cached-token counts
  cost_microdollars    bigint,
  error                text,
  started_at           timestamptz,
  completed_at         timestamptz
);

CREATE TABLE findings (
  id              uuid PRIMARY KEY,
  analysis_id     uuid REFERENCES analyses ON DELETE CASCADE,
  rule_id         text NOT NULL,
  severity        text NOT NULL,
  title           text NOT NULL,
  exposure        text NOT NULL,
  recommendation  text NOT NULL,
  quoted_text     text NOT NULL,          -- as returned by the agent
  matched_text    text,                   -- as found in the source, when verified
  char_start      int,
  char_end        int,
  page_number     int,
  verified        bool NOT NULL,
  confidence      text NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON findings (analysis_id, severity);

CREATE TABLE absences (                   -- rules checked and not triggered
  analysis_id     uuid REFERENCES analyses ON DELETE CASCADE,
  rule_id         text NOT NULL,
  rationale       text NOT NULL,
  PRIMARY KEY (analysis_id, rule_id)
);

CREATE TABLE key_terms (
  analysis_id     uuid PRIMARY KEY REFERENCES analyses ON DELETE CASCADE,
  payload         jsonb NOT NULL          -- validated by the KeyTerms Pydantic model
);

CREATE TABLE agent_events (               -- the trace; replayable after the fact
  analysis_id     uuid REFERENCES analyses ON DELETE CASCADE,
  seq             int  NOT NULL,
  kind            text NOT NULL,          -- reasoning|text|tool_call|tool_result|usage
  payload         jsonb NOT NULL,
  at              timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (analysis_id, seq)
);

CREATE TABLE jobs (
  id              uuid PRIMARY KEY,
  kind            text NOT NULL,
  payload         jsonb NOT NULL,
  status          text NOT NULL DEFAULT 'queued',
  attempts        int  NOT NULL DEFAULT 0,
  last_error      text,
  run_after       timestamptz NOT NULL DEFAULT now(),
  locked_at       timestamptz,
  locked_by       text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON jobs (status, run_after) WHERE status = 'queued';

CREATE TABLE usage_ledger (               -- cost control, §7
  day               date NOT NULL,
  ip_hash           text NOT NULL,        -- HMAC(ip, secret); the raw IP is never stored
  analyses          int  NOT NULL DEFAULT 0,
  cost_microdollars bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (day, ip_hash)
);
```

`agent_events` means the trace survives a page refresh and can be replayed for a finished analysis. Demo documents ship with their `agent_events` pre-populated, so the demo replays a *real* trace at a plausible speed with no API call.

---



## 6. Interfaces



### 6.1 HTTP API

```
POST   /api/documents                 multipart upload → 202 {document_id, analysis_id}
GET    /api/documents/{id}                            → document metadata
GET    /api/documents/{id}/file                       → signed PDF URL
GET    /api/analyses/{id}                             → status, summary, counts
GET    /api/analyses/{id}/findings                    → verified findings, severity-ranked
GET    /api/analyses/{id}/key-terms                   → typed extraction
GET    /api/analyses/{id}/events        (SSE)         → live trace, or replay if complete
GET    /api/analyses/{id}/memo?format=md|pdf          → the artifact
POST   /api/analyses/{id}/ask                         → SSE, grounded answer + citations
GET    /api/demo                                      → the pre-indexed sample set
GET    /api/health                                    → db, queue depth, spend headroom
```

`GET /api/analyses/{id}/events` is the same endpoint whether the analysis is running or finished. Running: it tails `agent_events` as rows arrive. Finished: it replays them. The client does not need to know which.

### 6.2 SSE event shapes

Provider event types are normalised into this vocabulary at the edge, so the frontend never sees an OpenAI type name. If the provider changes, one adapter changes.

```jsonc
{"kind": "status",      "status": "running"}
{"kind": "reasoning",   "text": "..."}          // summarised, when available
{"kind": "tool_call",   "name": "get_rule_detail", "input": {"rule_id": "auto_renewal"}}
{"kind": "tool_result", "name": "record_finding",  "output": {"verified": true, "page": 3}}
{"kind": "finding",     "finding": { /* full finding object, for optimistic render */ }}
{"kind": "usage",       "input_tokens": 412, "cached_input_tokens": 28104, "output_tokens": 1893}
{"kind": "status",      "status": "complete"}
```



### 6.3 Pipeline

```
upload
  ├─ validate       type ∈ {pdf, docx}, ≤ 10 MB, ≤ 40 pages, rate limit, spend cap
  ├─ hash           sha256 → dedupe against existing uploads
  ├─ store          object storage; expires_at = now() + 24h
  ├─ parse          PyMuPDF → full text + per-page char offsets → pages
  │                  if char_count / page_count < 100 → is_scanned = true
  ├─ chunk          split on numbered-section regex, then pack to ~800 tokens
  │                  with 100-token overlap; carry section_label forward
  ├─ embed          fastembed / bge-small, local, batched
  └─ enqueue        jobs(kind='analyse', payload={document_id})

worker
  ├─ claim          FOR UPDATE SKIP LOCKED
  ├─ scan           §4.3 agent loop, 4 rule-family passes, streaming into agent_events
  ├─ verify         every record_finding quote, §4.5
  ├─ extract        single mini call, strict structured output → key_terms
  ├─ render         memo → Markdown → PDF → object storage
  └─ settle         analyses.status, token_usage, cost; usage_ledger increment
```

**Scanned PDFs.** Detected at ingest by character density. Because we pass extracted text rather than page images (§3.2), a scanned document yields nothing to analyse. v1 rejects it at upload with an honest message rather than producing an empty analysis. Adding OCR is a post-launch enhancement, and the `is_scanned` column exists so that the rejection is data, not a special case.

---



## 7. Cost, abuse, and the public demo

The application is on a public URL with a real API key behind it. Since v1.3 the answer is not to meter strangers but to exclude them from the expensive path entirely: the demo is free and costs nothing to serve, and analysing your own contract is **invite-only** (§2.5). Anonymous visitors cannot spend anything, because there is no anonymous upload path at all.

### 7.1 Demo mode is the default path

Four pre-indexed sample contracts — a SaaS MSA, a mutual NDA, a commercial office lease, a freelance services agreement — with `findings`, `key_terms`, `agent_events`, and rendered memos already in the database. Sourced from public templates and lightly seeded with realistic bad clauses so the findings are interesting.

Clicking one costs **zero API calls** and renders instantly, trace replay and all. This is the primary call to action on the landing page. Most visitors will never upload anything, and they will still see the product work.

### 7.2 Uploads are capped

Since v1.3 the **first** cap is the invite gate in §2.5: you cannot upload without an account, and you cannot get an account without an access code you were handed. The set of people who can spend API budget is exactly the set of people you invited — there is no anonymous upload path to abuse. The remaining layers stand behind it:

| Layer            | Limit                                   | Behaviour on breach                                                    |
| ---------------- | --------------------------------------- | ---------------------------------------------------------------------- |
| Per account      | `upload_grant` analyses; admin = ∞      | Inline "grant spent, contact the author" (§2.5). No checkout.          |
| Per document     | 10 MB, 40 pages                         | 400 with a specific message                                            |
| Global per month | Hard spend ceiling, configurable        | Uploads disabled; the site degrades to demo-only with an honest banner |

Because signup itself requires a code, the per-IP daily counter that guarded an anonymous upload path is no longer load-bearing and is not in the MVP.

The global ceiling is checked *before* the analysis runs, against `SUM(cost_microdollars)` over the current month in `usage_ledger`.

Uploaded documents and their derived rows are deleted 24 hours after upload by a scheduled job. This is stated on the upload dropzone, because a person about to hand a contract to a stranger's website wants to read exactly that sentence.

### 7.3 What an analysis actually costs

A 30-page contract is roughly 28,000 input tokens. Prices per million tokens, verified 2026-07-10 — **re-verify before launch**:


| Model          | Input | Cached input | Output |
| -------------- | ----- | ------------ | ------ |
| `gpt-5.6-sol`  | $5.00 | $0.50        | $30.00 |
| `gpt-5.4-mini` | $0.75 | $0.075       | $4.50  |


**Risk scan** — four rule-family passes on Sol:


| Component                               | Tokens  | Cost       |
| --------------------------------------- | ------- | ---------- |
| First pass, uncached                    | 28,000  | $0.140     |
| Three further passes, cached @ 90% off  | 84,000  | $0.042     |
| Tool results and instructions, uncached | ~8,000  | $0.040     |
| Output, including reasoning             | ~14,000 | $0.420     |
|                                         |         | **$0.642** |


**Key-term extraction** on mini: ~$0.030. **Memo summary** on mini: ~$0.012. **Embeddings**: $0.

**Total per uploaded document: ≈ $0.68.** At a $60/month ceiling, roughly 85 anonymous analyses on top of unlimited free demo views. Grounded Q&A adds about $0.007 per question.

Two observations that should shape where effort goes.

**Output is 65% of the bill, and caching does nothing about it.** The lever that matters is how many tokens the agent *writes* — turn count and reasoning depth — not how cleverly the input is cached. Time spent tightening the system prompt's output discipline pays better than time spent on cache placement.

**The model tier is worth five times more than everything else combined.** If the eval sweep shows mini holds ≥0.80 recall on critical findings, the same scan costs about **$0.10** and the ceiling funds over 400 analyses. §8 makes that a measurement rather than a guess. This is the single highest-leverage experiment in the project and it happens on day 6.

### 7.4 Safety and failure paths

The model can decline a request, returning a refusal rather than content. A contract containing, say, security-testing scope language is a plausible trigger. Any code that reads the response content without first checking for a refusal will crash. The loop checks first, records it on `analyses.error`, and the UI reports it honestly rather than showing an empty result.

Uploaded PDFs are untrusted input. PyMuPDF parses them in the worker process, never in the API process. Files are stored under a generated key, never under a user-supplied filename.

---



## 8. Evaluation

Ten contracts, hand-labelled by the author: for each, the set of rules that *should* fire and the clause that should be quoted. Roughly 70 labelled findings, plus true negatives from rules that correctly do not fire.

`make eval` runs the full agent against all ten and reports:


| Metric                     | Meaning                                    | Gate     |
| -------------------------- | ------------------------------------------ | -------- |
| Recall (critical + high)   | Did we catch the dangerous things?         | ≥ 0.80   |
| Recall (all severities)    |                                            | ≥ 0.65   |
| Precision                  | Are the findings real?                     | ≥ 0.75   |
| Citation verification rate | Share of findings whose quote verified     | ≥ 0.85   |
| Anchor accuracy            | Verified span overlaps the labelled clause | ≥ 0.90   |
| Cost per document          |                                            | reported |
| Wall-clock per document    |                                            | reported |




### 8.1 The model-tier sweep

The harness runs the risk scan at three tiers — `sol`, `terra`, `mini` — and prints the three columns side by side. The decision rule is stated in advance so it cannot be rationalised after the fact:

> Take the cheapest tier that holds **recall (critical + high) ≥ 0.80** and **precision ≥ 0.75**.

If that is mini, the running cost falls fivefold. If it is Sol, the project has a defensible number explaining why it pays for the flagship. Either outcome is a good README section. The one unacceptable outcome is choosing by intuition.

This runs at the end of M2 and gates the M7 spend ceiling.

### 8.2 CI

Three of the ten documents run on every change to the system prompt or the rule library, so a prompt edit that quietly destroys recall cannot merge. The full ten run nightly.

Two invariants have their own tests, because both fail *silently* in production:

- The second pass of an analysis reports a non-zero cached-token count. Zero means a silent cache invalidator has crept into the prefix.
- A finding whose `quoted_text` is a fabricated sentence never reaches `verified = true`. Tested with a deliberately corrupted quote.

---



## 9. Frontend



### 9.1 Design register

Client-facing, so: dense, professional, unfussy. Legal-tech, not consumer-AI. Neutral slate ground, a single accent for interactive affordance, and severity communicated through a purpose-built four-step scale that stays legible in both light and dark and does not rely on red/green discrimination alone — severity carries an icon and a label, not just a hue.

Explicitly avoided: cream backgrounds with serif display type, purple-to-indigo gradients, Inter as a default, and the rest of the generative-design house style. A contract review tool that looks like every AI landing page reads as a toy.

### 9.2 Screens

**Landing.** One sentence on what it does. Four sample contracts as cards, each showing its worst finding as a teaser — clickable by anyone, no account. Upload dropzone beneath, with the 24-hour deletion promise stated inline; dropping a file while logged out routes to login first. Disclaimer above the fold.

**Login.** Email + password. Minimal, professional, same register as the rest — not a consumer-app splash. On success the SPA stores the JWT and returns the user to where they were headed (the upload they attempted, or the landing page).

**Sign up.** Email + password **+ access code.** The code field is required and validated server-side; a bad or spent code fails the signup with a clear message. On success the account is created with the code's grant and the user is logged in. This is the only way an account that can spend API budget comes into existence (§2.5). There is no Upgrade page — a spent grant shows an inline "contact the author" message, not a checkout.

**Document view.** Split pane. Left, the PDF with a highlight overlay. Right, four tabs.

*Risks* is the default tab: severity-grouped cards, critical first. Each card shows the title, the exposure sentence, the quoted clause in a distinct block, the page number, and the recommended redline. Clicking a card scrolls the PDF to the page and paints the character span. Beneath the findings, a collapsed "Checked and not found" list built from `absences` — this is what separates a tool that looks thorough from one that is.

*Key Terms* is a two-column table. Missing values render as an explicit "Not specified", which for a liability cap is itself the finding.

*Ask* is grounded chat. Answers stream. Citations render as superscripts that jump to the source span.

*Memo* previews the rendered Markdown with Download PDF and Copy Markdown.

**Agent trace** is a drawer, open by default during a live analysis, collapsed after. It renders the `agent_events` stream as a readable timeline: a reasoning summary, a tool call with its arguments, a result. It is the difference between "the AI did something" and "I watched it work."

### 9.3 The highlight overlay

The hardest piece of frontend work in the project, and worth budgeting honestly for. `findings.char_start` / `char_end` are offsets into the document's full extracted text. `pages.char_start` maps an offset to a page. Within the page, pdf.js exposes a text layer of positioned spans; we walk it, accumulate character counts, and locate the DOM range covering the offset window. Then we paint absolutely-positioned rectangles behind it.

The failure mode is a mismatch between PyMuPDF's text extraction order and pdf.js's, on multi-column or table-heavy pages. Mitigation: verify against the sample contracts during M4, and fall back to page-level highlighting (dim the page, outline it) when the span cannot be resolved. A slightly imprecise highlight is fine. A highlight on the wrong page is not, and the fallback is what prevents it.

---



## 10. Implementation plan

Fifteen working days. Each milestone ends in something demonstrable — not "the parser is done" but "I can run this and see it work."


| #   | Days | Milestone     | Done when                                                                                                                                                                                                                                                                                              |
| --- | ---- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| M0  | 1    | Foundation    | `docker compose up` gives Postgres+pgvector and a green FastAPI health check. CI runs lint, types, tests. Rule library YAML exists with all 15 rules. **Model IDs and SDK field names pinned from the live API reference**, not from this document.                                                    |
| M1  | 2–3  | Ingest        | `POST /api/documents` with a real PDF produces rows in `documents`, `pages`, and `chunks` with local embeddings. Hybrid search returns sane results from a script.                                                                                                                                     |
| M2  | 4–6  | **The agent** | `python -m clause.analyse sample.pdf` prints verified findings with page numbers to the terminal. Quote verification rejects a deliberately corrupted quote. Model-tier sweep run and the tier chosen (§8.1). This is the project. Everything before it is setup and everything after is presentation. |
| M3  | 7–8  | Async + trace | Job queue claims and runs analyses. `agent_events` populate. SSE endpoint streams live and replays when complete. Failures surface as `status: failed` with a real message.                                                                                                                            |
| M4  | 9–11 | Document view | React (Vite SPA) split pane. Risk cards render. **Highlight overlay lands.** Trace drawer renders the live stream. This is the longest milestone; the overlay is why.                                                                                                                                           |
| M5  | 12   | Ask           | Grounded Q&A over hybrid retrieval, streamed, with citations that jump to the source.                                                                                                                                                                                                                  |
| M6  | 13   | Memo          | Markdown → PDF. Download works. The artifact is good enough to send to someone.                                                                                                                                                                                                                        |
| M7  | 14   | Hardening     | Rate limits, spend ceiling (sized by the M2 sweep), demo mode with pre-baked traces, 24h deletion job, refusal handling, disclaimer everywhere.                                                                                                                                                        |
| M8  | 15   | Evidence      | README with architecture diagram, the tier-sweep table, and eval numbers. Deployed to production URL.                                                                                                                                                                                                  |


Two scheduled decision points, both driven by measurement rather than preference:

- **End of M2:** the model-tier sweep. Fixes the scan model and therefore the cost model, which gates the M7 ceiling.
- **End of M4:** if the highlight overlay is not working on the four sample contracts by end of day 11, ship the page-level fallback and move on. The overlay is a delight; the memo is the product.



### 10.1 If the schedule slips

Cut in this order, and no other:

1. The *Ask* tab (M5). Grounded Q&A is table stakes elsewhere; risks and the memo are what differentiate.
2. Span-precise highlighting, down to page-level. See above.
3. The `absences` display. Keep recording them — the eval harness needs the true negatives — just do not render the list.

Never cut: quote verification, the agent trace, the memo, the disclaimer, the spend ceiling.

---



## 11. Repository

```
clause/
├── README.md                 architecture diagram, tier sweep, eval results, demo GIF
├── SPEC.md                   this document
├── docker-compose.yml
├── Makefile                  dev · test · eval · seed-demo
├── api/
│   ├── clause/
│   │   ├── agent/
│   │   │   ├── loop.py       §4.3 — the forty lines
│   │   │   ├── tools.py      §4.4 — six tools, strict schemas
│   │   │   ├── prompts.py    §4.6 — frozen. no interpolation. ever.
│   │   │   └── verify.py     §4.5 — the hallucination guard
│   │   ├── models.py         model IDs and tiering. one place. pinned at M0.
│   │   ├── auth/             §2.5 — signup (access code) + login, JWT, bcrypt, the grant gate
│   │   ├── ingest/           parse, chunk, embed
│   │   ├── retrieval/        the hybrid query
│   │   ├── memo/             jinja templates → md → pdf
│   │   ├── jobs/             claim, run, retry
│   │   ├── routes/
│   │   └── db/               models, migrations
│   └── tests/
├── web/                      vite + react SPA (login, signup+code, analysis view)
├── rules/
│   └── v1.yaml               the 15 rules, grouped into 4 families
├── evals/
│   ├── corpus/               10 contracts
│   ├── labels/               hand-labelled ground truth
│   └── run.py                → the tables in §8
└── demo/
    └── seed.py               pre-bake the four samples: findings, terms, traces, memos
```

`prompts.py` opens with a comment explaining that any `f`-string, timestamp, or conditional branch in it silently costs the entire prompt-caching benefit and produces no error. That comment saves a future afternoon.

---



## 12. Risks


| Risk                                                     | Likelihood | Mitigation                                                                                 |
| -------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------ |
| Highlight overlay fights pdf.js text-layer ordering      | High       | Page-level fallback specced and time-boxed. Decided at end of M4, not day 15.              |
| Agent recall is poor at the cheap tier                   | Medium     | The M2 sweep makes this visible on day 6, with time to raise the tier or fix the prompt.   |
| Prompt caching silently breaks                           | Medium     | Asserted in an integration test. Zero cached tokens fails the build.                       |
| Anonymous uploads drain the budget                       | Medium     | Three independent caps; the global one degrades the site to demo mode rather than failing. |
| A demo visitor uploads a genuinely confidential contract | Certain    | 24h deletion, stated inline at the dropzone. Never logged, never left in Postgres.         |
| Scanned PDFs produce no text                             | Medium     | Detected and rejected at ingest with an honest message. OCR is post-launch.                |
| Model IDs or SDK field names in this spec go stale       | Certain    | Pinned from the live reference at M0; isolated in `models.py` and one SSE adapter.         |
| The model refuses a contract                             | Low        | Refusal checked before reading content. Surfaced honestly.                                 |
| Scope creep into cross-document comparison               | High       | It is in §1.3 for a reason. The schema permits it. v1 does not ship it.                    |


---



## 13. Open questions

1. **Scan model tier.** Sol is the specced default. Resolved by the M2 sweep (§8.1), not by argument.
2. **Retrieval weights.** `0.7` semantic / `0.3` lexical is a starting guess. Tune against the eval corpus at M5.
3. **Rule 16+.** The library is deliberately closed at 15 for v1. Additions are a post-launch pull request against YAML and fixtures.
4. **Sample contract sourcing.** Public templates, lightly seeded with realistic adverse clauses. Must be documented as synthetic in the README — a demo that implies real contracts were scraped is a credibility hole, not a shortcut.

---



## 14. Changelog


| Version | Date       | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.0     | 2026-07-10 | Initial specification. OpenAI API with hand-rolled tool-use loop; model tiering by task; local `bge-small` embeddings. Scope fixed at: risk flagging with verified quotations, internal key-term extraction, memo generation, grounded Q&A. Cross-document comparison and standalone structured extraction deferred.                                                                                                                                                                                                                                                                                                                                                                                     |
| 1.1     | 2026-07-14 | §4.5 rewritten. The specified `partial_ratio ≥ 95 → verified` guard was implemented and measured, and admitted a one-word negation flip at a score of 96.1 — a quote that inverts the contract's meaning, anchored to a real page. Fuzzy matching is demoted to locating a candidate span; authorisation now rests on an ordered token check with source/quote asymmetry. Also: model IDs and prices in §3.2 and §7.3 verified against the live API and found correct; `gpt-5.6-luna` and `gpt-5.4-nano` added to the §8.1 sweep. Delivery is now staged in three versions — see ROADMAP.md — with V1 shipping no retrieval at all, on the grounds that §4.1 already says the risk scan does not use it. |
| 1.2     | 2026-07-15 | **Product reframed around a shippable MVP.** Accounts, JWT login, and per-user access control added (§2.5, §3.1, §5): the public demo stays free and login-free, but uploading your own contract now requires an account, a free account gets exactly one analysis, and an `is_admin` tier is unlimited. A placeholder Upgrade page replaces the anonymous two-pool budget as the primary abuse control; Stripe is deferred. "No user accounts" and "no billing" removed from §1.3 non-goals accordingly. Frontend simplified from Next.js to a **Vite + React SPA** (§3.1, §9). The eval harness, memo generation, and grounded Q&A are pulled *out* of the MVP and resequenced in ROADMAP.md — the agent and quote-verification guard they were built around are unchanged and remain in the repo. |
| 1.3     | 2026-07-15 | **Access made invite-only; self-serve tier removed.** On the observation that this is a portfolio tool shown to a few prospects rather than a public SaaS, the v1.2 "free = 1 upload" self-serve tier and the Upgrade/Stripe flow were removed. Running the agent now requires signing up with a single-use **access code** you hand out, which sets a per-account `upload_grant` (§2.5); admins are unlimited on a protected reserve. `access_codes` table and `users.upload_grant` added (§5); §2.3 flow, §7.2 caps, and §9 screens updated (Upgrade page replaced by a code field on signup). The point of accounts is now (a) a real auth flow for the portfolio and (b) making the set of budget-spenders exactly the set of people you invited. Stripe moves to a "beyond V3" concern. |


