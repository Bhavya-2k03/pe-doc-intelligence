from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ValidationError, model_validator

logger = logging.getLogger(__name__)

try:
    import constants as _constants
    _KNOWN_FIELDS: list[str] = getattr(_constants, "parsed_field_name_list", [])
except Exception:
    _KNOWN_FIELDS = []


# ---------------------------------------------------------------------------
# Shared type aliases and registries
# ---------------------------------------------------------------------------

ValueType = Literal["number", "percentage", "string", "bool", "date", "currency"]

ASTValueType = Literal["date", "number", "percentage", "boolean", "string"]

NodeType = Literal[
    "literal", "field_ref", "comparison", "logical",
    "arithmetic", "temporal", "function_call", "aggregator",
]

Action = Literal["SET", "ADJUST", "CONSTRAIN", "GATE", "NO_ACTION", "MANUAL_REVIEW"]

GateScopeMode = Literal["AT", "FROM", "BEFORE"]

AdjustDirection = Literal["INCREASE", "REDUCTION"]

AdjustMode = Literal["additive", "multiplicative"]

ConstraintType = Literal["CAP", "FLOOR"]

GateTarget = Literal["REDUCTION", "INCREASE", "ANY"]

GateDirection = Literal["POSTPONE", "PREPONE", "RESCHEDULE"]

# Whitelist — LLM must not invent others.
FUNCTION_REGISTRY: frozenset[str] = frozenset({
    "FUND_REALIZATION_PCT", "INVESTOR_REALIZATION_PCT",
    "TOTAL_COMMITMENTS", "INVESTED_CAPITAL", "DPI",
    "NEXT_FISCAL_QUARTER_START", "FISCAL_QUARTER_START", "FISCAL_QUARTER_END",
    "MONTH_START", "MONTH_END", "ANNIVERSARY", "DAYS_SINCE",
})

# Reserved field_refs that the engine resolves at runtime.
RESERVED_FIELD_REFS: frozenset[str] = frozenset({"evaluation_date", "document_date"})


# ---------------------------------------------------------------------------
# MODEL 1: TimelineEntry
# ---------------------------------------------------------------------------

class TimelineEntry(BaseModel):
    start: date
    end: date | None = None                 # None = open-ended
    value: str | int | float | bool | date
    value_type: ValueType
    requires_confirmation: bool = False
    confirmation_date: date | None = None
    source: Literal["fund_metadata", "extracted_fields", "clause"]
    clause_id: str | None = None
    requires_true_up: bool = False
    snapshot_date: date
    # The effective date on which this version of the timeline was created.
    # Redundant with the outer dict key in self.timelines but kept for
    # debugging and for get_field_value return context.


# ---------------------------------------------------------------------------
# ASTNode — self-referential expression tree
# ---------------------------------------------------------------------------
# ALL six fields always present in LLM output (nulls explicit).
#
# node_type semantics:
#   literal        — value + value_type populated
#   field_ref      — field populated (parsed_field_name or reserved ref)
#   comparison     — op ∈ {GTE,LTE,GT,LT,EQ,NEQ}, args = [left, right]
#   logical        — op ∈ {AND,OR}, args = children
#   arithmetic     — op ∈ {ADD,SUB,MUL,DIV}, args = operands
#   temporal       — op ∈ {ADD_YEARS,ADD_MONTHS,ADD_DAYS}, args = [base, offset]
#   function_call  — fn ∈ FUNCTION_REGISTRY, args = function arguments
#   aggregator     — op ∈ {MIN,MAX}, args = children

class ASTNode(BaseModel):
    node_type: NodeType
    op: str | None = None
    value: Any = None
    value_type: ASTValueType | None = None
    field: str | None = None
    fn: str | None = None
    args: list[ASTNode] | None = None

    @model_validator(mode="after")
    def _validate_node(self) -> ASTNode:
        nt = self.node_type

        if nt == "literal":
            if self.value is None:
                raise ValueError("literal node requires value")
            if self.value_type is None:
                raise ValueError("literal node requires value_type")

        elif nt == "field_ref":
            if self.field is None:
                raise ValueError("field_ref node requires field")

        elif nt == "function_call":
            if self.fn is None:
                raise ValueError("function_call node requires fn")
            if self.fn not in FUNCTION_REGISTRY:
                raise ValueError(
                    f"fn '{self.fn}' is not in FUNCTION_REGISTRY. "
                    f"Allowed: {sorted(FUNCTION_REGISTRY)}"
                )

        elif nt in ("comparison", "logical", "arithmetic", "temporal", "aggregator"):
            if self.op is None:
                raise ValueError(f"{nt} node requires op")

        return self


# Required for self-referential Pydantic model
ASTNode.model_rebuild()


# ---------------------------------------------------------------------------
# ClauseInstruction (V6 — 6 actions)
# ---------------------------------------------------------------------------
# LLM always outputs a JSON array [{ ... }].
# ALL AST fields always present (nulls explicit).

