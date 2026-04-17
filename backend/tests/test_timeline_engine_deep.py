"""Deep unit tests for engine/timeline_engine.py.

Covers GATE edge cases, ADJUST stacking, CONSTRAIN with time bounds,
value_at edge cases, and integration sequences.
"""
from __future__ import annotations

from datetime import date

import pytest

from engine.models import ASTNode, ClauseInstruction
from engine.timeline_engine import (
    ConstraintRule,
    EvaluationContext,
    FieldTimeline,
    TimelineEntry,
    evaluate_ast,
    execute,
)
from tests.conftest import (
    comparison, fn_call, lit, lit_date, lit_pct, field_ref,
    make_set, make_adjust, make_constrain, make_gate_move, make_gate_condition,
)


# ═══════════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def base_ctx():
    return EvaluationContext(
        evaluation_date=date(2026, 6, 1),
        document_date=date(2025, 1, 1),
        fund_data={},
    )


@pytest.fixture
def empty_timelines():
    return {}


# ═══════════════════════════════════════════════════════════════════════════
# F. GATE deep cases
# ═══════════════════════════════════════════════════════════════════════════


class TestGATEDeep:

    def _setup_three_sets(self, tls, ctx):
        """Seed: 2.0 → 1.75 at mid → 1.5 at late."""
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), tls, ctx)
        execute(make_set("management_fee_rate", 1.75, eff_date="2025-06-01"), tls, ctx)
        execute(make_set("management_fee_rate", 1.5, eff_date="2026-01-01"), tls, ctx)

    def test_gate_at_moves_only_exact_date(self, empty_timelines, base_ctx):
        """scope_mode=AT: moves only the entry on exactly that date."""
        self._setup_three_sets(empty_timelines, base_ctx)
        execute(make_gate_move(
            "management_fee_rate", "REDUCTION", "AT", "2025-06-01",
            move_to_date="2027-01-01",
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        # The 2025-06-01 entry moved to 2027-01-01
        assert ft.value_at(date(2025, 9, 1)) == 2.0
        # The 2026-01-01 entry was NOT touched
        assert ft.value_at(date(2026, 6, 1)) == 1.5

    def test_gate_from_moves_all_after(self, empty_timelines, base_ctx):
        """scope_mode=FROM: moves all entries on or after scope date."""
        self._setup_three_sets(empty_timelines, base_ctx)
        execute(make_gate_move(
            "management_fee_rate", "REDUCTION", "FROM", "2025-06-01",
            move_to_date="2028-01-01",
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        # Both reductions (2025-06-01 and 2026-01-01) should be gone
        assert ft.value_at(date(2025, 9, 1)) == 2.0
        assert ft.value_at(date(2026, 6, 1)) == 2.0

    def test_gate_before_moves_entries_before_scope(self, empty_timelines, base_ctx):
        """scope_mode=BEFORE: moves entries before scope date."""
        self._setup_three_sets(empty_timelines, base_ctx)
        execute(make_gate_move(
            "management_fee_rate", "REDUCTION", "BEFORE", "2026-01-01",
            move_to_date="2027-06-01",
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        # 2025-06-01 reduction was before scope → moved
        assert ft.value_at(date(2025, 9, 1)) == 2.0
        # 2026-01-01 reduction was NOT before scope → untouched
        assert ft.value_at(date(2026, 6, 1)) == 1.5

    def test_gate_move_with_new_end_date(self, empty_timelines, base_ctx):
        """gate_new_end_date_expr updates the end_date of matched transitions."""
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 1.5, eff_date="2025-06-01"), empty_timelines, base_ctx)

        execute(make_gate_move(
            "management_fee_rate", "REDUCTION", "AT", "2025-06-01",
            move_to_date="2026-01-01", new_end_date="2026-07-01",
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2026, 3, 1)) == 1.5   # active during window
        assert ft.value_at(date(2026, 9, 1)) == 2.0   # expired, original resurfaces

    def test_gate_no_matching_transitions(self, empty_timelines, base_ctx):
        """No matching transitions → timeline unchanged."""
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), empty_timelines, base_ctx)
        # No reductions exist, GATE targets REDUCTION → nothing matches
        execute(make_gate_move(
            "management_fee_rate", "REDUCTION", None, None,
            move_to_date="2027-01-01",
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 1, 1)) == 2.0

    def test_gate_condition_true_keeps(self, empty_timelines, base_ctx):
        """condition_ast=TRUE → matched transitions stay untouched."""
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 1.5, eff_date="2025-06-01"), empty_timelines, base_ctx)

        cond = comparison("GTE", lit(100), lit(50))  # 100 >= 50 → TRUE
        execute(make_gate_condition(
            "management_fee_rate", "REDUCTION", "AT", "2025-06-01", cond,
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 9, 1)) == 1.5  # still there

    def test_gate_condition_false_removes(self, empty_timelines, base_ctx):
        """condition_ast=FALSE → matched transitions removed, prior value resurfaces."""
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 1.5, eff_date="2025-06-01"), empty_timelines, base_ctx)

        cond = comparison("GTE", lit(10), lit(50))  # 10 >= 50 → FALSE
        execute(make_gate_condition(
            "management_fee_rate", "REDUCTION", "AT", "2025-06-01", cond,
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 9, 1)) == 2.0  # prior value resurfaces

    def test_gate_false_extends_prior_bounded_entry(self, empty_timelines, base_ctx):
        """Removing a transition that was the handoff target of a bounded entry.

        Seed: 2.0% until 2029-01-15, then 1.5% from 2029-01-15 (post-investment).
        GATE FALSE removes the 1.5% reduction.
        The 2.0% entry's end_date should extend (become None) so it covers
        dates after 2029-01-15 — the fee rate should remain 2.0%.
        """
        # Bounded entry: 2.0% until investment period end
        instr_pre = make_set("management_fee_rate", 2.0, eff_date="2024-01-15",
                             eff_end="2029-01-15", clause_text="LPA: during investment")
        execute(instr_pre, empty_timelines, base_ctx)

        # Handoff entry: 1.5% from investment period end
        instr_post = make_set("management_fee_rate", 1.5, eff_date="2029-01-15",
                              clause_text="LPA: post investment")
        execute(instr_post, empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        # Before GATE: both entries work correctly
        assert ft.value_at(date(2028, 6, 1)) == 2.0
        assert ft.value_at(date(2029, 6, 1)) == 1.5

        # GATE FALSE removes the post-investment reduction
        cond = comparison("GTE", lit(10), lit(50))  # FALSE
        execute(make_gate_condition(
            "management_fee_rate", "REDUCTION", "AT", "2029-01-15", cond,
        ), empty_timelines, base_ctx)

        # After GATE: 2.0% should extend past 2029-01-15
        assert ft.value_at(date(2028, 6, 1)) == 2.0   # still covered
        assert ft.value_at(date(2029, 6, 1)) == 2.0   # was 1.5, now 2.0
        assert ft.value_at(date(2030, 6, 1)) == 2.0   # still 2.0 (no gap)

    def test_gate_false_extends_past_intermediate_temp_entry(self, empty_timelines, base_ctx):
        """GATE removes post-investment entry; temp waiver exists in between.

        Seed: 2.0% (end=2029), 0% waiver (Oct 2025, end=Nov 2025), 1.5% (from 2029)
        GATE FALSE removes 1.5%.
        The 2.0% should extend to permanent (None), NOT to the October waiver start.
        The October waiver still works independently within the 2.0% range.
        """
        # 2.0% during investment period
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15",
                         eff_end="2029-01-15"), empty_timelines, base_ctx)
        # October waiver (temporary, within the 2.0% range)
        execute(make_set("management_fee_rate", 0, eff_date="2025-10-01",
                         eff_end="2025-11-01", clause_text="Oct waiver"), empty_timelines, base_ctx)
        # 1.5% post investment
        execute(make_set("management_fee_rate", 1.5, eff_date="2029-01-15",
                         clause_text="post investment"), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 10, 15)) == 0     # waiver active
        assert ft.value_at(date(2025, 12, 1)) == 2.0    # waiver expired, 2% back
        assert ft.value_at(date(2029, 6, 1)) == 1.5     # post investment

        # GATE FALSE removes the 1.5% reduction
        cond = comparison("GTE", lit(10), lit(50))  # FALSE
        execute(make_gate_condition(
            "management_fee_rate", "REDUCTION", "AT", "2029-01-15", cond,
        ), empty_timelines, base_ctx)

        # 2.0% should extend permanently, October waiver unaffected
        assert ft.value_at(date(2025, 10, 15)) == 0     # waiver still works
        assert ft.value_at(date(2025, 12, 1)) == 2.0    # still 2%
        assert ft.value_at(date(2029, 6, 1)) == 2.0     # was 1.5, now 2.0
        assert ft.value_at(date(2032, 1, 1)) == 2.0     # still 2% far future

    def test_gate_target_reduction_matches_set_reductions(self, empty_timelines, base_ctx):
        """gate_target=REDUCTION matches SET entries where value < prior value."""
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 1.5, eff_date="2025-06-01"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 3.0, eff_date="2025-09-01"), empty_timelines, base_ctx)

        # GATE REDUCTION should match 1.5 (reduction) but NOT 3.0 (increase)
        cond = comparison("GTE", lit(10), lit(50))  # FALSE → removes
        execute(make_gate_condition(
            "management_fee_rate", "REDUCTION", None, None, cond,
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 7, 1)) == 2.0  # reduction removed
        assert ft.value_at(date(2025, 10, 1)) == 3.0  # increase untouched

    def test_gate_target_increase_matches_increases(self, empty_timelines, base_ctx):
        """gate_target=INCREASE matches entries where value > prior value."""
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 1.5, eff_date="2025-06-01"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 3.0, eff_date="2025-09-01"), empty_timelines, base_ctx)

        # GATE INCREASE + FALSE → should remove the 3.0 increase
        cond = comparison("GTE", lit(10), lit(50))  # FALSE
        execute(make_gate_condition(
            "management_fee_rate", "INCREASE", None, None, cond,
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 7, 1)) == 1.5   # reduction untouched
        assert ft.value_at(date(2025, 10, 1)) == 1.5   # increase removed

    def test_gate_target_any_matches_all(self, empty_timelines, base_ctx):
        """gate_target=ANY matches ALL entries including seed.

        Note: ANY literally matches every entry (is_match=True for all).
        This includes the seed/baseline entry. GATE FALSE removes them all.
        """
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 1.5, eff_date="2025-06-01"), empty_timelines, base_ctx)
        execute(make_set("management_fee_rate", 3.0, eff_date="2025-09-01"), empty_timelines, base_ctx)

        # GATE ANY + FALSE → removes ALL entries (including seed)
        cond = comparison("GTE", lit(10), lit(50))  # FALSE
        execute(make_gate_condition(
            "management_fee_rate", "ANY", None, None, cond,
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        # All entries removed — value_at returns None everywhere
        assert ft.value_at(date(2025, 7, 1)) is None
        assert ft.value_at(date(2025, 10, 1)) is None

    def test_gate_both_move_and_condition_rejected_at_model_level(self):
        """GATE with both gate_move_to_date_expr and condition_ast → rejected by model validator."""
        with pytest.raises(ValueError, match="exactly one"):
            ClauseInstruction(
                clause_text="invalid",
                affected_field="management_fee_rate",
                action="GATE",
                gate_target="REDUCTION",
                gate_direction="POSTPONE",
                gate_move_to_date_expr=ASTNode(
                    node_type="literal", value="2027-01-01", value_type="date",
                ),
                condition_ast=comparison("GTE", lit(100), lit(50)),
            )


# ═══════════════════════════════════════════════════════════════════════════
# G. ADJUST stacking
# ═══════════════════════════════════════════════════════════════════════════


class TestADJUSTStacking:

    def test_two_reductions_stack(self, empty_timelines, base_ctx):
        """Two REDUCTION adjustments stack additively."""
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), empty_timelines, base_ctx)
        execute(make_adjust("management_fee_rate", -0.25, "REDUCTION", eff_date="2025-01-01"), empty_timelines, base_ctx)
        execute(make_adjust("management_fee_rate", -0.25, "REDUCTION", eff_date="2025-06-01"), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2024, 6, 1)) == 2.0
        assert ft.value_at(date(2025, 3, 1)) == 1.75   # first adjust
        assert ft.value_at(date(2025, 9, 1)) == 1.5    # second stacks on first

    def test_increase_then_reduction_net_effect(self, empty_timelines, base_ctx):
        """INCREASE followed by REDUCTION: net effect correct."""
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), empty_timelines, base_ctx)
        execute(make_adjust("management_fee_rate", 0.5, "INCREASE", eff_date="2025-01-01"), empty_timelines, base_ctx)
        execute(make_adjust("management_fee_rate", -0.75, "REDUCTION", eff_date="2025-06-01"), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 3, 1)) == 2.5   # +0.5
        assert ft.value_at(date(2025, 9, 1)) == 1.75  # 2.5 - 0.75

    def test_adjust_with_document_date_field_ref(self, empty_timelines):
        """ADJUST effective_date_expr referencing document_date field_ref."""
        ctx = EvaluationContext(
            evaluation_date=date(2026, 6, 1),
            document_date=date(2025, 3, 15),
        )
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), empty_timelines, ctx)

        # ADJUST with no explicit effective_date → defaults to document_date
        instr = ClauseInstruction(
            clause_text="reduction",
            affected_field="management_fee_rate",
            action="ADJUST",
            value_expr=ASTNode(node_type="literal", value=-0.5, value_type="number"),
            adjust_direction="REDUCTION",
            # effective_date_expr is None → uses ctx.document_date = 2025-03-15
        )
        execute(instr, empty_timelines, ctx)

        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2025, 3, 14)) == 2.0
        assert ft.value_at(date(2025, 3, 15)) == 1.5

    def test_adjust_no_prior_set_uses_zero(self, empty_timelines, base_ctx):
        """ADJUST on field with no prior SET → value_at returns None, treated as 0."""
        execute(make_adjust("management_fee_rate", -0.25, "REDUCTION", eff_date="2025-01-01"), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        # No SET exists → current value is None → treated as 0 → 0 + (-0.25) = -0.25
        assert ft.value_at(date(2025, 6, 1)) == -0.25


# ═══════════════════════════════════════════════════════════════════════════
# H. CONSTRAIN with time bounds
#
# NOTE: Spec section H claimed "two simultaneous CAPs → lower wins (tightest)."
# This is WRONG. We changed constraint logic so the LATEST constraint
# (highest insertion_order) wins, not the tightest. Tests below reflect
# the actual behavior.
# ═══════════════════════════════════════════════════════════════════════════


class TestCONSTRAINDeep:

    def test_cap_active_range(self, empty_timelines, base_ctx):
        """CAP active only within active_from to active_until window."""
        execute(make_set("management_fee_rate", 3.0, eff_date="2024-01-15"), empty_timelines, base_ctx)
        execute(make_constrain(
            "management_fee_rate", 2.0, "CAP",
            eff_date="2025-01-01", eff_end="2026-01-01",
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2024, 6, 1)) == 3.0  # before active_from
        assert ft.value_at(date(2025, 6, 1)) == 2.0  # during active range
        assert ft.value_at(date(2026, 6, 1)) == 3.0  # after active_until

    def test_floor_permanent(self, empty_timelines, base_ctx):
        """FLOOR with no date bounds → always active."""
        execute(make_set("management_fee_rate", 0.5, eff_date="2024-01-15"), empty_timelines, base_ctx)
        execute(make_constrain(
            "management_fee_rate", 1.0, "FLOOR",
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        assert ft.value_at(date(2024, 6, 1)) == 1.0  # clamped up from 0.5
        assert ft.value_at(date(2030, 1, 1)) == 1.0  # still clamped far future

    def test_two_caps_latest_wins_not_tightest(self, empty_timelines, base_ctx):
        """Two simultaneous CAPs → the LATEST (highest insertion_order) wins.

        This contradicts the naive assumption that the tightest CAP wins.
        In PE, a later side letter can relax an earlier LPA cap.
        """
        execute(make_set("management_fee_rate", 3.0, eff_date="2024-01-15"), empty_timelines, base_ctx)
        # LPA: CAP at 2.0 (registered first)
        execute(make_constrain("management_fee_rate", 2.0, "CAP", clause_text="LPA cap"), empty_timelines, base_ctx)
        # Side letter: CAP at 2.5 (registered second, more relaxed)
        execute(make_constrain("management_fee_rate", 2.5, "CAP", clause_text="SL cap"), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_rate"]
        # Side letter's relaxed CAP wins → 3.0 capped to 2.5, NOT 2.0
        assert ft.value_at(date(2024, 6, 1)) == 2.5

    def test_cap_on_string_field_graceful(self, empty_timelines, base_ctx):
        """CAP on a string-valued field → incompatible types, returns raw value unconstrained."""
        execute(make_set(
            "management_fee_basis",
            ASTNode(node_type="literal", value="committed_capital", value_type="string"),
            eff_date="2024-01-15",
        ), empty_timelines, base_ctx)
        execute(make_constrain(
            "management_fee_basis", 2.0, "CAP",
        ), empty_timelines, base_ctx)

        ft = empty_timelines["management_fee_basis"]
        # Incompatible types (string vs float) — constraint is silently ignored,
        # raw value returned unconstrained.
        assert ft.value_at(date(2024, 6, 1)) == "committed_capital"


# ═══════════════════════════════════════════════════════════════════════════
# I. value_at edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestValueAtEdgeCases:

    def test_same_date_higher_insertion_order_wins(self):
        """Two SET entries on same date → higher insertion_order wins."""
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

    def test_end_date_exactly_on_query_not_valid(self):
        """Entry with end_date == query_date → NOT valid (exclusive end)."""
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), end_date=date(2025, 1, 1),
            value=2.0, source_clause_text="a", entry_type="SET",
        ))
        assert ft.value_at(date(2024, 12, 31)) == 2.0  # day before → valid
        assert ft.value_at(date(2025, 1, 1)) is None    # on end_date → expired

    def test_query_exactly_on_start_date_valid(self):
        """Entry with date == query_date → IS valid."""
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 6, 15), value=1.5,
            source_clause_text="a", entry_type="SET",
        ))
        assert ft.value_at(date(2024, 6, 15)) == 1.5

    def test_constraint_active_from_exactly_on_query(self):
        """Constraint with active_from == query_date → IS active."""
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=3.0,
            source_clause_text="a", entry_type="SET",
        ))
        ft.register_constraint(ConstraintRule(
            type="CAP", bound=2.0,
            active_from=date(2025, 1, 1),
            source_clause_text="cap",
        ))
        # Day before active_from → no cap
        assert ft.value_at(date(2024, 12, 31)) == 3.0
        # Exactly on active_from → cap applies
        assert ft.value_at(date(2025, 1, 1)) == 2.0


