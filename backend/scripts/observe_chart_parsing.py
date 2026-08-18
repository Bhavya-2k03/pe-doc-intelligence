"""
Observe what LlamaParse produces for chart PDFs under two configs:

  prod:        auto_mode + trigger_on_table_in_page (current pdf_parser.py)
  prod+image:  same, plus auto_mode_trigger_on_image_in_page=True
               (upgrades chart pages to premium/vision parsing)

Run from backend/: python scripts/observe_chart_parsing.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
from llama_parse import LlamaParse

HERE = Path(__file__).resolve().parent
API_KEY = os.getenv("LLAMA_CLOUD_API_KEY")

CONFIGS = {
    "prod": dict(result_type="markdown", auto_mode=True,
                 auto_mode_trigger_on_table_in_page=True),
    "prod+image": dict(result_type="markdown", auto_mode=True,
                       auto_mode_trigger_on_table_in_page=True,
                       auto_mode_trigger_on_image_in_page=True),
}

PDFS = [HERE / "_chart_labeled.pdf", HERE / "_chart_unlabeled.pdf"]


async def main():
    for pdf in PDFS:
        for label, kwargs in CONFIGS.items():
            parser = LlamaParse(api_key=API_KEY, **kwargs)
            docs = await parser.aload_data(str(pdf))
            text = "\n\n".join(d.text for d in docs)
            print("=" * 78)
            print(f"{pdf.name}  —  config: {label}")
            print("=" * 78)
            print(text)
            print()


if __name__ == "__main__":
    asyncio.run(main())
