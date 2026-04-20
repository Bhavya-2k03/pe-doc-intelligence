"""Tests for engine/fee_calculator.py — management fee computation.

Tests mirror the worked examples from the planning discussion:
A: LP at initial closing, no complications
B: LP at subsequent closing, evaluation in later full period
C: LP at subsequent closing, evaluation in same period (prorated)
D: Rate change mid-period (breakpoint splitting)
E: Basis switch mid-period (after final closing)
F: Catch-up + rate change + proration (full combo)
"""
from __future__ import annotations

from datetime import date

import pytest

from engine.fee_calculator import (
    FeeResult,
    _generate_billing_periods,
    _find_billing_period,
    compute_management_fee,
)
from engine.timeline_engine import FieldTimeline, TimelineEntry


# ═══════════════════════════════════════════════════════════════════════════
# Shared timeline builder
# ═══════════════════════════════════════════════════════════════════════════


def _build_base_timelines(
    rate: float = 2.0,
    basis: str = "committed_capital",
    commitment: float = 10_000_000,
    total_fund_commitment: float = 10_000_000,
    initial_closing: str = "2024-01-15",
    final_closing: str = "2024-12-15",
    cadence: str = "quarterly",
) -> dict[str, FieldTimeline]:
    """Build a standard set of timelines for fee calculation tests.

    Default: single LP with $10M commitment = 100% of fund.
    """
    timelines: dict[str, FieldTimeline] = {}
    ic_date = date.fromisoformat(initial_closing)

    def _add(field: str, d: date, value, source: str = "LPA"):
        if field not in timelines:
            timelines[field] = FieldTimeline()
        timelines[field].insert_entry(TimelineEntry(
            date=d, value=value,
            source_clause_text=source, entry_type="SET",
        ))

    _add("fund_initial_closing_date", ic_date, initial_closing)
    _add("fund_final_closing_date", ic_date, final_closing)
    _add("management_fee_rate", ic_date, rate)
    _add("management_fee_basis", ic_date, basis)
    _add("management_fee_billing_cadence", ic_date, cadence)
    _add("investor_commitment_amount", ic_date, commitment)
    _add("total_fund_commitment", ic_date, total_fund_commitment)

    return timelines


# ═══════════════════════════════════════════════════════════════════════════
# Billing period generation
# ═══════════════════════════════════════════════════════════════════════════


class TestBillingPeriods:

    def test_quarterly_periods_from_anchor(self):
        periods = _generate_billing_periods(
            date(2024, 1, 15), "quarterly", date(2025, 4, 15),
        )
        assert periods[0] == (date(2024, 1, 15), date(2024, 4, 15))
        assert periods[1] == (date(2024, 4, 15), date(2024, 7, 15))
        assert periods[2] == (date(2024, 7, 15), date(2024, 10, 15))
        assert periods[3] == (date(2024, 10, 15), date(2025, 1, 15))
        assert periods[4] == (date(2025, 1, 15), date(2025, 4, 15))

    def test_semi_annual_periods(self):
        periods = _generate_billing_periods(
            date(2024, 1, 15), "semi_annually", date(2025, 1, 15),
        )
        assert periods[0] == (date(2024, 1, 15), date(2024, 7, 15))
        assert periods[1] == (date(2024, 7, 15), date(2025, 1, 15))

    def test_find_period_for_date(self):
        periods = _generate_billing_periods(
            date(2024, 1, 15), "quarterly", date(2025, 1, 15),
        )
        assert _find_billing_period(periods, date(2024, 6, 1)) == (
            date(2024, 4, 15), date(2024, 7, 15),
        )

    def test_find_period_on_boundary(self):
        """Date on period start → belongs to that period."""
        periods = _generate_billing_periods(
            date(2024, 1, 15), "quarterly", date(2024, 7, 15),
        )
        assert _find_billing_period(periods, date(2024, 4, 15)) == (
            date(2024, 4, 15), date(2024, 7, 15),
        )


