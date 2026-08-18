"""Clause-level stability probe for the clause interpreter.

Sends each demo clause directly to interpret_clause() N times (no extraction,
no scenario runs) and reports per-clause stability + invariant pass rates.
Written to verify the INTERPRETER_REASONING_EFFORT=low fix and the
missing-end-date retry backstop.

Usage (CWD must be backend/):
    venv/bin/python scripts/probe_interpreter_clauses.py
"""

import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv

load_dotenv(BACKEND / ".env")

from openai import AsyncOpenAI

from engine import clause_interpreter
from engine.clause_interpreter import interpret_clause

CONCURRENCY = 10
OUT_PATH = Path(
    os.environ.get(
        "PROBE_OUT",
        "/private/tmp/claude-501/-Users-bhavyagupta-Truefee-pe-doc-intelligence/"
        "c0d6e4ff-829f-4cad-a62e-cf58b9b630e4/scratchpad/probe_results.json",
    )
)


# ---------------------------------------------------------------------------
# Demo clauses — verbatim what extraction feeds the interpreter
# ---------------------------------------------------------------------------

CLAUSES = [
    # ── multi_amendment ────────────────────────────────────────────────
    {
        "id": "m1_fee_cap",
        "runs": 15,
        "text": (
            "Notwithstanding any provision of the Partnership Agreement to the "
            "contrary, the annual Management Fee rate payable by the Fund in "
            "respect of any period commencing on or after the end of the "
            "Investment Period (as then in effect, giving effect to any "
            "extension thereof) shall not exceed one and one-quarter percent "
            "(1.25%) per annum of the applicable fee basis. This ceiling shall "
            "remain in effect for the remaining term of the Fund."
        ),
        "invariants": {
            "action=CONSTRAIN": lambda ins: ins[0].action == "CONSTRAIN",
            "type=CAP": lambda ins: ins[0].constraint_type == "CAP",
            "field=mgmt_fee_rate": lambda ins: ins[0].affected_field
            == "management_fee_rate",
            "value=1.25": lambda ins: _lit(ins[0].value_expr) == 1.25,
            "eff=IP_end": lambda ins: _fref(ins[0].effective_date_expr)
            == "fund_investment_end_date",
        },
    },
    {
        "id": "m2_fee_waiver (BUG CLAUSE)",
        "runs": 30,
        "text": (
            "The Management Fee rate otherwise payable by the Fund shall be "
            "reduced from 2.00% to 1.00% per annum for the period commencing "
            "January 1, 2028 and ending at the end of the Investment Period."
        ),
        "invariants": {
            "action=SET": lambda ins: ins[0].action == "SET",
            "field=mgmt_fee_rate": lambda ins: ins[0].affected_field
            == "management_fee_rate",
            "value=1.0": lambda ins: _lit(ins[0].value_expr) in (1, 1.0),
            "eff=2028-01-01": lambda ins: _lit(ins[0].effective_date_expr)
            == "2028-01-01",
            "END=IP_end (the bug)": lambda ins: _fref(ins[0].effective_end_date_expr)
            == "fund_investment_end_date",
        },
    },
    {
        "id": "m3_ip_extension",
        "runs": 15,
        "text": (
            "The end date of the Investment Period is hereby extended by "
            "eighteen (18) months. For the avoidance of doubt, all provisions "
            "of the Partnership Agreement and any prior amendments that "
            "reference the end of the Investment Period shall be construed by "
            "reference to such extended date."
        ),
        "invariants": {
            "action=SET": lambda ins: ins[0].action == "SET",
            "field=IP_end": lambda ins: ins[0].affected_field
            == "fund_investment_end_date",
            "+18 months": lambda ins: "18" in _dump(ins[0].value_expr)
            and "MONTH" in _dump(ins[0].value_expr).upper(),
        },
    },
    # ── side_letter_flow ───────────────────────────────────────────────
    {
        "id": "s1_deferral_gate",
        "runs": 15,
        "text": (
            "Notwithstanding Section [●] of the LPA or any schedule "
            "thereto, any reduction in the management fee rate otherwise "
            "applicable to the Investor following the end of the Investment "
            "Period shall be deferred and shall become effective only upon "
            "the earlier of:\n\n"
            "1. the eighth (8th) anniversary of the Fund’s Final Closing "
            "Date.\n"
            "2. the realization by the Fund of at least fifty percent (50%) "
            "of the Fund’s aggregate invested capital."
        ),
        "invariants": {
            "action=GATE": lambda ins: any(i.action == "GATE" for i in ins),
            "field=mgmt_fee_rate": lambda ins: all(
                i.affected_field == "management_fee_rate"
                for i in ins
                if i.action == "GATE"
            ),
            "target=REDUCTION": lambda ins: all(
                i.gate_target == "REDUCTION" for i in ins if i.action == "GATE"
            ),
            "one mechanism": lambda ins: all(
                (i.gate_move_to_date_expr is None) != (i.condition_ast is None)
                for i in ins
                if i.action == "GATE"
            ),
        },
    },
    # ── mfn_flow: disclosure notice ────────────────────────────────────
    {
        "id": "d1_rate_reduction",
        "runs": 15,
        "text": (
            "Reduction of Management Fee Rate: The General Partner has agreed "
            "to reduce the annual Management Fee from 2.0% to a fixed rate of "
            "1.75% per annum, following the execution of the election form."
        ),
        "invariants": {
            "action=SET": lambda ins: ins[0].action == "SET",
            "field=mgmt_fee_rate": lambda ins: ins[0].affected_field
            == "management_fee_rate",
            "value=1.75": lambda ins: _lit(ins[0].value_expr) == 1.75,
        },
    },
    {
        "id": "d2_billing_cadence",
        "runs": 15,
        "text": (
            "Modification of Billing Cadence: The Management Fee shall be "
            "billed on a semi-annual basis, following the execution of the "
            "election form."
        ),
        "invariants": {
            "action=SET": lambda ins: ins[0].action == "SET",
            "field=cadence": lambda ins: ins[0].affected_field
            == "management_fee_billing_cadence",
        },
    },
    {
        "id": "d3_q1_waiver",
        "runs": 15,
        "text": (
            "The Management Fee for the first quarter of 2025 is waived for "
            "all Investors whose Total Capital Commitment equals or exceeds "
            "USD 8,000,000, following the execution of the Election Form."
        ),
        "invariants": {
            "field=mgmt_fee_rate": lambda ins: ins[0].affected_field
            == "management_fee_rate",
            "value=0": lambda ins: _lit(ins[0].value_expr) in (0, 0.0),
            "END non-null": lambda ins: ins[0].effective_end_date_expr
            is not None,
            "condition non-null": lambda ins: ins[0].condition_ast is not None,
        },
    },
    {
        "id": "d4_reporting_freq",
        "runs": 15,
        "text": (
            "Enhanced Reporting Frequency: The General Partner has agreed to "
            "provide Monthly Unaudited Performance Summaries within 15 "
            "business days of each month-end, in addition to the standard "
            "quarterly financial reporting currently required under the "
            "Agreement."
        ),
        "invariants": {
            "action=NO_ACTION/MR": lambda ins: all(
                i.action in ("NO_ACTION", "MANUAL_REVIEW") for i in ins
            ),
        },
    },
    # ── mfn_flow: election form ────────────────────────────────────────
    {
        "id": "e1_rate_reduction",
        "runs": 15,
        "text": (
            "The annual Management Fee shall be reduced from 2.0% to a fixed "
            "rate of 1.75% per annum, following the execution of this "
            "election form."
        ),
        "invariants": {
            "action=SET": lambda ins: ins[0].action == "SET",
            "field=mgmt_fee_rate": lambda ins: ins[0].affected_field
            == "management_fee_rate",
            "value=1.75": lambda ins: _lit(ins[0].value_expr) == 1.75,
        },
    },
    {
        "id": "e2_q1_waiver",
        "runs": 15,
        "text": (
            "The Management Fee for the first quarter of 2025 is waived for "
            "all Investors whose Total Capital Commitment equals or exceeds "
            "USD 8,000,000, following the execution of the Election Form."
        ),
        "invariants": {
            "field=mgmt_fee_rate": lambda ins: ins[0].affected_field
            == "management_fee_rate",
            "value=0": lambda ins: _lit(ins[0].value_expr) in (0, 0.0),
            "END non-null": lambda ins: ins[0].effective_end_date_expr
            is not None,
            "condition non-null": lambda ins: ins[0].condition_ast is not None,
        },
    },
    {
        "id": "e3_billing_cadence",
        "runs": 15,
        "text": (
            "The Management Fee will be billed on a semi-annual basis, "
            "following the execution of the election form."
        ),
        "invariants": {
            "action=SET": lambda ins: ins[0].action == "SET",
            "field=cadence": lambda ins: ins[0].affected_field
            == "management_fee_billing_cadence",
        },
    },
]

