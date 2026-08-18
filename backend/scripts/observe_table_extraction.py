"""
Observe raw LlamaParse markdown output for table/chart-heavy documents.

Purpose: see EXACTLY what LlamaParse's default config gives us for tables
before deciding whether/how to improve table & chart extraction. No LLM
calls here — pure parsing observation.

Run from backend/: python scripts/observe_table_extraction.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import asyncio
from engine.pdf_parser import parse_pdf

FILES_DIR = Path(__file__).resolve().parent.parent / "files"
SCRIPTS_DIR = Path(__file__).resolve().parent

# Candidates most likely to contain tables/financial figures
CANDIDATES = [
    FILES_DIR / "FUND_REALIZATION_Q3_2025.pdf",
    FILES_DIR / "Realization_Statementent.pdf",
    FILES_DIR / "Subscription_Credit_Facility.pdf",
    SCRIPTS_DIR / "_test_LP_CAPITAL_ACCOUNT_STATEMENT.pdf",
]


async def main():
    for path in CANDIDATES:
        filename = path.name
        if not path.exists():
            print(f"[skip] {filename} not found")
            continue

        file_bytes = path.read_bytes()
        print("=" * 78)
        print(f"FILE: {filename}")
        print("=" * 78)

        pages = await parse_pdf(file_bytes, filename)
        print(f"-> {len(pages)} page(s) parsed\n")

        for i, page_text in enumerate(pages):
            print(f"--- page {i} ({len(page_text)} chars) ---")
            print(page_text)
            print()

        # Save raw output to a file too, for careful diffing later
        out_path = Path(__file__).resolve().parent / f"_raw_markdown_{filename}.txt"
        out_path.write_text("\n\n".join(pages), encoding="utf-8")
        print(f"[saved raw markdown to {out_path.name}]\n")


if __name__ == "__main__":
    asyncio.run(main())
