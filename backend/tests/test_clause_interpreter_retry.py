"""Tests for the clause-interpreter missing-end-date backstop.

The backstop retries the LLM call exactly once when a clause text carries a
bounded-duration cue but the parsed instructions have no
effective_end_date_expr. These tests mock the OpenAI client — no API calls.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.clause_interpreter import (
    _missing_bounded_end,
    interpret_clause,
    parse_clause_instructions,
)


BOUNDED_CLAUSE = (
    "The Management Fee rate otherwise payable by the Fund shall be reduced "
    "from 2.00% to 1.00% per annum for the period commencing January 1, 2028 "
    "and ending at the end of the Investment Period."
)

PERMANENT_CLAUSE = (
    "The Management Fee rate shall be 1.75% per annum following the "
    "execution of the election form."
)


def _instruction_json(action="SET", end_expr=None, **overrides):
    """Minimal valid instruction dict for parse_clause_instructions."""
    instr = {
        "clause_text": BOUNDED_CLAUSE,
        "affected_field": "management_fee_rate",
        "action": action,
        "condition_ast": None,
        "value_expr": {
            "node_type": "literal",
            "op": None,
            "value": 1.0,
            "value_type": "percentage",
            "field": None,
            "fn": None,
            "args": None,
        },
        "effective_date_expr": {
            "node_type": "literal",
            "op": None,
            "value": "2028-01-01",
            "value_type": "date",
            "field": None,
            "fn": None,
            "args": None,
        },
        "effective_end_date_expr": end_expr,
        "gate_move_to_date_expr": None,
        "gate_new_end_date_expr": None,
        "gate_scope_mode": None,
        "adjust_direction": None,
        "adjust_mode": None,
        "constraint_type": None,
        "gate_target": None,
        "gate_direction": None,
        "no_action_reason": None,
        "manual_review_reason": None,
    }
    instr.update(overrides)
    return instr


END_EXPR = {
    "node_type": "field_ref",
    "op": None,
    "value": None,
    "value_type": None,
    "field": "fund_investment_end_date",
    "fn": None,
    "args": None,
}


def _fake_client(responses: list[str]) -> MagicMock:
    """OpenAI client stub returning the given raw strings in sequence."""
    client = MagicMock()
    side_effects = []
    for raw in responses:
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = raw
        side_effects.append(resp)
    client.chat.completions.create = AsyncMock(side_effect=side_effects)
    return client


# ---------------------------------------------------------------------------
# _missing_bounded_end
# ---------------------------------------------------------------------------


class TestMissingBoundedEnd:
    def test_cue_and_null_end_is_flagged(self):
        instrs = parse_clause_instructions(json.dumps([_instruction_json()]))
        assert _missing_bounded_end(instrs, BOUNDED_CLAUSE) is True

    def test_cue_with_end_present_passes(self):
        instrs = parse_clause_instructions(
            json.dumps([_instruction_json(end_expr=END_EXPR)])
        )
        assert _missing_bounded_end(instrs, BOUNDED_CLAUSE) is False

    def test_no_cue_null_end_passes(self):
        instrs = parse_clause_instructions(json.dumps([_instruction_json()]))
        assert _missing_bounded_end(instrs, PERMANENT_CLAUSE) is False

    def test_quarter_waiver_cue_is_flagged(self):
        clause = (
            "The Management Fee for the first quarter of 2025 is waived for "
            "all Investors whose Total Capital Commitment equals or exceeds "
            "USD 8,000,000."
        )
        instrs = parse_clause_instructions(json.dumps([_instruction_json()]))
        assert _missing_bounded_end(instrs, clause) is True

    def test_gate_is_never_flagged(self):
        gate = _instruction_json(
            action="GATE",
            value_expr=None,
            gate_target="REDUCTION",
            gate_scope_mode="FROM",
            condition_ast={
                "node_type": "literal",
                "op": None,
                "value": True,
                "value_type": "boolean",
                "field": None,
                "fn": None,
                "args": None,
            },
        )
        instrs = parse_clause_instructions(json.dumps([gate]))
        # "until" cue present, but GATE must not carry effective_end_date_expr
        assert _missing_bounded_end(instrs, "deferred until the anniversary") is False


# ---------------------------------------------------------------------------
# interpret_clause retry behavior
# ---------------------------------------------------------------------------


class TestRetryOnce:
    async def test_no_cue_no_retry(self):
        client = _fake_client([json.dumps([_instruction_json()])] * 3)
        await interpret_clause(PERMANENT_CLAUSE, client)
        assert client.chat.completions.create.await_count == 1

    async def test_retry_recovers_end_date(self):
        client = _fake_client(
            [
                json.dumps([_instruction_json()]),  # end dropped
                json.dumps([_instruction_json(end_expr=END_EXPR)]),  # recovered
            ]
        )
        result = await interpret_clause(BOUNDED_CLAUSE, client)
        assert client.chat.completions.create.await_count == 2
        assert result[0].effective_end_date_expr is not None
        assert result[0].effective_end_date_expr.field == "fund_investment_end_date"

    async def test_retry_is_exactly_once_when_both_fail(self):
        # Three bad responses queued — only two may ever be consumed.
        client = _fake_client([json.dumps([_instruction_json()])] * 3)
        result = await interpret_clause(BOUNDED_CLAUSE, client)
        assert client.chat.completions.create.await_count == 2
        # Both attempts suspect → first result stands
        assert result[0].effective_end_date_expr is None

    async def test_failed_retry_keeps_first_result(self):
        good_first = json.dumps([_instruction_json()])
        client = _fake_client([good_first, "NOT JSON {{{"])
        result = await interpret_clause(BOUNDED_CLAUSE, client)
        assert client.chat.completions.create.await_count == 2
        assert result[0].action == "SET"