# d3 and e2 share identical text; keep one probe but count it for both.
CLAUSES = [c for c in CLAUSES if c["id"] != "e2_q1_waiver"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lit(node):
    return node.value if node is not None and node.node_type == "literal" else None


def _fref(node):
    return node.field if node is not None and node.node_type == "field_ref" else None


def _dump(node):
    return json.dumps(node.model_dump(), sort_keys=True) if node else "null"


def _render(node) -> str:
    """Compact one-line AST rendering for signature summaries."""
    if node is None:
        return "-"
    t = node.node_type
    if t == "literal":
        return repr(node.value)
    if t == "field_ref":
        return f"@{node.field}"
    args = ", ".join(_render(a) for a in (node.args or []))
    if t == "function_call":
        return f"{node.fn}({args})"
    return f"{node.op}({args})"


def _summarize(instructions) -> str:
    parts = []
    for i in instructions:
        bits = [i.action, str(i.affected_field)]
        if i.value_expr is not None:
            bits.append(f"val={_render(i.value_expr)}")
        if i.condition_ast is not None:
            bits.append(f"cond={_render(i.condition_ast)}")
        if i.effective_date_expr is not None:
            bits.append(f"eff={_render(i.effective_date_expr)}")
        if i.effective_end_date_expr is not None:
            bits.append(f"end={_render(i.effective_end_date_expr)}")
        else:
            bits.append("end=NULL")
        if i.action == "GATE":
            bits.append(
                f"move={_render(i.gate_move_to_date_expr)}"
                f" scope={i.gate_scope_mode} tgt={i.gate_target}"
                f" dir={i.gate_direction}"
            )
        if i.constraint_type:
            bits.append(f"ctype={i.constraint_type}")
        if i.adjust_direction:
            bits.append(f"adir={i.adjust_direction}")
        parts.append(" ".join(bits))
    return " || ".join(parts)


def _signature(instructions) -> str:
    return json.dumps(
        [
            {k: v for k, v in i.model_dump().items() if k != "clause_text"}
            for i in instructions
        ],
        sort_keys=True,
        default=str,
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def _one_run(sem, client, clause):
    async with sem:
        try:
            return await interpret_clause(clause["text"], client)
        except Exception as exc:  # keep the batch alive
            return exc


async def main():
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)
    effort = os.getenv("INTERPRETER_REASONING_EFFORT", "low")
    print(f"effort={effort}  concurrency={CONCURRENCY}", flush=True)

    all_results = {}
    for clause in CLAUSES:
        retry_before = dict(clause_interpreter.RETRY_STATS)
        runs = await asyncio.gather(
            *[_one_run(sem, client, clause) for _ in range(clause["runs"])]
        )
        retry_delta = {
            k: clause_interpreter.RETRY_STATS[k] - retry_before[k]
            for k in retry_before
        }

        errors = [r for r in runs if isinstance(r, Exception)]
        ok = [r for r in runs if not isinstance(r, Exception)]

        sig_counts = Counter(_signature(r) for r in ok)
        sig_summary = {}
        for r in ok:
            sig_summary.setdefault(_signature(r), _summarize(r))

        print(f"\n=== {clause['id']}  ({clause['runs']} runs) ===", flush=True)
        if errors:
            print(f"  ERRORS: {len(errors)} — {errors[0]!r:.200}")
        for name, check in clause["invariants"].items():
            passed = sum(1 for r in ok if _safe(check, r))
            flag = "PASS" if passed == len(ok) and not errors else "FAIL"
            print(f"  [{flag}] {name}: {passed}/{len(ok)}")
        print(f"  distinct signatures: {len(sig_counts)}")
        for sig, count in sig_counts.most_common():
            print(f"    {count:>2}x  {sig_summary[sig]}")
        if retry_delta["triggered"]:
            print(
                f"  backstop: triggered={retry_delta['triggered']} "
                f"recovered={retry_delta['recovered']}"
            )

        all_results[clause["id"]] = {
            "invariants": {
                name: sum(1 for r in ok if _safe(check, r))
                for name, check in clause["invariants"].items()
            },
            "n_ok": len(ok),
            "n_err": len(errors),
            "signatures": {
                sig_summary[sig]: count for sig, count in sig_counts.items()
            },
            "retry": retry_delta,
        }

    print(f"\nTOTAL RETRY_STATS: {clause_interpreter.RETRY_STATS}", flush=True)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(all_results, indent=2))
    print(f"full results -> {OUT_PATH}")


def _safe(check, r):
    try:
        return bool(check(r))
    except Exception:
        return False


if __name__ == "__main__":
    asyncio.run(main())