# ═══════════════════════════════════════════════════════════════════════════
# Scenario A: LP at initial closing, no complications
# ═══════════════════════════════════════════════════════════════════════════


class TestScenarioA:

    def test_basic_quarterly_fee(self):
        """LP joins at initial closing, evaluation in P2 (Apr 15 → Jul 15).
        Fee = 2.0% × $10M × 91/365 = $49,863.01
        """
        timelines = _build_base_timelines()
        result = compute_management_fee(
            timelines, date(2024, 6, 1),
        )
        assert result.catchup_fee is None
        assert result.billing_period_start == date(2024, 4, 15)
        assert result.billing_period_end == date(2024, 7, 15)
        assert result.current_period_fee.period_start == date(2024, 4, 15)
        assert len(result.current_period_fee.sub_periods) == 1

        sp = result.current_period_fee.sub_periods[0]
        assert sp.days == 91
        assert sp.annual_rate == 2.0
        assert sp.basis_label == "committed_capital"
        assert sp.basis_amount == 10_000_000
        # 2% × 10M × 91/365 = 49863.01
        assert result.current_period_fee.total_fee == pytest.approx(49863.01, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════════
# Scenario B: LP joins at subsequent closing, eval in later full period
# ═══════════════════════════════════════════════════════════════════════════


class TestScenarioB:

    def test_catchup_and_full_period(self):
        """LP joins Jun 1 (subsequent closing), evaluation Aug 1 (P3).
        Catch-up: Jan 15 → Jun 1 = 138 days → $75,616.44
        P3: Jul 15 → Oct 15 = 92 days → $50,410.96
        """
        timelines = _build_base_timelines()
        result = compute_management_fee(
            timelines, date(2024, 8, 1),
            lp_admission_date=date(2024, 6, 1),
        )

        # Catch-up
        assert result.catchup_fee is not None
        assert result.catchup_period_start == date(2024, 1, 15)
        assert result.catchup_period_end == date(2024, 6, 1)
        assert result.catchup_fee.total_fee == pytest.approx(75616.44, abs=0.01)

        # Current period (P3 — full, since admission was before P3)
        assert result.current_period_fee.period_start == date(2024, 7, 15)
        assert result.current_period_fee.period_end == date(2024, 10, 15)
        assert result.current_period_fee.total_fee == pytest.approx(50410.96, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════════
# Scenario C: LP joins mid-period, eval in same period (prorated)
# ═══════════════════════════════════════════════════════════════════════════


class TestScenarioC:

    def test_prorated_same_period(self):
        """LP joins Jun 1, evaluation Jun 20 (still in P2).
        Catch-up: Jan 15 → Jun 1 = 138 days → $75,616.44
        Current: Jun 1 → Jul 15 = 44 days → $24,109.59
        """
        timelines = _build_base_timelines()
        result = compute_management_fee(
            timelines, date(2024, 6, 20),
            lp_admission_date=date(2024, 6, 1),
        )

        assert result.catchup_fee is not None
        assert result.catchup_fee.total_fee == pytest.approx(75616.44, abs=0.01)

        # Current period prorated from Jun 1
        assert result.current_period_fee.period_start == date(2024, 6, 1)
        assert result.current_period_fee.period_end == date(2024, 7, 15)
        sp = result.current_period_fee.sub_periods[0]
        assert sp.days == 44
        assert result.current_period_fee.total_fee == pytest.approx(24109.59, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════════
# Scenario D: Rate change mid-period (breakpoint splitting)
# ═══════════════════════════════════════════════════════════════════════════


class TestScenarioD:

    def test_rate_change_midperiod(self):
        """Side letter reduces rate to 1.5% effective Mar 1.
        P1 sub-period 1: Jan 15 → Mar 1 = 46 days at 2.0% → $25,205.48
        P1 sub-period 2: Mar 1 → Apr 15 = 45 days at 1.5% → $18,493.15
        Total P1 = $43,698.63
        """
        timelines = _build_base_timelines()
        # Add rate change
        timelines["management_fee_rate"].insert_entry(TimelineEntry(
            date=date(2024, 3, 1), value=1.5,
            source_clause_text="Side letter: reduce to 1.5%",
            entry_type="SET",
        ))

        result = compute_management_fee(
            timelines, date(2024, 3, 15),
        )

        assert len(result.current_period_fee.sub_periods) == 2

        sp1 = result.current_period_fee.sub_periods[0]
        assert sp1.start == date(2024, 1, 15)
        assert sp1.end == date(2024, 3, 1)
        assert sp1.days == 46
        assert sp1.annual_rate == 2.0

        sp2 = result.current_period_fee.sub_periods[1]
        assert sp2.start == date(2024, 3, 1)
        assert sp2.end == date(2024, 4, 15)
        assert sp2.days == 45
        assert sp2.annual_rate == 1.5

        assert result.current_period_fee.total_fee == pytest.approx(43698.63, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════════
# Scenario E: Basis switch mid-period (after final closing)
# ═══════════════════════════════════════════════════════════════════════════


class TestScenarioE:

    def test_basis_switch_midperiod(self):
        """Basis switches from committed to invested at final closing (Dec 15).
        P4 sub-period 1: Oct 15 → Dec 15 = 61 days, 2% on $10M → $33,424.66
        P4 sub-period 2: Dec 15 → Jan 15 = 31 days, 2% on $6M → $10,191.78
        Total P4 = $43,616.44
        """
        timelines = _build_base_timelines()

        # Basis switches at final closing
        timelines["management_fee_basis"].insert_entry(TimelineEntry(
            date=date(2024, 12, 15), value="invested_capital",
            source_clause_text="LPA: basis switch post-final-closing",
            entry_type="SET",
        ))

        # Invested capital data
        timelines["fund_total_invested_capital"] = FieldTimeline()
        timelines["fund_total_invested_capital"].insert_entry(TimelineEntry(
            date=date(2024, 1, 15), value=6_000_000,
            source_clause_text="Extracted: invested capital",
            entry_type="SET",
        ))

        result = compute_management_fee(
            timelines, date(2025, 1, 10),
        )

        assert result.billing_period_start == date(2024, 10, 15)
        assert result.billing_period_end == date(2025, 1, 15)
        assert len(result.current_period_fee.sub_periods) == 2

        sp1 = result.current_period_fee.sub_periods[0]
        assert sp1.basis_label == "committed_capital"
        assert sp1.basis_amount == 10_000_000
        assert sp1.days == 61

        sp2 = result.current_period_fee.sub_periods[1]
        assert sp2.basis_label == "invested_capital"
        assert sp2.basis_amount == 6_000_000
        assert sp2.days == 31

        assert result.current_period_fee.total_fee == pytest.approx(43616.44, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════════
# Scenario F: Catch-up + rate change + proration (full combo)
# ═══════════════════════════════════════════════════════════════════════════


class TestScenarioF:

    def test_full_combo(self):
        """LP joins Jun 1, rate drops to 1.75% on May 15, eval Jun 20.
        Catch-up: Jan 15 → May 15 at 2.0% (121 days) = $66,301.37
                  May 15 → Jun 1 at 1.75% (17 days) = $8,150.68  (see note)
                  Total catch-up = $74,452.05
        Current: Jun 1 → Jul 15 at 1.75% (44 days) = $21,095.89
        """
        timelines = _build_base_timelines()

        # Rate change on May 15
        timelines["management_fee_rate"].insert_entry(TimelineEntry(
            date=date(2024, 5, 15), value=1.75,
            source_clause_text="Side letter: reduce to 1.75%",
            entry_type="SET",
        ))

        result = compute_management_fee(
            timelines, date(2024, 6, 20),
            lp_admission_date=date(2024, 6, 1),
        )

        # Catch-up with rate change
        assert result.catchup_fee is not None
        assert len(result.catchup_fee.sub_periods) == 2

        cu_sp1 = result.catchup_fee.sub_periods[0]
        assert cu_sp1.annual_rate == 2.0
        assert cu_sp1.days == 121  # Jan 15 → May 15

        cu_sp2 = result.catchup_fee.sub_periods[1]
        assert cu_sp2.annual_rate == 1.75
        assert cu_sp2.days == 17  # May 15 → Jun 1

        assert result.catchup_fee.total_fee == pytest.approx(74452.05, abs=0.01)

        # Current period prorated
        assert result.current_period_fee.total_fee == pytest.approx(21095.89, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:

    def test_admission_after_final_closing_defaults(self):
        """LP admission after final closing → defaults to initial closing."""
        timelines = _build_base_timelines()
        result = compute_management_fee(
            timelines, date(2025, 2, 1),
            lp_admission_date=date(2025, 6, 1),  # after final closing
        )
        assert result.lp_admission_date == date(2024, 1, 15)
        assert result.catchup_fee is None
        assert any("after final closing" in a for a in result.assumptions)

    def test_no_admission_date_defaults_to_initial(self):
        """No admission date → defaults to initial closing."""
        timelines = _build_base_timelines()
        result = compute_management_fee(timelines, date(2024, 6, 1))
        assert result.lp_admission_date == date(2024, 1, 15)
        assert result.catchup_fee is None

    def test_rate_zero_fee_waiver(self):
        """Rate = 0 (fee waiver) → fee amount is 0."""
        timelines = _build_base_timelines(rate=0.0)
        result = compute_management_fee(timelines, date(2024, 6, 1))
        assert result.current_period_fee.total_fee == 0.0

    def test_missing_initial_closing_returns_zero(self):
        """No fund_initial_closing_date → zero fee with assumption."""
        timelines: dict[str, FieldTimeline] = {}
        result = compute_management_fee(timelines, date(2024, 6, 1))
        assert result.current_period_fee.total_fee == 0.0
        assert any("fund_initial_closing_date" in a for a in result.assumptions)

    def test_eval_date_before_closing_returns_zero(self):
        """Evaluation date before initial closing → zero fee."""
        timelines = _build_base_timelines()
        result = compute_management_fee(timelines, date(2023, 6, 1))
        assert result.current_period_fee.total_fee == 0.0
        # value_at returns None for dates before the seed entry, which means
        # evaluation_date precedes the fund's initial closing.
        assert any("before the fund's initial closing" in a for a in result.assumptions)

    def test_eval_date_after_term_end_returns_zero(self):
        """Evaluation date on or after fund term end → fund has terminated, zero fee."""
        timelines = _build_base_timelines()
        timelines["fund_term_end_date"] = FieldTimeline()
        timelines["fund_term_end_date"].insert_entry(TimelineEntry(
            date=date(2024, 1, 15), value="2034-01-15",
            source_clause_text="LPA", entry_type="SET",
        ))
        result = compute_management_fee(timelines, date(2034, 6, 1))
        assert result.current_period_fee.total_fee == 0.0
        assert any("terminated" in a for a in result.assumptions)

    def test_invested_capital_pro_rata(self):
        """LP with 25% of fund → invested_capital basis uses pro-rata share.

        Fund: $40M total, LP committed $10M (25%).
        Fund invested $20M → LP's share = $5M.
        Fee = 2% × $5M × 91/365 = $24,931.51
        """
        timelines = _build_base_timelines(
            commitment=10_000_000,
            total_fund_commitment=40_000_000,
            basis="invested_capital",
        )
        timelines["fund_total_invested_capital"] = FieldTimeline()
        timelines["fund_total_invested_capital"].insert_entry(TimelineEntry(
            date=date(2024, 1, 15), value=20_000_000,
            source_clause_text="Extracted: fund invested", entry_type="SET",
        ))

        result = compute_management_fee(timelines, date(2024, 6, 1))

        sp = result.current_period_fee.sub_periods[0]
        assert sp.basis_label == "invested_capital"
        assert sp.basis_amount == pytest.approx(5_000_000)  # 25% of 20M
        # 2% × $5M × 91/365
        assert result.current_period_fee.total_fee == pytest.approx(24931.51, abs=0.01)

    def test_multiple_breakpoints_single_period(self):
        """3 breakpoints in one period: rate change, basis switch, commitment change.

        P2: Apr 15 → Jul 15
        Apr 15 → May 1:  16 days, 2.0%, committed, $10M  → $8,767.12
        May 1 → Jun 1:   31 days, 1.75%, committed, $10M → $14,863.01
        Jun 1 → Jun 15:  14 days, 1.75%, committed, $12M → $8,054.79
        Jun 15 → Jul 15: 30 days, 1.75%, invested,  LP=$3M (25% of $12M) → $4,315.07
        Total = $35,999.99
        """
        timelines = _build_base_timelines(
            commitment=10_000_000,
            total_fund_commitment=40_000_000,
        )

        # Breakpoint 1: rate drops May 1
        timelines["management_fee_rate"].insert_entry(TimelineEntry(
            date=date(2024, 5, 1), value=1.75,
            source_clause_text="Side letter: 1.75%", entry_type="SET",
        ))

        # Breakpoint 2: LP commitment increases Jun 1
        timelines["investor_commitment_amount"].insert_entry(TimelineEntry(
            date=date(2024, 6, 1), value=12_000_000,
            source_clause_text="Additional commitment", entry_type="SET",
        ))
        timelines["total_fund_commitment"].insert_entry(TimelineEntry(
            date=date(2024, 6, 1), value=48_000_000,
            source_clause_text="Fund total updated", entry_type="SET",
        ))

        # Breakpoint 3: basis switches Jun 15
        timelines["management_fee_basis"].insert_entry(TimelineEntry(
            date=date(2024, 6, 15), value="invested_capital",
            source_clause_text="Basis switch", entry_type="SET",
        ))
        timelines["fund_total_invested_capital"] = FieldTimeline()
        timelines["fund_total_invested_capital"].insert_entry(TimelineEntry(
            date=date(2024, 1, 15), value=12_000_000,
            source_clause_text="Fund invested capital", entry_type="SET",
        ))

        result = compute_management_fee(timelines, date(2024, 6, 20))

        assert result.billing_period_start == date(2024, 4, 15)
        assert len(result.current_period_fee.sub_periods) == 4

        sp1 = result.current_period_fee.sub_periods[0]
        assert sp1.start == date(2024, 4, 15)
        assert sp1.end == date(2024, 5, 1)
        assert sp1.days == 16
        assert sp1.annual_rate == 2.0
        assert sp1.basis_label == "committed_capital"
        assert sp1.basis_amount == 10_000_000
        assert sp1.fee_amount == pytest.approx(8767.12, abs=0.01)

        sp2 = result.current_period_fee.sub_periods[1]
        assert sp2.start == date(2024, 5, 1)
        assert sp2.end == date(2024, 6, 1)
        assert sp2.days == 31
        assert sp2.annual_rate == 1.75
        assert sp2.basis_label == "committed_capital"
        assert sp2.basis_amount == 10_000_000
        assert sp2.fee_amount == pytest.approx(14863.01, abs=0.01)

        sp3 = result.current_period_fee.sub_periods[2]
        assert sp3.start == date(2024, 6, 1)
        assert sp3.end == date(2024, 6, 15)
        assert sp3.days == 14
        assert sp3.annual_rate == 1.75
        assert sp3.basis_label == "committed_capital"
        assert sp3.basis_amount == 12_000_000
        assert sp3.fee_amount == pytest.approx(8054.79, abs=0.01)

        sp4 = result.current_period_fee.sub_periods[3]
        assert sp4.start == date(2024, 6, 15)
        assert sp4.end == date(2024, 7, 15)
        assert sp4.days == 30
        assert sp4.annual_rate == 1.75
        assert sp4.basis_label == "invested_capital"
        # LP = 25% of $48M fund, fund invested $12M → LP invested $3M
        assert sp4.basis_amount == pytest.approx(3_000_000)
        assert sp4.fee_amount == pytest.approx(4315.07, abs=0.01)

        expected_total = 8767.12 + 14863.01 + 8054.79 + 4315.07
        assert result.current_period_fee.total_fee == pytest.approx(expected_total, abs=0.02)

    def test_overwritten_entry_same_date_correct_value(self):
        """Two rate entries on same date — later insertion_order wins.

        LPA sets 2.0%, then side letter overrides to 1.5% on same date.
        Fee should use 1.5%, not 2.0%.
        """
        timelines = _build_base_timelines()

        # Override rate on same date as original
        timelines["management_fee_rate"].insert_entry(TimelineEntry(
            date=date(2024, 1, 15), value=1.5,
            source_clause_text="Side letter override", entry_type="SET",
        ))

        result = compute_management_fee(timelines, date(2024, 6, 1))
        sp = result.current_period_fee.sub_periods[0]
        assert sp.annual_rate == 1.5
        # 1.5% × $10M × 91/365 = $37,397.26
        assert result.current_period_fee.total_fee == pytest.approx(37397.26, abs=0.01)

    def test_catchup_with_multiple_breakpoints(self):
        """LP joins Jul 1. Catch-up has rate change + commitment change.

        Catch-up: Jan 15 → Jul 1
          Jan 15 → Mar 1:  46 days, 2.0%, $10M   → $25,205.48
          Mar 1 → May 15:  75 days, 1.5%, $10M   → $30,821.92
          May 15 → Jul 1:  47 days, 1.5%, $15M   → $28,972.60
        Total catch-up = $84,999.99 (approx)
        """
        timelines = _build_base_timelines()

        # Rate drops Mar 1
        timelines["management_fee_rate"].insert_entry(TimelineEntry(
            date=date(2024, 3, 1), value=1.5,
            source_clause_text="Rate reduction", entry_type="SET",
        ))

        # Commitment increases May 15
        timelines["investor_commitment_amount"].insert_entry(TimelineEntry(
            date=date(2024, 5, 15), value=15_000_000,
            source_clause_text="Additional commitment", entry_type="SET",
        ))

        result = compute_management_fee(
            timelines, date(2024, 8, 1),
            lp_admission_date=date(2024, 7, 1),
        )

        assert result.catchup_fee is not None
        assert len(result.catchup_fee.sub_periods) == 3

        cu1 = result.catchup_fee.sub_periods[0]
        assert cu1.days == 46
        assert cu1.annual_rate == 2.0
        assert cu1.basis_amount == 10_000_000

        cu2 = result.catchup_fee.sub_periods[1]
        assert cu2.days == 75
        assert cu2.annual_rate == 1.5
        assert cu2.basis_amount == 10_000_000

        cu3 = result.catchup_fee.sub_periods[2]
        assert cu3.days == 47
        assert cu3.annual_rate == 1.5
        assert cu3.basis_amount == 15_000_000

        expected = 25205.48 + 30821.92 + 28972.60
        assert result.catchup_fee.total_fee == pytest.approx(expected, abs=0.02)

    def test_unfunded_commitment_pro_rata(self):
        """Unfunded = LP commitment - LP's pro-rata invested.

        LP: $10M of $40M fund (25%). Fund invested $20M → LP invested $5M.
        Unfunded = $10M - $5M = $5M.
        Fee = 2% × $5M × 91/365 = $24,931.51
        """
        timelines = _build_base_timelines(
            commitment=10_000_000,
            total_fund_commitment=40_000_000,
            basis="unfunded_commitment",
        )
        timelines["fund_total_invested_capital"] = FieldTimeline()
        timelines["fund_total_invested_capital"].insert_entry(TimelineEntry(
            date=date(2024, 1, 15), value=20_000_000,
            source_clause_text="Extracted: fund invested", entry_type="SET",
        ))

        result = compute_management_fee(timelines, date(2024, 6, 1))

        sp = result.current_period_fee.sub_periods[0]
        assert sp.basis_label == "unfunded_commitment"
        assert sp.basis_amount == pytest.approx(5_000_000)  # 10M - 5M
        assert result.current_period_fee.total_fee == pytest.approx(24931.51, abs=0.01)
