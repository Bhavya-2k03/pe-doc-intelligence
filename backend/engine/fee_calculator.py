"""Fee Calculator — computes management fees from timelines.

Handles mid-period rate/basis changes via breakpoint splitting,
LP admission proration, and catch-up fee calculation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from dateutil.relativedelta import relativedelta

from engine.timeline_engine import FieldTimeline

logger = logging.getLogger(__name__)

DAY_COUNT_CONVENTION = "actual/365"
DAYS_IN_YEAR = 365


# ═══════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class FeeSubPeriod:
    """One contiguous slice within a billing period where all fee
    parameters (rate, basis, basis_amount) are constant."""
    start: date
    end: date                       # exclusive upper bound
    days: int
    annual_rate: float              # percentage, e.g. 2.0 means 2%
    basis_label: str                # e.g. "committed_capital"
    basis_amount: float             # dollar amount
    fee_amount: float               # rate/100 × basis_amount × days/365
    source_clause: str              # clause text that set the rate (audit trail)


@dataclass
class BillingPeriodFee:
    """Fee for one complete billing period, possibly split into sub-periods."""
    period_start: date
    period_end: date                # exclusive
    total_fee: float
    sub_periods: list[FeeSubPeriod]


@dataclass
class FeeResult:
    """Complete fee calculation output."""
    # Billing period info
    billing_period_start: date
    billing_period_end: date        # exclusive
    billing_cadence: str            # "quarterly" | "semi_annually" | "annually"
    anchor_date: date               # fund_initial_closing_date

    # Current period fee
    current_period_fee: BillingPeriodFee

    # Catch-up (if LP joined after initial closing)
    catchup_fee: Optional[BillingPeriodFee]     # None if no catch-up needed
    catchup_period_start: Optional[date]        # initial closing
    catchup_period_end: Optional[date]          # lp admission date

    # LP info
    lp_admission_date: date

    # Metadata
    day_count_convention: str = DAY_COUNT_CONVENTION
    assumptions: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# Billing Period Generation
# ═══════════════════════════════════════════════════════════════════════════


_CADENCE_MONTHS = {
    "quarterly": 3,
    "semi_annually": 6,
    "annually": 12,
}


def _generate_billing_periods(
    anchor: date,
    cadence: str,
    up_to: date,
) -> list[tuple[date, date]]:
    """Generate billing period (start, end) pairs from anchor forward.

    Periods are half-open: [start, end). Each period is cadence_months
    after the previous one.
    """
    months = _CADENCE_MONTHS.get(cadence, 3)  # default quarterly
    periods: list[tuple[date, date]] = []
    current = anchor

    while current <= up_to:
        next_start = current + relativedelta(months=months)
        periods.append((current, next_start))
        current = next_start

    return periods


def _find_billing_period(
    periods: list[tuple[date, date]],
    target: date,
) -> tuple[date, date] | None:
    """Find which billing period contains the target date."""
    for start, end in periods:
        if start <= target < end:
            return start, end
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Breakpoint Collection
# ═══════════════════════════════════════════════════════════════════════════


def _fee_inputs_at(
    timelines: dict[str, FieldTimeline],
    query_date: date,
) -> tuple[float, str, float]:
    """Read (rate, basis_label, basis_amount) at a given date.

    Used to compare fee-relevant inputs across a candidate breakpoint.
    """
    rate = 0.0
    rate_tl = timelines.get("management_fee_rate")
    if rate_tl is not None:
        val = rate_tl.value_at(query_date)
        if val is not None:
            try:
                rate = float(val)
            except (TypeError, ValueError):
                rate = 0.0

    basis_label = "committed_capital"
    basis_tl = timelines.get("management_fee_basis")
    if basis_tl is not None:
        val = basis_tl.value_at(query_date)
        if val is not None:
            basis_label = str(val)

    basis_amount, _ = _resolve_basis_amount(basis_label, timelines, query_date)
    return rate, basis_label, basis_amount


def _collect_breakpoints(
    timelines: dict[str, FieldTimeline],
    period_start: date,
    period_end: date,
) -> list[date]:
    """Collect all dates within [period_start, period_end) where the fee
    inputs (rate, basis label, basis amount) actually change.

    Phase 1: gather candidate dates from any fee-relevant timeline entry
    or constraint activation.
    Phase 2: filter to only dates where (rate, basis_label, basis_amount)
    differs across the boundary. A change to investor_invested_capital
    while basis is committed_capital, for example, is not a real breakpoint.
    """
    fee_fields = [
        "management_fee_rate",
        "management_fee_basis",
        "investor_commitment_amount",
        "investor_invested_capital",
        "fund_total_invested_capital",
        "total_fund_commitment",
    ]

    candidates: set[date] = set()
    for field_name in fee_fields:
        ft = timelines.get(field_name)
        if ft is None:
            continue
        for entry in ft.entries:
            if period_start < entry.date < period_end:
                candidates.add(entry.date)
            # Also include end_date — when a temporary override expires
            # (e.g., a fee waiver for one quarter), the rate reverts mid-period.
            if entry.end_date is not None and period_start < entry.end_date < period_end:
                candidates.add(entry.end_date)
        # Also include constraint activation/deactivation dates —
        # a CAP/FLOOR starting mid-period changes the effective rate.
        for constraint in ft.constraints:
            if constraint.active_from and period_start < constraint.active_from < period_end:
                candidates.add(constraint.active_from)
            if constraint.active_until and period_start < constraint.active_until < period_end:
                candidates.add(constraint.active_until)

    # Filter: keep only breakpoints where the fee inputs differ across the boundary.
    real_breakpoints: list[date] = []
    for bp in sorted(candidates):
        before = bp - timedelta(days=1)
        if before < period_start:
            before = period_start
        before_inputs = _fee_inputs_at(timelines, before)
        at_inputs = _fee_inputs_at(timelines, bp)
        if before_inputs != at_inputs:
            real_breakpoints.append(bp)
        else:
            logger.info(
                "Dropping non-affecting breakpoint %s (inputs unchanged across boundary)",
                bp,
            )

    return real_breakpoints


# ═══════════════════════════════════════════════════════════════════════════
# Basis Resolution
# ═══════════════════════════════════════════════════════════════════════════


def _get_timeline_value(
    timelines: dict[str, FieldTimeline],
    field: str,
    query_date: date,
) -> float | None:
    """Read a numeric value from a timeline, returning None if missing."""
    tl = timelines.get(field)
    if tl is None:
        return None
    val = tl.value_at(query_date)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        logger.warning("Cannot convert %r to float for field %s", val, field)
        return None


def _resolve_basis_amount(
    basis_label: str,
    timelines: dict[str, FieldTimeline],
    query_date: date,
) -> tuple[float, list[str]]:
    """Resolve the dollar amount for a given basis label.

    Returns (amount, assumptions) where assumptions lists any fallbacks used.
    """
    assumptions: list[str] = []

    if basis_label == "committed_capital":
        val = _get_timeline_value(timelines, "investor_commitment_amount", query_date)
        if val is not None:
            return val, assumptions
        assumptions.append("investor_commitment_amount not found — basis amount is 0")
        return 0.0, assumptions

    elif basis_label == "invested_capital":
        # Prefer LP's actual invested capital if available
        lp_invested = _get_timeline_value(timelines, "investor_invested_capital", query_date)
        if lp_invested is not None:
            return lp_invested, assumptions

        # Fallback: LP's pro-rata share of fund invested capital
        fund_invested = _get_timeline_value(timelines, "fund_total_invested_capital", query_date)
        if fund_invested is None:
            assumptions.append("investor_invested_capital and fund_total_invested_capital not found, hence basis amount is 0")
            return 0.0, assumptions

        lp_commitment = _get_timeline_value(timelines, "investor_commitment_amount", query_date)
        total_commitment = _get_timeline_value(timelines, "total_fund_commitment", query_date)

        if lp_commitment is not None and total_commitment is not None and total_commitment > 0:
            pro_rata = lp_commitment / total_commitment
            assumptions.append("Using pro-rata share of fund invested capital (investor_invested_capital not available)")
            return float(fund_invested) * pro_rata, assumptions
        else:
            assumptions.append("Using fund-level invested capital directly (no commitment data for pro-rata)")
            return float(fund_invested), assumptions

    elif basis_label == "unfunded_commitment":
        # LP's commitment minus LP's invested capital
        lp_commitment = _get_timeline_value(timelines, "investor_commitment_amount", query_date)
        if lp_commitment is None:
            assumptions.append("investor_commitment_amount not found — basis amount is 0")
            return 0.0, assumptions

        # Prefer LP's actual invested capital
        lp_invested = _get_timeline_value(timelines, "investor_invested_capital", query_date)
        if lp_invested is None:
            # Fallback to pro-rata
            fund_invested = _get_timeline_value(timelines, "fund_total_invested_capital", query_date)
            total_commitment = _get_timeline_value(timelines, "total_fund_commitment", query_date)
            lp_invested = 0.0
            if fund_invested is not None and total_commitment is not None and total_commitment > 0:
                lp_invested = fund_invested * (lp_commitment / total_commitment)

        return max(float(lp_commitment) - float(lp_invested), 0.0), assumptions

    else:
        # nav, net_contributed_capital, etc. — not available in V1
        assumptions.append(
            f"Basis '{basis_label}' not supported in V1 — using committed_capital as fallback"
        )
        return _resolve_basis_amount("committed_capital", timelines, query_date)


# ═══════════════════════════════════════════════════════════════════════════
# Sub-period Fee Computation
# ═══════════════════════════════════════════════════════════════════════════


def _find_source_clause(ft: FieldTimeline, query_date: date) -> str:
    """Find the source clause text for the value at query_date."""
    candidates = [
        e for e in ft.entries
        if e.date <= query_date
        and (e.end_date is None or query_date < e.end_date)
    ]
    if not candidates:
        return "unknown"
    winner = max(candidates, key=lambda e: e.insertion_order)
    return winner.source_clause_text


def _compute_sub_periods(
    timelines: dict[str, FieldTimeline],
    period_start: date,
    period_end: date,
) -> tuple[list[FeeSubPeriod], list[str]]:
    """Split a period at breakpoints and compute fee for each sub-period.

    Returns (sub_periods, assumptions).
    """
    breakpoints = _collect_breakpoints(timelines, period_start, period_end)

    # Build sub-period boundaries: [period_start, bp1, bp2, ..., period_end]
    boundaries = [period_start] + breakpoints + [period_end]
    # Deduplicate and sort
    boundaries = sorted(set(boundaries))

    sub_periods: list[FeeSubPeriod] = []
    all_assumptions: list[str] = []

    rate_tl = timelines.get("management_fee_rate")
    basis_tl = timelines.get("management_fee_basis")

    for i in range(len(boundaries) - 1):
        sub_start = boundaries[i]
        sub_end = boundaries[i + 1]
        days = (sub_end - sub_start).days

        if days <= 0:
            continue

        # Rate
        rate = 0.0
        source_clause = "no rate set"
        if rate_tl is not None:
            val = rate_tl.value_at(sub_start)
            if val is not None:
                try:
                    rate = float(val)
                except (TypeError, ValueError):
                    logger.warning("Non-numeric fee rate %r at %s, using 0", val, sub_start)
                    rate = 0.0
            source_clause = _find_source_clause(rate_tl, sub_start)

        # Basis label
        basis_label = "committed_capital"  # default
        if basis_tl is not None:
            val = basis_tl.value_at(sub_start)
            if val is not None:
                basis_label = str(val)
            else:
                all_assumptions.append(
                    "management_fee_basis not set — defaulting to committed_capital"
                )

        # Basis amount
        basis_amount, basis_assumptions = _resolve_basis_amount(
            basis_label, timelines, sub_start,
        )
        all_assumptions.extend(basis_assumptions)

        # Fee = rate% × basis × days/365
        fee_amount = (rate / 100) * basis_amount * (days / DAYS_IN_YEAR)

        sub_periods.append(FeeSubPeriod(
            start=sub_start,
            end=sub_end,
            days=days,
            annual_rate=rate,
            basis_label=basis_label,
            basis_amount=basis_amount,
            fee_amount=round(fee_amount, 2),
            source_clause=source_clause,
        ))

    return sub_periods, all_assumptions


# ═══════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════


def compute_management_fee(
    timelines: dict[str, FieldTimeline],
    evaluation_date: date,
    lp_admission_date: date | None = None,
) -> FeeResult:
    """Compute management fee for the billing period containing evaluation_date.

    Args:
        timelines: complete timelines from pipeline execution.
        evaluation_date: the date to evaluate fees for.
        lp_admission_date: when the LP joined the fund. None or before initial
            closing → defaults to initial closing.

    Returns:
        FeeResult with current period fee, optional catch-up, and audit trail.
    """
    assumptions: list[str] = []

    # ── Read anchor and cadence from timelines ────────────────────────
    anchor: date | None = None
    anchor_tl = timelines.get("fund_initial_closing_date")
    if anchor_tl is not None:
        val = anchor_tl.value_at(evaluation_date)
        if val is not None:
            anchor = val if isinstance(val, date) else date.fromisoformat(str(val))

    if anchor is None:
        # Two paths here: (1) the field is absent from timelines (malformed seed),
        # or (2) the field exists but value_at returned None, which can only mean
        # evaluation_date precedes the seed entry — i.e. the fund is not yet operational.
        if anchor_tl is None:
            assumptions.append("fund_initial_closing_date not found in timelines")
        else:
            assumptions.append(
                f"Evaluation date ({evaluation_date}) is before the fund's initial closing. "
                f"The fund is not yet operational and no management fee accrues."
            )
        return FeeResult(
            billing_period_start=evaluation_date,
            billing_period_end=evaluation_date,
            billing_cadence="unknown",
            anchor_date=evaluation_date,
            current_period_fee=BillingPeriodFee(
                period_start=evaluation_date, period_end=evaluation_date,
                total_fee=0.0, sub_periods=[],
            ),
            catchup_fee=None,
            catchup_period_start=None,
            catchup_period_end=None,
            lp_admission_date=evaluation_date,
            assumptions=assumptions,
        )

    cadence = "quarterly"  # default
    cadence_tl = timelines.get("management_fee_billing_cadence")
    if cadence_tl is not None:
        val = cadence_tl.value_at(evaluation_date)
        if val is not None:
            cadence = str(val)
        else:
            assumptions.append("Billing cadence not set — defaulting to quarterly")
    else:
        assumptions.append("Billing cadence not set — defaulting to quarterly")

    # ── Guard: evaluation_date at or after fund's term end ────────────
    # Fund life is over; no management fee accrues post-termination (V1).
    term_tl = timelines.get("fund_term_end_date")
    if term_tl is not None:
        val = term_tl.value_at(evaluation_date)
        if val is not None:
            term_end = val if isinstance(val, date) else date.fromisoformat(str(val))
            if evaluation_date >= term_end:
                assumptions.append(
                    f"Evaluation date ({evaluation_date}) is on or after the fund's term end "
                    f"({term_end}). The fund has terminated and no management fee accrues."
                )
                return FeeResult(
                    billing_period_start=term_end,
                    billing_period_end=term_end,
                    billing_cadence=cadence,
                    anchor_date=anchor,
                    current_period_fee=BillingPeriodFee(
                        period_start=term_end, period_end=term_end,
                        total_fee=0.0, sub_periods=[],
                    ),
                    catchup_fee=None,
                    catchup_period_start=None,
                    catchup_period_end=None,
                    lp_admission_date=lp_admission_date or anchor,
                    assumptions=assumptions,
                )

    # ── Validate and default lp_admission_date ────────────────────────
    final_closing: date | None = None
    fc_tl = timelines.get("fund_final_closing_date")
    if fc_tl is not None:
        val = fc_tl.value_at(evaluation_date)
        if val is not None:
            final_closing = val if isinstance(val, date) else date.fromisoformat(str(val))

    _admission_note: str | None = None  # set below, appended at end
    if lp_admission_date is None:
        lp_admission_date = anchor
        _admission_note = "LP Admission Date not set — assumes LP joined at initial closing"
    elif lp_admission_date < anchor:
        _admission_note = (
            f"LP cannot be admitted before the initial closing ({anchor}) "
            f"— assuming LP joined at initial closing"
        )
        lp_admission_date = anchor
    elif lp_admission_date == anchor:
        _admission_note = None  # standard case — LP joined at first close, no assumption needed
    elif final_closing is not None and lp_admission_date > final_closing:
        _admission_note = (
            f"LP admission date ({lp_admission_date}) is after final closing "
            f"({final_closing}) — defaulting to initial closing ({anchor})"
        )
        lp_admission_date = anchor
    else:
        _admission_note = None  # valid date between closings, message set at end

    # ── Check if LP was admitted by evaluation date ────────────────────
    if evaluation_date < lp_admission_date:
        assumptions.append(
            f"As of {evaluation_date}, LP had not yet been admitted to the fund "
            f"(admission date: {lp_admission_date})"
        )
        return FeeResult(
            billing_period_start=lp_admission_date,
            billing_period_end=lp_admission_date,
            billing_cadence=cadence,
            anchor_date=anchor,
            current_period_fee=BillingPeriodFee(
                period_start=lp_admission_date, period_end=lp_admission_date,
                total_fee=0.0, sub_periods=[],
            ),
            catchup_fee=None,
            catchup_period_start=None,
            catchup_period_end=None,
            lp_admission_date=lp_admission_date,
            assumptions=assumptions,
        )

    # ── Generate billing periods and find the target ──────────────────
    periods = _generate_billing_periods(anchor, cadence, evaluation_date)

    target_period = _find_billing_period(periods, evaluation_date)
    if target_period is None:
        reason = (
            f"Evaluation date ({evaluation_date}) is before fund initial closing ({anchor})"
            if evaluation_date < anchor
            else f"Could not find billing period for {evaluation_date} with anchor {anchor}"
        )
        assumptions.append(reason)
        return FeeResult(
            billing_period_start=anchor,
            billing_period_end=anchor,
            billing_cadence=cadence,
            anchor_date=anchor,
            current_period_fee=BillingPeriodFee(
                period_start=anchor, period_end=anchor,
                total_fee=0.0, sub_periods=[],
            ),
            catchup_fee=None,
            catchup_period_start=None,
            catchup_period_end=None,
            lp_admission_date=lp_admission_date or anchor,
            assumptions=assumptions,
        )

    period_start, period_end = target_period

    # ── Compute current period fee ────────────────────────────────────
    # If LP admission falls within this period, prorate from admission date
    effective_start = period_start
    if lp_admission_date > period_start:
        effective_start = lp_admission_date
        if lp_admission_date < period_end:
            assumptions.append(
                f"Current period prorated from LP admission date ({lp_admission_date})"
            )

    current_sub_periods, current_assumptions = _compute_sub_periods(
        timelines, effective_start, period_end,
    )
    assumptions.extend(current_assumptions)

    current_period = BillingPeriodFee(
        period_start=effective_start,
        period_end=period_end,
        total_fee=round(sum(sp.fee_amount for sp in current_sub_periods), 2),
        sub_periods=current_sub_periods,
    )

    # ── Compute catch-up fee (if LP joined after initial closing) ─────
    catchup_fee: BillingPeriodFee | None = None
    catchup_start: date | None = None
    catchup_end: date | None = None

    if lp_admission_date > anchor:
        catchup_start = anchor
        catchup_end = lp_admission_date

        catchup_sub_periods, catchup_assumptions = _compute_sub_periods(
            timelines, catchup_start, catchup_end,
        )
        assumptions.extend(catchup_assumptions)

        catchup_fee = BillingPeriodFee(
            period_start=catchup_start,
            period_end=catchup_end,
            total_fee=round(sum(sp.fee_amount for sp in catchup_sub_periods), 2),
            sub_periods=catchup_sub_periods,
        )

    # ── Assemble result ───────────────────────────────────────────────
    assumptions.append(f"Day count convention: {DAY_COUNT_CONVENTION}")
    if _admission_note:
        assumptions.append(_admission_note)
    elif lp_admission_date != anchor:
        assumptions.append(f"LP admission date: {lp_admission_date}")

    return FeeResult(
        billing_period_start=period_start,
        billing_period_end=period_end,
        billing_cadence=cadence,
        anchor_date=anchor,
        current_period_fee=current_period,
        catchup_fee=catchup_fee,
        catchup_period_start=catchup_start,
        catchup_period_end=catchup_end,
        lp_admission_date=lp_admission_date,
        assumptions=assumptions,
    )
