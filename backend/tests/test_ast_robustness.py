"""Robustness tests for evaluate_ast — type coercion and None safety.

Tests every node type against:
1. Mixed date/str args (field_ref returns str, literal returns date)
2. None args (missing field_ref, missing timeline)
3. Edge cases that could crash in production
"""
from __future__ import annotations

from datetime import date

import pytest

from engine.models import ASTNode
from engine.timeline_engine import (
    EvaluationContext,
    FieldTimeline,
    TimelineEntry,
    evaluate_ast,
)
from tests.conftest import (
    comparison, fn_call, lit, lit_date, field_ref,
    temporal, aggregator,
)


@pytest.fixture
def ctx():
    return EvaluationContext(
        evaluation_date=date(2026, 6, 1),
        document_date=date(2025, 6, 1),
    )


@pytest.fixture
def timelines_with_string_dates():
    """Timelines where date fields store values as strings (like seed data)."""
    tls = {}
    ft = FieldTimeline()
    ft.insert_entry(TimelineEntry(
        date=date(2024, 1, 15), value="2029-01-15",  # string!
        source_clause_text="LPA", entry_type="SET",
    ))
    tls["fund_investment_end_date"] = ft

    ft2 = FieldTimeline()
    ft2.insert_entry(TimelineEntry(
        date=date(2024, 1, 15), value="2024-12-15",  # string!
        source_clause_text="LPA", entry_type="SET",
    ))
    tls["fund_final_closing_date"] = ft2
    return tls


@pytest.fixture
def empty_timelines():
    return {}


# ═══════════════════════════════════════════════════════════════════════════
# Aggregator: MIN/MAX with mixed types
# ═══════════════════════════════════════════════════════════════════════════


class TestAggregatorRobustness:

    def test_min_date_vs_string(self, timelines_with_string_dates, ctx):
        """MIN(literal_date, field_ref_string_date) — mixed types."""
        node = aggregator("MIN",
            lit_date("2030-06-01"),
            field_ref("fund_investment_end_date"),
        )
        result = evaluate_ast(node, timelines_with_string_dates, ctx)
        assert result == date(2029, 1, 15)  # string "2029-01-15" < date 2030-06-01

    def test_max_date_vs_string(self, timelines_with_string_dates, ctx):
        """MAX(literal_date, field_ref_string_date) — mixed types."""
        node = aggregator("MAX",
            lit_date("2025-01-01"),
            field_ref("fund_investment_end_date"),
        )
        result = evaluate_ast(node, timelines_with_string_dates, ctx)
        assert result == date(2029, 1, 15)

    def test_min_with_none(self, empty_timelines, ctx):
        """MIN(date, None) — missing field_ref returns None."""
        node = aggregator("MIN",
            lit_date("2029-01-15"),
            field_ref("nonexistent_field"),
        )
        result = evaluate_ast(node, empty_timelines, ctx)
        assert result == date(2029, 1, 15)  # None filtered out

    def test_max_with_none(self, empty_timelines, ctx):
        """MAX(None, date) — None filtered out."""
        node = aggregator("MAX",
            field_ref("nonexistent_field"),
            lit_date("2029-01-15"),
        )
        result = evaluate_ast(node, empty_timelines, ctx)
        assert result == date(2029, 1, 15)

    def test_min_all_none(self, empty_timelines, ctx):
        """MIN(None, None) — all None returns None."""
        node = aggregator("MIN",
            field_ref("a"),
            field_ref("b"),
        )
        result = evaluate_ast(node, empty_timelines, ctx)
        assert result is None

    def test_min_three_mixed(self, timelines_with_string_dates, ctx):
        """MIN(literal, field_ref_str, field_ref_str) — three args."""
        node = aggregator("MIN",
            lit_date("2030-01-01"),
            field_ref("fund_investment_end_date"),   # "2029-01-15"
            field_ref("fund_final_closing_date"),    # "2024-12-15"
        )
        result = evaluate_ast(node, timelines_with_string_dates, ctx)
        assert result == date(2024, 12, 15)


# ═══════════════════════════════════════════════════════════════════════════
# Comparison: mixed types and None
# ═══════════════════════════════════════════════════════════════════════════


