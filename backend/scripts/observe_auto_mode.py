"""
Test auto_mode + auto_mode_trigger_on_table_in_page: upgrades only pages
LlamaParse detects as containing a table to premium parsing, leaving other
pages (e.g. prose-only side letters) on default parsing.

Checks two things against the SAME set used so far:
  1. Does it still fix the NAV-drop bug on the complex test table?
  2. Does it avoid the regressions seen with blanket premium_mode /
     outlined_table_extraction on the existing demo corpus?

Run from backend/: python scripts/observe_auto_mode.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import os
import asyncio
from llama_parse import LlamaParse

FILES_DIR = Path(__file__).resolve().parent.parent / "files"
SCRIPTS_DIR = Path(__file__).resolve().parent
API_KEY = os.getenv("LLAMA_CLOUD_API_KEY")

TARGETS = [
    SCRIPTS_DIR / "_test_LP_CAPITAL_ACCOUNT_STATEMENT.pdf",
    FILES_DIR / "FUND_REALIZATION_Q3_2025.pdf",
    FILES_DIR / "SIDE_LETTER_AGREEMENT.pdf",
    FILES_DIR / "SIDE_LETTER_FEE_CAP.pdf",
    FILES_DIR / "SIDE_LETTER_AGREEMENT_TEST_1.pdf",
]

AUTO_MODE_KWARGS = dict(
    result_type="markdown",
    auto_mode=True,
    auto_mode_trigger_on_table_in_page=True,
)


async def main():
    baseline_parser_kwargs = dict(result_type="markdown")

    for path in TARGETS:
        if not path.exists():
            print(f"[skip] {path.name} not found")
            continue

        baseline_parser = LlamaParse(api_key=API_KEY, **baseline_parser_kwargs)
        auto_parser = LlamaParse(api_key=API_KEY, **AUTO_MODE_KWARGS)

        t0 = time.monotonic()
        baseline_docs = await baseline_parser.aload_data(str(path))
        t1 = time.monotonic()
        auto_docs = await auto_parser.aload_data(str(path))
        t2 = time.monotonic()

        baseline_text = "\n\n".join(d.text for d in baseline_docs)
        auto_text = "\n\n".join(d.text for d in auto_docs)

        print("=" * 78)
        print(f"FILE: {path.name}")
        print(f"  baseline:   {t1 - t0:6.2f}s  {len(baseline_text)} chars")
        print(f"  auto_mode:  {t2 - t1:6.2f}s  {len(auto_text)} chars  "
              f"({'SAME' if auto_text == baseline_text else f'{len(auto_text) - len(baseline_text):+d} chars'})")
        print("=" * 78)
        print(auto_text)
        print()


if __name__ == "__main__":
    asyncio.run(main())
