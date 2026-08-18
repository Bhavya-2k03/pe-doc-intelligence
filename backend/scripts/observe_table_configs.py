"""
A/B different LlamaParse config options against the complex test table
(_test_LP_CAPITAL_ACCOUNT_STATEMENT.pdf) to see which one(s) fix the observed
failure: dropped NAV column + garbled merged-header row under the default
config (result_type="markdown" only).

Pure observation, no LLM extraction calls.

Run from backend/: python scripts/observe_table_configs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import os
import asyncio
from llama_parse import LlamaParse

PDF_PATH = Path(__file__).resolve().parent / "_test_LP_CAPITAL_ACCOUNT_STATEMENT.pdf"
API_KEY = os.getenv("LLAMA_CLOUD_API_KEY")

CONFIGS = {
    "baseline (current prod config)": dict(result_type="markdown"),
    "premium_mode": dict(result_type="markdown", premium_mode=True),
    "output_tables_as_HTML": dict(result_type="markdown", output_tables_as_HTML=True),
    "outlined_table_extraction": dict(result_type="markdown", outlined_table_extraction=True),
}


async def run_one(label: str, kwargs: dict):
    parser = LlamaParse(api_key=API_KEY, **kwargs)
    docs = await parser.aload_data(str(PDF_PATH))
    text = "\n\n".join(d.text for d in docs)
    print("=" * 78)
    print(f"CONFIG: {label}  ({kwargs})")
    print("=" * 78)
    print(text)
    print()

    out_path = Path(__file__).resolve().parent / f"_config_test_{label.split()[0]}.txt"
    out_path.write_text(text, encoding="utf-8")


async def main():
    for label, kwargs in CONFIGS.items():
        await run_one(label, kwargs)


if __name__ == "__main__":
    asyncio.run(main())
