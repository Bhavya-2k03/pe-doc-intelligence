"""Async PDF parser — wraps LlamaParse with byte-hash caching.

Parses PDF bytes into markdown text pages. Caches results by SHA256
of the file bytes so the same PDF is never parsed twice in a session.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def _parse_pdf_sync(file_bytes: bytes, filename: str) -> list[str]:
    """Parse PDF bytes via LlamaParse (sync). Returns list of page texts."""
    from llama_parse import LlamaParse

    api_key = os.getenv("LLAMA_CLOUD_API_KEY")
    if not api_key:
        raise RuntimeError("LLAMA_CLOUD_API_KEY not set")

    parser = LlamaParse(api_key=api_key, result_type="markdown")

    # LlamaParse needs a file path — write to temp file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        documents = parser.load_data(tmp_path)
        return [doc.text for doc in documents]
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


async def parse_pdf(file_bytes: bytes, filename: str) -> list[str]:
    """Parse PDF bytes via LlamaParse (async). Returns list of page texts."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _parse_pdf_sync, file_bytes, filename)


async def parse_attachments(
    attachments: list[dict],
    parse_cache: dict[str, list[str]],
) -> list[dict]:
    """Parse all attachments, using cache to skip already-parsed PDFs.

    Args:
        attachments: list of dicts with keys:
            - name: str (filename)
            - attachment_index: int
            - file_bytes: bytes (raw PDF content)
        parse_cache: SHA256(file_bytes) → list of page texts. Modified in place.

    Returns:
        list of dicts with keys:
            - attachment_name: str
            - attachment_index: int
            - attachment_text: list[str] (parsed page texts)
    """
    # Separate cached vs uncached
    cached_results: dict[int, list[str]] = {}  # index → pages
    to_parse: list[tuple[int, bytes, str]] = []  # (index, file_bytes, filename)

    for i, att in enumerate(attachments):
        file_bytes: bytes = att["file_bytes"]
        filename: str = att["name"]
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        if file_hash in parse_cache:
            logger.info("PDF cache hit for %s (hash=%s...)", filename, file_hash[:12])
            cached_results[i] = parse_cache[file_hash]
        else:
            to_parse.append((i, file_bytes, filename, file_hash))

    # Parse all uncached PDFs in parallel
    if to_parse:
        logger.info("Parsing %d PDFs in parallel...", len(to_parse))

        async def _parse_one(idx, fb, fn, fh):
            try:
                pages = await parse_pdf(fb, fn)
                parse_cache[fh] = pages
                return idx, pages
            except Exception:
                logger.exception("Failed to parse PDF: %s", fn)
                return idx, []

        parse_tasks = [_parse_one(idx, fb, fn, fh) for idx, fb, fn, fh in to_parse]
        parse_results = await asyncio.gather(*parse_tasks)
        for idx, pages in parse_results:
            cached_results[idx] = pages

    # Build output in original order
    results: list[dict] = []
    for i, att in enumerate(attachments):
        results.append({
            "attachment_name": att["name"],
            "attachment_index": att["attachment_index"],
            "attachment_text": cached_results.get(i, []),
        })

    return results
