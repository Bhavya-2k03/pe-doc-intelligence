"""
Pipeline Orchestrator — connects all 5 layers.

Layer 1: Extraction (pre-computed, loaded from DB)
Layer 2: Clause Interpretation (LLM)
Layer 3: Document Date Resolution
Layer 4: Confirmation Resolution
Layer 5: Timeline Execution (engine)
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from datetime import date
from typing import Any, Optional

from engine.clause_interpreter import interpret_clause, resolve_date_condition
from engine.fee_calculator import compute_management_fee
from engine.models import ASTNode, ClauseInstruction
from engine.pipeline_models import (
    ClauseWithContext,
    DocumentIntent,
    ExtractionResult,
)
from engine.timeline_engine import (
    EvaluationContext,
    FieldTimeline,
    TimelineEntry,
    evaluate_ast,
    execute,
)

logger = logging.getLogger(__name__)



# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

EXTRACTION_TO_REGISTRY_MAP: dict[str, str] = {
    "fund_percentage_realized": "fund_percentage_realized",
    "fund_total_invested_capital": "fund_total_invested_capital",
    "fund_total_realized_capital": "fund_total_realized_capital",
    "fund_total_distributions": "fund_total_distributions",
    "fund_total_paid_in_capital": "fund_total_paid_in_capital",
    "investment_period_end_date": "fund_investment_end_date",
    "fund_term_expiration_date": "fund_term_end_date",
    "total_fund_committed_capital": "total_fund_commitment",
    "investor_invested_capital": "investor_invested_capital",
    "investor_total_realized_capital": "investor_realized_amount",
    "investor_percentage_realized": "investor_percentage_realized",
    "subscription_line_total_amount": "sub_line_total_payable",
    "subscription_line_principal_amount": "sub_line_principal",
    "subscription_line_fee_amount": "sub_line_fees",
    "subscription_line_interest_amount": "sub_line_interest",
    "subscription_line_repayment_due_date": "sub_line_repayment_due_date",
    "gp_commitment_amount": "gp_commitment_amount",
    "fund_initial_closing_date": "fund_initial_closing_date",
    "fund_final_closing_date": "fund_final_closing_date",
}

SKIP_DOC_TYPES: set[str] = {"mfn_disclosure", "capital_call_notice"}
FIELDS_ALLOWED_FROM_SKIP_DOCS: set[str] = {"fund_total_paid_in_capital","fund_total_distributions"}

SEED_TIMELINES: dict[str, list[dict]] = {
    "management_fee_rate": [
        {"date": "2024-01-15", "end_date": "2029-01-15",
         "value": 2.0, "source": "LPA: during investment period"},
        {"date": "2029-01-15",
         "value": 1.5, "source": "LPA: post investment period"},
    ],
    "management_fee_basis": [
        {"date": "2024-01-15", "end_date": "2029-01-15",
         "value": "committed_capital", "source": "LPA: during investment period"},
        {"date": "2029-01-15",
         "value": "invested_capital", "source": "LPA: post investment period"},
    ],
    "management_fee_billing_cadence": [
        {"date": "2024-01-15", "value": "quarterly", "source": "LPA"},
    ],
    "fund_initial_closing_date": [
        {"date": "2024-01-15", "value": "2024-01-15", "source": "LPA"},
    ],
    "fund_final_closing_date": [
        {"date": "2024-01-15", "value": "2024-12-15", "source": "LPA"},
    ],
    "fund_investment_end_date": [
        {"date": "2024-01-15", "value": "2029-01-15", "source": "LPA"},
    ],
    "fund_term_end_date": [
        {"date": "2024-01-15", "value": "2034-01-15", "source": "LPA"},
    ],
    "investor_commitment_amount": [
        {"date": "2024-01-15", "value": 10_000_000, "source": "LPA"},
    ],
    "total_fund_commitment": [
        {"date": "2024-01-15", "value": 50_000_000, "source": "LPA"},
    ],
}

# ═══════════════════════════════════════════════════════════════════════════
# Session State
# ═══════════════════════════════════════════════════════════════════════════

class SessionState:
    """In-memory state for one user session."""

    def __init__(self, session_id: str) -> None:
        self.session_id: str = session_id
        self.emails: list[dict] = []
        self.extraction_cache: dict[str, ExtractionResult] = {}
        self.interpreter_cache: dict[str, list[ClauseInstruction]] = {}
        self.condition_cache: dict[str, tuple[str, Any]] = {}  # hash -> (output_type, ASTNode)
        self.parse_cache: dict[str, list[str]] = {}  # pdf_bytes_hash -> parsed pages
        self.timelines: Optional[dict[str, FieldTimeline]] = None
        self.evaluation_date: Optional[date] = None
        self.last_accessed: float = time.time()


SESSIONS: dict[str, SessionState] = {}

# TTL for idle sessions. Default 2h; override with SESSION_TTL_SECONDS env var.
# Sessions not touched within this window are evicted on the next start_session
# call. Evaluations also bump last_accessed so an in-progress session never
# gets killed mid-flight.
SESSION_TTL_SECONDS: int = int(os.getenv("SESSION_TTL_SECONDS", "7200"))


def _sweep_expired_sessions() -> int:
    """Remove sessions idle beyond SESSION_TTL_SECONDS. Returns count removed."""
    now = time.time()
    expired = [
        sid for sid, sess in SESSIONS.items()
        if now - sess.last_accessed > SESSION_TTL_SECONDS
    ]
    for sid in expired:
        del SESSIONS[sid]
    if expired:
        logger.info(
            "Session sweep: evicted %d idle session(s) (ttl=%ds, active=%d)",
            len(expired), SESSION_TTL_SECONDS, len(SESSIONS),
        )
    return len(expired)


# ═══════════════════════════════════════════════════════════════════════════
# 1. start_session
# ═══════════════════════════════════════════════════════════════════════════

def start_session() -> str:
    """Create a new empty session. Returns session_id.

    Opportunistically sweeps expired sessions on each new-session request —
    keeps the in-memory SESSIONS dict bounded without needing a background task.
    """
    _sweep_expired_sessions()
    session_id = str(uuid.uuid4())
    session = SessionState(session_id)
    SESSIONS[session_id] = session
    return session_id


# ═══════════════════════════════════════════════════════════════════════════
# 2. build_clause_contexts
# ═══════════════════════════════════════════════════════════════════════════

def _compute_ordering_key(
    resolved_date: str | None,
    source_signed_date: str | None,
    attachment_index: int | None,
    clause_index: int,
) -> int:
    """Deterministic ordering key: date * 1_000_000 + att * 1_000 + clause.

    Uses resolved_document_date (when clause takes effect) as primary sort.
    Falls back to source_signed_date if resolved date not yet available.
    """
    date_str = resolved_date or source_signed_date
    date_component = 0
    if date_str:
        try:
            d = date.fromisoformat(date_str)
            date_component = int(d.strftime("%Y%m%d")) * 1_000_000
        except ValueError:
            pass
    att_component = 0 if attachment_index is None else (attachment_index + 1) * 1_000
    return date_component + att_component + clause_index


def build_clause_contexts(
    extraction_results: list[ExtractionResult],
) -> list[ClauseWithContext]:
    """Convert extraction results into ordered ClauseWithContext list."""
    contexts: list[ClauseWithContext] = []

    for result in extraction_results:
        # Build intent lookup: attachment_index -> DocumentIntent
        intent_by_att: dict[int | None, DocumentIntent] = {}
        for intent in result.document_intent:
            intent_by_att[intent.attachment_index] = intent

        for i, clause in enumerate(result.clauses):
            if clause.doc_type in SKIP_DOC_TYPES:
                continue

            matched_intent = intent_by_att.get(clause.attachment_index)

            clause_id = (
                f"{clause.email_source_id}:"
                f"{clause.attachment_index if clause.attachment_index is not None else 'body'}:"
                f"{i}"
            )

            # Preliminary ordering_key using source_signed_date.
            # Recomputed after resolve_document_dates() with resolved dates.
            ordering_key = _compute_ordering_key(
                None,
                clause.source_signed_date,
                clause.attachment_index,
                i,
            )

            contexts.append(ClauseWithContext(
                clause_id=clause_id,
                clause_text=clause.clause_text,
                doc_type=clause.doc_type,
                source_signed_date=clause.source_signed_date,
                source_effective_date=clause.source_effective_date,
                source_effective_date_condition=clause.source_effective_date_condition,
                source_context=clause.source_context,
                email_source_id=clause.email_source_id,
                attachment_index=clause.attachment_index,
                document_intent=matched_intent,
                ordering_key=ordering_key,
            ))

    contexts.sort(key=lambda c: c.ordering_key)
    return contexts


# ═══════════════════════════════════════════════════════════════════════════
# 3. insert_extracted_fields
# ═══════════════════════════════════════════════════════════════════════════

def _safe_parse_date(s: str | None) -> date | None:
    """Parse YYYY-MM-DD string to date, return None on failure."""
    if s is None:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


async def insert_extracted_fields(
    timelines: dict[str, FieldTimeline],
    extraction_results: list[ExtractionResult],
    evaluation_date: date,
    openai_client: Any = None,
    condition_cache: dict | None = None,
    email_dates: dict[str, str] | None = None,
) -> None:
    """Insert extracted field values into timelines as SET entries.

    Entries are collected per field, sorted by date, then inserted in
    chronological order so that later data points get higher insertion_order
    and correctly override earlier ones via value_at().
    """
    _email_dates = email_dates or {}

    # Phase 1: Collect and resolve all entries with their dates
    # Key = registry_name, Value = list of (date, value, source_text, email_source_id)
    pending: dict[str, list[tuple[date, Any, str, str | None]]] = {}

    for result in extraction_results:
        for field_name, entries in result.extracted_fields.items():
            registry_name = EXTRACTION_TO_REGISTRY_MAP.get(field_name)
            if registry_name is None:
                continue

            for entry in entries:
                if entry.doc_type in SKIP_DOC_TYPES and registry_name not in FIELDS_ALLOWED_FROM_SKIP_DOCS:
                    continue

                # Determine entry date — prefer explicit date, then resolve condition via LLM
                entry_date = _safe_parse_date(entry.value_as_of_date)

                if entry_date is None and entry.value_as_of_condition and openai_client:
                    raw_cond = entry.value_as_of_condition
                    src_email_date = _email_dates.get(entry.email_source_id, "")
                    if src_email_date:
                        condition_text = f"{raw_cond} (document signed {src_email_date})"
                    else:
                        condition_text = raw_cond
                    cache = condition_cache if condition_cache is not None else {}
                    cond_hash = hashlib.sha256(condition_text.encode()).hexdigest()

                    if cond_hash in cache:
                        output_type, ast_node = cache[cond_hash]
                    else:
                        try:
                            output_type, ast_node = await resolve_date_condition(
                                condition_text, openai_client,
                            )
                            cache[cond_hash] = (output_type, ast_node)
                        except Exception:
                            logger.exception(
                                "Failed to resolve value_as_of_condition: %s",
                                raw_cond,
                            )
                            ast_node = None
                            output_type = None

                    if output_type == "date" and ast_node is not None:
                        doc_date = _safe_parse_date(src_email_date)
                        temp_ctx = EvaluationContext(
                            evaluation_date=evaluation_date,
                            document_date=doc_date,
                        )
                        resolved = evaluate_ast(ast_node, timelines, temp_ctx)
                        if resolved is not None:
                            entry_date = (
                                resolved if isinstance(resolved, date)
                                else _safe_parse_date(str(resolved))
                            )

                if entry_date is not None and entry_date > evaluation_date:
                    continue

                if entry_date is None:
                    entry_date = evaluation_date

                source_text = f"Extracted: {entry.source_context or field_name}"
                if registry_name not in pending:
                    pending[registry_name] = []
                pending[registry_name].append(
                    (entry_date, entry.value, source_text, entry.email_source_id)
                )

    # Phase 2: Sort by date and insert in chronological order.
    # This ensures later data points get higher insertion_order and
    # correctly override earlier ones via value_at().
    for registry_name, field_entries in pending.items():
        field_entries.sort(key=lambda t: t[0])  # sort by date

        if registry_name not in timelines:
            timelines[registry_name] = FieldTimeline()

        for entry_date, value, source_text, email_source_id in field_entries:
            timelines[registry_name].insert_entry(TimelineEntry(
                date=entry_date,
                value=value,
                source_clause_text=source_text,
                entry_type="SET",
                email_source_id=email_source_id,
            ))


# ═══════════════════════════════════════════════════════════════════════════
# Helper: find first date where a boolean AST becomes TRUE
# ═══════════════════════════════════════════════════════════════════════════

def _find_first_true_date(
    ast: ASTNode,
    timelines: dict[str, FieldTimeline],
    signed_date: date,
    evaluation_date: date,
) -> date | None:
    """Find earliest date >= signed_date where boolean AST evaluates to TRUE.

    Scans all discrete dates where timeline values change (entry dates).
    Returns None if condition never becomes TRUE up to evaluation_date.
    """
    # Collect all unique entry dates from ALL timelines
    all_dates: set[date] = set()
    for ft in timelines.values():
        for entry in ft.entries:
            all_dates.add(entry.date)

    # Build sorted candidate list within [signed_date, evaluation_date]
    candidates = sorted(d for d in all_dates if signed_date <= d <= evaluation_date)

    # Ensure signed_date and evaluation_date are included
    if not candidates or candidates[0] != signed_date:
        candidates.insert(0, signed_date)
    if candidates[-1] != evaluation_date:
        candidates.append(evaluation_date)

    # Evaluate at each candidate date
    for check_date in candidates:
        ctx = EvaluationContext(
            evaluation_date=check_date,
            document_date=signed_date,
        )
        result = evaluate_ast(ast, timelines, ctx)
        if result is True:
            return check_date

    return None


# ═══════════════════════════════════════════════════════════════════════════
# 4. run_clause_interpretation (async — Layer 2)
# ═══════════════════════════════════════════════════════════════════════════

async def run_clause_interpretation(
    contexts: list[ClauseWithContext],
    openai_client: Any,
    cache: dict[str, list[ClauseInstruction]],
) -> list[ClauseWithContext]:
    """Run clause interpreter LLM for each clause. Uses content-hash cache."""
    for ctx in contexts:
        clause_hash = hashlib.sha256(ctx.clause_text.encode()).hexdigest()

        if clause_hash in cache:
            ctx.interpreter_output = cache[clause_hash]
            continue

        try:
            result = await interpret_clause(ctx.clause_text, openai_client)
            ctx.interpreter_output = result
            cache[clause_hash] = result
        except Exception:
            logger.exception(
                "Clause interpretation failed: %s", ctx.clause_text[:80]
            )
            ctx.interpreter_output = None

    return contexts


# ═══════════════════════════════════════════════════════════════════════════
# 5. resolve_document_dates (Layer 3)
# ═══════════════════════════════════════════════════════════════════════════

async def resolve_document_dates(
    contexts: list[ClauseWithContext],
    timelines: dict[str, FieldTimeline],
    evaluation_date: date,
    openai_client: Any,
    condition_cache: dict[str, tuple[str, Any]],
) -> list[ClauseWithContext]:
    """Resolve document_date for each clause.

    Priority:
    1. source_effective_date (if present and no condition)
    2. source_effective_date_condition → LLM → AST → evaluate
    3. source_signed_date (fallback)
    """
    for ctx in contexts:
        logger.info(
            "resolve_doc_dates: clause='%s' eff=%s cond=%s signed=%s",
            ctx.clause_text[:50], ctx.source_effective_date,
            ctx.source_effective_date_condition, ctx.source_signed_date,
        )
        if (
            ctx.source_effective_date is not None
            and ctx.source_effective_date_condition is None
        ):
            ctx.resolved_document_date = ctx.source_effective_date
            logger.info("  -> path 1 (effective_date): %s", ctx.resolved_document_date)

        elif ctx.source_effective_date_condition is not None:
            # Enrich the condition text with signed date so the LLM
            # knows the reference point for relative expressions like
            # "next fiscal quarter" or "the following year".
            raw_cond = ctx.source_effective_date_condition
            if ctx.source_signed_date:
                condition_text = (
                    f"{raw_cond} (document signed {ctx.source_signed_date})"
                )
            else:
                condition_text = raw_cond
            condition_hash = hashlib.sha256(condition_text.encode()).hexdigest()

            # Check cache
            if condition_hash in condition_cache:
                output_type, ast_node = condition_cache[condition_hash]
            else:
                try:
                    output_type, ast_node = await resolve_date_condition(
                        condition_text, openai_client
                    )
                    condition_cache[condition_hash] = (output_type, ast_node)
                except Exception:
                    logger.exception(
                        "Failed to resolve date condition, falling back to "
                        "source_signed_date: %s", ctx.clause_text[:80],
                    )
                    ctx.resolved_document_date = ctx.source_signed_date
                    continue

            signed = _safe_parse_date(ctx.source_signed_date)

            if output_type == "date":
                # AST evaluates to a concrete date
                temp_ctx = EvaluationContext(
                    evaluation_date=evaluation_date,
                    document_date=signed,
                )
                resolved = evaluate_ast(ast_node, timelines, temp_ctx)
                if resolved is not None:
                    ctx.resolved_document_date = (
                        str(resolved) if not isinstance(resolved, str) else resolved
                    )
                else:
                    logger.warning(
                        "Date condition AST evaluated to None, falling back: %s",
                        ctx.clause_text[:80],
                    )
                    ctx.resolved_document_date = ctx.source_signed_date

            elif output_type == "boolean":
                # AST evaluates to True/False — find first TRUE date
                if signed is None:
                    logger.warning(
                        "Boolean condition with no signed_date, skipping: %s",
                        ctx.clause_text[:80],
                    )
                    ctx.resolved_document_date = None
                    continue

                first_true = _find_first_true_date(
                    ast_node, timelines, signed, evaluation_date
                )
                if first_true is not None:
                    ctx.resolved_document_date = str(first_true)
                else:
                    # Condition never met — clause not yet effective
                    ctx.resolved_document_date = None

        else:
            ctx.resolved_document_date = ctx.source_signed_date
            logger.info("  -> path 3 (signed_date): %s", ctx.resolved_document_date)

    return contexts


# ═══════════════════════════════════════════════════════════════════════════
# 6. resolve_confirmations (Layer 4)
# ═══════════════════════════════════════════════════════════════════════════

async def resolve_confirmations(
    contexts: list[ClauseWithContext],
    all_intents: list[tuple[DocumentIntent, str | None]],
    all_email_dates: dict[str, str],
    timelines: dict[str, FieldTimeline],
    evaluation_date: date,
    openai_client: Any,
    condition_cache: dict[str, tuple[str, Any]],
) -> list[ClauseWithContext]:
    """Match confirmation intents to clauses that require them."""
    for ctx in contexts:
        intent = ctx.document_intent
        if intent is None or not intent.confirmation_required:
            ctx.is_confirmed = True
            logger.debug("Layer4: clause '%s' → no confirmation needed", ctx.clause_text[:60])
            continue

        source_email_date = all_email_dates.get(ctx.email_source_id)
        logger.info(
            "Layer4: clause '%s' needs confirmation | intent_type=%s email_date=%s email_source_id=%s",
            ctx.clause_text[:60], intent.intent_type, source_email_date, ctx.email_source_id,
        )

        # Find confirming intent
        confirming: DocumentIntent | None = None
        confirming_date: str | None = None
        for other_intent, confirming_email_date in all_intents:
            if other_intent.references is None:
                logger.debug("  skip: no references")
                continue
            if other_intent.binding_status not in ("binding", "supersedes_prior"):
                logger.debug("  skip: binding_status=%s", other_intent.binding_status)
                continue
            if other_intent.intent_type not in ("confirmation", "partial_acceptance"):
                logger.debug("  skip: intent_type=%s", other_intent.intent_type)
                continue

            # Skip confirmations dated after evaluation_date
            if confirming_email_date:
                try:
                    conf_date = date.fromisoformat(confirming_email_date.split("T")[0])
                    if conf_date > evaluation_date:
                        logger.info("  skip: confirming email dated %s > eval_date %s", conf_date, evaluation_date)
                        continue
                except ValueError:
                    pass

            ref = other_intent.references
            logger.info(
                "  candidate: intent_type=%s binding=%s ref.doc_type=%s ref.ref_date=%s (need doc_type~=%s ref_date=%s)",
                other_intent.intent_type, other_intent.binding_status,
                ref.document_type, ref.reference_date,
                intent.intent_type, source_email_date,
            )
            # Flexible document_type matching: "mfn_election" matches "election",
            # "mfn_disclosure" matches "offer"/"disclosure", etc.
            ref_type = (ref.document_type or "").lower().replace("_", " ")
            target_type = (intent.intent_type or "").lower()
            type_match = (
                ref.document_type == intent.intent_type           # exact match
                or target_type in ref_type                        # "election" in "mfn_election"
                or ref_type.endswith(target_type)                 # "mfn election" ends with "election"
                or (target_type == "offer" and "disclosure" in ref_type)  # offer ↔ disclosure
            )
            if type_match:
                if ref.reference_date == source_email_date:
                    logger.info("  MATCH FOUND (ref_type=%s ~ target=%s)", ref.document_type, intent.intent_type)
                    confirming = other_intent
                    confirming_date = confirming_email_date
                    break
                else:
                    logger.info("  ref_date mismatch: %s != %s", ref.reference_date, source_email_date)
            else:
                logger.info("  doc_type mismatch: %s !~ %s", ref.document_type, intent.intent_type)

        if confirming is None:
            logger.info("Layer4: clause '%s' → NOT CONFIRMED (no matching confirming document)", ctx.clause_text[:60])
            ctx.is_confirmed = False
            continue

        logger.info("Layer4: clause '%s' → CONFIRMED", ctx.clause_text[:60])
        ctx.is_confirmed = True

        # Apply effective date override if present
        if confirming.references and confirming.references.confirmed_effective_date is not None:
            ctx.resolved_document_date = confirming.references.confirmed_effective_date
        elif (
            confirming.references
            and confirming.references.confirmed_effective_date_condition is not None
        ):
            # Enrich with confirming email date for relative expression context
            raw_cond = confirming.references.confirmed_effective_date_condition
            if confirming_date:
                condition_text = f"{raw_cond} (document signed {confirming_date})"
            else:
                condition_text = raw_cond
            condition_hash = hashlib.sha256(condition_text.encode()).hexdigest()

            # Check cache
            if condition_hash in condition_cache:
                output_type, ast_node = condition_cache[condition_hash]
            else:
                try:
                    output_type, ast_node = await resolve_date_condition(
                        condition_text, openai_client
                    )
                    condition_cache[condition_hash] = (output_type, ast_node)
                except Exception:
                    logger.exception(
                        "Failed to resolve confirmed_effective_date_condition: %s",
                        ctx.clause_text[:280],
                    )
                    continue  # Keep existing resolved_document_date

            signed = _safe_parse_date(ctx.source_signed_date)

            if output_type == "date":
                temp_ctx = EvaluationContext(
                    evaluation_date=evaluation_date,
                    document_date=signed,
                )
                resolved = evaluate_ast(ast_node, timelines, temp_ctx)
                if resolved is not None:
                    ctx.resolved_document_date = (
                        str(resolved) if not isinstance(resolved, str) else resolved
                    )

            elif output_type == "boolean":
                if signed is not None:
                    first_true = _find_first_true_date(
                        ast_node, timelines, signed, evaluation_date
                    )
                    if first_true is not None:
                        ctx.resolved_document_date = str(first_true)
                    else:
                        ctx.resolved_document_date = None

    return contexts


# ═══════════════════════════════════════════════════════════════════════════
# 7. Helpers for evaluate
# ═══════════════════════════════════════════════════════════════════════════

def _adjust_seed_for_structural_dates(
    timelines: dict[str, FieldTimeline],
    evaluation_date: date,
) -> None:
    """After execution, update LPA seed entries whose start/end dates
    are anchored to structural fields (fund_investment_end_date).

    The LPA says "2.0% during investment period, 1.5% post investment
    period". If a clause extends the investment period from 2029-01-15
    to 2030-01-15, the seed entries' transition dates must shift too.
    """
    inv_end_tl = timelines.get("fund_investment_end_date")
    if inv_end_tl is None:
        return
    raw_val = inv_end_tl.value_at(evaluation_date)
    if raw_val is None:
        return
    try:
        inv_end = date.fromisoformat(str(raw_val)) if not isinstance(raw_val, date) else raw_val
    except ValueError:
        return

    for fname in ("management_fee_rate", "management_fee_basis"):
        ft = timelines.get(fname)
        if ft is None:
            continue
        for entry in ft.entries:
            if "during investment period" in entry.source_clause_text:
                entry.end_date = inv_end
            elif "post investment period" in entry.source_clause_text:
                entry.date = inv_end
        ft.entries.sort(key=lambda e: e.date)


def _build_timelines() -> dict[str, FieldTimeline]:
    """Build fresh timelines from seed data only.

    Extracted fields are inserted separately via insert_extracted_fields()
    (async, for value_as_of_condition LLM resolution).
    """
    timelines: dict[str, FieldTimeline] = {}
    for field_name, entries in SEED_TIMELINES.items():
        ft = FieldTimeline()
        for entry in entries:
            seed_date = entry["date"]
            if isinstance(seed_date, str):
                seed_date = date.fromisoformat(seed_date)
            end_date = entry.get("end_date")
            if isinstance(end_date, str):
                end_date = date.fromisoformat(end_date)
            ft.insert_entry(TimelineEntry(
                date=seed_date,
                end_date=end_date,
                value=entry["value"],
                source_clause_text=entry.get("source", "LPA"),
                entry_type="SET",
            ))
        timelines[field_name] = ft
    return timelines


def _recompute_ordering_and_filter(
    contexts: list[ClauseWithContext],
    evaluation_date: date,
) -> list[ClauseWithContext]:
    """Recompute ordering keys and filter to executable clauses."""
    for i, ctx in enumerate(contexts):
        ctx.ordering_key = _compute_ordering_key(
            ctx.resolved_document_date,
            ctx.source_signed_date,
            ctx.attachment_index,
            i,
        )

    executable: list[ClauseWithContext] = []
    for ctx in contexts:
        if not ctx.is_confirmed:
            continue
        if ctx.resolved_document_date is None:
            logger.warning(
                "Skipping clause with no resolved_document_date: %s",
                ctx.clause_text[:80],
            )
            continue
        doc_date = (
            date.fromisoformat(ctx.resolved_document_date)
            if isinstance(ctx.resolved_document_date, str)
            else ctx.resolved_document_date
        )
        if doc_date > evaluation_date:
            continue
        executable.append(ctx)

    executable.sort(key=lambda c: c.ordering_key)
    return executable


def _execute_clauses(
    executable: list[ClauseWithContext],
    timelines: dict[str, FieldTimeline],
    evaluation_date: date,
    skip_clause_texts: set[str] | None = None,
) -> None:
    """Execute clause instructions sequentially. Modifies timelines in place.

    Args:
        skip_clause_texts: if provided, skip instructions whose clause_text
            is in this set (used to skip self-referential instructions on
            stability re-passes — their frozen result is already in the
            timeline from carry-forward).
    """
    eval_ctx = EvaluationContext(
        evaluation_date=evaluation_date,
        fund_data={},
    )

    for clause_ctx in executable:
        if clause_ctx.interpreter_output is None:
            continue

        doc_date = clause_ctx.resolved_document_date
        if isinstance(doc_date, str):
            doc_date = date.fromisoformat(doc_date)
        eval_ctx.document_date = doc_date

        for instruction in clause_ctx.interpreter_output:
            if skip_clause_texts and instruction.clause_text in skip_clause_texts:
                continue
            execute(instruction, timelines, eval_ctx)


def _snapshot_conditional_dates(
    contexts: list[ClauseWithContext],
) -> dict[str, str | None]:
    """Snapshot resolved_document_date for clauses whose date may change.

    Includes:
    - Clauses with source_effective_date_condition (Layer 3 may re-resolve)
    - Clauses requiring confirmation (Layer 4 may override via
      confirmed_effective_date_condition on the confirming document)
    """
    result: dict[str, str | None] = {}
    for ctx in contexts:
        has_condition = ctx.source_effective_date_condition is not None
        needs_confirmation = (
            ctx.document_intent is not None
            and ctx.document_intent.confirmation_required
        )
        if has_condition or needs_confirmation:
            result[ctx.clause_id] = ctx.resolved_document_date
    return result


def _snapshot_field_ref_values(
    executable: list[ClauseWithContext],
    timelines: dict[str, FieldTimeline],
    evaluation_date: date,
) -> dict[str, list]:
    """Snapshot all resolved values from field_ref AST expressions in clause instructions.

    For each clause, evaluates effective_date_expr, effective_end_date_expr,
    and value_expr against the current timelines. Returns a dict of
    clause_id → list of resolved values. If any value changes between passes,
    the clauses need re-execution.
    """
    from engine.timeline_engine import evaluate_ast, EvaluationContext

    result: dict[str, list] = {}
    for ctx in executable:
        if ctx.interpreter_output is None:
            continue

        doc_date = ctx.resolved_document_date
        if isinstance(doc_date, str):
            doc_date = date.fromisoformat(doc_date)

        eval_ctx = EvaluationContext(
            evaluation_date=evaluation_date,
            document_date=doc_date,
        )

        values: list = []
        for instr in ctx.interpreter_output:
            for expr in [
                instr.effective_date_expr,
                instr.effective_end_date_expr,
                instr.value_expr,
                instr.gate_move_to_date_expr,
                instr.gate_new_end_date_expr,
            ]:
                if expr is not None:
                    try:
                        val = evaluate_ast(expr, timelines, eval_ctx)
                        values.append(str(val) if val is not None else None)
                    except Exception:
                        values.append("__error__")

        result[ctx.clause_id] = values

    return result


MAX_STABILITY_PASSES = 3


# ═══════════════════════════════════════════════════════════════════════════
# 8. evaluate — main entry point
# ═══════════════════════════════════════════════════════════════════════════

async def evaluate(
    session_id: str,
    extraction_results: list[ExtractionResult],
    evaluation_date_str: str,
    openai_client: Any,
    lp_admission_date_str: str | None = None,
    on_progress: Any = None,
    email_dates_by_id: dict[str, str] | None = None,
) -> dict:
    """Run layers 2-5 of the pipeline and return timelines + metadata.

    Layer 1 (extraction) is handled by the caller (main.py) which
    passes validated ExtractionResult objects.

    Uses a stability loop: after executing all clauses, re-evaluate any
    date conditions against the post-execution timelines. If any conditions
    resolve to different dates (because they depended on clause outputs),
    recompute ordering and re-execute. Repeat until stable or max passes.

    Args:
        on_progress: optional async callable(stage: str, detail: str)
            for streaming progress updates to the frontend.
    """
    session = SESSIONS[session_id]
    session.last_accessed = time.time()  # Keep alive; don't let sweep evict us.
    evaluation_date = date.fromisoformat(evaluation_date_str)

    # ── Debug trace ──────────────────────────────────────────────────
    # Gated behind DEBUG_TRACE=1 — prod filesystems (Railway) are read-only
    # and/or ephemeral; enable only when you need the local trace file.
    import os as _os
    _trace_enabled = _os.getenv("DEBUG_TRACE") == "1"
    _trace_lines: list[str] = []

    def _trace(msg: str):
        if _trace_enabled:
            _trace_lines.append(msg)

    def _flush_trace():
        if not _trace_enabled:
            return
        _os.makedirs("debug_output", exist_ok=True)
        with open("debug_output/evaluate_trace.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(_trace_lines))

    _trace(f"{'='*80}")
    _trace(f"EVALUATE TRACE — {evaluation_date_str}")
    _trace(f"Session: {session_id}")
    _trace(f"Extraction results: {len(extraction_results)} emails")
    _trace(f"LP admission: {lp_admission_date_str}")
    _trace(f"{'='*80}")

    # Log extracted clauses
    for ei, er in enumerate(extraction_results):
        _trace(f"\n--- Extraction {ei} ---")
        _trace(f"  Fields: {list(er.extracted_fields.keys())}")
        _trace(f"  Clauses: {len(er.clauses)}")
        for ci, cl in enumerate(er.clauses):
            _trace(f"    [{ci}] {cl.clause_text}")
            _trace(f"        doc_type={cl.doc_type} signed={cl.source_signed_date} eff={cl.source_effective_date} cond={cl.source_effective_date_condition}")
        _trace(f"  Intents: {len(er.document_intent)}")
        for di in er.document_intent:
            _trace(f"    intent={di.intent_type} binding={di.binding_status} confirm_req={di.confirmation_required}")

    try:
      return await _evaluate_inner(
          extraction_results, evaluation_date, session, openai_client,
          lp_admission_date_str, on_progress, _trace, _flush_trace,
          email_dates_by_id or {},
      )
    except Exception:
        _trace(f"\n\nPIPELINE CRASHED — see traceback in server logs")
        raise
    finally:
        _flush_trace()


async def _evaluate_inner(
    extraction_results, evaluation_date, session, openai_client,
    lp_admission_date_str, on_progress, _trace, _flush_trace,
    email_dates_by_id: dict[str, str],
):
    """Inner evaluate logic — separated so try/finally can flush trace."""
    async def _progress(stage: str, detail: str = ""):
        if on_progress:
            await on_progress(stage, detail)

    # ── Layer 2: Clause interpretation (parallel) ──────────────────────
    import asyncio as _asyncio
    contexts = build_clause_contexts(extraction_results)
    total_clauses = len(contexts)
    _trace(f"\n{'='*80}")
    _trace(f"LAYER 2: CLAUSE INTERPRETATION ({total_clauses} clauses)")
    _trace(f"{'='*80}")

    # Split into cached vs uncached
    uncached: list[tuple[int, ClauseWithContext, str]] = []
    for ci, ctx in enumerate(contexts):
        clause_hash = hashlib.sha256(ctx.clause_text.encode()).hexdigest()
        if clause_hash in session.interpreter_cache:
            ctx.interpreter_output = session.interpreter_cache[clause_hash]
            _trace(f"\n  [{ci}] CACHED: {ctx.clause_text[:200]}")
        else:
            uncached.append((ci, ctx, clause_hash))

    if uncached:
        await _progress("layer2", f"Interpreting {len(uncached)} clauses in parallel ({total_clauses - len(uncached)} cached)...")

        async def _interpret_one(ci, ctx, clause_hash):
            try:
                result = await interpret_clause(ctx.clause_text, openai_client)
                ctx.interpreter_output = result
                session.interpreter_cache[clause_hash] = result
                _trace(f"\n  [{ci}] LLM: {ctx.clause_text[:280]}")
            except Exception:
                logger.exception("Clause interpretation failed: %s", ctx.clause_text[:280])
                ctx.interpreter_output = None
                _trace(f"\n  [{ci}] FAILED: {ctx.clause_text[:280]}")

        await _asyncio.gather(*[
            _interpret_one(ci, ctx, h) for ci, ctx, h in uncached
        ])
    else:
        await _progress("layer2", f"All {total_clauses} clauses cached")

    # Log full interpretation output for all contexts
    for ci, ctx in enumerate(contexts):
        _trace(f"\n  Clause [{ci}]: {ctx.clause_text}")
        _trace(f"    signed={ctx.source_signed_date} eff={ctx.source_effective_date} cond={ctx.source_effective_date_condition}")
        if ctx.interpreter_output:
            _trace(f"    Instructions: {len(ctx.interpreter_output)}")
            for ii, instr in enumerate(ctx.interpreter_output):
                _trace(f"    [{ii}] action={instr.action} field={instr.affected_field}")
                if instr.effective_date_expr:
                    _trace(f"        eff_date_expr={instr.effective_date_expr.model_dump_json()}")
                if instr.effective_end_date_expr:
                    _trace(f"        eff_end_expr={instr.effective_end_date_expr.model_dump_json()}")
                if instr.value_expr:
                    _trace(f"        value_expr={instr.value_expr.model_dump_json()}")
                if instr.condition_ast:
                    _trace(f"        condition_ast={instr.condition_ast.model_dump_json()}")
                if instr.gate_move_to_date_expr:
                    _trace(f"        gate_move={instr.gate_move_to_date_expr.model_dump_json()}")
                if instr.gate_new_end_date_expr:
                    _trace(f"        gate_new_end={instr.gate_new_end_date_expr.model_dump_json()}")
                if instr.gate_target:
                    _trace(f"        gate_target={instr.gate_target} scope={instr.gate_scope_mode} direction={instr.gate_direction}")
                if instr.adjust_direction:
                    _trace(f"        adjust_direction={instr.adjust_direction}")
                if instr.constraint_type:
                    _trace(f"        constraint_type={instr.constraint_type}")
                if instr.no_action_reason:
                    _trace(f"        reason={instr.no_action_reason}")
                if instr.manual_review_reason:
                    _trace(f"        manual_review={instr.manual_review_reason}")
        else:
            _trace(f"    Instructions: None (failed)")

    await _progress("layer2", f"Interpreted {total_clauses} clauses")

    # ── Build intents lookup (constant across passes) ─────────────────
    # Each intent is paired with its source email date for temporal filtering
    all_intents: list[tuple[DocumentIntent, str | None]] = []
    all_email_dates: dict[str, str] = {}
    for er in extraction_results:
        # Find the email date for this extraction result
        er_email_date = None
        for clause in er.clauses:
            if clause.email_source_id and clause.source_signed_date:
                er_email_date = clause.source_signed_date
                break
        for intent in er.document_intent:
            all_intents.append((intent, er_email_date))
        for clause in er.clauses:
            if clause.email_source_id and clause.source_signed_date:
                all_email_dates[clause.email_source_id] = clause.source_signed_date

    # ── Initial pass: resolve + execute ───────────────────────────────
    await _progress("layer3", "Building timelines from seed data...")
    timelines = _build_timelines()
    await insert_extracted_fields(
        timelines, extraction_results, evaluation_date,
        openai_client, session.condition_cache, email_dates_by_id,
    )

    _trace(f"\n{'='*80}")
    _trace(f"SEED TIMELINES (after extracted fields)")
    _trace(f"{'='*80}")
    for fname, ft in timelines.items():
        if ft.entries:
            _trace(f"\n  {fname}:")
            for e in ft.entries:
                end_s = f" end={e.end_date}" if e.end_date else ""
                _trace(f"    {e.date} -> {e.value}{end_s}  ({e.source_clause_text[:50]})")

    # Layer 3: Resolve document dates
    _trace(f"\n{'='*80}")
    _trace(f"LAYER 3: DOCUMENT DATE RESOLUTION")
    _trace(f"{'='*80}")
    await _progress("layer3", "Resolving document dates...")
    contexts = await resolve_document_dates(
        contexts, timelines, evaluation_date,
        openai_client, session.condition_cache,
    )

    for ctx in contexts:
        _trace(f"  clause: {ctx.clause_text}")
        _trace(f"    signed={ctx.source_signed_date} eff={ctx.source_effective_date} cond={ctx.source_effective_date_condition}")
        _trace(f"    -> resolved_document_date = {ctx.resolved_document_date}")

    # Layer 4: Resolve confirmations
    _trace(f"\n{'='*80}")
    _trace(f"LAYER 4: CONFIRMATION RESOLUTION")
    _trace(f"{'='*80}")
    _trace(f"\n  All intents available ({len(all_intents)} total):")
    for intent_obj, intent_email_date in all_intents:
        _trace(f"    intent_type={intent_obj.intent_type} binding={intent_obj.binding_status} confirm_req={intent_obj.confirmation_required} email_date={intent_email_date}")
        if intent_obj.references:
            ref = intent_obj.references
            _trace(f"      references: doc_type={ref.document_type} ref_date={ref.reference_date} signals={ref.reference_signals}")
            _trace(f"      confirmed_eff_date={ref.confirmed_effective_date} confirmed_eff_cond={ref.confirmed_effective_date_condition}")
    _trace(f"\n  Email dates map: {all_email_dates}")
    await _progress("layer4", "Resolving confirmations...")
    contexts = await resolve_confirmations(
        contexts, all_intents, all_email_dates,
        timelines, evaluation_date,
        openai_client, session.condition_cache,
    )

    _trace(f"\n  Results:")
    for ctx in contexts:
        _trace(f"  confirmed={ctx.is_confirmed} date={ctx.resolved_document_date} | {ctx.clause_text}")

    # Compute ordering, filter, execute
    _trace(f"\n{'='*80}")
    _trace(f"LAYER 5: EXECUTION")
    _trace(f"{'='*80}")
    await _progress("layer5", "Executing clause instructions...")
    executable = _recompute_ordering_and_filter(contexts, evaluation_date)

    _trace(f"  Executable clauses: {len(executable)} (of {len(contexts)} total)")
    for i, ctx in enumerate(executable):
        _trace(f"\n  EXECUTE [{i}] ordering_key={ctx.ordering_key} doc_date={ctx.resolved_document_date}")
        _trace(f"    clause: {ctx.clause_text[:80]}")
        if ctx.interpreter_output:
            for instr in ctx.interpreter_output:
                _trace(f"    -> {instr.action} on {instr.affected_field}")

    _adjust_seed_for_structural_dates(timelines, evaluation_date)
    _execute_clauses(executable, timelines, evaluation_date)

    _trace(f"\n--- Timelines after execution ---")
    for fname, ft in timelines.items():
        if ft.entries:
            _trace(f"\n  {fname}:")
            for e in ft.entries:
                end_s = f" end={e.end_date}" if e.end_date else ""
                _trace(f"    {e.date} -> {e.value}{end_s}  (order={e.insertion_order}) ({e.source_clause_text[:50]})")
            if ft.constraints:
                for c in ft.constraints:
                    _trace(f"    CONSTRAINT: {c.type} bound={c.bound} from={c.active_from} until={c.active_until} order={c.insertion_order}")

    # ── Stability loop ────────────────────────────────────────────────
    # After execution, clause B may have SET a field that clause A
    # references via field_ref. On re-execution, clause A should see
    # clause B's output — but A runs before B (earlier ordering_key).
    #
    # Fix: identify which fields are REFERENCED via field_ref across
    # all clause instructions. After execution, carry forward ONLY
    # those fields' clause-produced entries into the next pass's
    # fresh timelines. This lets earlier clauses read later clauses'
    # outputs from the previous pass.
    await _progress("stability", "Checking stability...")

    # Collect all fields referenced via field_ref in clause AST expressions
    def _collect_field_refs(node):
        if node is None:
            return set()
        refs = set()
        if node.node_type == "field_ref" and node.field:
            refs.add(node.field)
        if node.args:
            for arg in node.args:
                refs.update(_collect_field_refs(arg))
        return refs

    referenced_fields: set[str] = set()
    # Detect self-referential instructions: instruction reads AND writes
    # the same field (e.g., SET fund_term_end_date = ADD_YEARS(fund_term_end_date, 1)).
    #
    # These need special handling in the stability loop:
    # - Their pass-1 result is FROZEN and carried forward on every pass
    #   (so other clauses can see the updated value)
    # - They are SKIPPED on re-execution passes (so they don't re-read
    #   their own output and create an infinite x = x + 1 loop)
    self_ref_clause_texts: set[str] = set()
    for ctx in executable:
        if not ctx.interpreter_output:
            continue
        for instr in ctx.interpreter_output:
            instr_refs = set()
            for expr in [instr.effective_date_expr, instr.effective_end_date_expr,
                         instr.value_expr, instr.gate_move_to_date_expr,
                         instr.gate_new_end_date_expr, instr.condition_ast]:
                instr_refs.update(_collect_field_refs(expr))
            if instr.affected_field and instr.affected_field in instr_refs:
                self_ref_clause_texts.add(instr.clause_text)
                instr_refs.discard(instr.affected_field)
            referenced_fields.update(instr_refs)
    referenced_fields.discard("evaluation_date")
    referenced_fields.discard("document_date")

    # Freeze self-referential entries from the initial execution.
    # These are the correct "execute once" results that get carried
    # forward on every stability pass without re-computation.
    frozen_self_ref: list[tuple[str, TimelineEntry]] = []  # (field_name, entry)
    if self_ref_clause_texts:
        for fname, ft in timelines.items():
            for entry in ft.entries:
                if entry.source_clause_text in self_ref_clause_texts:
                    frozen_self_ref.append((fname, entry))

    _trace(f"\n  Stability: referenced fields = {referenced_fields}")
    if self_ref_clause_texts:
        _trace(f"  Stability: self-referential clauses (frozen after pass 1, skipped on re-execution): {len(self_ref_clause_texts)}")
        for ct in self_ref_clause_texts:
            _trace(f"    {ct[:280]}")

    def _timeline_snapshot(tls):
        snap = {}
        for fname, ft in tls.items():
            snap[fname] = [
                (str(e.date), str(e.end_date), str(e.value))
                for e in ft.entries
            ]
        return snap

    prev_snap = _timeline_snapshot(timelines)
    prev_cond_dates = _snapshot_conditional_dates(contexts)

    for pass_num in range(MAX_STABILITY_PASSES):
        # Re-resolve conditions against current timelines
        contexts = await resolve_document_dates(
            contexts, timelines, evaluation_date,
            openai_client, session.condition_cache,
        )
        contexts = await resolve_confirmations(
            contexts, all_intents, all_email_dates,
            timelines, evaluation_date,
            openai_client, session.condition_cache,
        )

        new_cond_dates = _snapshot_conditional_dates(contexts)

        # Save previous timelines for carry-forward
        prev_timelines = timelines

        # Rebuild fresh from seed + extracted fields
        timelines = _build_timelines()
        await insert_extracted_fields(
            timelines, extraction_results, evaluation_date,
            openai_client, session.condition_cache, email_dates_by_id,
        )

        # Carry forward ONLY entries for REFERENCED fields (not affected fields).
        # This lets clause A (which references fund_investment_end_date) see
        # clause B's output (which SETs fund_investment_end_date) from the
        # previous pass — even though B runs after A in document order.
        for fname in referenced_fields:
            ft = prev_timelines.get(fname)
            if ft is None:
                continue
            for entry in ft.entries:
                # Skip seed and extracted — already in fresh timelines
                if entry.source_clause_text.startswith("LPA"):
                    continue
                if entry.source_clause_text.startswith("Extracted"):
                    continue
                # Skip entries that are themselves carry-forwards from a
                # prior pass — only carry fresh clause-execution entries.
                # Without this, entries accumulate every pass and the
                # snapshot never matches → loop never converges.
                if "[prior pass]" in entry.source_clause_text:
                    continue
                # Skip self-referential entries — they are handled
                # separately via frozen_self_ref below.
                if entry.source_clause_text in self_ref_clause_texts:
                    continue
                src = entry.source_clause_text

                if fname not in timelines:
                    timelines[fname] = FieldTimeline()
                timelines[fname].insert_entry(TimelineEntry(
                    date=entry.date,
                    end_date=entry.end_date,
                    value=entry.value,
                    source_clause_text=src + " [prior pass]",
                    entry_type=entry.entry_type,
                    direction=entry.direction,
                ))

        # Carry forward FROZEN self-referential entries. These are the
        # pass-1 results that never change — they provide the correct
        # value for other clauses to read without re-executing the
        # self-referential instruction (which would create x = x + 1).
        for fname, entry in frozen_self_ref:
            if fname not in timelines:
                timelines[fname] = FieldTimeline()
            timelines[fname].insert_entry(TimelineEntry(
                date=entry.date,
                end_date=entry.end_date,
                value=entry.value,
                source_clause_text=entry.source_clause_text,
                entry_type=entry.entry_type,
                direction=entry.direction,
            ))

        executable = _recompute_ordering_and_filter(contexts, evaluation_date)
        _adjust_seed_for_structural_dates(timelines, evaluation_date)
        # Skip self-referential instructions — their frozen result is
        # already in the timeline from the carry-forward above.
        _execute_clauses(executable, timelines, evaluation_date,
                         skip_clause_texts=self_ref_clause_texts)

        new_snap = _timeline_snapshot(timelines)

        cond_changed = new_cond_dates != prev_cond_dates
        tl_changed = new_snap != prev_snap

        if not cond_changed and not tl_changed:
            _trace(f"\n  Stability: converged after pass {pass_num + 1}")
            await _progress("stability", "Stable")
            logger.info("Pipeline stable after pass %d", pass_num + 1)
            break

        reason = []
        if cond_changed:
            reason.append("condition dates")
        if tl_changed:
            # Log which fields changed
            for fname in set(list(prev_snap.keys()) + list(new_snap.keys())):
                if prev_snap.get(fname) != new_snap.get(fname):
                    _trace(f"\n  Stability: {fname} changed")
                    _trace(f"    prev: {prev_snap.get(fname)}")
                    _trace(f"    new:  {new_snap.get(fname)}")
            reason.append("timeline entries")
        reason_str = " + ".join(reason)

        _trace(f"\n  Stability: pass {pass_num + 1} changed: {reason_str}")
        await _progress("stability", f"Pass {pass_num + 1}: {reason_str} changed...")
        logger.info("Pass %d: %s changed", pass_num + 1, reason_str)

        prev_snap = new_snap
        prev_cond_dates = new_cond_dates
    else:
        logger.warning("Pipeline did not converge after %d passes", MAX_STABILITY_PASSES)

    # ── Fee calculation ─────────────────────────────────────────────────
    _trace(f"\n{'='*80}")
    _trace(f"FEE CALCULATION")
    _trace(f"{'='*80}")
    await _progress("fees", "Calculating management fees...")
    lp_admission_date = None
    if lp_admission_date_str:
        try:
            lp_admission_date = date.fromisoformat(lp_admission_date_str)
        except ValueError:
            logger.warning("Invalid lp_admission_date_str: %s", lp_admission_date_str)

    fee_response: dict | None = None
    try:
        fee_result = compute_management_fee(
            timelines, evaluation_date, lp_admission_date,
        )
        fee_response = {
            "billing_period_start": str(fee_result.billing_period_start),
            "billing_period_end": str(fee_result.billing_period_end),
            "billing_cadence": fee_result.billing_cadence,
            "anchor_date": str(fee_result.anchor_date),
            "lp_admission_date": str(fee_result.lp_admission_date),
            "current_period": {
                "period_start": str(fee_result.current_period_fee.period_start),
                "period_end": str(fee_result.current_period_fee.period_end),
                "total_fee": fee_result.current_period_fee.total_fee,
                "sub_periods": [
                    {
                        "start": str(sp.start),
                        "end": str(sp.end),
                        "days": sp.days,
                        "annual_rate": sp.annual_rate,
                        "basis_label": sp.basis_label,
                        "basis_amount": sp.basis_amount,
                        "fee_amount": sp.fee_amount,
                        "source_clause": sp.source_clause,
                    }
                    for sp in fee_result.current_period_fee.sub_periods
                ],
            },
            "catchup": None,
            "day_count_convention": fee_result.day_count_convention,
            "assumptions": fee_result.assumptions,
        }
        if fee_result.catchup_fee is not None:
            fee_response["catchup"] = {
                "period_start": str(fee_result.catchup_period_start),
                "period_end": str(fee_result.catchup_period_end),
                "total_fee": fee_result.catchup_fee.total_fee,
                "sub_periods": [
                    {
                        "start": str(sp.start),
                        "end": str(sp.end),
                        "days": sp.days,
                        "annual_rate": sp.annual_rate,
                        "basis_label": sp.basis_label,
                        "basis_amount": sp.basis_amount,
                        "fee_amount": sp.fee_amount,
                        "source_clause": sp.source_clause,
                    }
                    for sp in fee_result.catchup_fee.sub_periods
                ],
            }
        _trace(f"  Billing period: {fee_result.billing_period_start} to {fee_result.billing_period_end}")
        _trace(f"  Cadence: {fee_result.billing_cadence}")
        _trace(f"  LP admission: {fee_result.lp_admission_date}")
        _trace(f"  Current period fee: ${fee_result.current_period_fee.total_fee:.2f}")
        for sp in fee_result.current_period_fee.sub_periods:
            _trace(f"    {sp.start} to {sp.end}: {sp.days}d @ {sp.annual_rate}% on {sp.basis_label}=${sp.basis_amount:,.0f} -> ${sp.fee_amount:.2f}  [{sp.source_clause[:40]}]")
        if fee_result.catchup_fee:
            _trace(f"  Catch-up fee: ${fee_result.catchup_fee.total_fee:.2f}")
            for sp in fee_result.catchup_fee.sub_periods:
                _trace(f"    {sp.start} to {sp.end}: {sp.days}d @ {sp.annual_rate}% on {sp.basis_label}=${sp.basis_amount:,.0f} -> ${sp.fee_amount:.2f}")

    except Exception as exc:
        logger.exception("Fee calculation failed")
        _trace(f"  FEE CALCULATION FAILED: {exc}")

    _trace(f"\n{'='*80}")
    _trace(f"TRACE COMPLETE")
    _trace(f"{'='*80}")
    _flush_trace()
    if os.getenv("DEBUG_TRACE") == "1":
        logger.info("Trace written to debug_output/evaluate_trace.txt")

    await _progress("done", "Building response...")

    # ── Compute fund_term_end_cap for timeline trimming ──────────────
    # Entries at or after this date represent periods after the fund ends
    # and should not appear in the timeline response.
    _fund_term_tl = timelines.get("fund_term_end_date")
    fund_term_end_cap: date | None = None
    if _fund_term_tl:
        _fte_val = _fund_term_tl.value_at(evaluation_date)
        if _fte_val is not None:
            fund_term_end_cap = (
                date.fromisoformat(str(_fte_val))
                if not isinstance(_fte_val, date) else _fte_val
            )

    # ── Build response (resolved timelines) ─────────────────────────
    # Instead of dumping raw entries (which can overlap), build a
    # flattened view where each segment shows what value_at() returns.
    timeline_response: dict[str, list[dict]] = {}
    for field_name, ft in timelines.items():
        if not ft.entries:
            continue

        # Collect all boundary dates (entry starts + end dates)
        boundaries: set[date] = set()
        for e in ft.entries:
            boundaries.add(e.date)
            if e.end_date:
                boundaries.add(e.end_date)

        sorted_dates = sorted(boundaries)
        if not sorted_dates:
            continue

        # Walk boundaries and build resolved segments
        resolved: list[dict] = []
        for i, d in enumerate(sorted_dates):
            # Skip entries starting at or after the fund's end date —
            # those represent periods after the fund has wound down.
            if fund_term_end_cap is not None and d >= fund_term_end_cap:
                continue

            val = ft.value_at(d)
            if val is None:
                continue

            # Find the winning entry for source info + unconstrained value
            candidates = [
                e for e in ft.entries
                if e.date <= d and (e.end_date is None or d < e.end_date)
            ]
            winner = max(candidates, key=lambda e: e.insertion_order) if candidates else None
            raw_value = winner.value if winner else val

            # Determine end: next boundary where value changes, or None
            end_date = None
            for nd in sorted_dates[i + 1:]:
                if fund_term_end_cap is not None and nd >= fund_term_end_cap:
                    # Don't look past fund end for next-change boundary
                    break
                next_val = ft.value_at(nd)
                if next_val != val:
                    end_date = nd
                    break
            # If value is same through all remaining boundaries, check if it expires
            if end_date is None and winner and winner.end_date:
                end_date = winner.end_date

            # Cap end_date at fund term end — open-ended entries should not
            # appear to extend past the fund's wind-down date.
            if fund_term_end_cap is not None:
                if end_date is None or end_date > fund_term_end_cap:
                    end_date = fund_term_end_cap

            # Skip if this segment duplicates the previous one
            if resolved and resolved[-1]["value"] == raw_value and resolved[-1]["date"] == str(d):
                continue

            # Merge with previous if same base value + same constraint effect and contiguous
            if (resolved and resolved[-1]["value"] == raw_value
                    and resolved[-1].get("effective_value") == (val if raw_value != val else None)
                    and resolved[-1].get("end_date") == str(d)):
                resolved[-1]["end_date"] = str(end_date) if end_date else None
                continue

            entry_dict = {
                "date": str(d),
                "end_date": str(end_date) if end_date else None,
                "value": raw_value,  # bar shows the base rate (what was SET)
                "source": winner.source_clause_text if winner else "",
                "email_source_id": winner.email_source_id if winner else None,
                "clause_id": winner.clause_id if winner else None,
            }
            # When a constraint changes the effective value, include both
            if raw_value != val:
                entry_dict["effective_value"] = val  # what you actually pay after CAP/FLOOR
            resolved.append(entry_dict)

        timeline_response[field_name] = resolved

    # ── Serialize constraints for frontend visualization ──────────────
    constraints_response: dict[str, list[dict]] = {}
    for field_name, ft in timelines.items():
        if not ft.constraints:
            continue
        constraints_response[field_name] = [
            {
                "type": c.type,
                "bound": c.bound,
                "active_from": str(c.active_from) if c.active_from else None,
                "active_until": str(c.active_until) if c.active_until else None,
                "source": c.source_clause_text,
            }
            for c in ft.constraints
        ]

    manual_review_items: list[dict] = []
    unconfirmed_docs: list[dict] = []
    for ctx_item in contexts:
        if ctx_item.interpreter_output:
            for instr in ctx_item.interpreter_output:
                if instr.action == "MANUAL_REVIEW":
                    manual_review_items.append({
                        "clause_text": instr.clause_text,
                        "reason": instr.manual_review_reason,
                        "affected_field": instr.affected_field,
                    })
        if not ctx_item.is_confirmed:
            unconfirmed_docs.append({
                "clause_text": ctx_item.clause_text[:100],
                "email_source_id": ctx_item.email_source_id,
                "doc_type": ctx_item.doc_type,
            })

    session.timelines = timelines
    session.evaluation_date = evaluation_date

    # Extract fund_term_end_date for frontend timeline bounds
    fund_term_end = None
    fte_tl = timelines.get("fund_term_end_date")
    if fte_tl:
        val = fte_tl.value_at(evaluation_date)
        if val is not None:
            fund_term_end = str(val) if not isinstance(val, str) else val

    return {
        "timelines": timeline_response,
        "constraints": constraints_response,
        "fund_term_end_date": fund_term_end,
        "fee_calculation": fee_response,
        "assumptions": [
            *(["No documents in inbox. Timelines reflect LPA baseline terms only. "
               "Add emails with side letters, amendments, or fund reports to see "
               "how they affect fee calculations."]
              if not extraction_results or all(
                  not er.clauses and not any(er.extracted_fields.values())
                  for er in extraction_results
              ) else []),
            "Fund term and commitment period start at initial closing "
            "(per standard LPA terms)",
            "Fiscal quarters are anchored to the fund's initial closing date",
            "For runtime boolean conditions (e.g., 'effective when realization "
            "hits 50%'), the system finds the earliest available data point "
            "where the condition is met.",
        ],
        "manual_review_items": manual_review_items,
        "unconfirmed_documents": unconfirmed_docs,
        "stats": {
            "total_clauses": len(contexts),
            "executed_clauses": len(executable),
            "confirmed": sum(1 for c in contexts if c.is_confirmed),
            "unconfirmed": sum(1 for c in contexts if not c.is_confirmed),
            "manual_review": len(manual_review_items),
        },
    }