class ClauseInstruction(BaseModel):
    clause_text: str
    affected_field: str | None = None
    action: Action

    condition_ast: ASTNode | None = None
    value_expr: ASTNode | None = None
    effective_date_expr: ASTNode | None = None
    effective_end_date_expr: ASTNode | None = None

    gate_move_to_date_expr: ASTNode | None = None
    gate_new_end_date_expr: ASTNode | None = None
    gate_scope_mode: GateScopeMode | None = None

    adjust_direction: AdjustDirection | None = None
    adjust_mode: AdjustMode | None = None  # "additive" (default) or "multiplicative"
    constraint_type: ConstraintType | None = None
    gate_target: GateTarget | None = None
    gate_direction: GateDirection | None = None

    no_action_reason: str | None = None
    manual_review_reason: str | None = None

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def _validate(self) -> ClauseInstruction:
        a = self.action

        # ── SET: write a value at a date ──────────────────────────────
        if a == "SET":
            if self.affected_field is None:
                raise ValueError("SET requires affected_field")
            if self.value_expr is None:
                raise ValueError("SET requires value_expr")

        # ── ADJUST: relative delta, stackable ─────────────────────────
        elif a == "ADJUST":
            if self.affected_field is None:
                raise ValueError("ADJUST requires affected_field")
            if self.value_expr is None:
                raise ValueError("ADJUST requires value_expr")
            if self.adjust_direction is None:
                raise ValueError("ADJUST requires adjust_direction")
            # Default adjust_mode to "additive" if not specified
            if self.adjust_mode is None:
                self.adjust_mode = "additive"

        # ── CONSTRAIN: persistent bound (CAP/FLOOR) ──────────────────
        elif a == "CONSTRAIN":
            if self.affected_field is None:
                raise ValueError("CONSTRAIN requires affected_field")
            if self.value_expr is None:
                raise ValueError("CONSTRAIN requires value_expr")
            if self.constraint_type is None:
                raise ValueError("CONSTRAIN requires constraint_type")

        # ── GATE: modifies timing of an existing transition ───────────
        elif a == "GATE":
            if self.affected_field is None:
                raise ValueError("GATE requires affected_field")
            has_move = self.gate_move_to_date_expr is not None
            has_cond = self.condition_ast is not None
            if has_move == has_cond:  # both set or both null
                raise ValueError(
                    "GATE requires exactly one of "
                    "gate_move_to_date_expr or condition_ast (not both, not neither)"
                )
            if has_move and self.gate_direction is None:
                raise ValueError(
                    "GATE with gate_move_to_date_expr requires gate_direction "
                    "(POSTPONE, PREPONE, or RESCHEDULE)"
                )
            if has_cond and self.gate_direction is not None:
                raise ValueError(
                    "GATE with condition_ast must have gate_direction = null"
                )

        # ── NO_ACTION: clause has no impact on any field ──────────────
        elif a == "NO_ACTION":
            if self.no_action_reason is None:
                raise ValueError("NO_ACTION requires no_action_reason")

        # ── MANUAL_REVIEW: system can't fully interpret ───────────────
        elif a == "MANUAL_REVIEW":
            if self.manual_review_reason is None:
                raise ValueError("MANUAL_REVIEW requires manual_review_reason")

        # ── affected_field validation against registry ────────────────
        if self.affected_field is not None and _KNOWN_FIELDS:
            if self.affected_field not in _KNOWN_FIELDS:
                raise ValueError(
                    f"affected_field '{self.affected_field}' is not in "
                    f"parsed_field_name_list. Valid fields: {_KNOWN_FIELDS}"
                )

        return self


# ---------------------------------------------------------------------------
# Parsing helper — validates raw LLM JSON into ClauseInstruction list
# ---------------------------------------------------------------------------

def parse_clause_instructions(raw_json: str) -> list[ClauseInstruction]:
    """Parse a JSON string (from LLM) into a list of ClauseInstruction.

    The LLM always outputs a JSON object with a top-level key wrapping an
    array, or a bare JSON array.  Both forms are accepted:
      {"instructions": [{ ... }, ...]}   or   [{ ... }, ...]
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        logger.error("JSON parse failure. Raw response:\n%s", raw_json)
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

    # Unwrap: if dict, could be:
    #   1. Object wrapping an array: {"instructions": [{...}, ...]}
    #   2. Single instruction object: {"clause_text": ..., "action": ...}
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                data = v
                break
        else:
            # No list-valued key — treat as a single instruction object
            data = [data]

    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data).__name__}")

    instructions: list[ClauseInstruction] = []
    for i, item in enumerate(data):
        try:
            instructions.append(ClauseInstruction(**item))
        except ValidationError as exc:
            # If the LLM chose an action but couldn't construct the
            # instruction (e.g., GATE with no gate_move_to_date_expr
            # and no condition_ast), fall back to MANUAL_REVIEW if the
            # LLM provided a manual_review_reason.
            reason = item.get("manual_review_reason")
            if reason:
                logger.warning(
                    "Instruction %d failed validation, recovering as "
                    "MANUAL_REVIEW: %s", i, reason,
                )
                instructions.append(ClauseInstruction(
                    clause_text=item.get("clause_text", ""),
                    action="MANUAL_REVIEW",
                    affected_field=item.get("affected_field"),
                    manual_review_reason=reason,
                ))
            else:
                logger.error(
                    "Pydantic validation failed for instruction %d.\n"
                    "Raw JSON item: %s\nErrors: %s",
                    i, json.dumps(item, default=str), exc.errors(),
                )
                raise
    return instructions
