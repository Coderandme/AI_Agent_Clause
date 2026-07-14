---
title: Clause
emoji: 📄
colorFrom: gray
colorTo: blue
sdk: gradio
sdk_version: 6.20.0
python_version: '3.12'
app_file: app.py
pinned: false
license: mit
short_description: Contract risk agent with verified quotations
---

# Clause — Contract Intelligence Agent

An agent that reads a commercial contract, flags the risks, and **proves every quotation it shows
you exists in your document.**

Not a chatbot. You upload a contract, and an agent works through a versioned library of 15 risk
rules on its own — calling `get_rule_detail("auto_renewal")`, checking the notice period, recording
a finding — while you watch. It takes about a minute and it does not ask you anything.

> ⚠️ **Status: in development, and this README describes what is *built*, not what is planned.**
> The agent, the hallucination guard, and the eval harness work, and every number below is real.
> The UI is an interim **Gradio** app — the dense Next.js frontend in [SPEC.md](SPEC.md) §9 does not
> exist yet, and neither do the job queue, the memo, or the Q&A tab. See [ROADMAP.md](ROADMAP.md).

**Run it yourself** — two contracts ship pre-analysed and replay instantly at zero cost, agent trace
and all, so the demo works without an API key:

```bash
cd api && uv sync --extra dev
cd .. && uv run --project api python app.py     # http://localhost:7860
```

A hosted Gradio demo is configured and ready ([DEPLOY.md](DEPLOY.md)) but is not currently up — the
free Hugging Face CPU tier allows one running Space per account, and that slot is in use. The app,
the Dockerfile, and the spend caps all work; it is a quota, not a bug.

---

## The thing worth reading about

Everything else here is plumbing. This is the part I would want a reviewer to look at.

**There is no citations API.** When a model tells you a contract contains a dangerous clause, nothing
in its response tells you where that clause lives, or whether it lives there at all. So the agent
supplies a verbatim quote, and the server verifies it against the source **before the finding is
allowed to exist**. A quotation that isn't in the document is discarded, never rendered, never
memoed, and the agent is told so it can correct itself.

The spec ([SPEC.md §4.5](SPEC.md)) specified that guard as:

```
normalise → exact match, else rapidfuzz partial_ratio ≥ 95 → verified
```

I built exactly that, wrote adversarial tests, and they passed. Then I printed the scores instead of
trusting the green checkmarks:

| | |
|---|---|
| document says | "…the indemnification obligations … are **not** subject to the limitations of liability in Section 9." |
| agent says | "…the indemnification obligations … are **fully** subject to the limitations of liability in Section 9." |
| `partial_ratio` | **96.1 — PASSES** |

One word. The clause now means the *opposite* of what the contract says — and it would have rendered
in the UI with a real page number and a real highlight. That is not a missed finding. It is a
confident, well-anchored lie, and it is precisely what the mechanism exists to prevent.

**No threshold fixes this.** A substituted word in a 123-character clause costs about four points of
character similarity. Raise the bar to 98 and you still admit substitutions in longer quotes, while
rejecting honest quotes that PDF hyphenation damaged. The number wasn't wrong — **the metric was.**
Character similarity cannot distinguish text that extraction *damaged* from text the model *altered*,
and those are the only two things this guard needs to tell apart.

So fuzzy matching was demoted to what it's actually good at — finding *where* to look — and
authorisation now rests on an asymmetry:

> **Every token of the quote must appear, in order, in the source span.
> The source may contain extra tokens. The quote may not.**

That asymmetry falls out of what the two kinds of damage look like. A quote spanning a page break
picks up a header and a page number; a wrapped line splits a hyphenated word. In both cases the
*source* gains junk while the quote's words survive intact and in order — forgivable. But when a
model reconstructs a clause from memory, the *quote* acquires a word the document never contained.
There is no innocent explanation for that, and a fabrication cannot be expressed any other way.

The guard catches it **by construction, not by calibration.**

| adversarial quote | locate score | verdict |
|---|---|---|
| exact clause | 100.0 | verified, p4 |
| hard-wrapped across lines | 100.0 | verified, p5 |
| curly quotes straightened | 100.0 | verified, p2 |
| **negation flipped** (`not` → `fully`) | **96.1** | **rejected** |
| parties reversed | 92.3 | rejected |
| number swapped (120 → 30 days) | 86.3 | rejected |
| fabricated clause appended to a real one | 80.5 | rejected |
| invented clause | 57.5 | rejected |
| clause from a different contract | 48.2 | rejected |

