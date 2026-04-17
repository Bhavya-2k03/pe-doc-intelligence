"""Tests for engine/models.py — ASTNode, ClauseInstruction, parse_clause_instructions."""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from engine.models import (
    ASTNode,
    ClauseInstruction,
    FUNCTION_REGISTRY,
    parse_clause_instructions,
)


# ═══════════════════════════════════════════════════════════════════════════
# ASTNode — valid construction
# ═══════════════════════════════════════════════════════════════════════════

class TestASTNodeValid:

    def test_literal_number(self):
        n = ASTNode(node_type="literal", value=1.5, value_type="percentage")
        assert n.value == 1.5 and n.value_type == "percentage"

    def test_literal_date_string(self):
        n = ASTNode(node_type="literal", value="2025-06-01", value_type="date")
        assert n.value == "2025-06-01"

    def test_literal_boolean(self):
        n = ASTNode(node_type="literal", value=True, value_type="boolean")
        assert n.value is True

    def test_field_ref(self):
        n = ASTNode(node_type="field_ref", field="management_fee_rate")
        assert n.field == "management_fee_rate"

    def test_field_ref_reserved(self):
        n = ASTNode(node_type="field_ref", field="evaluation_date")
        assert n.field == "evaluation_date"

    def test_comparison(self):
        n = ASTNode(node_type="comparison", op="GTE", args=[
            ASTNode(node_type="field_ref", field="fund_percentage_realized"),
            ASTNode(node_type="literal", value=50, value_type="percentage"),
        ])
        assert n.op == "GTE" and len(n.args) == 2

    def test_logical_and(self):
        n = ASTNode(node_type="logical", op="AND", args=[
            ASTNode(node_type="literal", value=True, value_type="boolean"),
            ASTNode(node_type="literal", value=False, value_type="boolean"),
        ])
        assert n.op == "AND"

    def test_arithmetic(self):
        n = ASTNode(node_type="arithmetic", op="ADD", args=[
            ASTNode(node_type="literal", value=1, value_type="number"),
            ASTNode(node_type="literal", value=2, value_type="number"),
        ])
        assert n.op == "ADD"

    def test_temporal(self):
        n = ASTNode(node_type="temporal", op="ADD_YEARS", args=[
            ASTNode(node_type="field_ref", field="fund_initial_closing_date"),
            ASTNode(node_type="literal", value=2, value_type="number"),
        ])
        assert n.op == "ADD_YEARS"

    def test_function_call_all_registered(self):
        """Every function in FUNCTION_REGISTRY can be used."""
        for fn_name in FUNCTION_REGISTRY:
            n = ASTNode(node_type="function_call", fn=fn_name, args=[])
            assert n.fn == fn_name

    def test_aggregator_min_max(self):
        for op in ("MIN", "MAX"):
            n = ASTNode(node_type="aggregator", op=op, args=[
                ASTNode(node_type="literal", value=1, value_type="number"),
                ASTNode(node_type="literal", value=2, value_type="number"),
            ])
            assert n.op == op

    def test_deeply_nested_ast(self):
        """Arbitrary nesting works."""
        n = ASTNode(node_type="logical", op="AND", args=[
            ASTNode(node_type="comparison", op="GTE", args=[
                ASTNode(node_type="function_call", fn="FUND_REALIZATION_PCT", args=[]),
                ASTNode(node_type="literal", value=50, value_type="percentage"),
            ]),
            ASTNode(node_type="comparison", op="LTE", args=[
                ASTNode(node_type="field_ref", field="management_fee_rate"),
                ASTNode(node_type="arithmetic", op="MUL", args=[
                    ASTNode(node_type="literal", value=2, value_type="number"),
                    ASTNode(node_type="literal", value=0.5, value_type="number"),
                ]),
            ]),
        ])
        assert n.op == "AND" and len(n.args) == 2


# ═══════════════════════════════════════════════════════════════════════════
# ASTNode — validation failures
# ═══════════════════════════════════════════════════════════════════════════

