"""
Battle-test harness for the extraction layer (Layer 1).

A graded golden set: each case is a real PDF + email metadata + assertions
about what the extraction LLM must (and must NOT) produce. Runs each case
N times (LLM output is stochastic) and reports per-case pass rates, so a
prompt change is measured against a baseline instead of eyeballed.

Cost controls:
  - Parsed markdown is disk-cached in scripts/_battle_cache/ keyed by file
    bytes hash — each PDF hits LlamaParse ONCE ever, across runs.
  - Extraction trials each get a fresh in-memory cache (the session cache
    would otherwise collapse N trials into a single LLM call).

Usage from backend/:
    python scripts/battle_test_extraction.py                 # all cases, 3 trials
    python scripts/battle_test_extraction.py --trials 5
    python scripts/battle_test_extraction.py --cases lp_     # substring filter

Assertion semantics per trial:
  required:   field -> expected value. Field must be present with this value.
  required_entries: list of (field, value, allowed_as_of_list). Each must be
              present as an entry whose value matches AND whose as_of matches
              one of allowed_as_of_list. Used for period-column tables where
              EVERY dated column must be extracted. Quarter columns list the
              verbatim label only (e.g. ["Q4 2029"]) — a model-translated
              calendar date is a FAILURE, since fiscal periods are
              fund-anchored and must be resolved by the engine, not guessed.
  forbidden:  list of (field, value) or (field, value, allowed_as_of_list).
              2-tuple: field must NOT carry this value at all (scope leaks).
              3-tuple: the value is allowed ONLY when its entry is dated to
              one of allowed_as_of_list — a prior-period figure is legitimate
              timeline data when correctly dated, and poison when undated or
              dated to the statement date (it would corrupt value_at lookups).
  optional:   field -> expected value. Reported, never fails the trial —
              EXCEPT if present with a different value (then it fails).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import argparse
import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone

from openai import AsyncOpenAI

from constants import emails_and_attachment_fields
from engine.extractor import extract_email
from engine.pdf_parser import parse_pdf

BACKEND = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
FILES = BACKEND / "files"
LOCAL_FILES = BACKEND / "local_packages" / "files"
CACHE_DIR = SCRIPTS / "_battle_cache"
RESULTS_DIR = SCRIPTS / "_battle_results"

# Marker for the parser config baked into cached markdown. Bump when the
# LlamaParse config in engine/pdf_parser.py changes, so stale cache entries
# are not reused against a different parser setup.
PARSE_CONFIG_TAG = "automode-v1"


# ═══════════════════════════════════════════════════════════════════════════
# Case definitions
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Case:
    name: str
    pdf: Path
    subject: str
    email_date: str
    required: dict[str, object]
    required_entries: list[tuple] = dc_field(default_factory=list)
    forbidden: list[tuple] = dc_field(default_factory=list)
    optional: dict[str, object] = dc_field(default_factory=dict)
    note: str = ""


CASES: list[Case] = [
    # ── Regression guards: currently-working extraction paths ──────────────
    Case(
        name="fund_realization_simple_table",
        pdf=FILES / "FUND_REALIZATION_Q3_2025.pdf",
        subject="Q3 2025 Fund Realization Report",
        email_date="2025-10-12",
        required={
            "fund_total_invested_capital": 19_500_000,
            "fund_total_realized_capital": 6_500_000,
            "fund_percentage_realized": 13,
        },
        note="Live demo doc. Simple 2-col table, fund scope. Must keep passing.",
    ),
    Case(
        name="realization_statement_prose",
        pdf=FILES / "Realization_Statementent.pdf",
        subject="Fund Realization Statement",
        email_date="2025-12-02",
        required={
            "fund_total_invested_capital": 10_000_000,
            "fund_total_realized_capital": 2_600_000,
            "fund_percentage_realized": 26,
        },
        note="Prose label-value doc, explicit Fund's attribution (Layer 1).",
    ),
    Case(
        name="subscription_facility_prose",
        pdf=FILES / "Subscription_Credit_Facility.pdf",
        subject="Subscription Credit Facility — Outstanding Balance",
        email_date="2025-11-30",
        required={
            "subscription_line_principal_amount": 4_800_000,
            "subscription_line_interest_amount": 96_000,
            "subscription_line_total_amount": 4_896_000,
            "subscription_line_repayment_due_date": "2026-10-05",
        },
        forbidden=[
            # dual-unit trap: the parenthetical cents figures must never win
            ("subscription_line_principal_amount", 480_000_000),
            ("subscription_line_interest_amount", 9_600_000),
            ("subscription_line_total_amount", 489_600_000),
        ],
        note="Prose + dual-unit (cents) trap + date field.",
    ),
    # ── The target: LP capital account statements ──────────────────────────
    Case(
        name="lp_statement_period_columns",
        pdf=SCRIPTS / "_test_LP_STATEMENT_PERIOD_COLUMNS.pdf",
        subject="Q3 2025 Capital Account Statement",
        email_date="2025-10-15",
        required={
            "investor_invested_capital": 6_850_000,
        },
        required_entries=[
            # every period column, quarter labels VERBATIM (engine resolves them)
            ("investor_invested_capital", 4_900_000, ["Q1 2025"]),
            ("investor_invested_capital", 6_050_000, ["Q2 2025"]),
            ("investor_invested_capital", 6_850_000, ["Q3 2025", "2025-09-30"]),
        ],
        forbidden=[
            # Prior-period columns: allowed ONLY as verbatim quarter labels.
            ("investor_invested_capital", 4_900_000, ["Q1 2025"]),
            ("investor_invested_capital", 6_050_000, ["Q2 2025"]),
            ("investor_total_realized_capital", 700_000, ["Q1 2025"]),
            ("investor_total_realized_capital", 1_150_000, ["Q2 2025"]),
            # Scope leaks: LP figures must not land in fund-scoped fields, ever
            ("fund_total_invested_capital", 6_850_000),
            ("total_fund_committed_capital", 10_000_000),
            ("fund_total_distributions", 1_780_000),
        ],
        optional={
            "investor_total_realized_capital": 1_780_000,
        },
        note="Fund letterhead + LP body + 3 period columns. THE failing shape.",
    ),
    Case(
        name="lp_statement_single_column",
        pdf=SCRIPTS / "_iso_A_single_column.pdf",
        subject="Q3 2025 Capital Account Statement",
        email_date="2025-10-15",
        required={
            "investor_invested_capital": 6_850_000,
        },
        forbidden=[
            ("fund_total_invested_capital", 6_850_000),
            ("total_fund_committed_capital", 10_000_000),
        ],
        optional={
            "investor_total_realized_capital": 1_780_000,
        },
        note="Isolation A: single column, competing scope kept. Measured ~100% at effort=none; leak-prone under subject-line prompt v1 (reverted).",
    ),
    Case(
        name="lp_statement_no_competing_scope",
        pdf=SCRIPTS / "_iso_B_no_competing_scope.pdf",
        subject="Q3 2025 Capital Account Statement",
        email_date="2025-10-15",
        required={
            "investor_invested_capital": 6_850_000,
        },
        required_entries=[
            ("investor_invested_capital", 4_900_000, ["Q1 2025"]),
            ("investor_invested_capital", 6_050_000, ["Q2 2025"]),
            ("investor_invested_capital", 6_850_000, ["Q3 2025", "2025-09-30"]),
        ],
        forbidden=[
            ("investor_invested_capital", 4_900_000, ["Q1 2025"]),
            ("investor_invested_capital", 6_050_000, ["Q2 2025"]),
        ],
        note="Isolation B (control): LP-only framing. Passes pre-fix.",
    ),
    # ── The actual demo documents (local_packages/files/) ──────────────────
    Case(
        name="demo_capital_stmt_dec2028",
        pdf=LOCAL_FILES / "LP_CAPITAL_ACCOUNT_STATEMENT_DEC2028.pdf",
        subject="Capital Account Statement - As of December 1, 2028",
        email_date="2028-12-01",
        required={
            "investor_invested_capital": 8_200_000,
        },
        required_entries=[
            ("investor_invested_capital", 7_400_000, ["Q3 2027"]),
            ("investor_invested_capital", 7_800_000, ["Q1 2028"]),
            ("investor_invested_capital", 8_200_000, ["Q3 2028"]),
            ("investor_total_realized_capital", 1_250_000, ["Q3 2027"]),
            ("investor_total_realized_capital", 1_400_000, ["Q1 2028"]),
            ("investor_total_realized_capital", 1_600_000, ["Q3 2028"]),
        ],
        forbidden=[
            ("investor_invested_capital", 7_400_000, ["Q3 2027"]),
            ("investor_invested_capital", 7_800_000, ["Q1 2028"]),
            ("fund_total_invested_capital", 8_200_000),
            # commitments are no longer extractable at all
            ("total_fund_committed_capital", 10_000_000),
            ("total_fund_committed_capital", 50_000_000),
            ("investor_commitment_amount", 10_000_000),
            # deferral-gate insulation: LP distributions must NEVER touch the
            # fund realization/distribution timelines the 50% condition reads
            ("fund_total_distributions", 1_250_000),
            ("fund_total_distributions", 1_400_000),
            ("fund_total_distributions", 1_600_000),
            ("fund_total_realized_capital", 1_600_000),
        ],
        note="Replaces e038 body (side_letter_flow). Final col = today's body value.",
    ),
    Case(
        name="demo_capital_stmt_jun2030",
        pdf=LOCAL_FILES / "LP_CAPITAL_ACCOUNT_STATEMENT_JUN2030.pdf",
        subject="Capital Account Statement - As of June 15, 2030",
        email_date="2030-06-15",
        required={
            "investor_invested_capital": 8_500_000,
        },
        required_entries=[
            ("investor_invested_capital", 8_100_000, ["Q1 2029"]),
            ("investor_invested_capital", 8_300_000, ["Q3 2029"]),
            ("investor_invested_capital", 8_500_000, ["Q1 2030"]),
            ("investor_total_realized_capital", 1_900_000, ["Q1 2029"]),
            ("investor_total_realized_capital", 2_050_000, ["Q3 2029"]),
            ("investor_total_realized_capital", 2_200_000, ["Q1 2030"]),
        ],
        forbidden=[
            ("investor_invested_capital", 8_100_000, ["Q1 2029"]),
            ("investor_invested_capital", 8_300_000, ["Q3 2029"]),
            ("fund_total_invested_capital", 8_500_000),
            ("total_fund_committed_capital", 10_000_000),
            ("fund_total_distributions", 1_900_000),
            ("fund_total_distributions", 2_050_000),
            ("fund_total_distributions", 2_200_000),
            ("fund_total_realized_capital", 2_200_000),
        ],
        note="Replaces e039 body (multi_amendment). Final col = today's body value.",
    ),
    Case(
        name="demo_capital_chart_dec2028",
        pdf=LOCAL_FILES / "LP_CAPITAL_ACCOUNT_CHART_DEC2028.pdf",
        subject="Capital Account Statement - As of December 1, 2028",
        email_date="2028-12-01",
        required={
            "investor_invested_capital": 8_200_000,
        },
        required_entries=[
            ("investor_invested_capital", 7_000_000, ["Q1 2027"]),
            ("investor_invested_capital", 7_400_000, ["Q3 2027"]),
            ("investor_invested_capital", 7_800_000, ["Q1 2028"]),
            ("investor_invested_capital", 8_200_000, ["Q3 2028"]),
        ],
        forbidden=[
            ("investor_invested_capital", 7_000_000, ["Q1 2027"]),
            ("investor_invested_capital", 7_400_000, ["Q3 2027"]),
            ("investor_invested_capital", 7_800_000, ["Q1 2028"]),
            ("fund_total_invested_capital", 8_200_000),
            ("total_fund_committed_capital", 10_000_000),
        ],
        note="Replaces e037 body (mfn_flow). Labeled bar CHART — parsed via vision.",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════
# Parsing with disk cache
# ═══════════════════════════════════════════════════════════════════════════

async def parse_cached(pdf: Path) -> list[str]:
    file_bytes = pdf.read_bytes()
    key = hashlib.sha256(file_bytes).hexdigest()[:24]
    cache_file = CACHE_DIR / f"{key}__{PARSE_CONFIG_TAG}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    pages = await parse_pdf(file_bytes, pdf.name)
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file.write_text(json.dumps(pages), encoding="utf-8")
    return pages


# ═══════════════════════════════════════════════════════════════════════════
# Trial execution + grading
# ═══════════════════════════════════════════════════════════════════════════

def _norm(v) -> object:
    """Normalize a value for comparison: numbers -> float, else stripped str."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return str(v).strip()


