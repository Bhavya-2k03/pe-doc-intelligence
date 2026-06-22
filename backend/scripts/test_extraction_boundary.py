"""
Focused test for the operand-list clause-boundary fix (Rule 0).

Feeds the exact side-letter text (from LlamaParse) that previously got
split into 3 clauses and verifies the extractor now returns it as ONE
clause containing the intro + both 'earlier of' operands.

Run from backend/:  python scripts/test_extraction_boundary.py
Runs the extraction N times to check determinism (the bug was intermittent).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()  # picks up .env from repo root (searches upward), like clause_interpreter.py

from openai import AsyncOpenAI
from engine.extractor import extract_email
from constants import emails_and_attachment_fields

# The exact parsed side-letter text from _parse_pdf_sync (the deferral scenario)
SIDE_LETTER_TEXT = (
    "\nSIDE LETTER AGREEMENT\n\nThis Side Letter Agreement (this “Agreement”) is made and "
    "entered into as of November 17, 2024 (the “Effective Date”), by and between General "
    "Partner X, a Delaware corporation (the “General Partner”), and Limited Partner Y, a "
    "Texas corporation (the “Limited Partner”).\n\n# RECITALS\n\nWHEREAS, the Limited Partner "
    "has been admitted as a limited partner pursuant to that certain Limited Partnership "
    "Agreement, dated as of January 5, 2024, as amended from time to time (the “LPA”);\n\n"
    "WHEREAS, the General Partner and the Limited Partner desire to set forth certain "
    "understandings and agreements that shall apply specifically to the Limited Partner and "
    "shall supplement the LPA;\n\nNOW, THEREFORE, in consideration of the mutual covenants and "
    "agreements herein, the parties agree as follows:\n\n# Deferred Management Fee Rate "
    "Reduction\n\nNotwithstanding Section [●] of the LPA or any schedule thereto, any "
    "reduction in the management fee rate otherwise applicable to the Investor following the "
    "end of the Investment Period shall be deferred and shall become effective only upon the "
    "earlier of:\n\n1. the eighth (8th) anniversary of the Fund’s Final Closing Date.\n2. the "
    "realization by the Fund of at least fifty percent (50%) of the Fund’s aggregate invested "
    "capital.\n\n# IN WITNESS WHEREOF\n\nThe parties have executed this Side Letter Agreement as "
    "of the date first written above.\n"
)

EMAIL_DATA = {
    "_id": "test_deferral_boundary",
    "subject": "Side Letter — Deferred Management Fee Rate Reduction",
    "body": "Please find attached the executed side letter.",
    "date": "2024-11-17",
    "from": "gp@example.com",
}

ATTACHMENT_TEXTS = [{
    "attachment_name": "side_letter.pdf",
    "attachment_index": 0,
    "attachment_text": [SIDE_LETTER_TEXT],
}]

N_RUNS = 3


async def main():
    client = AsyncOpenAI()

    print("=" * 70)
    print("OPERAND-LIST BOUNDARY FIX TEST — deferral side letter")
    print(f"Running extraction {N_RUNS}x (bug was intermittent)")
    print("=" * 70)

    for run in range(1, N_RUNS + 1):
        cache: dict = {}  # fresh cache each run to force a real LLM call
        result = await extract_email(
            EMAIL_DATA, ATTACHMENT_TEXTS, emails_and_attachment_fields, client, cache,
        )
        clauses = result.clauses
        print(f"\n--- Run {run}/{N_RUNS}: {len(clauses)} clause(s) extracted ---")
        for i, c in enumerate(clauses):
            txt = c.clause_text.replace("\n", " ")
            has_earlier = "earlier of" in txt.lower()
            has_op1 = "eighth" in txt.lower() or "8th" in txt.lower()
            has_op2 = "fifty percent" in txt.lower() or "50%" in txt
            # ascii-safe for cp1252 Windows consoles
            safe = txt[:160].encode("ascii", "replace").decode("ascii")
            print(f"  [{i}] len={len(txt)} earlier_of={has_earlier} op1={has_op1} op2={has_op2}")
            print(f"      cond={c.source_effective_date_condition!r}")
            print(f"      text: {safe}")

        # Verdict for this run
        deferral_clauses = [c for c in clauses if "earlier of" in c.clause_text.lower()]
        if len(deferral_clauses) == 1:
            c = deferral_clauses[0]
            both_ops = (("eighth" in c.clause_text.lower() or "8th" in c.clause_text.lower())
                        and ("fifty percent" in c.clause_text.lower() or "50%" in c.clause_text))
            if both_ops:
                print(f"  => PASS: single deferral clause with BOTH operands inline")
            else:
                print(f"  => PARTIAL: single 'earlier of' clause but operands missing")
        elif len(deferral_clauses) == 0:
            print(f"  => FAIL: no clause contains 'earlier of' (intro may have been dropped/split)")
        else:
            print(f"  => FAIL: {len(deferral_clauses)} clauses contain 'earlier of' (still splitting)")


if __name__ == "__main__":
    asyncio.run(main())
