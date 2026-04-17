"""Shared fixtures for all test modules."""
from __future__ import annotations

import os
import sys
from datetime import date
from copy import deepcopy

import pytest

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.models import ASTNode, ClauseInstruction
from engine.timeline_engine import (
    ConstraintRule,
    EvaluationContext,
    FieldTimeline,
    TimelineEntry,
)
from engine.pipeline import SEED_TIMELINES


# ═══════════════════════════════════════════════════════════════════════════
# AST Node helpers — build nodes concisely
# ═══════════════════════════════════════════════════════════════════════════

def lit(value, value_type="number"):
    return ASTNode(node_type="literal", value=value, value_type=value_type,
                   op=None, field=None, fn=None, args=None)

def lit_date(value):
    return ASTNode(node_type="literal", value=value, value_type="date",
                   op=None, field=None, fn=None, args=None)

def lit_pct(value):
    return ASTNode(node_type="literal", value=value, value_type="percentage",
                   op=None, field=None, fn=None, args=None)

def field_ref(name):
    return ASTNode(node_type="field_ref", field=name,
                   op=None, value=None, value_type=None, fn=None, args=None)

def comparison(op, left, right):
    return ASTNode(node_type="comparison", op=op, args=[left, right],
                   value=None, value_type=None, field=None, fn=None)

def logical(op, *children):
    return ASTNode(node_type="logical", op=op, args=list(children),
                   value=None, value_type=None, field=None, fn=None)

def temporal(op, base, amount):
    return ASTNode(node_type="temporal", op=op, args=[base, amount],
                   value=None, value_type=None, field=None, fn=None)

def fn_call(fn_name, *fn_args):
    return ASTNode(node_type="function_call", fn=fn_name, args=list(fn_args),
                   op=None, value=None, value_type=None, field=None)

def aggregator(op, *children):
    return ASTNode(node_type="aggregator", op=op, args=list(children),
                   value=None, value_type=None, field=None, fn=None)


# ═══════════════════════════════════════════════════════════════════════════
# Instruction builders
# ═══════════════════════════════════════════════════════════════════════════

def make_set(field, value, eff_date=None, eff_end=None,
             clause_text="test SET", condition=None):
    return ClauseInstruction(
        clause_text=clause_text,
        affected_field=field,
        action="SET",
        value_expr=lit_pct(value) if isinstance(value, (int, float)) else value,
        effective_date_expr=lit_date(eff_date) if eff_date else None,
        effective_end_date_expr=lit_date(eff_end) if eff_end else None,
        condition_ast=condition,
    )

def make_adjust(field, delta, direction, eff_date=None, eff_end=None,
                clause_text="test ADJUST", condition=None,
                adjust_mode="additive"):
    return ClauseInstruction(
        clause_text=clause_text,
        affected_field=field,
        action="ADJUST",
        value_expr=lit(delta),
        adjust_direction=direction,
        adjust_mode=adjust_mode,
        effective_date_expr=lit_date(eff_date) if eff_date else None,
        effective_end_date_expr=lit_date(eff_end) if eff_end else None,
        condition_ast=condition,
    )

def make_constrain(field, bound, constraint_type, eff_date=None, eff_end=None,
                   clause_text="test CONSTRAIN"):
    return ClauseInstruction(
        clause_text=clause_text,
        affected_field=field,
        action="CONSTRAIN",
        value_expr=lit(bound) if isinstance(bound, (int, float)) else bound,
        constraint_type=constraint_type,
        effective_date_expr=lit_date(eff_date) if eff_date else None,
        effective_end_date_expr=lit_date(eff_end) if eff_end else None,
    )

def make_gate_move(field, gate_target, scope_mode, scope_date,
                   move_to_date, new_end_date=None,
                   gate_direction="POSTPONE",
                   clause_text="test GATE move"):
    return ClauseInstruction(
        clause_text=clause_text,
        affected_field=field,
        action="GATE",
        gate_target=gate_target,
        gate_direction=gate_direction,
        gate_scope_mode=scope_mode,
        effective_date_expr=lit_date(scope_date) if scope_date else None,
        gate_move_to_date_expr=lit_date(move_to_date),
        gate_new_end_date_expr=lit_date(new_end_date) if new_end_date else None,
    )

def make_gate_condition(field, gate_target, scope_mode, scope_date,
                        condition_ast, clause_text="test GATE condition"):
    return ClauseInstruction(
        clause_text=clause_text,
        affected_field=field,
        action="GATE",
        gate_target=gate_target,
        gate_scope_mode=scope_mode,
        effective_date_expr=lit_date(scope_date) if scope_date else None,
        condition_ast=condition_ast,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Timeline fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def empty_timelines():
    """Empty dict of FieldTimelines."""
    return {}


@pytest.fixture
def seed_timelines():
    """Deep copy of SEED_TIMELINES as FieldTimeline objects."""
    timelines = {}
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


@pytest.fixture
def base_ctx():
    """Evaluation context with sensible defaults."""
    return EvaluationContext(
        evaluation_date=date(2026, 6, 1),
        document_date=date(2025, 6, 1),
        fund_data={},
    )


