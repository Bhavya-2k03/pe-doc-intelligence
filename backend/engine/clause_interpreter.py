from __future__ import annotations

import json
import logging
import os
import re
from typing import TYPE_CHECKING
from dotenv import load_dotenv
import asyncio

from engine.models import ASTNode, ClauseInstruction, parse_clause_instructions
from prompts import CLAUSE_INTERPRETER_PROMPT, EFFECTIVE_DATE_CONDITION_PROMPT

if TYPE_CHECKING:
    from openai import AsyncOpenAI

load_dotenv()
logger = logging.getLogger(__name__)


# Textual cues that a clause bounds its effect to a time window. If any
# SET/ADJUST/CONSTRAIN instruction comes back with a null
# effective_end_date_expr while the clause text carries one of these cues,
# the end date was likely dropped by the LLM (null is also the legal value
# for "permanent", so schema validation cannot catch the omission).
_BOUNDED_DURATION_CUE = re.compile(
    r"\b("
    r"until|through|during|ending|expir\w+"
    r"|for the period"
    r"|for the (?:first|second|third|fourth) quarter"
    r"|for Q[1-4]"
    r"|for the month"
    r")\b",
    re.IGNORECASE,
)

# Dev instrumentation: how often the missing-end-date backstop fired and
# whether the single retry recovered an end date.
RETRY_STATS = {"triggered": 0, "recovered": 0}


def _missing_bounded_end(
    instructions: list[ClauseInstruction], clause_text: str
) -> bool:
    """True if the clause signals a bounded window but no end date came back.

    Only SET/ADJUST/CONSTRAIN are checked — GATE must not carry
    effective_end_date_expr, and NO_ACTION/MANUAL_REVIEW have no timeline
    effect.
    """
    if not _BOUNDED_DURATION_CUE.search(clause_text):
        return False
    return any(
        instr.action in ("SET", "ADJUST", "CONSTRAIN")
        and instr.effective_end_date_expr is None
        for instr in instructions
    )


async def _call_interpreter_llm(
    clause_text: str,
    openai_client: AsyncOpenAI,
) -> str:
    """Single LLM call for clause interpretation; returns the raw response."""
    user_message = f"<clause>\nclause_text: {clause_text}\n</clause>"

    # Reasoning effort for clause interpretation. Default "low": measured on
    # the e036 fee-waiver clause ("...for the period commencing January 1,
    # 2028 and ending at the end of the Investment Period") — at effort none
    # (temperature=0, no reasoning) the LLM dropped effective_end_date_expr
    # ~1 in 11 runs, making the waiver permanent (25% fee error). Same fix
    # class as EXTRACTION_REASONING_EFFORT in engine/extractor.py.
    # Override via INTERPRETER_REASONING_EFFORT; "none" restores the old
    # behavior.
    effort = os.getenv("INTERPRETER_REASONING_EFFORT", "low")
    sampling_kwargs: dict = (
        {"temperature": 0} if effort == "none" else {"reasoning_effort": effort}
    )

    response = await openai_client.chat.completions.create(
        model="gpt-5.2",
        messages=[
            {"role": "system", "content": CLAUSE_INTERPRETER_PROMPT},
            {"role": "user", "content": user_message},
        ],
        **sampling_kwargs,
    )
    return response.choices[0].message.content


async def interpret_clause(
    clause_text: str,
    openai_client: AsyncOpenAI,
) -> list[ClauseInstruction]:
    """Send clause_text to GPT 5.2 and return validated ClauseInstruction list.

    The LLM receives CLAUSE_INTERPRETER_PROMPT as the system message and the
    clause wrapped in <clause> tags as the user message.  Response is parsed
    and validated via parse_clause_instructions.

    Backstop: if the clause text signals a bounded duration but the parsed
    instructions carry no effective_end_date_expr, the call is retried
    exactly once (never more). The retry result is kept only if it recovers
    an end date; otherwise the first result stands.
    """
    try:
        raw_json = await _call_interpreter_llm(clause_text, openai_client)
    except Exception:
        logger.exception("OpenAI API call failed for clause: %.120s", clause_text)
        raise

    logger.debug("Interpreter raw response: %s", raw_json)
    instructions = parse_clause_instructions(raw_json)

    if _missing_bounded_end(instructions, clause_text):
        RETRY_STATS["triggered"] += 1
        logger.warning(
            "Bounded-duration cue present but effective_end_date_expr is null; "
            "retrying once for clause: %.120s",
            clause_text,
        )
        try:
            retry_raw = await _call_interpreter_llm(clause_text, openai_client)
            retry_instructions = parse_clause_instructions(retry_raw)
        except Exception:
            # First result is valid; a failed retry must not break the pipeline.
            logger.exception(
                "Retry failed for clause: %.120s — keeping first result",
                clause_text,
            )
            return instructions
        if not _missing_bounded_end(retry_instructions, clause_text):
            RETRY_STATS["recovered"] += 1
            return retry_instructions
        logger.warning(
            "Retry also returned null effective_end_date_expr — keeping first "
            "result for clause: %.120s",
            clause_text,
        )

    return instructions


async def resolve_date_condition(
    condition_text: str,
    openai_client: AsyncOpenAI,
) -> tuple[str, ASTNode]:
    """Resolve a date condition string to an AST via LLM.

    Used by Layer 3 (source_effective_date_condition) and Layer 4
    (confirmed_effective_date_condition).

    Returns:
        (output_type, ast_node) where output_type is "date" or "boolean".
        - "date": AST evaluates to a concrete date.
        - "boolean": AST evaluates to True/False (runtime condition).
    """
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-5.2",
            temperature=0,
            messages=[
                {"role": "system", "content": EFFECTIVE_DATE_CONDITION_PROMPT},
                {"role": "user", "content": condition_text},
            ],
        )
    except Exception:
        logger.exception(
            "OpenAI API call failed for date condition: %.120s", condition_text
        )
        raise

    raw_json = response.choices[0].message.content
    logger.info("Date condition AST raw: %s", raw_json)

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        logger.error(
            "Invalid JSON from date condition LLM: %s", raw_json[:200]
        )
        raise ValueError(
            f"Date condition LLM returned invalid JSON: {raw_json[:200]}"
        )

    output_type = parsed.get("output_type")
    if output_type not in ("date", "boolean"):
        raise ValueError(
            f"Expected output_type 'date' or 'boolean', got: {output_type!r}"
        )

    ast_data = parsed.get("ast")
    if ast_data is None:
        raise ValueError("Date condition LLM response missing 'ast' field")

    return output_type, ASTNode(**ast_data)