class TestASTNodeInvalid:

    def test_literal_missing_value(self):
        with pytest.raises(ValidationError, match="value"):
            ASTNode(node_type="literal", value_type="number")

    def test_literal_missing_value_type(self):
        with pytest.raises(ValidationError, match="value_type"):
            ASTNode(node_type="literal", value=42)

    def test_field_ref_missing_field(self):
        with pytest.raises(ValidationError, match="field"):
            ASTNode(node_type="field_ref")

    def test_function_call_missing_fn(self):
        with pytest.raises(ValidationError, match="fn"):
            ASTNode(node_type="function_call", args=[])

    def test_function_call_unknown_fn(self):
        with pytest.raises(ValidationError, match="FUNCTION_REGISTRY"):
            ASTNode(node_type="function_call", fn="FAKE_FUNCTION", args=[])

    def test_comparison_missing_op(self):
        with pytest.raises(ValidationError, match="op"):
            ASTNode(node_type="comparison", args=[
                ASTNode(node_type="literal", value=1, value_type="number"),
                ASTNode(node_type="literal", value=2, value_type="number"),
            ])

    def test_logical_missing_op(self):
        with pytest.raises(ValidationError, match="op"):
            ASTNode(node_type="logical")

    def test_temporal_missing_op(self):
        with pytest.raises(ValidationError, match="op"):
            ASTNode(node_type="temporal")

    def test_aggregator_missing_op(self):
        with pytest.raises(ValidationError, match="op"):
            ASTNode(node_type="aggregator")

    def test_invalid_node_type(self):
        with pytest.raises(ValidationError):
            ASTNode(node_type="nonexistent_type")


# ═══════════════════════════════════════════════════════════════════════════
# ClauseInstruction — valid construction for each action
# ═══════════════════════════════════════════════════════════════════════════

class TestClauseInstructionValid:

    def test_set(self):
        ci = ClauseInstruction(
            clause_text="fee is 1.5%",
            affected_field="management_fee_rate",
            action="SET",
            value_expr=ASTNode(node_type="literal", value=1.5, value_type="percentage"),
        )
        assert ci.action == "SET"

    def test_set_with_dates(self):
        ci = ClauseInstruction(
            clause_text="fee is 1.5% from June",
            affected_field="management_fee_rate",
            action="SET",
            value_expr=ASTNode(node_type="literal", value=1.5, value_type="percentage"),
            effective_date_expr=ASTNode(node_type="literal", value="2025-06-01", value_type="date"),
            effective_end_date_expr=ASTNode(node_type="literal", value="2026-12-31", value_type="date"),
        )
        assert ci.effective_date_expr is not None and ci.effective_end_date_expr is not None

    def test_set_with_condition(self):
        ci = ClauseInstruction(
            clause_text="fee reduced if realized > 50%",
            affected_field="management_fee_rate",
            action="SET",
            value_expr=ASTNode(node_type="literal", value=1.5, value_type="percentage"),
            condition_ast=ASTNode(node_type="comparison", op="GTE", args=[
                ASTNode(node_type="function_call", fn="FUND_REALIZATION_PCT", args=[]),
                ASTNode(node_type="literal", value=50, value_type="percentage"),
            ]),
        )
        assert ci.condition_ast is not None

    def test_adjust(self):
        ci = ClauseInstruction(
            clause_text="reduce by 25bps",
            affected_field="management_fee_rate",
            action="ADJUST",
            value_expr=ASTNode(node_type="literal", value=-0.25, value_type="number"),
            adjust_direction="REDUCTION",
        )
        assert ci.adjust_direction == "REDUCTION"
        assert ci.adjust_mode == "additive"  # defaults to additive

    def test_adjust_multiplicative(self):
        ci = ClauseInstruction(
            clause_text="step down by 50%",
            affected_field="management_fee_rate",
            action="ADJUST",
            value_expr=ASTNode(node_type="literal", value=0.5, value_type="number"),
            adjust_direction="REDUCTION",
            adjust_mode="multiplicative",
        )
        assert ci.adjust_direction == "REDUCTION"
        assert ci.adjust_mode == "multiplicative"

    def test_adjust_defaults_to_additive(self):
        """ADJUST without explicit adjust_mode defaults to 'additive'."""
        ci = ClauseInstruction(
            clause_text="reduce by 25bps",
            affected_field="management_fee_rate",
            action="ADJUST",
            value_expr=ASTNode(node_type="literal", value=-0.25, value_type="number"),
            adjust_direction="REDUCTION",
        )
        assert ci.adjust_mode == "additive"

    def test_constrain_cap(self):
        ci = ClauseInstruction(
            clause_text="fee capped at 1.75%",
            affected_field="management_fee_rate",
            action="CONSTRAIN",
            value_expr=ASTNode(node_type="literal", value=1.75, value_type="percentage"),
            constraint_type="CAP",
        )
        assert ci.constraint_type == "CAP"

    def test_constrain_floor(self):
        ci = ClauseInstruction(
            clause_text="fee floored at 0.5%",
            affected_field="management_fee_rate",
            action="CONSTRAIN",
            value_expr=ASTNode(node_type="literal", value=0.5, value_type="percentage"),
            constraint_type="FLOOR",
        )
        assert ci.constraint_type == "FLOOR"

    def test_gate_with_move(self):
        ci = ClauseInstruction(
            clause_text="defer reduction to anniversary",
            affected_field="management_fee_rate",
            action="GATE",
            gate_target="REDUCTION",
            gate_direction="POSTPONE",
            gate_move_to_date_expr=ASTNode(
                node_type="function_call", fn="ANNIVERSARY", args=[
                    ASTNode(node_type="literal", value=2, value_type="number"),
                    ASTNode(node_type="field_ref", field="fund_final_closing_date"),
                ]
            ),
        )
        assert ci.gate_move_to_date_expr is not None
        assert ci.gate_direction == "POSTPONE"

    def test_gate_with_condition(self):
        ci = ClauseInstruction(
            clause_text="keep reduction only if realized > 50%",
            affected_field="management_fee_rate",
            action="GATE",
            gate_target="REDUCTION",
            condition_ast=ASTNode(node_type="comparison", op="GTE", args=[
                ASTNode(node_type="function_call", fn="FUND_REALIZATION_PCT", args=[]),
                ASTNode(node_type="literal", value=50, value_type="percentage"),
            ]),
        )
        assert ci.condition_ast is not None

    def test_no_action(self):
        ci = ClauseInstruction(
            clause_text="informational only",
            action="NO_ACTION",
            no_action_reason="disclosure, no economic impact",
        )
        assert ci.no_action_reason is not None

    def test_manual_review(self):
        ci = ClauseInstruction(
            clause_text="complex external dependency",
            affected_field="management_fee_rate",
            action="MANUAL_REVIEW",
            manual_review_reason="depends on external valuation agent",
        )
        assert ci.manual_review_reason is not None