All nine are pinned as tests in [`test_verify.py`](api/tests/test_verify.py). The spec was amended to
v1.1 to describe the new design.

**Why this matters more than the model:** the scan model is a config value I can change in one line.
This guard is the reason the product's central claim is *true*.

---

## The model-tier sweep

The scan runs on `gpt-5.6-sol` by default. Is that worth 30× what the cheapest model costs? The
decision rule was written down **before** the numbers existed, so it couldn't be rationalised
afterwards ([SPEC.md §8.1](SPEC.md)):

> Take the cheapest tier that holds **recall (critical+high) ≥ 0.80** and **precision ≥ 0.75**.

Run against a real filed **salesforce.com Master Subscription Agreement** (SEC EDGAR, EX-10.28 — the
filer was the *customer*, which is our reader's position exactly). Ten labelled findings, five true
negatives.

```
                        gpt-5.6-sol   gpt-5.6-terra    gpt-5.6-luna    gpt-5.4-mini    gpt-5.4-nano
────────────────────────────────────────────────────────────────────────────────────────────────────
recall (critical+high)         1.00            1.00            0.80            0.80            1.00
recall (all)                   1.00            1.00            0.80            0.70            0.80
precision                      1.00            1.00            1.00            0.88            0.89
quote verification             1.00            1.00            1.00            1.00            0.91
anchor accuracy                0.90            0.80            0.88            0.71            0.75

cost per document            $0.332          $0.173          $0.061          $0.035          $0.018
seconds per document           111s             45s             34s             31s             38s

GATE                           PASS            PASS            PASS            PASS            PASS
```

Read literally: **choose `nano`, 18× cheaper than `sol`.**

**I am not doing that, and the reason is the most useful thing in this repository.**

### The sweep is not reproducible, and that is the result

I ran it twice. Same contract. Same answer key. Nothing changed but the dice.

| | run 1 | run 2 |
|---|---|---|
| `terra` recall (all) | 0.90 | **1.00** |
| `luna` recall (critical+high) | 1.00 | **0.80** |
| `mini` gate | **fail** | **PASS** |
| **what the decision rule recommended** | **`nano`** | **`mini`** |

**The recommendation flipped between two runs of the same experiment.** The run-to-run variance is as
large as the difference between the models.

That is not a disappointment — it is the finding. It means one contract with ten labelled findings
**cannot distinguish these tiers**, and any conclusion drawn from this table is noise wearing the
costume of data. SPEC.md §8 assumed ten contracts and ~70 findings, and this is why.

There's a tell in the numbers that says the same thing more cheaply: in run 1, `nano` — the weakest,
cheapest model in the lineup — *outscored* `mini`, which sits above it. Nothing about how these models
work would produce that ordering.

So the honest conclusion is **not** "nano wins." It's:

> On this document, all five tiers are within noise of each other. The cheap tiers are *plausibly*
> competitive — which is genuinely worth knowing, and would save 18× if it holds — but the corpus is
> too small to license a decision.

`sol` stays until the corpus is big enough to say otherwise. The harness now prints
`DO NOT ACT ON THIS TABLE YET` below any run with fewer than five documents, because a number that
looks rigorous is more dangerous than no number at all.

### And a bug in the harness itself

On one run, `nano` reported `0.00` across every metric and `$0.000` in cost — and the table showed it
failing the gate. It hadn't performed badly. It had **crashed** on a transient API error, and my
`except` block had swallowed it and scored the wreckage as zeros. Run alone, it worked fine.

An eval harness that reports infrastructure failure as model failure is worse than no harness,
because you will believe it. Crashed tiers now print `ERROR` and are never given a score.

### The finding the eval actually produced

Every single model, at every tier, fired `payment_terms` — and my answer key said it shouldn't.

```
gpt-5.6-sol     invented   payment_terms
gpt-5.6-terra   invented   payment_terms
gpt-5.6-luna    invented   payment_terms
gpt-5.4-mini    invented   payment_terms
gpt-5.4-nano    invented   payment_terms
```

When five independent models unanimously disagree with the answer key, the likeliest explanation is
that **the answer key is wrong.** And it was. I'd marked it a true negative because the late-payment
interest (1%/month) and the 60-day dispute window are both fine. But the contract also makes fees
annual, in advance, *noncancelable*, *nonrefundable*, and payable for licenses "whether or not
actively used." Every model read that and said: these payment terms are stacked against the customer.
They're right. My rule's detection guidance simply doesn't enumerate that case.

The fix is **not** to flip the label to agree with the models — that's changing the exam to match the
student. The fix is to sharpen the rule, re-label, and re-run. Until then the rule is marked `unsure`
and excluded from the metrics.

That bug was in my work, not the model's, and the harness is what surfaced it.

---

## Architecture

```
   PDF ──► parse (PyMuPDF)                  full text + per-page character offsets
            │                               ── the offsets are load-bearing: quote verification
            │                                  turns a span into a page number, and the highlight
            │                                  overlay paints it
            ▼
        agent loop  ────────────────────►  OpenAI Responses API
            │  4 rule-family passes             one warm pass, then three in parallel
            │  5 strict tools                   (see "prompt caching" below)
            │  25-turn ceiling
            ▼
        record_finding(quoted_text=…)
            │
            ├──►  QUOTE VERIFICATION  ──► rejected ──► discarded, agent told, never rendered
            │                          └─ verified ──► char span → page number
            ▼
        Postgres (Neon + pgvector)      documents · pages · findings · absences · key_terms
                                        agent_events · jobs · usage_ledger · eval_runs
```

### Decisions worth defending

**The risk scan reads the whole document. It does not use RAG.**
A contract is 15k–50k tokens; the context window is hundreds of thousands. Chunking would *lose*
information, because contract risk lives in the interaction between distant clauses — a liability cap
in §9 gutted by a carve-out in §14. On the first real run the agent caught exactly that, five pages
apart, on a synthetic MSA written to plant it. Retrieval ships in V2 for the Q&A tab, where questions
are narrow and users ask many. **Building RAG and then deliberately not using it for the marquee
feature is the point.**

**A hand-rolled tool-use loop, not LangGraph.**
[`loop.py`](api/clause/agent/loop.py) is a `for` loop over a message list. When an analysis wedges at
turn nineteen you want to read that, not reason about how a graph checkpointer serialised its state.
LangGraph earns its place with durable mid-run resume and human-in-the-loop interrupts; this system
has neither.

**One database, no vector store.**
Postgres does semantic search (`pgvector`), keyword search (`tsvector`), relational integrity, and the
job queue (`SELECT … FOR UPDATE SKIP LOCKED`). A separate vector DB would add an operational surface,
a synchronisation problem, and zero capability at this scale.

**Local embeddings — and cost is not the reason.**
Embedding a 30-page contract costs a fraction of a cent anywhere. It's local because retrieval only
powers Q&A, which makes embedding quality a *low-stakes* decision — and low-stakes decisions should
be resolved in favour of fewer dependencies. `fastembed` runs `bge-small-en-v1.5` through ONNX
(~150 MB) instead of PyTorch (~2 GB).

### Prompt caching, and the thing that made it faster *and* cheaper

The four rule-family passes share a byte-identical prefix — frozen system prompt, tools sorted by
name, document text — and vary only in the trailing instruction. OpenAI caches the longest
previously-seen prefix at ~90% off.

The four passes are independent, so running them in sequence wastes wall clock for nothing. But
firing all four at once makes **all four miss the cache**, because the cache is a prefix match against
a prefix the API has *already seen* — and none of them has finished writing it yet.

So: run one pass to warm the prefix, then fan out the other three.

| | serial | warm-then-fan-out |
|---|---|---|
| wall clock | 237s | **137s** |
| cost | $0.412 | **$0.319** |
| cache hit rate | 63% | **88%** |

Cheaper *and* faster. [`prompts.py`](api/clause/agent/prompts.py) opens with a warning that any
f-string, timestamp, or conditional branch in it silently costs the entire caching benefit and
produces no error.

---

## Running it

```bash
# 1. Postgres. Neon's free tier works; so does the local compose file.
echo "DATABASE_URL=postgresql://…" >> .env
echo "OPENAI_API_KEY=sk-…"        >> .env

# 2. Analyse a contract. Prints verified findings with page numbers.
cd api && uv sync --extra dev
uv run python -m clause.analyse ../demo/contracts/saas_msa.pdf

# 3. The eval harness — offline, against the frozen corpus in evals/
uv run python -m clause.evals.run --sweep

# 4. Tests. 21 of them; the ones that matter are in test_verify.py
uv run pytest
```

---

## What is and isn't built

| | |
|---|---|
| ✅ | Ingest: PDF → text + per-page character offsets, sha256 dedupe, scanned-PDF rejection |
| ✅ | The agent: hand-rolled loop, 5 strict tools, 4 rule-family passes, prompt caching |
| ✅ | **Quote verification** — the hallucination guard, with an adversarial test suite |
| ✅ | The 15-rule library, as versioned YAML, hashed into every analysis |
| ✅ | Eval harness + model-tier sweep, with the decision rule stated in advance |
| ✅ | Full schema on Neon: pgvector, HNSW index, job queue, usage ledger |
| ✅ | Demo mode — both contracts pre-analysed, real traces, **$0.00 per view** |
| ✅ | Spend caps: two-pool budget, per-IP and per-session limits, hard ceiling |
| ✅ | Deployable: one container, Gradio + Neon, **$0 infrastructure**. Not currently hosted — free-tier quota, not a defect. |
| 🟡 | UI — interim **Gradio** app, runs locally. The Next.js frontend in SPEC.md §9 is not built. |
| ⬜ | Job queue worker, `agent_events`, SSE streaming trace (the trace currently replays, not streams) |
| ⬜ | Memo generation, Q&A tab, retrieval, span-precise PDF highlighting |

### The two-pool spend cap

A public URL with an upload box and a real API key behind it is an invitation. The obvious defence is
one global ceiling — and it fails in a specific, avoidable way: a bot drains the budget on Tuesday,
and on Thursday you open your own project in an interview and it says *uploads disabled*. The cap
protects the money by sabotaging the only reason the money was being spent.

So the budget is split. Anonymous visitors draw from a small pool ($2/month, one upload per session,
three per IP per day). Anyone with an access code draws from a reserve strangers cannot reach. A bot
can empty the first; it cannot touch the second. Both sit under a hard $5 ceiling.

Demo mode is unaffected by any of it, because it costs nothing at all.

**The public demo runs on `gpt-5.4-mini`, and that is a budget decision, not an eval one.** The sweep
above explicitly cannot tell us mini is as good as sol. But at sol's $0.33 an analysis, a $5 ceiling
buys *fifteen uploads* — which is not a demo. On mini it buys about a hundred and forty. `sol`
remains the default for the real product. Saying which kind of decision this is seemed more useful
than quietly picking the cheap one and letting the sweep table imply it was evidence-based.

---

## Honest caveats

Read these before quoting any number above.

**The eval corpus is one contract.** Ten labelled findings. Two consecutive runs of the sweep
disagreed about which model to choose — the error bars are wider than the gaps between tiers. This is
demonstrated above, not merely suspected, and it is why the sweep's literal recommendation is being
ignored. Two more contracts are downloaded and awaiting labels.

**The answer key was written by Claude, not by a human.** Claude also wrote the agent being graded
against it. The specific bias: a clause Claude is bad at spotting is also missing from the key, so it
never counts as a miss, and **recall comes out higher than it should**. Treat the absolute recall
figures as an upper bound.

What *survives* that bias is the tier **comparison** — every tier is graded against the same key, so
whatever error it carries is roughly constant across all five columns. The absolute numbers are soft;
the relative ones are sound.

**The demo contracts in `demo/` are synthetic**, written for this project and seeded with realistic
adverse clauses. They are not real contracts and are not scraped from anywhere. The *eval* corpus in
`evals/corpus/` is real, and comes from SEC EDGAR with provenance recorded next to each file.

**Clause is not a lawyer.** It is an automated analysis tool. Its output is a starting point for
review by qualified counsel, not a substitute for it.

---

## Repository

```
api/clause/
  agent/
    loop.py      the hand-rolled tool-use loop
    tools.py     5 tools, strict schemas, sorted (the sort is a caching requirement)
    prompts.py   the frozen system prompt — read the warning at the top
    verify.py    ★ the hallucination guard
  ingest/        parse, offsets, storage
  evals/
    run.py       the scorecard and the tier sweep
    label.py     answer-key tooling — `new` and `check`
  models.py      every model ID and price, in one place, pinned from the live API
  text.py        normalisation + the offset map back to the original document
rules/v1.yaml    the 15 rules. data, not code.
evals/
  corpus/        real contracts from SEC EDGAR, with provenance
  labels/        the answer keys
demo/            synthetic contracts, clearly marked as such
SPEC.md          the specification. v1.1 — §4.5 amended after the guard was found to have a hole.
ROADMAP.md       V1 / V2 / V3, and how the free-tier infrastructure fits together
```
