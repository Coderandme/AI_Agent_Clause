# Deploying to Hugging Face Spaces

The whole application — Gradio UI, agent, ingest — is one Python container. Postgres is Neon. There
is nothing else to deploy.

**Total infrastructure cost: $0.** The only thing that costs money is OpenAI tokens, and the demo
path never touches them.

---

## 1. Create the Space

At **huggingface.co/new-space**:

| Field | Value |
|---|---|
| Owner | your account |
| Space name | `clause` |
| License | MIT |
| SDK | **Docker** → *Blank* |
| Hardware | **CPU basic — free** |
| Visibility | Public |

## 2. Set the secrets

Space → **Settings** → **Variables and secrets** → *New secret*, for each of:

| Secret | Value | Why |
|---|---|---|
| `OPENAI_API_KEY` | `sk-…` | the only thing that costs money |
| `DATABASE_URL` | your Neon URI | the usage ledger lives here |
| `ACCESS_CODE` | anything you like | unlocks full uploads from the reserved budget |
| `IP_HASH_SECRET` | any long random string | IPs are stored only as `HMAC(ip, secret)` |

**Secrets, not Variables.** A Variable is visible to anyone who opens the Space.

## 3. Push

```bash
git remote add space https://huggingface.co/spaces/<you>/clause
git push space main
```

The Space builds the [Dockerfile](Dockerfile) and boots. First build takes a few minutes.

> **One manual step:** Hugging Face reads configuration from YAML frontmatter at the top of
> `README.md`. Adding it here would put a stray config block on the GitHub landing page, so it is
> deliberately absent. Either add these four lines to the README **on the Space only**, or set the
> same values in the Space's Settings UI:
>
> ```yaml
> ---
> title: Clause
> sdk: docker
> app_port: 7860
> ---
> ```

---

## What it costs, and what stops it costing more

The Space is free and does not sleep until ~48 hours idle. Neon's free tier is idle most of the
time, because nothing polls it.

**OpenAI is the only bill**, and three things stand between a stranger and it — see
[`api/clause/guard.py`](api/clause/guard.py):

**Demo mode is the default and costs nothing.** Both sample contracts are pre-analysed and replay
from disk, traces and all. Most visitors will never upload anything and will still watch the agent
work. Zero API calls.

**The budget is split in two.** A single global ceiling protects your wallet by breaking the demo at
exactly the wrong moment — a bot drains it on Tuesday, and on Thursday you open your own project in
an interview and it says *uploads disabled*. So:

| pool | ceiling | who |
|---|---|---|
| `anonymous` | $2/month | anyone. one upload per session, three per IP per day. |
| `reserved` | the rest | anyone with the access code. strangers cannot touch it. |
| **hard ceiling** | **$5/month** | nothing crosses this, code or not. |

A bot can empty the anonymous pool. It cannot reach the reserve, so your demo still works on the day
it matters.

**The public demo runs on `gpt-5.4-mini`, not `gpt-5.6-sol`** — and that is a *budget* decision, not
an eval one. The tier sweep cannot yet tell us mini is as good (see the README: two runs of it
disagreed about the winner). But at sol's $0.33 per analysis, a $5 ceiling buys **fifteen uploads**,
which is not a demo. On mini it buys about **a hundred and forty**. `sol` remains the default for the
real product.

Change any of it in [`api/clause/config.py`](api/clause/config.py).

---

## Re-baking the demo

The pre-computed analyses are the output of a specific prompt, rule library, and model. Change any of
those and the demo is showing you a system that no longer exists:

```bash
cd api && uv run python -m clause.demo
```

Costs about $0.80 (two contracts on `sol`) and then the demo is free forever again.