# ═══════════════════════════════════════════════════════════════════════════
# ClauseInstruction — validation failures
# ═══════════════════════════════════════════════════════════════════════════

class TestClauseInstructionInvalid:

    def test_set_missing_affected_field(self):
        with pytest.raises(ValidationError, match="SET requires affected_field"):
            ClauseInstruction(
                clause_text="x", action="SET",
                value_expr=ASTNode(node_type="literal", value=1, value_type="number"),
            )

    def test_set_missing_value_expr(self):
        with pytest.raises(ValidationError, match="SET requires value_expr"):
            ClauseInstruction(
                clause_text="x", action="SET",
                affected_field="management_fee_rate",
            )

    def test_adjust_missing_affected_field(self):
        with pytest.raises(ValidationError, match="ADJUST requires affected_field"):
            ClauseInstruction(
                clause_text="x", action="ADJUST",
                value_expr=ASTNode(node_type="literal", value=1, value_type="number"),
                adjust_direction="REDUCTION",
            )

    def test_adjust_missing_value_expr(self):
        with pytest.raises(ValidationError, match="ADJUST requires value_expr"):
            ClauseInstruction(
                clause_text="x", action="ADJUST",
                affected_field="management_fee_rate",
                adjust_direction="REDUCTION",
            )

    def test_adjust_missing_direction(self):
        with pytest.raises(ValidationError, match="ADJUST requires adjust_direction"):
            ClauseInstruction(
                clause_text="x", action="ADJUST",
                affected_field="management_fee_rate",
                value_expr=ASTNode(node_type="literal", value=1, value_type="number"),
            )

    def test_constrain_missing_constraint_type(self):
        with pytest.raises(ValidationError, match="CONSTRAIN requires constraint_type"):
            ClauseInstruction(
                clause_text="x", action="CONSTRAIN",
                affected_field="management_fee_rate",
                value_expr=ASTNode(node_type="literal", value=1, value_type="number"),
            )

    def test_gate_both_move_and_condition(self):
        with pytest.raises(ValidationError, match="exactly one"):
            ClauseInstruction(
                clause_text="x", action="GATE",
                affected_field="management_fee_rate",
                gate_target="REDUCTION",
                gate_direction="POSTPONE",
                gate_move_to_date_expr=ASTNode(
                    node_type="literal", value="2025-01-01", value_type="date"
                ),
                condition_ast=ASTNode(
                    node_type="literal", value=True, value_type="boolean"
                ),
            )

    def test_gate_neither_move_nor_condition(self):
        with pytest.raises(ValidationError, match="exactly one"):
            ClauseInstruction(
                clause_text="x", action="GATE",
                affected_field="management_fee_rate",
                gate_target="REDUCTION",
            )

    def test_gate_missing_affected_field(self):
        with pytest.raises(ValidationError, match="GATE requires affected_field"):
            ClauseInstruction(
                clause_text="x", action="GATE",
                gate_target="REDUCTION",
                gate_direction="POSTPONE",
                gate_move_to_date_expr=ASTNode(
                    node_type="literal", value="2025-01-01", value_type="date"
                ),
            )

    def test_gate_move_missing_gate_direction(self):
        with pytest.raises(ValidationError, match="gate_direction"):
            ClauseInstruction(
                clause_text="x", action="GATE",
                affected_field="management_fee_rate",
                gate_target="REDUCTION",
                gate_move_to_date_expr=ASTNode(
                    node_type="literal", value="2025-01-01", value_type="date"
                ),
            )

    def test_gate_condition_with_gate_direction_rejected(self):
        with pytest.raises(ValidationError, match="gate_direction = null"):
            ClauseInstruction(
                clause_text="x", action="GATE",
                affected_field="management_fee_rate",
                gate_target="REDUCTION",
                gate_direction="POSTPONE",
                condition_ast=ASTNode(
                    node_type="literal", value=True, value_type="boolean"
                ),
            )

    def test_no_action_missing_reason(self):
        with pytest.raises(ValidationError, match="NO_ACTION requires no_action_reason"):
            ClauseInstruction(clause_text="x", action="NO_ACTION")

    def test_manual_review_missing_reason(self):
        with pytest.raises(ValidationError, match="MANUAL_REVIEW requires manual_review_reason"):
            ClauseInstruction(
                clause_text="x", action="MANUAL_REVIEW",
                affected_field="management_fee_rate",
            )


