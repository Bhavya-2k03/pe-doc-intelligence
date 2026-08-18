"""
End-to-end table extraction test: PDF -> LlamaParse (new auto_mode config)
-> real extraction LLM -> assert the CORRECT period column was read.

The trap this test checks for: with periods as columns, an extractor that
grabs the first numeric cell in a row returns a stale Q1 figure that looks
entirely plausible. Only the Q3 (as-of) column is correct.

Run from backend/: python scripts/test_table_extraction_e2e.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import asyncio
import os

from openai import AsyncOpenAI

from constants import emails_and_attachment_fields
from engine.extractor import extract_email
from engine.pdf_parser import parse_pdf

PDF_PATH = Path(__file__).resolve().parent / "_test_LP_STATEMENT_PERIOD_COLUMNS.pdf"

# Correct values = the Q3 2025 "as of" column (the LAST one).
# The decoys are the Q1/Q2 values in the same row.
EXPECTED = {
    "investor_invested_capital": {
        "correct": 6_850_000,
        "decoys": {4_900_000: "Q1 2025", 6_050_000: "Q2 2025"},
    },
    "investor_total_realized_capital": {
        "correct": 1_780_000,
        "decoys": {700_000: "Q1 2025", 1_150_000: "Q2 2025"},
    },
}


async def main():
    file_bytes = PDF_PATH.read_bytes()
    pages = await parse_pdf(file_bytes, PDF_PATH.name)

    print("=" * 78)
    print("PARSED MARKDOWN")
    print("=" * 78)
    for p in pages:
        print(p)
    print()

    email_data = {
        "_id": "test-table-001",
        "subject": "Q3 2025 Capital Account Statement",
        "body": "Please find attached your capital account statement.",
        "date": "2025-10-15",
        "attachments": [{"name": PDF_PATH.name, "attachment_index": 0}],
    }
    attachment_texts = [{
        "attachment_name": PDF_PATH.name,
        "attachment_index": 0,
        "attachment_text": pages,
    }]

    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    result = await extract_email(
        email_data=email_data,
        attachment_texts=attachment_texts,
        field_registry=emails_and_attachment_fields,
        openai_client=client,
        extraction_cache={},
    )

    print("=" * 78)
    print("EXTRACTED FIELDS (all entries per field)")
    print("=" * 78)
    for field_name, entries in result.extracted_fields.items():
        print(f"\n  {field_name}  ({len(entries)} entry/entries)")
        for e in entries:
            print(f"     value={e.value!r}  as_of_date={e.value_as_of_date!r}  "
                  f"as_of_condition={e.value_as_of_condition!r}")
            if e.source_context:
                print(f"     context: {e.source_context[:110]}")

    print()
    print("=" * 78)
    print("PERIOD-COLUMN BEHAVIOUR CHECK")
    print("=" * 78)

    def as_number(v) -> float | None:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        cleaned = str(v).replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None

    for field, spec in EXPECTED.items():
        entries = result.extracted_fields.get(field)
        if not entries:
            print(f"\n  [MISSING] {field}: not extracted at all")
            continue

        values = [as_number(e.value) for e in entries]
        want = float(spec["correct"])
        decoys = {float(k): v for k, v in spec["decoys"].items()}

        print(f"\n  {field}: got {len(entries)} entry/entries -> {values}")

        if len(entries) == 1:
            got = values[0]
            if got == want:
                print("     [OK] single entry = current (Q3) value — correct column picked.")
            elif got in decoys:
                print(f"     [BUG] single entry is STALE {decoys[got]} value "
                      f"(expected {want:,.0f}) — wrong column picked.")
            else:
                print(f"     [BUG] unexpected value (expected {want:,.0f}).")
        else:
            # Multiple entries: the timeline-correct answer, IF each is dated.
            undated = [e for e in entries if not (e.value_as_of_date or e.value_as_of_condition)]
            if want in values and not undated:
                print("     [OK] multi-entry timeline, all dated, includes current value.")
            elif undated:
                print(f"     [RISK] {len(undated)} entry/entries have NO as-of date — "
                      "ambiguous which period they belong to.")
            else:
                print(f"     [BUG] current value {want:,.0f} missing from entries.")

    print()
    print("Observation run complete — read the output above, no pass/fail asserted.")


if __name__ == "__main__":
    asyncio.run(main())
