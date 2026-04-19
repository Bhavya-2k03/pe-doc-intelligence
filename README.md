# truefee

A system that reads the paperwork behind a private-equity fund (side letters, amendments, MFN forms, capital account statements) and independently verifies the GP's management-fee calculation against what those documents actually say.

Live demo: **[truefee.io](https://truefee.io)**

---

## What this solves

Limited partners in PE funds routinely overpay management fees. The reason isn't sloppy GPs; it's that the rules governing those fees live in a 200-page LPA, half a dozen amendments, and per-LP side letters, and those documents interact in ways that are brutal to track by hand. A fee waiver from 2025 that "expires at the end of the Investment Period" silently extends when a 2028 amendment pushes the Investment Period out by 18 months, and a team reading source documents in sequence has to catch that dependency.

This isn't a niche problem:

- The SEC fined Blackstone, KKR, and Apollo a combined ~$120M for fee-allocation issues in 2015–2016.
- CalPERS admitted publicly in 2015 it couldn't calculate the carried interest it had paid across its PE portfolio without external reconstruction.
- Begenau & Siriwardane (HBS Working Paper, 2022) documented tens of basis points of fee dispersion between LPs in the same fund.

Large LPs (BlackRock, GIC, CPPIB) run shadow-accounting teams for exactly this. Smaller ones trust the GP and lose money quietly.

## The non-obvious bit

Most of this system is straightforward: parse the documents, pull out fee-relevant clauses, apply them in order, compute the fee. The part worth writing a README section for is the cross-clause stability loop.

A clause can reference fund fields that another clause changes. For example:

> **Clause A** (side letter, 2024): the management fee rate is capped at 1.25% after the end of the Investment Period.
>
> **Clause B** (amendment, 2028): the Investment Period end date is extended by 18 months.

Executing A first and B second gives you a different answer than running both to a fixed point. The cap's active-from date is a `field_ref` to `fund_investment_end_date`, which changes when B executes. After one pass, the engine re-evaluates every date condition that references a mutated field, rebuilds the timeline, and loops until nothing moves. Usually converges in one or two passes.

Most implementations of this flavor of problem skip the dependency or hardcode a specific ordering. Here every clause becomes a typed AST (`SET`, `ADJUST`, `CONSTRAIN`, `GATE`, `NO_ACTION`, `MANUAL_REVIEW`) and the engine handles convergence explicitly.

## How it works

Five layers, each with one job:

1. **Extract** — LlamaParse reads signed PDFs; an LLM pulls structured clauses, fields, and document intent from each source.
2. **Interpret** — every clause becomes a typed AST against a field registry (`management_fee_rate`, `fund_investment_end_date`, etc.).
3. **Resolve dates** — ambiguous and conditional effective dates ("the earlier of the 2nd anniversary of final closing or 50% fund realization") are resolved against current timelines.
4. **Confirm** — multi-document flows (GP disclosure → LP election → GP confirmation) are matched by intent type and reference date. Unconfirmed clauses don't execute.
5. **Execute** — clauses run in document order to build per-field timelines; stability loop resolves cross-clause dependencies.

A fee calculator then splits the billing period at every rate or basis transition, resolves the basis amount (committed, invested, unfunded — with LP pro-rata fallback), and returns a sub-period breakdown with source-clause references.

## Stack

- FastAPI (Python) on the backend
- React + Vite + Tailwind on the frontend (dark Bloomberg theme)
- Supabase Postgres for seed emails and attachment blobs
- LlamaParse for PDF parsing
- OpenAI GPT-5.2 for clause extraction and interpretation
- Server-Sent Events for real-time pipeline progress streaming

## Run locally

You'll need three API keys: OpenAI, LlamaParse, and a Postgres connection string. I use Supabase. Use their transaction-mode pooler URL on port 6543; the direct URL on 5432 has connection-limit issues under any real load.

```bash
# backend
cd backend
pip install -r requirements.txt
cp .env.example .env          # fill in the three keys
uvicorn main:app --reload     # :8000

# frontend
cd frontend
npm install
npm run dev                   # :5173
```

The backend refuses to start if any required env var is missing. Deliberate, to prevent silent misconfiguration in production.

Want full pipeline traces on every evaluate? Set `DEBUG_TRACE=1` in `.env` and check `backend/debug_output/evaluate_trace.txt` after each run.

## Scope

**V1 (what's live):**

- Side-letter overrides on any fee term (rate, basis, caps, floors, step-downs)
- MFN election chains with GP confirmation
- Amendments to investment period, fund term, other dates
- Bounded fee waivers
- Cross-clause dependencies via stability loop
- Compound date conditions (earlier-of, later-of, Boolean combinations over anniversaries, fiscal-quarter anchors, and fund metrics)
- Billing-period splitting at rate / basis transitions
- LP admission proration and catch-up fees for late-closers
- Ambiguous or unsupported clauses flagged for manual review, not silently ignored
- GP-claimed fee cross-checked against the calculated fee with a discrepancy delta

**V2 (deferred because they require data beyond the document inbox):**

- Transaction / monitoring fee offsets (needs portfolio-company fee ledger)
- Carried interest, waterfall, clawback (needs NAV + distribution ledger)
- Equalization at subsequent closings
- NAV-adjusted invested-capital basis on write-downs
- Recallable distribution tracking
- Successor-fund step-down triggers (external event signal)
- Organizational, placement, and wind-down fees
- Cross-fund side letter inheritance

## Layout

```
backend/
  main.py           FastAPI app (3 endpoints)
  prompts.py        LLM prompts
  constants.py      field registry
  engine/           pipeline, extractor, clause interpreter, timeline engine, fee calculator
  scripts/          dev-only: migrate, push packages, demo
  tests/            256+ unit tests
frontend/
  src/components/   inbox, evaluation, timeline, shared
  src/pages/        Landing, Demo
  vercel.json       SPA rewrite so /demo reloads don't 404
```

## Deployment

Frontend on Vercel, backend on Render.

Render's free tier has a 15-minute idle sleep that adds ~30 seconds to the first request after idle; Starter ($7/mo) removes that.

Cloudflare proxy (orange cloud) on the backend subdomain will buffer SSE responses and break the evaluate endpoint. Keep the `api.*` record DNS-only (gray cloud).

## Tests

```bash
cd backend && pytest
```

256 passing, 11 skipped. The skipped cases exercise a legacy graceful-None pattern in the AST evaluator that was removed in favor of raising `MissingFieldValueError` — raising surfaces cleaner user-facing error messages from the UI when a clause references a field that no email has reported yet.

---

Built by [Bhavya Gupta](https://github.com/Bhavya-2k03). Feedback or questions: open an issue, or reach me on LinkedIn.