# ═══════════════════════════════════════════════════════════════════════════
# parse_clause_instructions
# ═══════════════════════════════════════════════════════════════════════════

class TestParseClauseInstructions:

    _VALID_ITEM = {
        "clause_text": "fee is 1.5%",
        "affected_field": "management_fee_rate",
        "action": "SET",
        "value_expr": {"node_type": "literal", "value": 1.5,
                       "value_type": "percentage", "op": None,
                       "field": None, "fn": None, "args": None},
        "condition_ast": None,
        "effective_date_expr": None,
        "effective_end_date_expr": None,
        "gate_move_to_date_expr": None,
        "gate_new_end_date_expr": None,
        "gate_scope_mode": None,
        "adjust_direction": None,
        "constraint_type": None,
        "gate_target": None,
        "gate_direction": None,
        "no_action_reason": None,
        "manual_review_reason": None,
    }

    def test_bare_array(self):
        raw = json.dumps([self._VALID_ITEM])
        result = parse_clause_instructions(raw)
        assert len(result) == 1 and result[0].action == "SET"

    def test_wrapped_in_object(self):
        raw = json.dumps({"instructions": [self._VALID_ITEM]})
        result = parse_clause_instructions(raw)
        assert len(result) == 1

    def test_single_object(self):
        """LLM returns bare object instead of array."""
        raw = json.dumps(self._VALID_ITEM)
        result = parse_clause_instructions(raw)
        assert len(result) == 1

    def test_multiple_items(self):
        raw = json.dumps([self._VALID_ITEM, self._VALID_ITEM])
        result = parse_clause_instructions(raw)
        assert len(result) == 2

    def test_invalid_json(self):
        with pytest.raises(ValueError, match="invalid JSON"):
            parse_clause_instructions("not json {{{")

    def test_validation_error_propagates(self):
        bad = {**self._VALID_ITEM, "action": "SET", "value_expr": None}
        with pytest.raises(ValidationError):
            parse_clause_instructions(json.dumps([bad]))

    def test_empty_array(self):
        result = parse_clause_instructions("[]")
        assert result == []
