"""Tests for engine/timeline_engine.py — the core execution engine.

Covers: value_at, insert_entry, find_transitions, evaluate_ast,
        execute (SET/ADJUST/CONSTRAIN/GATE), execute_all, edge cases.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from engine.models import ASTNode, ClauseInstruction
from engine.timeline_engine import (
    ConstraintRule,
    EvaluationContext,
    FieldTimeline,
    TimelineEntry,
    evaluate_ast,
    execute,
    execute_all,
)
from tests.conftest import (
    lit, lit_date, lit_pct, field_ref, comparison, logical,
    temporal, fn_call, aggregator,
    make_set, make_adjust, make_constrain, make_gate_move, make_gate_condition,
)


# ═══════════════════════════════════════════════════════════════════════════
# FieldTimeline.value_at
# ═══════════════════════════════════════════════════════════════════════════

class TestValueAt:

    def test_single_entry_covers_all_future(self):
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=2.0,
            source_clause_text="seed", entry_type="SET",
        ))
        assert ft.value_at(date(2024, 6, 1)) == 2.0
        assert ft.value_at(date(2030, 12, 31)) == 2.0

    def test_query_before_first_entry_returns_none(self):
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=2.0,
            source_clause_text="seed", entry_type="SET",
        ))
        assert ft.value_at(date(2023, 12, 31)) is None

    def test_empty_timeline_returns_none(self):
        ft = FieldTimeline()
        assert ft.value_at(date(2025, 1, 1)) is None

    def test_two_entries_correct_split(self):
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=2.0,
            source_clause_text="a", entry_type="SET",
        ))
        ft.insert_entry(TimelineEntry(
            date=date(2025, 6, 1), value=1.5,
            source_clause_text="b", entry_type="SET",
        ))
        assert ft.value_at(date(2024, 6, 1)) == 2.0
        assert ft.value_at(date(2025, 5, 31)) == 2.0
        assert ft.value_at(date(2025, 6, 1)) == 1.5
        assert ft.value_at(date(2026, 1, 1)) == 1.5

    def test_end_date_expiry(self):
        """Entry with end_date is not valid on or after that date."""
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=2.0,
            source_clause_text="base", entry_type="SET",
        ))
        ft.insert_entry(TimelineEntry(
            date=date(2025, 1, 1), end_date=date(2025, 7, 1), value=1.5,
            source_clause_text="temp", entry_type="SET",
        ))
        assert ft.value_at(date(2025, 3, 1)) == 1.5
        assert ft.value_at(date(2025, 6, 30)) == 1.5
        # After expiry, the earlier entry should resurface
        assert ft.value_at(date(2025, 7, 1)) == 2.0
        assert ft.value_at(date(2026, 1, 1)) == 2.0

    def test_insertion_order_tiebreak(self):
        """When two entries cover the same date, highest insertion_order wins."""
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value="first",
            source_clause_text="a", entry_type="SET",
        ))
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value="second",
            source_clause_text="b", entry_type="SET",
        ))
        assert ft.value_at(date(2024, 1, 1)) == "second"

    def test_three_entries_same_date(self):
        ft = FieldTimeline()
        for i in range(3):
            ft.insert_entry(TimelineEntry(
                date=date(2024, 1, 1), value=i,
                source_clause_text=f"entry_{i}", entry_type="SET",
            ))
        assert ft.value_at(date(2024, 1, 1)) == 2  # last inserted

    def test_constraint_cap(self):
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=2.0,
            source_clause_text="seed", entry_type="SET",
        ))
        ft.register_constraint(ConstraintRule(
            type="CAP", bound=1.75,
            source_clause_text="cap clause",
        ))
        assert ft.value_at(date(2024, 6, 1)) == 1.75

    def test_constraint_floor(self):
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=0.5,
            source_clause_text="seed", entry_type="SET",
        ))
        ft.register_constraint(ConstraintRule(
            type="FLOOR", bound=1.0,
            source_clause_text="floor clause",
        ))
        assert ft.value_at(date(2024, 6, 1)) == 1.0

    def test_constraint_active_range(self):
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=3.0,
            source_clause_text="seed", entry_type="SET",
        ))
        ft.register_constraint(ConstraintRule(
            type="CAP", bound=2.0,
            active_from=date(2025, 1, 1),
            active_until=date(2026, 1, 1),
            source_clause_text="temp cap",
        ))
        assert ft.value_at(date(2024, 6, 1)) == 3.0   # before cap active
        assert ft.value_at(date(2025, 6, 1)) == 2.0   # during cap
        assert ft.value_at(date(2026, 6, 1)) == 3.0   # after cap expires

    def test_cap_and_floor_together(self):
        """CAP and FLOOR both apply — value is clamped to [FLOOR, CAP]."""
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=3.0,
            source_clause_text="seed", entry_type="SET",
        ))
        ft.register_constraint(ConstraintRule(
            type="CAP", bound=2.5, source_clause_text="cap",
        ))
        ft.register_constraint(ConstraintRule(
            type="FLOOR", bound=1.0, source_clause_text="floor",
        ))
        assert ft.value_at(date(2024, 6, 1)) == 2.5  # capped from 3.0

    def test_later_cap_overrides_earlier_cap(self):
        """Side letter relaxes LPA cap — later CAP wins."""
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=2.5,
            source_clause_text="seed", entry_type="SET",
        ))
        # LPA: cap at 2.0 (registered first)
        ft.register_constraint(ConstraintRule(
            type="CAP", bound=2.0, source_clause_text="LPA cap",
        ))
        # Side letter: cap at 3.0 (registered second, relaxes the cap)
        ft.register_constraint(ConstraintRule(
            type="CAP", bound=3.0, source_clause_text="side letter cap",
        ))
        # Side letter's relaxed cap wins — value 2.5 is under 3.0
        assert ft.value_at(date(2024, 6, 1)) == 2.5

    def test_later_floor_overrides_earlier_floor(self):
        """Later document lowers the floor — later FLOOR wins."""
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=1.0,
            source_clause_text="seed", entry_type="SET",
        ))
        # LPA: floor at 1.5
        ft.register_constraint(ConstraintRule(
            type="FLOOR", bound=1.5, source_clause_text="LPA floor",
        ))
        # Side letter: floor at 1.25 (relaxes the floor)
        ft.register_constraint(ConstraintRule(
            type="FLOOR", bound=1.25, source_clause_text="side letter floor",
        ))
        # Side letter's relaxed floor wins — value 1.0 is raised to 1.25 not 1.5
        assert ft.value_at(date(2024, 6, 1)) == 1.25

    def test_cap_and_floor_independent_latest(self):
        """Latest CAP and latest FLOOR apply independently."""
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=2.5,
            source_clause_text="seed", entry_type="SET",
        ))
        # Constraint 1: CAP=2 (LPA)
        ft.register_constraint(ConstraintRule(
            type="CAP", bound=2.0,
            active_from=date(2024, 1, 1), active_until=date(2025, 3, 1),
            source_clause_text="c1",
        ))
        # Constraint 2: CAP=3 (side letter, later)
        ft.register_constraint(ConstraintRule(
            type="CAP", bound=3.0,
            active_from=date(2023, 11, 3), active_until=date(2024, 7, 1),
            source_clause_text="c2",
        ))
        # Constraint 3: FLOOR=1.5
        ft.register_constraint(ConstraintRule(
            type="FLOOR", bound=1.5,
            active_from=date(2022, 11, 3), active_until=date(2024, 7, 1),
            source_clause_text="c3",
        ))
        # Constraint 4: FLOOR=1.25 (later)
        ft.register_constraint(ConstraintRule(
            type="FLOOR", bound=1.25,
            active_from=date(2022, 11, 4), active_until=date(2025, 3, 1),
            source_clause_text="c4",
        ))
        # At 2024-02-14: all 4 active. Latest CAP=3 (c2), latest FLOOR=1.25 (c4)
        # value 2.5 → min(2.5, 3.0) = 2.5 → max(2.5, 1.25) = 2.5
        assert ft.value_at(date(2024, 2, 14)) == 2.5

    def test_overlapping_constraints_different_ranges(self):
        """When earlier constraint expires, only the remaining one applies."""
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=2.5,
            source_clause_text="seed", entry_type="SET",
        ))
        # CAP=2 active until 2024-06-01
        ft.register_constraint(ConstraintRule(
            type="CAP", bound=2.0,
            active_from=date(2024, 1, 1), active_until=date(2024, 6, 1),
            source_clause_text="strict cap",
        ))
        # CAP=3 active until 2025-01-01 (registered later, more relaxed)
        ft.register_constraint(ConstraintRule(
            type="CAP", bound=3.0,
            active_from=date(2024, 1, 1), active_until=date(2025, 1, 1),
            source_clause_text="relaxed cap",
        ))
        # Both active: latest wins → CAP=3 → value stays 2.5
        assert ft.value_at(date(2024, 3, 1)) == 2.5
        # Strict cap expired, only relaxed cap remains → CAP=3 → value stays 2.5
        assert ft.value_at(date(2024, 8, 1)) == 2.5
        # Both expired → no cap → value stays 2.5
        assert ft.value_at(date(2025, 3, 1)) == 2.5


# ═══════════════════════════════════════════════════════════════════════════
# FieldTimeline.find_transitions
# ═══════════════════════════════════════════════════════════════════════════

class TestFindTransitions:

    def _make_timeline(self):
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=2.0,
            source_clause_text="seed", entry_type="SET",
        ))
        ft.insert_entry(TimelineEntry(
            date=date(2025, 6, 1), value=1.5,
            source_clause_text="reduction SET", entry_type="SET",
        ))
        ft.insert_entry(TimelineEntry(
            date=date(2026, 1, 1), value=1.25,
            source_clause_text="adjust", entry_type="ADJUST", direction="REDUCTION",
        ))
        return ft

    def test_any_returns_all_non_seed(self):
        ft = self._make_timeline()
        found = ft.find_transitions("ANY", None, None)
        assert len(found) == 3  # all entries

    def test_reduction_matches_adjust_and_set(self):
        ft = self._make_timeline()
        found = ft.find_transitions("REDUCTION", None, None)
        assert len(found) == 2  # SET(1.5 < 2.0) + ADJUST(direction=REDUCTION)

    def test_increase_finds_none(self):
        ft = self._make_timeline()
        found = ft.find_transitions("INCREASE", None, None)
        assert len(found) == 0

    def test_scope_at(self):
        ft = self._make_timeline()
        found = ft.find_transitions("REDUCTION", date(2025, 6, 1), "AT")
        assert len(found) == 1 and found[0].date == date(2025, 6, 1)

    def test_scope_from(self):
        ft = self._make_timeline()
        found = ft.find_transitions("ANY", date(2025, 6, 1), "FROM")
        assert all(e.date >= date(2025, 6, 1) for e in found)

    def test_scope_before(self):
        ft = self._make_timeline()
        found = ft.find_transitions("ANY", date(2025, 6, 1), "BEFORE")
        assert all(e.date < date(2025, 6, 1) for e in found)


# ═══════════════════════════════════════════════════════════════════════════
# evaluate_ast
# ═══════════════════════════════════════════════════════════════════════════

class TestEvaluateAST:

    @pytest.fixture
    def ctx(self):
        return EvaluationContext(
            evaluation_date=date(2026, 6, 1),
            document_date=date(2025, 6, 1),
            fund_data={},
        )

    @pytest.fixture
    def timelines(self):
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 15), value=2.0,
            source_clause_text="seed", entry_type="SET",
        ))
        return {"management_fee_rate": ft}

    def test_literal_number(self, timelines, ctx):
        assert evaluate_ast(lit(42), timelines, ctx) == 42

    def test_literal_date_string(self, timelines, ctx):
        result = evaluate_ast(lit_date("2025-06-01"), timelines, ctx)
        assert result == date(2025, 6, 1)

    def test_field_ref_evaluation_date(self, timelines, ctx):
        assert evaluate_ast(field_ref("evaluation_date"), timelines, ctx) == date(2026, 6, 1)

    def test_field_ref_document_date(self, timelines, ctx):
        assert evaluate_ast(field_ref("document_date"), timelines, ctx) == date(2025, 6, 1)

    def test_field_ref_timeline(self, timelines, ctx):
        result = evaluate_ast(field_ref("management_fee_rate"), timelines, ctx)
        assert result == 2.0

    def test_field_ref_missing_raises(self, timelines, ctx):
        from engine.timeline_engine import MissingFieldValueError
        import pytest as _pytest
        with _pytest.raises(MissingFieldValueError) as exc_info:
            evaluate_ast(field_ref("nonexistent_field"), timelines, ctx)
        assert exc_info.value.field == "nonexistent_field"

    def test_comparison_gte_true(self, timelines, ctx):
        node = comparison("GTE", lit(50), lit(50))
        assert evaluate_ast(node, timelines, ctx) is True

    def test_comparison_lt_true(self, timelines, ctx):
        node = comparison("LT", lit(10), lit(50))
        assert evaluate_ast(node, timelines, ctx) is True

    def test_comparison_neq(self, timelines, ctx):
        assert evaluate_ast(comparison("NEQ", lit(1), lit(2)), timelines, ctx) is True
        assert evaluate_ast(comparison("NEQ", lit(1), lit(1)), timelines, ctx) is False

    def test_logical_and(self, timelines, ctx):
        node = logical("AND",
            ASTNode(node_type="literal", value=True, value_type="boolean"),
            ASTNode(node_type="literal", value=False, value_type="boolean"),
        )
        assert evaluate_ast(node, timelines, ctx) is False

    def test_logical_or(self, timelines, ctx):
        node = logical("OR",
            ASTNode(node_type="literal", value=True, value_type="boolean"),
            ASTNode(node_type="literal", value=False, value_type="boolean"),
        )
        assert evaluate_ast(node, timelines, ctx) is True

    def test_logical_not(self, timelines, ctx):
        node = logical("NOT",
            ASTNode(node_type="literal", value=True, value_type="boolean"),
        )
        assert evaluate_ast(node, timelines, ctx) is False

    def test_arithmetic_add(self, timelines, ctx):
        node = ASTNode(node_type="arithmetic", op="ADD",
                       args=[lit(1.5), lit(0.25)])
        assert evaluate_ast(node, timelines, ctx) == 1.75

    def test_arithmetic_sub(self, timelines, ctx):
        node = ASTNode(node_type="arithmetic", op="SUB",
                       args=[lit(2.0), lit(0.5)])
        assert evaluate_ast(node, timelines, ctx) == 1.5

    def test_arithmetic_mul(self, timelines, ctx):
        node = ASTNode(node_type="arithmetic", op="MUL",
                       args=[lit(2.0), lit(3.0)])
        assert evaluate_ast(node, timelines, ctx) == 6.0

    def test_arithmetic_div(self, timelines, ctx):
        node = ASTNode(node_type="arithmetic", op="DIV",
                       args=[lit(10.0), lit(4.0)])
        assert evaluate_ast(node, timelines, ctx) == 2.5

    def test_temporal_add_years(self, timelines, ctx):
        node = temporal("ADD_YEARS", lit_date("2024-01-15"), lit(2))
        result = evaluate_ast(node, timelines, ctx)
        assert result == date(2026, 1, 15)

    def test_temporal_add_months(self, timelines, ctx):
        node = temporal("ADD_MONTHS", lit_date("2024-01-15"), lit(6))
        result = evaluate_ast(node, timelines, ctx)
        assert result == date(2024, 7, 15)

    def test_temporal_add_days(self, timelines, ctx):
        node = temporal("ADD_DAYS", lit_date("2024-01-15"), lit(180))
        result = evaluate_ast(node, timelines, ctx)
        assert result == date(2024, 1, 15) + timedelta(days=180)

    def test_temporal_negative_years(self, timelines, ctx):
        node = temporal("ADD_YEARS", lit_date("2026-01-15"), lit(-1))
        assert evaluate_ast(node, timelines, ctx) == date(2025, 1, 15)

    def test_aggregator_min(self, timelines, ctx):
        node = aggregator("MIN", lit(5), lit(3), lit(8))
        assert evaluate_ast(node, timelines, ctx) == 3

    def test_aggregator_max(self, timelines, ctx):
        node = aggregator("MAX", lit(5), lit(3), lit(8))
        assert evaluate_ast(node, timelines, ctx) == 8

    def test_aggregator_max_dates(self, timelines, ctx):
        node = aggregator("MAX", lit_date("2025-01-01"), lit_date("2025-06-15"))
        assert evaluate_ast(node, timelines, ctx) == date(2025, 6, 15)

    def test_fn_anniversary(self, timelines, ctx):
        node = fn_call("ANNIVERSARY", lit(2), lit_date("2024-01-15"))
        assert evaluate_ast(node, timelines, ctx) == date(2026, 1, 15)

    def test_fn_days_since(self, timelines, ctx):
        node = fn_call("DAYS_SINCE", lit_date("2026-01-01"))
        result = evaluate_ast(node, timelines, ctx)
        assert result == (date(2026, 6, 1) - date(2026, 1, 1)).days

    def test_fn_next_fiscal_quarter_start(self, timelines, ctx):
        node = fn_call("NEXT_FISCAL_QUARTER_START", lit_date("2025-02-15"))
        result = evaluate_ast(node, timelines, ctx)
        assert result == date(2025, 4, 1)

    def test_fn_next_fiscal_quarter_wraps_year(self, timelines, ctx):
        node = fn_call("NEXT_FISCAL_QUARTER_START", lit_date("2025-11-15"))
        result = evaluate_ast(node, timelines, ctx)
        assert result == date(2026, 1, 1)

    def test_fn_fiscal_quarter_end(self, timelines, ctx):
        node = fn_call("FISCAL_QUARTER_END", lit(2), lit(2025))
        result = evaluate_ast(node, timelines, ctx)
        assert result == date(2025, 6, 30)

    def test_fn_fiscal_quarter_start_q1(self, timelines, ctx):
        node = fn_call("FISCAL_QUARTER_START", lit(1), lit(2025))
        assert evaluate_ast(node, timelines, ctx) == date(2025, 1, 1)

    def test_fn_fiscal_quarter_start_q2(self, timelines, ctx):
        node = fn_call("FISCAL_QUARTER_START", lit(2), lit(2025))
        assert evaluate_ast(node, timelines, ctx) == date(2025, 4, 1)

    def test_fn_fiscal_quarter_start_q3(self, timelines, ctx):
        node = fn_call("FISCAL_QUARTER_START", lit(3), lit(2025))
        assert evaluate_ast(node, timelines, ctx) == date(2025, 7, 1)

    def test_fn_fiscal_quarter_start_q4(self, timelines, ctx):
        node = fn_call("FISCAL_QUARTER_START", lit(4), lit(2025))
        assert evaluate_ast(node, timelines, ctx) == date(2025, 10, 1)

    def test_fn_month_start_with_year(self, timelines, ctx):
        node = fn_call("MONTH_START", lit(3), lit(2025))
        assert evaluate_ast(node, timelines, ctx) == date(2025, 3, 1)

    def test_fn_month_start_nearest(self, timelines, ctx):
        node = fn_call("MONTH_START", lit(6), lit_date("2025-05-15"),
                        lit("nearest", "string"))
        assert evaluate_ast(node, timelines, ctx) == date(2025, 6, 1)

    def test_fn_month_start_next_wraps_year(self, timelines, ctx):
        # Asking for month 5 with hint "next" when ref is already in May
        node = fn_call("MONTH_START", lit(5), lit_date("2025-05-15"),
                        lit("next", "string"))
        assert evaluate_ast(node, timelines, ctx) == date(2026, 5, 1)

    def test_fn_month_end_leap_year(self, timelines, ctx):
        node = fn_call("MONTH_END", lit(2), lit(2024))
        assert evaluate_ast(node, timelines, ctx) == date(2024, 2, 29)

    def test_fn_month_end_non_leap(self, timelines, ctx):
        node = fn_call("MONTH_END", lit(2), lit(2025))
        assert evaluate_ast(node, timelines, ctx) == date(2025, 2, 28)

    def test_fn_fund_realization_pct_from_timelines(self, ctx):
        """FUND_REALIZATION_PCT computes from component timelines."""
        tls = {
            "fund_total_realized_capital": FieldTimeline(),
            "fund_total_invested_capital": FieldTimeline(),
        }
        tls["fund_total_realized_capital"].insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=2_600_000,
            source_clause_text="r", entry_type="SET",
        ))
        tls["fund_total_invested_capital"].insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=10_000_000,
            source_clause_text="i", entry_type="SET",
        ))
        node = fn_call("FUND_REALIZATION_PCT")
        result = evaluate_ast(node, tls, ctx)
        assert result == pytest.approx(26.0)

    def test_fn_fund_realization_pct_primary_timeline(self, ctx):
        """Prefers fund_percentage_realized if present."""
        tls = {
            "fund_percentage_realized": FieldTimeline(),
        }
        tls["fund_percentage_realized"].insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=42.0,
            source_clause_text="r", entry_type="SET",
        ))
        node = fn_call("FUND_REALIZATION_PCT")
        assert evaluate_ast(node, tls, ctx) == 42.0

    def test_fn_dpi_from_distributions_and_paid_in(self, ctx):
        """DPI computes from fund_total_distributions / fund_total_paid_in_capital."""
        tls = {
            "fund_total_distributions": FieldTimeline(),
            "fund_total_paid_in_capital": FieldTimeline(),
        }
        tls["fund_total_distributions"].insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=150_000_000,
            source_clause_text="d", entry_type="SET",
        ))
        tls["fund_total_paid_in_capital"].insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=300_000_000,
            source_clause_text="p", entry_type="SET",
        ))
        node = fn_call("DPI")
        result = evaluate_ast(node, tls, ctx)
        assert result == pytest.approx(0.5)

    def test_fn_dpi_prefers_primary_timeline(self, ctx):
        """DPI uses precomputed dpi timeline if present."""
        tls = {
            "dpi": FieldTimeline(),
            "fund_total_distributions": FieldTimeline(),
            "fund_total_paid_in_capital": FieldTimeline(),
        }
        tls["dpi"].insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=1.2,
            source_clause_text="d", entry_type="SET",
        ))
        tls["fund_total_distributions"].insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=999,
            source_clause_text="d", entry_type="SET",
        ))
        tls["fund_total_paid_in_capital"].insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=999,
            source_clause_text="p", entry_type="SET",
        ))
        node = fn_call("DPI")
        assert evaluate_ast(node, tls, ctx) == 1.2

    def test_fn_dpi_returns_zero_when_new_fields_missing(self, ctx):
        """DPI returns 0 when fund_total_distributions or fund_total_paid_in_capital unavailable."""
        tls = {
            "fund_total_realized_capital": FieldTimeline(),
            "total_fund_commitment": FieldTimeline(),
        }
        tls["fund_total_realized_capital"].insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=5_000_000,
            source_clause_text="r", entry_type="SET",
        ))
        tls["total_fund_commitment"].insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=50_000_000,
            source_clause_text="c", entry_type="SET",
        ))
        node = fn_call("DPI")
        assert evaluate_ast(node, tls, ctx) == 0


# ═══════════════════════════════════════════════════════════════════════════
# execute — SET
# ═══════════════════════════════════════════════════════════════════════════

class TestExecuteSET:

    def test_basic_set(self, empty_timelines, base_ctx):
        instr = make_set("management_fee_rate", 1.5, eff_date="2025-06-01")
        execute(instr, empty_timelines, base_ctx)
        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 7, 1)) == 1.5

    def test_set_uses_document_date_when_no_effective_date(self, empty_timelines, base_ctx):
        instr = make_set("management_fee_rate", 1.5)
        execute(instr, empty_timelines, base_ctx)
        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(base_ctx.document_date) == 1.5
        assert ft.value_at(base_ctx.document_date - timedelta(days=1)) is None

    def test_set_with_end_date(self, empty_timelines, base_ctx):
        instr = make_set("management_fee_rate", 1.5,
                         eff_date="2025-01-01", eff_end="2025-07-01")
        execute(instr, empty_timelines, base_ctx)
        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 3, 1)) == 1.5
        assert ft.value_at(date(2025, 7, 1)) is None  # expired

    def test_set_with_condition_true(self, empty_timelines, base_ctx):
        cond = comparison("GTE", lit(100), lit(50))
        instr = make_set("management_fee_rate", 1.5,
                         eff_date="2025-06-01", condition=cond)
        execute(instr, empty_timelines, base_ctx)
        assert empty_timelines["management_fee_rate"].value_at(date(2025, 7, 1)) == 1.5

    def test_set_with_condition_false(self, empty_timelines, base_ctx):
        cond = comparison("GTE", lit(10), lit(50))
        instr = make_set("management_fee_rate", 1.5,
                         eff_date="2025-06-01", condition=cond)
        execute(instr, empty_timelines, base_ctx)
        assert "management_fee_rate" not in empty_timelines or \
               empty_timelines.get("management_fee_rate", FieldTimeline()).value_at(date(2025, 7, 1)) is None

    def test_set_skipped_when_no_date(self, empty_timelines):
        """SET with no document_date and no effective_date_expr is skipped."""
        ctx = EvaluationContext(evaluation_date=date(2026, 6, 1), document_date=None)
        instr = make_set("management_fee_rate", 1.5)
        execute(instr, empty_timelines, ctx)
        assert "management_fee_rate" not in empty_timelines

    def test_set_non_date_end_expr_graceful(self, seed_timelines, base_ctx):
        """If effective_end_date_expr evaluates to a non-date (e.g., a number
        from FUND_REALIZATION_PCT used by mistake), eff_end becomes None
        (treated as permanent) instead of crashing."""
        instr = ClauseInstruction(
            clause_text="fee is 3% until realization hits 50%",
            affected_field="management_fee_rate",
            action="SET",
            value_expr=lit_pct(3),
            effective_date_expr=lit_date("2025-06-01"),
            # WRONG: FUND_REALIZATION_PCT returns a number, not a date.
            # The engine should handle this gracefully.
            effective_end_date_expr=fn_call("FUND_REALIZATION_PCT"),
        )
        # Should not crash — just treats end_date as None (permanent)
        execute(instr, seed_timelines, base_ctx)
        ft = seed_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 7, 1)) == 3  # SET applied
        # Since end_date was non-date → treated as None → value persists
        assert ft.value_at(date(2028, 1, 1)) == 3


# ═══════════════════════════════════════════════════════════════════════════
# execute — ADJUST
# ═══════════════════════════════════════════════════════════════════════════

class TestExecuteADJUST:

    def test_adjust_on_existing(self, seed_timelines, base_ctx):
        instr = make_adjust("management_fee_rate", -0.25, "REDUCTION",
                            eff_date="2025-06-01")
        execute(instr, seed_timelines, base_ctx)
        ft = seed_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 7, 1)) == 1.75  # 2.0 - 0.25

    def test_adjust_stacking(self, seed_timelines, base_ctx):
        """Two ADJUSTs stack correctly."""
        execute(make_adjust("management_fee_rate", -0.25, "REDUCTION",
                            eff_date="2025-06-01"), seed_timelines, base_ctx)
        execute(make_adjust("management_fee_rate", -0.25, "REDUCTION",
                            eff_date="2025-06-01"), seed_timelines, base_ctx)
        ft = seed_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 7, 1)) == 1.5  # 2.0 - 0.25 - 0.25

    def test_adjust_on_empty_defaults_to_zero(self, empty_timelines, base_ctx):
        instr = make_adjust("management_fee_rate", 0.5, "INCREASE",
                            eff_date="2025-06-01")
        execute(instr, empty_timelines, base_ctx)
        assert empty_timelines["management_fee_rate"].value_at(date(2025, 7, 1)) == 0.5

    def test_adjust_does_not_affect_prior_dates(self, seed_timelines, base_ctx):
        execute(make_adjust("management_fee_rate", -0.5, "REDUCTION",
                            eff_date="2025-06-01"), seed_timelines, base_ctx)
        ft = seed_timelines["management_fee_rate"]
        assert ft.value_at(date(2024, 6, 1)) == 2.0   # untouched
        assert ft.value_at(date(2025, 7, 1)) == 1.5   # adjusted

    # ── Multiplicative ADJUST tests ──────────────────────────────────

    def test_multiplicative_reduction_50pct(self, seed_timelines, base_ctx):
        """'Step down by 50%' → current × 0.5 = 1.0 (from 2.0)."""
        instr = make_adjust("management_fee_rate", 0.5, "REDUCTION",
                            eff_date="2025-06-01", adjust_mode="multiplicative")
        execute(instr, seed_timelines, base_ctx)
        ft = seed_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 7, 1)) == 1.0  # 2.0 * 0.5

    def test_multiplicative_increase_20pct(self, seed_timelines, base_ctx):
        """'Increase by 20%' → current × 1.2 = 2.4 (from 2.0)."""
        instr = make_adjust("management_fee_rate", 1.2, "INCREASE",
                            eff_date="2025-06-01", adjust_mode="multiplicative")
        execute(instr, seed_timelines, base_ctx)
        ft = seed_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 7, 1)) == pytest.approx(2.4)  # 2.0 * 1.2

    def test_multiplicative_on_empty_defaults_to_zero(self, empty_timelines, base_ctx):
        """Multiplicative on empty timeline: 0 * 0.5 = 0."""
        instr = make_adjust("management_fee_rate", 0.5, "REDUCTION",
                            eff_date="2025-06-01", adjust_mode="multiplicative")
        execute(instr, empty_timelines, base_ctx)
        assert empty_timelines["management_fee_rate"].value_at(date(2025, 7, 1)) == 0

    def test_multiplicative_does_not_affect_prior_dates(self, seed_timelines, base_ctx):
        """Multiplicative ADJUST only applies from effective date forward."""
        execute(make_adjust("management_fee_rate", 0.5, "REDUCTION",
                            eff_date="2025-06-01", adjust_mode="multiplicative"),
                seed_timelines, base_ctx)
        ft = seed_timelines["management_fee_rate"]
        assert ft.value_at(date(2024, 6, 1)) == 2.0  # untouched
        assert ft.value_at(date(2025, 7, 1)) == 1.0  # adjusted

    def test_multiplicative_stacking(self, seed_timelines, base_ctx):
        """Two multiplicative ADJUSTs stack: 2.0 * 0.5 = 1.0, then 1.0 * 0.5 = 0.5."""
        execute(make_adjust("management_fee_rate", 0.5, "REDUCTION",
                            eff_date="2025-06-01", adjust_mode="multiplicative"),
                seed_timelines, base_ctx)
        execute(make_adjust("management_fee_rate", 0.5, "REDUCTION",
                            eff_date="2025-06-01", adjust_mode="multiplicative"),
                seed_timelines, base_ctx)
        ft = seed_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 7, 1)) == 0.5  # 2.0 * 0.5 * 0.5

    def test_multiplicative_with_end_date(self, seed_timelines, base_ctx):
        """Multiplicative ADJUST with end_date: effective within window only."""
        execute(make_adjust("management_fee_rate", 0.5, "REDUCTION",
                            eff_date="2025-06-01", eff_end="2026-01-01",
                            adjust_mode="multiplicative"),
                seed_timelines, base_ctx)
        ft = seed_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 7, 1)) == 1.0   # during: 2.0 * 0.5
        assert ft.value_at(date(2026, 6, 1)) == 2.0   # after: original resurfaces

    def test_additive_is_default(self, seed_timelines, base_ctx):
        """make_adjust defaults to additive mode."""
        instr = make_adjust("management_fee_rate", -0.25, "REDUCTION",
                            eff_date="2025-06-01")
        assert instr.adjust_mode == "additive"
        execute(instr, seed_timelines, base_ctx)
        ft = seed_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 7, 1)) == 1.75  # 2.0 + (-0.25)

    def test_mixed_additive_then_multiplicative(self, seed_timelines, base_ctx):
        """Additive ADJUST followed by multiplicative: (2.0 - 0.5) * 0.5 = 0.75."""
        execute(make_adjust("management_fee_rate", -0.5, "REDUCTION",
                            eff_date="2025-06-01", adjust_mode="additive"),
                seed_timelines, base_ctx)
        execute(make_adjust("management_fee_rate", 0.5, "REDUCTION",
                            eff_date="2025-06-01", adjust_mode="multiplicative"),
                seed_timelines, base_ctx)
        ft = seed_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 7, 1)) == 0.75  # (2.0 - 0.5) * 0.5


# ═══════════════════════════════════════════════════════════════════════════
# execute — CONSTRAIN
# ═══════════════════════════════════════════════════════════════════════════

class TestExecuteCONSTRAIN:

    def test_cap_limits_value(self, seed_timelines, base_ctx):
        execute(make_constrain("management_fee_rate", 1.75, "CAP"),
                seed_timelines, base_ctx)
        ft = seed_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 1, 1)) == 1.75  # capped from 2.0

    def test_floor_raises_value(self, empty_timelines, base_ctx):
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=0.3,
            source_clause_text="seed", entry_type="SET",
        ))
        empty_timelines["management_fee_rate"] = ft
        execute(make_constrain("management_fee_rate", 0.5, "FLOOR"),
                empty_timelines, base_ctx)
        assert empty_timelines["management_fee_rate"].value_at(date(2024, 6, 1)) == 0.5

    def test_constrain_with_active_range(self, seed_timelines, base_ctx):
        instr = make_constrain("management_fee_rate", 1.0, "CAP",
                               eff_date="2025-01-01", eff_end="2026-01-01")
        execute(instr, seed_timelines, base_ctx)
        ft = seed_timelines["management_fee_rate"]
        assert ft.value_at(date(2024, 6, 1)) == 2.0   # before cap
        assert ft.value_at(date(2025, 6, 1)) == 1.0   # during cap
        assert ft.value_at(date(2026, 6, 1)) == 2.0   # after cap


# ═══════════════════════════════════════════════════════════════════════════
# execute — GATE
# ═══════════════════════════════════════════════════════════════════════════

class TestExecuteGATE:

    def _setup_reduction(self, timelines, ctx):
        """Create a timeline with a reduction at 2025-06-01."""
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15",
                         clause_text="LPA seed"), timelines, ctx)
        execute(make_set("management_fee_rate", 1.5, eff_date="2025-06-01",
                         clause_text="side letter reduction"), timelines, ctx)

    def test_gate_move_defers_reduction(self, empty_timelines, base_ctx):
        self._setup_reduction(empty_timelines, base_ctx)
        execute(make_gate_move(
            "management_fee_rate", "REDUCTION", "AT", "2025-06-01",
            move_to_date="2026-01-01",
        ), empty_timelines, base_ctx)
        ft = empty_timelines["management_fee_rate"]
        # Original date should now show seed value
        assert ft.value_at(date(2025, 7, 1)) == 2.0
        # Reduction has moved to 2026-01-01
        assert ft.value_at(date(2026, 2, 1)) == 1.5

    def test_gate_move_with_new_end_date(self, empty_timelines, base_ctx):
        self._setup_reduction(empty_timelines, base_ctx)
        execute(make_gate_move(
            "management_fee_rate", "REDUCTION", "AT", "2025-06-01",
            move_to_date="2026-01-01", new_end_date="2026-07-01",
        ), empty_timelines, base_ctx)
        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2026, 3, 1)) == 1.5
        assert ft.value_at(date(2026, 7, 1)) == 2.0  # expired, seed resurfaces

    def test_gate_condition_true_keeps_transition(self, empty_timelines, base_ctx):
        self._setup_reduction(empty_timelines, base_ctx)
        cond = comparison("GTE", lit(100), lit(50))  # True
        execute(make_gate_condition(
            "management_fee_rate", "REDUCTION", "AT", "2025-06-01", cond,
        ), empty_timelines, base_ctx)
        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 7, 1)) == 1.5  # still there

    def test_gate_condition_false_removes_transition(self, empty_timelines, base_ctx):
        self._setup_reduction(empty_timelines, base_ctx)
        cond = comparison("GTE", lit(10), lit(50))  # False
        execute(make_gate_condition(
            "management_fee_rate", "REDUCTION", "AT", "2025-06-01", cond,
        ), empty_timelines, base_ctx)
        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 7, 1)) == 2.0  # reduction removed

    def test_gate_scope_from(self, empty_timelines, base_ctx):
        """GATE with scope_mode=FROM matches all reductions from the scope date."""
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 1.5, eff_date="2025-06-01"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 1.0, eff_date="2026-01-01"), empty_timelines, base_ctx)

        execute(make_gate_move(
            "management_fee_rate", "REDUCTION", "FROM", "2025-01-01",
            move_to_date="2027-01-01",
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        # Both reductions moved to 2027
        assert ft.value_at(date(2025, 7, 1)) == 2.0
        assert ft.value_at(date(2026, 6, 1)) == 2.0

    def test_gate_move_does_not_prepone(self, empty_timelines, base_ctx):
        """GATE with no scope should only move transitions BEFORE the destination.
        A reduction already past the move-to date must not be moved backward."""
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 1.5, eff_date="2025-06-01"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 1.0, eff_date="2027-01-01"), empty_timelines, base_ctx)

        # Defer reductions to 2026-06-01 — no scope (effective_date_expr=None)
        execute(make_gate_move(
            "management_fee_rate", "REDUCTION", None, None,
            move_to_date="2026-06-01",
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        # The 2025-06-01 reduction (before 2026-06-01) should have moved
        assert ft.value_at(date(2025, 7, 1)) == 2.0   # no longer reduced here
        assert ft.value_at(date(2026, 7, 1)) == 1.5   # moved here

        # The 2027-01-01 reduction (after 2026-06-01) must NOT have moved
        assert ft.value_at(date(2027, 6, 1)) == 1.0   # still at original date

    def test_gate_prepone(self, empty_timelines, base_ctx):
        """GATE with PREPONE only moves transitions AFTER the destination earlier."""
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 1.5, eff_date="2025-06-01"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 1.0, eff_date="2027-01-01"), empty_timelines, base_ctx)

        # Prepone reductions to 2026-06-01
        execute(make_gate_move(
            "management_fee_rate", "REDUCTION", None, None,
            move_to_date="2026-06-01", gate_direction="PREPONE",
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        # 2025-06-01 reduction (before 2026-06-01) must NOT move
        assert ft.value_at(date(2025, 7, 1)) == 1.5
        # 2027-01-01 reduction (after 2026-06-01) should have moved to 2026-06-01
        assert ft.value_at(date(2026, 7, 1)) == 1.0

    def test_gate_reschedule_moves_all(self, empty_timelines, base_ctx):
        """GATE with RESCHEDULE moves ALL matching transitions regardless of direction."""
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 1.5, eff_date="2025-06-01"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 1.0, eff_date="2027-01-01"), empty_timelines, base_ctx)

        # Reschedule ALL reductions to 2026-06-01
        execute(make_gate_move(
            "management_fee_rate", "REDUCTION", None, None,
            move_to_date="2026-06-01", gate_direction="RESCHEDULE",
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        # Both reductions should now be at 2026-06-01
        assert ft.value_at(date(2025, 7, 1)) == 2.0   # both moved away
        assert ft.value_at(date(2026, 7, 1)) == 1.0   # latest insertion order wins

    def test_gate_no_action_manual_review_skip(self, empty_timelines, base_ctx):
        """NO_ACTION and MANUAL_REVIEW are no-ops."""
        instr_noop = ClauseInstruction(
            clause_text="noop", action="NO_ACTION",
            no_action_reason="test",
        )
        instr_mr = ClauseInstruction(
            clause_text="manual", action="MANUAL_REVIEW",
            affected_field="management_fee_rate",
            manual_review_reason="test",
        )
        execute(instr_noop, empty_timelines, base_ctx)
        execute(instr_mr, empty_timelines, base_ctx)
        assert len(empty_timelines) == 0


# ═══════════════════════════════════════════════════════════════════════════
# execute_all — integration
# ═══════════════════════════════════════════════════════════════════════════

class TestExecuteAll:

    def test_seed_set_adjust(self):
        """The canonical test: seed -> SET -> ADJUST."""
        seed = {
            "management_fee_rate": [
                {"date": "2024-01-15", "value": 2.0, "source": "LPA"},
            ],
        }
        instructions = [
            make_set("management_fee_rate", 1.5, eff_date="2025-06-01",
                     clause_text="reduce to 1.5"),
            make_adjust("management_fee_rate", -0.25, "REDUCTION",
                        eff_date="2026-01-01", clause_text="extra 25bps"),
        ]
        doc_dates = {
            "reduce to 1.5": date(2025, 6, 1),
            "extra 25bps": date(2026, 1, 1),
        }
        tls = execute_all(instructions, seed, date(2026, 12, 31), doc_dates, {})
        ft = tls["management_fee_rate"]
        assert ft.value_at(date(2024, 6, 1)) == 2.0
        assert ft.value_at(date(2025, 7, 1)) == 1.5
        assert ft.value_at(date(2026, 6, 1)) == 1.25

    def test_set_then_constrain_then_query(self):
        seed = {"management_fee_rate": [
            {"date": "2024-01-15", "value": 2.0, "source": "LPA"},
        ]}
        instructions = [
            make_set("management_fee_rate", 3.0, eff_date="2025-01-01",
                     clause_text="increase"),
            make_constrain("management_fee_rate", 2.5, "CAP",
                           clause_text="cap at 2.5"),
        ]
        doc_dates = {"increase": date(2025, 1, 1), "cap at 2.5": date(2025, 1, 1)}
        tls = execute_all(instructions, seed, date(2026, 1, 1), doc_dates, {})
        assert tls["management_fee_rate"].value_at(date(2025, 6, 1)) == 2.5

    def test_set_then_gate_defer(self):
        seed = {"management_fee_rate": [
            {"date": "2024-01-15", "value": 2.0, "source": "LPA"},
        ]}
        instructions = [
            make_set("management_fee_rate", 1.5, eff_date="2025-06-01",
                     clause_text="reduction"),
            make_gate_move("management_fee_rate", "REDUCTION", "AT", "2025-06-01",
                           move_to_date="2026-06-01", clause_text="defer"),
        ]
        doc_dates = {"reduction": date(2025, 6, 1), "defer": date(2025, 6, 1)}
        tls = execute_all(instructions, seed, date(2027, 1, 1), doc_dates, {})
        ft = tls["management_fee_rate"]
        assert ft.value_at(date(2025, 9, 1)) == 2.0   # deferred
        assert ft.value_at(date(2026, 9, 1)) == 1.5   # now active

    def test_empty_instructions(self):
        seed = {"management_fee_rate": [
            {"date": "2024-01-15", "value": 2.0, "source": "LPA"},
        ]}
        tls = execute_all([], seed, date(2026, 1, 1), {}, {})
        assert tls["management_fee_rate"].value_at(date(2025, 1, 1)) == 2.0

    def test_multiple_fields(self):
        seed = {
            "management_fee_rate": [{"date": "2024-01-15", "value": 2.0, "source": "LPA"}],
            "management_fee_basis": [{"date": "2024-01-15", "value": "committed_capital", "source": "LPA"}],
        }
        instructions = [
            make_set("management_fee_rate", 1.5, eff_date="2025-01-01", clause_text="rate"),
            make_set("management_fee_basis",
                     ASTNode(node_type="literal", value="invested_capital", value_type="string"),
                     eff_date="2025-01-01", clause_text="basis"),
        ]
        doc_dates = {"rate": date(2025, 1, 1), "basis": date(2025, 1, 1)}
        tls = execute_all(instructions, seed, date(2026, 1, 1), doc_dates, {})
        assert tls["management_fee_rate"].value_at(date(2025, 6, 1)) == 1.5
        assert tls["management_fee_basis"].value_at(date(2025, 6, 1)) == "invested_capital"


# ═══════════════════════════════════════════════════════════════════════════
# Registry consistency
# ═══════════════════════════════════════════════════════════════════════════

def test_runtime_registry_matches_model_registry():
    """RUNTIME_FUNCTION_REGISTRY keys must exactly match FUNCTION_REGISTRY."""
    from engine.models import FUNCTION_REGISTRY
    from engine.timeline_engine import RUNTIME_FUNCTION_REGISTRY
    assert set(RUNTIME_FUNCTION_REGISTRY.keys()) == FUNCTION_REGISTRY
