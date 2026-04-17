from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from dotenv import load_dotenv
import asyncio

from engine.models import ASTNode, ClauseInstruction, parse_clause_instructions
from prompts import CLAUSE_INTERPRETER_PROMPT, EFFECTIVE_DATE_CONDITION_PROMPT

if TYPE_CHECKING:
    from openai import AsyncOpenAI

load_dotenv()
logger = logging.getLogger(__name__)



async def interpret_clause(
    clause_text: str,
    openai_client: AsyncOpenAI,
) -> list[ClauseInstruction]:
    """Send clause_text to GPT 5.2 and return validated ClauseInstruction list.

    The LLM receives CLAUSE_INTERPRETER_PROMPT as the system message and the
    clause wrapped in <clause> tags as the user message.  Response is parsed
    and validated via parse_clause_instructions.
    """
    user_message = f"<clause>\nclause_text: {clause_text}\n</clause>"

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-5.2",
            temperature=0,

            messages=[
                {"role": "system", "content": CLAUSE_INTERPRETER_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
    except Exception:
        logger.exception("OpenAI API call failed for clause: %.120s", clause_text)
        raise

    raw_json = response.choices[0].message.content
    print("raw_json is: ", raw_json)
    return parse_clause_instructions(raw_json)


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
