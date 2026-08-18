"""Extraction orchestrator — Layer 1 of the pipeline.

Builds email packages, calls the extraction LLM, validates output,
and caches results by content hash.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, TYPE_CHECKING


from engine.pipeline_models import (
    ClauseRecord,
    DocumentIntent,
    ExtractionResult,
    ExtractedFieldEntry,
)
from prompts import fields_and_clauses_and_document_intent_extractor_prompt

if TYPE_CHECKING:
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Email package building
# ═══════════════════════════════════════════════════════════════════════════


def build_email_package(
    email_data: dict,
    attachment_texts: list[dict] | None,
) -> dict:
    """Build the email_package dict that the extraction LLM receives.

    Args:
        email_data: raw email dict with _id, subject, body, date, attachments
        attachment_texts: parsed attachment texts from pdf_parser, or None

    Returns:
        {"email_data": {...filtered...}, "attachment_text": [...] | None}
    """
    # Filter email_data to only the fields the LLM needs
    attachments = email_data.get("attachments", [])
    filtered_attachments = [
        {"name": att.get("name"), "attachment_index": att.get("attachment_index")}
        for att in attachments
    ] if attachments else []

    filtered_email = {
        "_id": email_data.get("_id"),
        "subject": email_data.get("subject"),
        "body": email_data.get("body"),
        "date": email_data.get("date"),
        "attachments": filtered_attachments,
    }

    # Clean attachment text (strip whitespace from each page)
    cleaned_att_text = None
    if attachment_texts:
        cleaned_att_text = []
        for att in attachment_texts:
            cleaned_pages = [
                page.strip() for page in att.get("attachment_text", [])
            ]
            cleaned_att_text.append({
                "attachment_name": att.get("attachment_name"),
                "attachment_index": att.get("attachment_index"),
                "attachment_text": cleaned_pages,
            })

    return {
        "email_data": filtered_email,
        "attachment_text": cleaned_att_text,
    }


def compute_email_hash(email_package: dict) -> str:
    """Hash the exact input the LLM would see."""
    canonical = json.dumps(email_package, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════
# LLM extraction
# ═══════════════════════════════════════════════════════════════════════════


async def _call_extraction_llm(
    email_package: dict,
    field_registry: list[dict],
    openai_client: AsyncOpenAI,
) -> dict:
    """Call GPT 5.2 with the extraction prompt. Returns raw parsed JSON."""
    input_obj = {
        "email_package": email_package,
        "emails_and_attachment_fields": field_registry,
    }

    user_message = json.dumps(input_obj, default=str)

    # Reasoning effort for extraction. Default "low": measured on the graded
    # golden set (scripts/battle_test_extraction.py) — LP capital-account
    # statements (fund letterhead + LP subject + period-column tables) extract
    # ~35% at effort none vs ~100% at low, with prior-period columns emitted
    # as correctly dated timeline entries. Cost: ~4s → ~13s per call.
    # Override via EXTRACTION_REASONING_EFFORT; set "none" to restore the old
    # behavior (temperature=0, no reasoning).
    effort = os.getenv("EXTRACTION_REASONING_EFFORT", "low")
    sampling_kwargs: dict = (
        {"temperature": 0} if effort == "none" else {"reasoning_effort": effort}
    )

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-5.2",
            messages=[
                {
                    "role": "system",
                    "content": fields_and_clauses_and_document_intent_extractor_prompt,
                },
                {"role": "user", "content": user_message},
            ],
            **sampling_kwargs,
        )
    except Exception:
        logger.exception("Extraction LLM call failed for email %s",
                         email_package.get("email_data", {}).get("_id", "?"))
        raise

    raw = response.choices[0].message.content

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Extraction LLM returned invalid JSON: %.200s", raw)
        raise ValueError(f"Extraction LLM returned invalid JSON: {raw[:200]}")


def _parse_extraction_output(raw: dict) -> ExtractionResult:
    """Validate and convert raw LLM output to ExtractionResult."""
    # extracted_fields
    ef_raw = raw.get("extracted_fields") or {}
    extracted_fields: dict[str, list[ExtractedFieldEntry]] = {}
    for field_name, entries in ef_raw.items():
        if entries is None:
            continue
        extracted_fields[field_name] = [ExtractedFieldEntry(**e) for e in entries]

    # clauses
    cl_raw = raw.get("clauses") or []
    clauses = [ClauseRecord(**c) for c in cl_raw]

    # document_intent
    di_raw = raw.get("document_intent") or []
    document_intent = [DocumentIntent(**d) for d in di_raw]

    return ExtractionResult(
        extracted_fields=extracted_fields,
        clauses=clauses,
        document_intent=document_intent,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════


async def extract_email(
    email_data: dict,
    attachment_texts: list[dict] | None,
    field_registry: list[dict],
    openai_client: AsyncOpenAI,
    extraction_cache: dict[str, ExtractionResult],
) -> ExtractionResult:
    """Extract fields, clauses, and document intent from one email.

    Uses content-hash caching: if the email package hasn't changed
    since last extraction, returns cached result without LLM call.

    Args:
        email_data: raw email dict
        attachment_texts: parsed attachment texts (from pdf_parser)
        field_registry: emails_and_attachment_fields from constants
        openai_client: AsyncOpenAI instance
        extraction_cache: session-scoped cache, modified in place

    Returns:
        Validated ExtractionResult
    """
    package = build_email_package(email_data, attachment_texts)
    pkg_hash = compute_email_hash(package)

    email_id = email_data.get("_id", "?")

    if pkg_hash in extraction_cache:
        logger.info("Extraction cache hit for email %s (hash=%s...)",
                     email_id, pkg_hash[:12])
        return extraction_cache[pkg_hash]

    logger.info("Extracting email %s (hash=%s...)", email_id, pkg_hash[:12])

    # Intentionally NOT wrapped in a broad try/except — we want transient
    # upstream failures (OpenAI timeout, rate limit, malformed output) to
    # propagate up to main.py's run_pipeline so the user sees a clean retry
    # message instead of silently getting empty extractions + a downstream
    # "No result received from pipeline" error.
    raw_output = await _call_extraction_llm(
        package, field_registry, openai_client,
    )
    result = _parse_extraction_output(raw_output)

    # Fallback: if a clause has no date at all, use email_data.date.
    # This guarantees every clause has a resolvable document_date.
    email_date = email_data.get("date")
    if email_date:
        # Normalize to YYYY-MM-DD
        email_date_str = email_date.split("T")[0] if "T" in email_date else email_date
        for clause in result.clauses:
            if (clause.source_signed_date is None
                and clause.source_effective_date is None
                and clause.source_effective_date_condition is None):
                clause.source_signed_date = email_date_str
                logger.info(
                    "Clause missing all dates, falling back to email date %s: %s",
                    email_date_str, clause.clause_text[:60],
                )

    extraction_cache[pkg_hash] = result
    return result


def _plural(n: int, noun: str) -> str:
    """'1 email' / '2 emails' — progress lines are user-facing copy."""
    return noun if n == 1 else f"{noun}s"


async def extract_all_emails(
    email_dataset: list[dict],
    attachment_texts_by_email: dict[str, list[dict]],
    field_registry: list[dict],
    openai_client: AsyncOpenAI,
    extraction_cache: dict[str, ExtractionResult],
    on_progress: Any = None,
) -> list[ExtractionResult]:
    """Extract all emails in a dataset in parallel. Handles caching and diffing.

    Progress counts reflect the work actually being done: emails already in
    extraction_cache are reported as cached rather than being counted as
    extractions in flight. The cached/uncached split is therefore computed
    up front, which costs one hash per email and no LLM calls.
    """
    import asyncio
    total = len(email_dataset)

    # Partition before dispatching so the reported numbers are true.
    cached_by_idx: dict[int, ExtractionResult] = {}
    to_extract: list[tuple[int, dict]] = []
    for i, email_data in enumerate(email_dataset):
        att_texts = attachment_texts_by_email.get(email_data.get("_id", "?"))
        pkg_hash = compute_email_hash(build_email_package(email_data, att_texts))
        if pkg_hash in extraction_cache:
            cached_by_idx[i] = extraction_cache[pkg_hash]
        else:
            to_extract.append((i, email_data))

    n_cached = len(cached_by_idx)
    if not to_extract:
        if on_progress and total:
            await on_progress(
                "layer1", f"{total} {_plural(total, 'email')} — all cached"
            )
        return [cached_by_idx[i] for i in range(total)]

    if on_progress:
        suffix = f" ({n_cached} cached)" if n_cached else ""
        await on_progress(
            "layer1",
            f"Extracting {len(to_extract)} "
            f"{_plural(len(to_extract), 'email')}{suffix}...",
        )

    done = 0

    async def _extract_one(idx, email_data):
        nonlocal done
        email_id = email_data.get("_id", "?")
        att_texts = attachment_texts_by_email.get(email_id)
        result = await extract_email(
            email_data, att_texts, field_registry,
            openai_client, extraction_cache,
        )
        done += 1
        if on_progress:
            # Counts only — no subject, no _id. The terminal collapses
            # same-stage events into one line, so any per-item label would
            # leave whichever email finished last sitting on screen as if it
            # were the only one. Ids are meaningless to a reader anyway
            # ("e038", or "new_1712..." for a user-added email), and subjects
            # are long enough to need truncating mid-word.
            await on_progress(
                "layer1",
                f"Extracting {done}/{len(to_extract)} "
                f"{_plural(len(to_extract), 'email')}...",
            )
        return idx, result

    extracted = await asyncio.gather(*[
        _extract_one(i, email) for i, email in to_extract
    ])

    # Settle on a stage summary — the line that persists once done.
    if on_progress:
        suffix = f" ({n_cached} cached)" if n_cached else ""
        await on_progress(
            "layer1",
            f"Extracted {len(to_extract)} "
            f"{_plural(len(to_extract), 'email')}{suffix}",
        )

    by_idx = dict(cached_by_idx)
    for idx, result in extracted:
        by_idx[idx] = result
    return [by_idx[i] for i in range(total)]