class TestComparisonRobustness:

    def test_gte_date_vs_string(self, timelines_with_string_dates, ctx):
        """evaluation_date (date obj) >= fund_investment_end_date (string)."""
        node = comparison(">=",
            field_ref("evaluation_date"),
            field_ref("fund_investment_end_date"),
        )
        result = evaluate_ast(node, timelines_with_string_dates, ctx)
        # 2026-06-01 >= 2029-01-15 → False
        assert result is False

    def test_gte_string_vs_date(self, timelines_with_string_dates, ctx):
        """field_ref_string >= literal_date."""
        node = comparison(">=",
            field_ref("fund_investment_end_date"),
            lit_date("2025-01-01"),
        )
        result = evaluate_ast(node, timelines_with_string_dates, ctx)
        # "2029-01-15" coerced to date >= 2025-01-01 → True
        assert result is True

    def test_comparison_left_none(self, empty_timelines, ctx):
        """None >= 50 — left is None from missing field."""
        node = comparison(">=",
            field_ref("nonexistent"),
            lit(50),
        )
        result = evaluate_ast(node, empty_timelines, ctx)
        assert result is False  # None safety → False

    def test_comparison_right_none(self, empty_timelines, ctx):
        """50 >= None — right is None."""
        node = comparison(">=",
            lit(50),
            field_ref("nonexistent"),
        )
        result = evaluate_ast(node, empty_timelines, ctx)
        assert result is False

    def test_comparison_both_none(self, empty_timelines, ctx):
        """None >= None."""
        node = comparison(">=",
            field_ref("a"),
            field_ref("b"),
        )
        result = evaluate_ast(node, empty_timelines, ctx)
        assert result is False

    def test_eq_date_vs_string(self, timelines_with_string_dates, ctx):
        """date == string_date — should coerce and compare."""
        node = comparison("==",
            lit_date("2029-01-15"),
            field_ref("fund_investment_end_date"),
        )
        result = evaluate_ast(node, timelines_with_string_dates, ctx)
        assert result is True

    def test_lt_string_vs_date(self, timelines_with_string_dates, ctx):
        """string_date < literal_date."""
        node = comparison("<",
            field_ref("fund_final_closing_date"),  # "2024-12-15"
            lit_date("2025-01-01"),
        )
        result = evaluate_ast(node, timelines_with_string_dates, ctx)
        assert result is True


# ═══════════════════════════════════════════════════════════════════════════
# Temporal: string dates and None
# ═══════════════════════════════════════════════════════════════════════════


class TestTemporalRobustness:

    def test_add_years_to_string_date(self, timelines_with_string_dates, ctx):
        """ADD_YEARS(field_ref_string, 5) — string date as base."""
        node = temporal("ADD_YEARS",
            field_ref("fund_final_closing_date"),  # "2024-12-15"
            lit(5),
        )
        result = evaluate_ast(node, timelines_with_string_dates, ctx)
        assert result == date(2029, 12, 15)

    def test_add_months_to_string_date(self, timelines_with_string_dates, ctx):
        """ADD_MONTHS(field_ref_string, 18)."""
        node = temporal("ADD_MONTHS",
            field_ref("fund_final_closing_date"),  # "2024-12-15"
            lit(18),
        )
        result = evaluate_ast(node, timelines_with_string_dates, ctx)
        assert result == date(2026, 6, 15)

    def test_add_days_none_base(self, empty_timelines, ctx):
        """ADD_DAYS(None, 90) — None base returns None."""
        node = temporal("ADD_DAYS",
            field_ref("nonexistent"),
            lit(90),
        )
        result = evaluate_ast(node, empty_timelines, ctx)
        assert result is None

    def test_add_years_none_base(self, empty_timelines, ctx):
        """ADD_YEARS(None, 5) — None base returns None."""
        node = temporal("ADD_YEARS",
            field_ref("nonexistent"),
            lit(5),
        )
        result = evaluate_ast(node, empty_timelines, ctx)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# Arithmetic: None safety
# ═══════════════════════════════════════════════════════════════════════════


