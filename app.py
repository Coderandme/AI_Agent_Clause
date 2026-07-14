"""Clause — Gradio demo. Deployed to Hugging Face Spaces.

    python app.py

THIS IS AN INTERIM UI, AND THE README SAYS SO.
──────────────────────────────────────────────
SPEC.md §9.1 specifies a dense, professional Next.js frontend, and is pointed about why: "A contract
review tool that looks like every AI landing page reads as a toy." Gradio has a look, and it is the
ML-demo look. It works against the client-facing job this product is supposed to do.

But it ships today, in Python, in the same container as everything else — no separate frontend build,
no CORS, one deploy. For an engineering audience it is fine, and honestly stated a work-in-progress
costs nothing. The Next.js frontend remains the plan.

THE COST DESIGN (SPEC.md §7, clause/guard.py)
─────────────────────────────────────────────
This is a public URL with an upload box and a real API key behind it. Three things stand between a
stranger and the author's bank account:

  1. DEMO MODE IS THE DEFAULT and costs exactly nothing. Both sample contracts are pre-analysed,
     traces and all, and replay from disk. Most visitors will never upload anything and will still
     watch the agent work.
  2. THE BUDGET IS SPLIT IN TWO. Anonymous visitors draw from a small pool. Anyone with an access
     code draws from a reserve that strangers cannot touch — so a bot draining the public budget on
     Tuesday cannot break the author's own demo in an interview on Thursday.
  3. A HARD CEILING nothing crosses.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import gradio as gr

sys.path.insert(0, str(Path(__file__).parent / "api"))

from clause import guard, models, rules  # noqa: E402
from clause.agent import loop  # noqa: E402
from clause.agent.execute import AnalysisState, ToolExecutor  # noqa: E402
from clause.agent.verify import DocumentIndex  # noqa: E402
from clause.config import REPO_ROOT, settings  # noqa: E402
from clause.db import pool  # noqa: E402
from clause.ingest import parse  # noqa: E402

PRECOMPUTED = REPO_ROOT / "demo" / "precomputed"

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEVERITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}

DISCLAIMER = (
    "**Clause is an automated analysis tool. It is not a lawyer and does not provide legal "
    "advice.** Its output is a starting point for review by qualified counsel, not a substitute "
    "for it."
)


def load_demo(slug: str) -> dict[str, Any]:
    return json.loads((PRECOMPUTED / f"{slug}.json").read_text(encoding="utf-8"))


DEMOS = {p.stem: load_demo(p.stem) for p in PRECOMPUTED.glob("*.json")}


# ── rendering ────────────────────────────────────────────────────────────────────────────────────


def render_findings(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "_No findings._"

    ranked = sorted(
        findings, key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["rule_id"])
    )
    out = []
    for f in ranked:
        icon = SEVERITY_ICON.get(f["severity"], "⚪")
        quote = " ".join((f.get("matched_text") or f["quoted_text"]).split())
        out.append(
            f"### {icon} {f['severity'].upper()} — {f['title']}\n\n"
            f"{f['exposure']}\n\n"
            f"> {quote}\n\n"
            f"<sub>**page {f['page_number']}** · `{f['rule_id']}` · confidence "
            f"{f['confidence']} · ✅ quote verified against the source</sub>\n\n"
            f"**Ask for:** {f['recommendation']}\n\n---\n"
        )
    return "\n".join(out)


def render_absences(absences: list[dict[str, Any]]) -> str:
    """SPEC.md §9.2: 'this is what separates a tool that looks thorough from one that is.'"""
    if not absences:
        return ""
    rows = "\n".join(
        f"- **{a['rule_id']}** — {a['rationale']}"
        for a in sorted(absences, key=lambda a: a["rule_id"])
    )
    return f"\n## Checked and not found\n\n{rows}\n"


def render_key_terms(terms: dict[str, Any] | None) -> str:
    if not terms:
        return "_Not extracted._"
    rows = ["| Term | Value |", "|---|---|"]
    for key, value in terms.items():
        if isinstance(value, list):
            value = ", ".join(value) if value else None
        # A null is MEANINGFUL, not a failure. No liability cap IS the finding.
        shown = value if value else "_Not specified_"
        rows.append(f"| **{key.replace('_', ' ').title()}** | {shown} |")
    return "\n".join(rows)


def render_trace(trace: list[dict[str, Any]]) -> str:
    """The agent trace. Not a debug panel — a feature (SPEC.md §2.3). It is the difference between
    'the AI did something' and 'I watched it work'."""
    lines = []
    for e in trace:
        if e["kind"] == "tool_call":
            arg = e.get("input", {}).get("rule_id") or ""
            lines.append(f"`{e['at']:>6.1f}s`  → **{e['name']}**(`{arg}`)")
        elif e["kind"] == "tool_result" and e["name"] == "record_finding":
            out = e.get("output", {})
            if out.get("verified"):
                lines.append(f"`      `      ✅ quote verified — page {out['page']}")
            else:
                lines.append("`      `      ❌ **quote rejected — finding discarded**")
    return "\n\n".join(lines) if lines else "_No trace._"


def render_stats(data: dict[str, Any]) -> str:
    u = data["usage"]
    total = len(data["findings"]) + data.get("unverified_count", 0)
    cached = (
        100 * u["cached_input_tokens"] / u["input_tokens"]
        if u.get("input_tokens")
        else 0
    )
    return (
        f"**{len(data['findings'])} findings** · "
        f"quote verification **{len(data['findings'])}/{total}** · "
        f"{data['scan_model']} · "
        f"${u['cost_microdollars'] / 1e6:.3f} · "
        f"{data['seconds']}s · "
        f"{cached:.0f}% of input tokens served from cache"
    )


def show_demo(slug: str) -> tuple[str, str, str, str, str]:
    data = DEMOS[slug]
    return (
        f"### {data['filename']} — {data['page_count']} pages\n\n"
        f"_{data['blurb']}_\n\n"
        f"**Summary.** {data['summary']}\n\n"
        f"{render_stats(data)}\n\n"
        f"<sub>Pre-computed. This view costs $0.00 and makes no API calls — the trace below is the "
        f"real one, recorded when the agent actually ran.</sub>",
        render_findings(data["findings"]) + render_absences(data["absences"]),
        render_key_terms(data["key_terms"]),
        render_trace(data["trace"]),
        str(PRECOMPUTED / f"{slug}.pdf"),
    )


# ── live analysis ────────────────────────────────────────────────────────────────────────────────

PRIVATE_PREFIXES = ("10.", "127.", "172.16.", "172.17.", "192.168.", "::1", "fc", "fd")


def client_ip(request: gr.Request | None) -> str:
    """The visitor's IP, for the per-IP daily cap.

    Behind Hugging Face's proxy, `request.client.host` is the PROXY, not the visitor — so every
    visitor looks like the same person and the per-IP cap silently applies to all of them at once
    (or, worse, to none of them). The real address arrives in `X-Forwarded-For`.

    XFF is a comma-separated chain, appended to by each proxy it passes through:

        X-Forwarded-For: <client>, <proxy-1>, <proxy-2>

    We take the LAST entry that is not a private address, not the first. The first is the one a
    client can forge — anyone can send their own `X-Forwarded-For: 1.2.3.4` header and the proxies
    will simply append to it, so trusting the leftmost value means trusting the attacker. The
    rightmost public entry was written by infrastructure we do not control but do at least trust
    more than the caller.

    This is defence in depth, not a wall. XFF can still be gamed, and IP rotation is cheap. The cap
    that actually bounds the damage is the $2 anonymous spend pool in guard.py — this one just
    makes casual abuse annoying, and stops one visitor consuming the whole month in an afternoon.
    """
    if request is None:
        return "unknown"

    forwarded = request.headers.get("x-forwarded-for", "")
    candidates = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
    for ip in reversed(candidates):
        if not ip.lower().startswith(PRIVATE_PREFIXES):
            return ip

    if request.client and request.client.host:
        return request.client.host
    return "unknown"


async def analyse_upload(
    file: Any,
    access_code: str,
    state: dict[str, Any],
    request: gr.Request,
) -> tuple[str, str, str, str]:
    if file is None:
        return "Upload a PDF first.", "", "", ""

    s = settings()
    path = Path(file)

    # Size is checked BEFORE the bytes are read, not after. An uploaded PDF is untrusted input, and
    # `read_bytes()` on a 200 MB file would put 200 MB in this container's memory before any limit
    # had a chance to reject it — on a free tier, that is how the Space falls over.
    size = path.stat().st_size
    if size > s.max_upload_bytes:
        return (
            f"That file is {size / 1_048_576:.1f} MB. The limit is "
            f"{s.max_upload_bytes / 1_048_576:.0f} MB.",
            "",
            "",
            "",
        )

    data = path.read_bytes()

    p = await pool.pool()
    async with p.acquire() as conn:
        # Checked BEFORE the money is spent, never after — see guard.py.
        decision = await guard.may_analyse(
            conn,
            ip=client_ip(request),
            access_code=access_code,
            session_uploads=state.get("uploads", 0),
        )

    if not decision.allowed:
        return f"### Not analysed\n\n{decision.reason}", "", "", ""

    try:
        doc = parse.parse(data)
    except parse.UnparseablePDF as exc:
        return f"That file could not be read as a PDF: {exc}", "", "", ""

    if doc.is_scanned:
        return (
            "That PDF appears to be a **scan** — images of text rather than text itself, so there "
            "is nothing for us to read. Clause cannot analyse scanned documents yet.",
            "",
            "",
            "",
        )

    # Anonymous visitors get a tighter page limit than code holders. Pages are tokens and tokens are
    # money: a 40-page contract costs several times what a 15-page one does, and the anonymous pool
    # is small. Code holders — people the author actually invited — get the full limit.
    page_limit = s.max_pages if decision.pool == "reserved" else s.max_pages_anonymous
    if doc.page_count > page_limit:
        extra = (
            ""
            if decision.pool == "reserved"
            else " Enter an access code above for the full 40-page limit."
        )
        return (
            f"That document is {doc.page_count} pages. The limit is {page_limit}.{extra}",
            "",
            "",
            "",
        )

    index = DocumentIndex(
        doc.full_text,
        [(pg.page_number, pg.char_start, pg.char_end) for pg in doc.pages],
    )
    agent_state = AnalysisState()
    execute = ToolExecutor(index, agent_state)

    # The public demo runs on the CHEAP tier, and this is a BUDGET decision, not an eval one. The
    # tier sweep cannot yet tell us mini is as good as sol (see README) — but at sol's $0.33 an
    # analysis, a $5 monthly ceiling buys fifteen uploads, which is not a demo. On mini it buys
    # about a hundred and forty.
    spec = models.MINI

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings().openai_api_key)
    trace: list[dict[str, Any]] = []
    started = time.monotonic()

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        trace.append(
            {"at": round(time.monotonic() - started, 2), "kind": kind, **payload}
        )

    async def run(family: rules.Family) -> loop.PassResult:
        return await loop.run_pass(
            client,
            family=family,
            document_text=doc.full_text,
            execute_tool=execute,
            emit=emit,
            model=spec,
        )

    families = list(rules.Family)
    first = await run(families[0])
    rest = await asyncio.gather(*(run(f) for f in families[1:]))

    usage = loop.Usage()
    for r in [first, *rest]:
        usage.input_tokens += r.usage.input_tokens
        usage.cached_input_tokens += r.usage.cached_input_tokens
        usage.output_tokens += r.usage.output_tokens

    cost = usage.cost_microdollars(spec)
    elapsed = time.monotonic() - started

    async with p.acquire() as conn:
        await guard.record_spend(
            conn, ip="gradio", pool=decision.pool, cost_microdollars=cost
        )

    state["uploads"] = state.get("uploads", 0) + 1

    total = len(agent_state.findings)
    verified = len(agent_state.verified_findings)

    header = (
        f"### {Path(file).name} — {doc.page_count} pages\n\n"
        f"**Summary.** {first.summary}\n\n"
        f"**{verified} findings** · quote verification **{verified}/{total}** · {spec.id} · "
        f"${cost / 1e6:.3f} · {elapsed:.0f}s\n\n"
        f"<sub>Your file is not stored. Nothing was written to disk.</sub>"
    )

    from dataclasses import asdict

    return (
        header,
        render_findings([asdict(f) for f in agent_state.verified_findings])
        + render_absences([asdict(a) for a in agent_state.absences]),
        render_key_terms(agent_state.key_terms),
        render_trace(trace),
    )


# ── the page ─────────────────────────────────────────────────────────────────────────────────────

CSS = """
.gradio-container { max-width: 1200px !important; }
footer { display: none !important; }
"""

with gr.Blocks(title="Clause — contract intelligence") as app:
    session = gr.State({})

    gr.Markdown(
        "# Clause\n"
        "### An agent reads your contract, flags the risks, and **proves every quotation it shows "
        "you exists in the document.**\n\n"
        "Not a chatbot. It works through a library of 15 risk rules on its own — loading a rule, "
        "checking a clause, recording a finding — and every quote is verified against the source "
        "before it is allowed to reach you. A quotation the agent invents is structurally unable "
        "to be displayed.\n\n"
        f"> {DISCLAIMER}"
    )

    with gr.Tab("Sample contracts  ·  free, instant"):
        gr.Markdown(
            "Pre-analysed. **Zero API calls, zero cost, no waiting** — but the trace below is the "
            "real one, recorded while the agent actually worked."
        )
        demo_pick = gr.Radio(
            choices=[
                (f"{DEMOS[s]['filename']}  ·  {len(DEMOS[s]['findings'])} findings", s)
                for s in DEMOS
            ],
            value=next(iter(DEMOS), None),
            label="Contract",
        )
        demo_header = gr.Markdown()
        with gr.Row():
            with gr.Column(scale=3):
                demo_findings = gr.Markdown()
            with gr.Column(scale=2):
                with gr.Tab("Key terms"):
                    demo_terms = gr.Markdown()
                with gr.Tab("Agent trace"):
                    gr.Markdown(
                        "_What the agent actually did, in order. This is not a log — it is the "
                        "product._"
                    )
                    demo_trace = gr.Markdown()
                with gr.Tab("The contract"):
                    demo_pdf = gr.File(label="Source PDF")

        demo_pick.change(
            show_demo,
            inputs=demo_pick,
            outputs=[demo_header, demo_findings, demo_terms, demo_trace, demo_pdf],
        )
        app.load(
            show_demo,
            inputs=demo_pick,
            outputs=[demo_header, demo_findings, demo_terms, demo_trace, demo_pdf],
        )

    with gr.Tab("Analyse your own"):
        gr.Markdown(
            "**Your file is never stored.** It is parsed in memory and discarded when the request "
            "ends — nothing is written to disk, and nothing reaches the database but a cost "
            "figure.\n\n"
            "Every analysis costs the author real money, and a public URL attracts bots. So:\n\n"
            "| | anonymous | with an access code |\n"
            "|---|---|---|\n"
            "| analyses | 1 per session · 3 per day per IP | unlimited |\n"
            "| page limit | 15 | 40 |\n"
            "| budget | a small shared pool | a separate reserve strangers cannot drain |\n\n"
            "The **sample contracts** on the other tab are unlimited and free — pre-computed, with "
            "no API calls at all."
        )
        with gr.Row():
            upload = gr.File(label="Contract (PDF, max 10 MB)", file_types=[".pdf"])
            code = gr.Textbox(
                label="Access code (optional)",
                placeholder="leave blank for the anonymous allowance",
                type="password",
            )
        go = gr.Button("Analyse", variant="primary")
        gr.Markdown(
            "_Takes about 30–60 seconds. The agent reads the whole contract first._"
        )

        live_header = gr.Markdown()
        with gr.Row():
            with gr.Column(scale=3):
                live_findings = gr.Markdown()
            with gr.Column(scale=2):
                with gr.Tab("Key terms"):
                    live_terms = gr.Markdown()
                with gr.Tab("Agent trace"):
                    live_trace = gr.Markdown()

        go.click(
            analyse_upload,
            inputs=[upload, code, session],
            outputs=[live_header, live_findings, live_terms, live_trace],
        )

    with gr.Tab("How it works"):
        gr.Markdown((REPO_ROOT / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    # Gradio 6 takes theme and css at launch, not on Blocks.
    app.launch(server_name="0.0.0.0", server_port=7860, css=CSS, theme=gr.themes.Base())