def _matches(got, want) -> bool:
    ng, nw = _norm(got), _norm(want)
    if isinstance(ng, float) and isinstance(nw, float):
        return ng == nw
    # date-ish: accept exact or substring (e.g. "2026-10-05T00:00:00")
    return ng == nw or (isinstance(ng, str) and isinstance(nw, str) and nw in ng)


async def run_trial(case: Case, pages: list[str], client: AsyncOpenAI) -> dict:
    email_data = {
        "_id": f"battle-{case.name}",
        "subject": case.subject,
        "body": "Please see the attached document.",
        "date": case.email_date,
        "attachments": [{"name": case.pdf.name, "attachment_index": 0}],
    }
    attachment_texts = [{
        "attachment_name": case.pdf.name,
        "attachment_index": 0,
        "attachment_text": pages,
    }]

    t0 = time.monotonic()
    try:
        result = await extract_email(
            email_data=email_data,
            attachment_texts=attachment_texts,
            field_registry=emails_and_attachment_fields,
            openai_client=client,
            extraction_cache={},  # fresh — never collapse trials
        )
    except Exception as exc:  # noqa: BLE001 — harness must survive LLM hiccups
        return {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}",
                "elapsed": time.monotonic() - t0}

    elapsed = time.monotonic() - t0
    got: dict[str, list[dict]] = {
        name: [
            {"value": e.value,
             "as_of": e.value_as_of_date or e.value_as_of_condition}
            for e in entries
        ]
        for name, entries in result.extracted_fields.items()
    }

    problems: list[str] = []
    for fname, want in case.required.items():
        entries = got.get(fname, [])
        if not entries:
            problems.append(f"MISSING required {fname} (want {want})")
        elif not any(_matches(e["value"], want) for e in entries):
            problems.append(f"WRONG {fname}: got {entries}, want {want}")

    for fname, want, allowed_as_of in case.required_entries:
        entries = got.get(fname, [])
        hit = any(
            _matches(e["value"], want)
            and e["as_of"] is not None
            and any(_matches(e["as_of"], d) for d in allowed_as_of)
            for e in entries
        )
        if not hit:
            got_summary = [(e["value"], e["as_of"]) for e in entries]
            problems.append(
                f"MISSING dated entry {fname}={want} @ {allowed_as_of} "
                f"(got {got_summary})")

    for rule in case.forbidden:
        fname, bad = rule[0], rule[1]
        allowed_as_of = rule[2] if len(rule) > 2 else None
        for e in got.get(fname, []):
            if not _matches(e["value"], bad):
                continue
            if allowed_as_of and e["as_of"] is not None and any(
                _matches(e["as_of"], d) for d in allowed_as_of
            ):
                continue  # correctly dated prior-period entry — legit timeline data
            detail = (f" (as_of={e['as_of']!r}, allowed {allowed_as_of})"
                      if allowed_as_of else "")
            problems.append(f"FORBIDDEN {fname}={bad} present{detail}")

    for fname, want in case.optional.items():
        entries = got.get(fname, [])
        if entries and not any(_matches(e["value"], want) for e in entries):
            problems.append(f"OPTIONAL-WRONG {fname}: got {entries}, want {want}")

    return {
        "status": "PASS" if not problems else "FAIL",
        "problems": problems,
        "extracted": got,
        "elapsed": elapsed,
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--cases", type=str, default="",
                    help="substring filter on case name")
    args = ap.parse_args()

    cases = [c for c in CASES if args.cases in c.name]
    if not cases:
        print(f"no cases match filter {args.cases!r}")
        sys.exit(1)

    missing = [c for c in cases if not c.pdf.exists()]
    if missing:
        for c in missing:
            print(f"[skip] {c.name}: {c.pdf} not found")
        cases = [c for c in cases if c.pdf.exists()]

    # Parse all PDFs first (disk-cached — LlamaParse hit once per file, ever)
    parsed: dict[str, list[str]] = {}
    for c in cases:
        parsed[c.name] = await parse_cached(c.pdf)

    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    sem = asyncio.Semaphore(4)

    async def guarded(case: Case, trial_idx: int):
        async with sem:
            r = await run_trial(case, parsed[case.name], client)
            return case.name, trial_idx, r

    jobs = [guarded(c, t) for c in cases for t in range(args.trials)]
    outcomes = await asyncio.gather(*jobs)

    by_case: dict[str, list[dict]] = {c.name: [] for c in cases}
    for name, _, r in outcomes:
        by_case[name].append(r)

    print()
    print("=" * 78)
    print(f"BATTLE TEST RESULTS — {args.trials} trial(s) per case")
    print("=" * 78)
    for c in cases:
        trials = by_case[c.name]
        n_pass = sum(1 for t in trials if t["status"] == "PASS")
        marker = "OK  " if n_pass == len(trials) else ("PART" if n_pass else "FAIL")
        avg_t = sum(t.get("elapsed", 0) for t in trials) / len(trials)
        print(f"\n[{marker}] {c.name}  — {n_pass}/{len(trials)} pass  (avg {avg_t:.1f}s)")
        if c.note:
            print(f"       note: {c.note}")
        for i, t in enumerate(trials):
            if t["status"] == "PASS":
                continue
            if t["status"] == "ERROR":
                print(f"       trial {i}: ERROR {t['error']}")
            else:
                for p in t["problems"]:
                    print(f"       trial {i}: {p}")

    # persist for baseline-vs-fix comparison
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS_DIR / f"run_{stamp}.json"
    out.write_text(json.dumps({
        "timestamp": stamp,
        "trials": args.trials,
        "parse_config": PARSE_CONFIG_TAG,
        "results": by_case,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\n[results saved to {out.relative_to(BACKEND)}]")

    total_pass = sum(1 for rs in by_case.values() for r in rs if r["status"] == "PASS")
    total = sum(len(rs) for rs in by_case.values())
    print(f"\nTOTAL: {total_pass}/{total} trials passed")


if __name__ == "__main__":
    asyncio.run(main())
