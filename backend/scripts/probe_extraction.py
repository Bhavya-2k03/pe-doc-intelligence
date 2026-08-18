"""
Probe: run the REAL extraction LLM over a single PDF and dump raw output.

Isolates the question "does extraction read markdown tables at all?" from
parsing — the PDF is parsed first, the markdown printed, then the exact
same markdown is handed to the extraction LLM.

Usage from backend/:
    python scripts/probe_extraction.py files/FUND_REALIZATION_Q3_2025.pdf
    python scripts/probe_extraction.py scripts/_test_LP_STATEMENT_PERIOD_COLUMNS.pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import os

from openai import AsyncOpenAI

from constants import emails_and_attachment_fields
from engine.extractor import build_email_package, _call_extraction_llm
from engine.pdf_parser import parse_pdf


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    if not path.exists():
        print(f"not found: {path}")
        sys.exit(1)

    pages = await parse_pdf(path.read_bytes(), path.name)

    print("=" * 78)
    print(f"PARSED MARKDOWN — {path.name}")
    print("=" * 78)
    for p in pages:
        print(p)
    print()

    email_data = {
        "_id": "probe-001",
        "subject": path.stem.replace("_", " "),
        "body": "Please see attached.",
        "date": "2025-10-15",
        "attachments": [{"name": path.name, "attachment_index": 0}],
    }
    attachment_texts = [{
        "attachment_name": path.name,
        "attachment_index": 0,
        "attachment_text": pages,
    }]

    package = build_email_package(email_data, attachment_texts)
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    raw = await _call_extraction_llm(package, emails_and_attachment_fields, client)

    print("=" * 78)
    print("RAW EXTRACTION LLM OUTPUT")
    print("=" * 78)
    print(json.dumps(raw, indent=2, default=str))

    print()
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    fields = raw.get("extracted_fields")
    if not fields:
        print("  extracted_fields: NULL / EMPTY  <-- nothing extracted")
    else:
        for name, entries in fields.items():
            entries = entries if isinstance(entries, list) else [entries]
            for e in entries:
                if isinstance(e, dict):
                    print(f"  {name:<34} = {e.get('value')!r}  "
                          f"(as_of={e.get('value_as_of_date') or e.get('value_as_of_condition')!r})")
                else:
                    print(f"  {name:<34} = {e!r}")

    clauses = raw.get("clauses") or []
    print(f"\n  clauses: {len(clauses)}")


if __name__ == "__main__":
    asyncio.run(main())
