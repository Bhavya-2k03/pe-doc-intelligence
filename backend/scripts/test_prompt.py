"""
Test the clause interpreter prompt by sending real clauses to GPT 5.2
and saving input/output to test_prompt_output.txt.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure backend/ (the parent of scripts/) is on sys.path so that
# `from engine.xxx import ...` resolves when this script is executed
# directly as `python scripts/test_prompt.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import AsyncOpenAI
from engine.clause_interpreter import interpret_clause


# ── Test clauses ──────────────────────────────────────────────────────────
# Chosen to cover: end-date convention (through/until/to), SET, ADJUST,
# CONSTRAIN, GATE, NO_ACTION, multi-field, bounded duration, function dates.

TEST_CLAUSES = [
    # 1. "next year"
    # "The management fee shall be reduced to 1.25% effective next year.",

    # 2. "through end of this year"
    # "Management fees are hereby waived through the end of this year.",

    # 3. "beginning of this year"
    # "The new carried interest rate of 22% shall apply from the beginning of this year.",

    "The Management Fee rate shall be reduced from 2.00% to 1.75% per annum effective as of the next fiscal quarter start date following the expiration of the Commitment Period."
]

TEST_CLAUSES_OLD = [
    # 1. Simple SET with literal date
    "The management fee shall be 1.5% effective 1 July 2026.",

    # 2. Bounded SET — "through" (inclusive end date → should output next day)
    "The management fee is reduced to 1.0% from 1 January 2026 through 30 June 2026.",

    # 3. Bounded SET — "until" (exclusive end date → should use directly)
    "The management fee shall be waived until 1 April 2026.",

    # 4. ADJUST with direction
    "Management fee reduced by 50 basis points after the commitment period.",

    # 5. CONSTRAIN — CAP
    "In no event shall the management fee exceed 1.75% per annum.",

    # 6. GATE — postpone with literal date
    "The fee reduction scheduled for 1 June 2026 is deferred until 1 December 2026.",

    # 7. GATE — condition-based (runtime metric)
    "The fee reduction shall be deferred until fund realization reaches 75%.",

    # 8. Multi-field — rate + basis switch
    "Management fee shall be 2% on committed capital during the commitment period, then 1.5% on invested capital thereafter.",

    # 9. NO_ACTION
    "The General Partner shall deliver quarterly reports within 60 days of each quarter end.",

    # 10. Bounded SET with "to" (inclusive → should add one day)
    "The carried interest rate is temporarily increased to 25% from 1 March 2026 to 31 August 2026.",
]


async def main():
    client = AsyncOpenAI()
    results = []
    output_lines = []

    output_lines.append(f"Clause Interpreter Prompt Test Run — {datetime.now().isoformat()}")
    output_lines.append("=" * 80)

    for i, clause in enumerate(TEST_CLAUSES, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{len(TEST_CLAUSES)}] Sending: {clause[:80]}...")
        output_lines.append(f"\n{'='*80}")
        output_lines.append(f"TEST {i}/{len(TEST_CLAUSES)}")
        output_lines.append(f"{'='*80}")
        output_lines.append(f"\nINPUT CLAUSE:\n{clause}\n")

        try:
            instructions = await interpret_clause(clause, client)
            parsed = [inst.model_dump(mode="json") for inst in instructions]
            formatted = json.dumps(parsed, indent=2)

            print(f"  -> {len(instructions)} instruction(s) returned")
            for inst in instructions:
                print(f"    action={inst.action}, field={inst.affected_field}")
                if inst.effective_end_date_expr:
                    print(f"    effective_end_date_expr={inst.effective_end_date_expr.model_dump(mode='json')}")
                if inst.gate_new_end_date_expr:
                    print(f"    gate_new_end_date_expr={inst.gate_new_end_date_expr.model_dump(mode='json')}")

            output_lines.append(f"OUTPUT ({len(instructions)} instruction(s)):")
            output_lines.append(formatted)

            results.append({"clause": clause, "success": True, "count": len(instructions)})

        except Exception as e:
            error_msg = f"ERROR: {type(e).__name__}: {e}"
            print(f"  -> {error_msg}")
            output_lines.append(f"OUTPUT:\n{error_msg}")
            results.append({"clause": clause, "success": False, "error": str(e)})

    # Summary
    output_lines.append(f"\n{'='*80}")
    output_lines.append("SUMMARY")
    output_lines.append(f"{'='*80}")
    passed = sum(1 for r in results if r["success"])
    output_lines.append(f"Total: {len(results)} | Passed: {passed} | Failed: {len(results) - passed}")
    for i, r in enumerate(results, 1):
        status = "OK" if r["success"] else f"FAIL ({r.get('error', 'unknown')[:60]})"
        output_lines.append(f"  [{i}] {status} — {r['clause'][:70]}")

    # Write to file
    output_path = "test_prompt_output.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))

    print(f"\n\nResults saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
