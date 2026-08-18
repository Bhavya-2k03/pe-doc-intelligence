"""
Regression + latency check: does enabling premium_mode or
outlined_table_extraction change (or break) parsing of the EXISTING demo
corpus, not just the synthetic complex-table test file?

For each file in backend/files/, parses with baseline vs each candidate
config, reports: parse time, output char-length delta, and a content diff
flag if the text actually changed.

Run from backend/: python scripts/regression_check_table_configs.py
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
API_KEY = os.getenv("LLAMA_CLOUD_API_KEY")

CONFIGS = {
    "baseline": dict(result_type="markdown"),
    "auto_mode": dict(result_type="markdown", auto_mode=True, auto_mode_trigger_on_table_in_page=True),
}


async def parse_one(path: Path, kwargs: dict) -> tuple[str, float]:
    parser = LlamaParse(api_key=API_KEY, **kwargs)
    start = time.monotonic()
    docs = await parser.aload_data(str(path))
    elapsed = time.monotonic() - start
    text = "\n\n".join(d.text for d in docs)
    return text, elapsed


async def main():
    files = sorted(FILES_DIR.glob("*.pdf"))
    results: dict[str, dict[str, tuple[str, float]]] = {}

    for path in files:
        results[path.name] = {}
        for label, kwargs in CONFIGS.items():
            text, elapsed = await parse_one(path, kwargs)
            results[path.name][label] = (text, elapsed)

    print(f"{'file':<45} {'config':<28} {'time(s)':>8} {'chars':>8} {'vs baseline':>14}")
    print("-" * 110)
    for filename, by_config in results.items():
        baseline_text, _ = by_config["baseline"]
        for label, (text, elapsed) in by_config.items():
            if label == "baseline":
                delta = "-"
            else:
                delta = "SAME" if text == baseline_text else f"DIFF ({len(text) - len(baseline_text):+d} chars)"
            print(f"{filename:<45} {label:<28} {elapsed:>8.2f} {len(text):>8} {delta:>14}")
        print()

    # save full text for any file where a candidate config differs, for manual review
    out_dir = Path(__file__).resolve().parent / "_regression_diffs"
    out_dir.mkdir(exist_ok=True)
    for filename, by_config in results.items():
        baseline_text, _ = by_config["baseline"]
        for label, (text, _) in by_config.items():
            if label != "baseline" and text != baseline_text:
                safe_name = filename.replace(" ", "_")
                (out_dir / f"{safe_name}__{label}.txt").write_text(text, encoding="utf-8")
                (out_dir / f"{safe_name}__baseline.txt").write_text(baseline_text, encoding="utf-8")

    print(f"[diffs saved to {out_dir}]")


if __name__ == "__main__":
    asyncio.run(main())