# ═══════════════════════════════════════════════════════════════════════════
# J. Sequential ordering correctness — integration-style (no LLM)
# ═══════════════════════════════════════════════════════════════════════════


class TestSequentialIntegration:

    def test_set_set_constrain_sequence(self):
        """SET 2.0 → SET 1.75 from X → CONSTRAIN CAP 1.5 from Y.

        Before X: 2.0
        Between X and Y: 1.75
        After Y: 1.5 (1.75 capped to 1.5)
        """
        tls: dict[str, FieldTimeline] = {}
        ctx = EvaluationContext(
            evaluation_date=date(2027, 1, 1),
            document_date=date(2024, 1, 15),
        )

        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), tls, ctx)
        execute(make_set("management_fee_rate", 1.75, eff_date="2025-06-01"), tls, ctx)
        execute(make_constrain("management_fee_rate", 1.5, "CAP", eff_date="2026-01-01"), tls, ctx)

        ft = tls["management_fee_rate"]
        assert ft.value_at(date(2024, 6, 1)) == 2.0
        assert ft.value_at(date(2025, 9, 1)) == 1.75
        assert ft.value_at(date(2026, 6, 1)) == 1.5

    def test_set_adjust_gate_false_removes_adjust(self):
        """SET 2.0 → ADJUST -0.25 REDUCTION from X → GATE FALSE targeting REDUCTION.

        GATE removes the ADJUST, restoring 2.0 after X.
        """
        tls: dict[str, FieldTimeline] = {}
        ctx = EvaluationContext(
            evaluation_date=date(2027, 1, 1),
            document_date=date(2024, 1, 15),
        )

        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), tls, ctx)
        execute(make_adjust(
            "management_fee_rate", -0.25, "REDUCTION", eff_date="2025-06-01",
        ), tls, ctx)

        # Verify ADJUST applied
        ft = tls["management_fee_rate"]
        assert ft.value_at(date(2025, 9, 1)) == 1.75

        # GATE FALSE removes the reduction
        cond_false = comparison("GTE", lit(10), lit(50))  # FALSE
        execute(make_gate_condition(
            "management_fee_rate", "REDUCTION", "AT", "2025-06-01", cond_false,
        ), tls, ctx)

        assert ft.value_at(date(2025, 9, 1)) == 2.0  # restored

    def test_set_set_gate_move(self):
        """SET 2.0 → SET 1.75 from X → GATE move to Z.

        After GATE: 1.75 starts at Z (not X). Between X and Z: 2.0.
        """
        tls: dict[str, FieldTimeline] = {}
        ctx = EvaluationContext(
            evaluation_date=date(2028, 1, 1),
            document_date=date(2024, 1, 15),
        )

        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15"), tls, ctx)
        execute(make_set("management_fee_rate", 1.75, eff_date="2025-06-01"), tls, ctx)

        # GATE: move the reduction at 2025-06-01 to 2027-01-01
        execute(make_gate_move(
            "management_fee_rate", "REDUCTION", "AT", "2025-06-01",
            move_to_date="2027-01-01",
        ), tls, ctx)

        ft = tls["management_fee_rate"]
        assert ft.value_at(date(2024, 6, 1)) == 2.0   # seed
        assert ft.value_at(date(2025, 9, 1)) == 2.0   # between X and Z — original 2.0
        assert ft.value_at(date(2027, 6, 1)) == 1.75   # after Z — moved here

    def test_set_then_multiplicative_adjust_step_down(self):
        """Real-world scenario: SET 1.5% then 'step down by 50%' → 0.75%.

        This is the exact bug case: before adjust_mode, the engine did
        current + (-50) = -48.5 instead of current * 0.5 = 0.75.
        """
        tls: dict[str, FieldTimeline] = {}
        ctx = EvaluationContext(
            evaluation_date=date(2030, 1, 1),
            document_date=date(2027, 7, 1),
        )

        # LPA seed: 2.0% during investment period, 1.5% post
        execute(make_set("management_fee_rate", 2.0, eff_date="2024-01-15",
                         eff_end="2029-01-15"), tls, ctx)
        execute(make_set("management_fee_rate", 1.5, eff_date="2029-01-15"), tls, ctx)

        # Side letter: SET to 1.5% from election date
        execute(make_set("management_fee_rate", 1.5, eff_date="2027-10-01"), tls, ctx)

        # Side letter: step down by 50% at investment end, until fund term end
        execute(make_adjust("management_fee_rate", 0.5, "REDUCTION",
                            eff_date="2029-01-15", eff_end="2034-01-15",
                            adjust_mode="multiplicative"), tls, ctx)

        ft = tls["management_fee_rate"]
        # Before election: LPA rate 2.0%
        assert ft.value_at(date(2025, 1, 1)) == 2.0
        # After election, before investment end: side letter 1.5%
        assert ft.value_at(date(2028, 1, 1)) == 1.5
        # After investment end: 1.5% * 0.5 = 0.75% (NOT -48.5!)
        assert ft.value_at(date(2029, 6, 1)) == 0.75
        # After fund term end: multiplicative expired, LPA post-period 1.5% resurfaces
        assert ft.value_at(date(2034, 6, 1)) == 1.5