class TestArithmeticRobustness:

    def test_add_none_left(self, empty_timelines, ctx):
        """None + 1 — returns None."""
        node = ASTNode(
            node_type="arithmetic", op="ADD",
            args=[field_ref("nonexistent"), lit(1)],
        )
        result = evaluate_ast(node, empty_timelines, ctx)
        assert result is None

    def test_sub_none_right(self, empty_timelines, ctx):
        """1 - None — returns None."""
        node = ASTNode(
            node_type="arithmetic", op="SUB",
            args=[lit(1), field_ref("nonexistent")],
        )
        result = evaluate_ast(node, empty_timelines, ctx)
        assert result is None

    def test_normal_arithmetic(self, empty_timelines, ctx):
        """Normal 10 + 5 = 15."""
        node = ASTNode(
            node_type="arithmetic", op="ADD",
            args=[lit(10), lit(5)],
        )
        result = evaluate_ast(node, empty_timelines, ctx)
        assert result == 15


# ═══════════════════════════════════════════════════════════════════════════
# Complex nested expressions with mixed types
# ═══════════════════════════════════════════════════════════════════════════


class TestComplexExpressions:

    def test_min_of_field_ref_and_anniversary(self, timelines_with_string_dates, ctx):
        """MIN(field_ref("fund_investment_end_date"), ANNIVERSARY(5, field_ref("fund_final_closing_date")))

        This is the exact pattern from the MFN clause that crashed:
        "Upon expiration of Investment Period (or 5th anniversary of Final Closing, whichever first)"
        """
        node = aggregator("MIN",
            field_ref("fund_investment_end_date"),      # returns string "2029-01-15"
            fn_call("ANNIVERSARY", lit(5),
                field_ref("fund_final_closing_date")),  # returns date 2029-12-15
        )
        result = evaluate_ast(node, timelines_with_string_dates, ctx)
        # MIN(2029-01-15, 2029-12-15) = 2029-01-15
        assert result == date(2029, 1, 15)

    def test_comparison_eval_date_vs_anniversary_of_string(self, timelines_with_string_dates, ctx):
        """evaluation_date >= ANNIVERSARY(2, fund_final_closing_date)

        Pattern from GATE condition: "deferred until 2nd anniversary of final closing"
        """
        node = comparison(">=",
            field_ref("evaluation_date"),
            fn_call("ANNIVERSARY", lit(2),
                field_ref("fund_final_closing_date")),
        )
        result = evaluate_ast(node, timelines_with_string_dates, ctx)
        # 2026-06-01 >= ANNIVERSARY(2, "2024-12-15") = 2026-12-15 → False
        assert result is False

    def test_max_with_temporal_and_field_ref(self, timelines_with_string_dates, ctx):
        """MAX(fund_final_closing_date, ADD_MONTHS(fund_initial_closing_date, 18))

        Pattern: "later of final closing or 18 months after initial closing"
        fund_final_closing_date is string, temporal returns date.
        """
        # Add fund_initial_closing_date
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 15), value="2024-01-15",
            source_clause_text="LPA", entry_type="SET",
        ))
        timelines_with_string_dates["fund_initial_closing_date"] = ft

        node = aggregator("MAX",
            field_ref("fund_final_closing_date"),      # string "2024-12-15"
            temporal("ADD_MONTHS",
                field_ref("fund_initial_closing_date"),  # string "2024-01-15"
                lit(18)),                                 # → date 2025-07-15
        )
        result = evaluate_ast(node, timelines_with_string_dates, ctx)
        # MAX(2024-12-15, 2025-07-15) = 2025-07-15
        assert result == date(2025, 7, 15)

    def test_gate_condition_with_none_realization(self, empty_timelines, ctx):
        """FUND_REALIZATION_PCT() >= 50 when no realization data exists.

        Should return False (None >= 50 → False), not crash.
        """
        node = comparison(">=",
            fn_call("FUND_REALIZATION_PCT"),
            lit(50),
        )
        result = evaluate_ast(node, empty_timelines, ctx)
        # FUND_REALIZATION_PCT returns 0 when no data → 0 >= 50 → False
        assert result is False

    def test_nested_min_with_none_and_dates(self, timelines_with_string_dates, ctx):
        """MIN(field_ref(exists), field_ref(missing), literal_date)

        One arg is None → filtered out, MIN of remaining two.
        """
        node = aggregator("MIN",
            field_ref("fund_investment_end_date"),    # "2029-01-15"
            field_ref("nonexistent_field"),           # None
            lit_date("2030-06-01"),                    # date
        )
        result = evaluate_ast(node, timelines_with_string_dates, ctx)
        assert result == date(2029, 1, 15)
