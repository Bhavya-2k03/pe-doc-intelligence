"""
Timeline Execution Engine — Layer 5.

Pure deterministic logic. No LLM calls. Takes ClauseInstruction objects
(produced by the clause interpreter) and builds solid timelines by
executing them sequentially.
"""
from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta
from typing import Any, Optional

from dateutil.relativedelta import relativedelta
from pydantic import BaseModel

from engine.models import ASTNode, ClauseInstruction

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════════


class TimelineEntry(BaseModel):
    date: date
    end_date: Optional[date] = None  # None = permanent
    value: Any
    source_clause_text: str
    entry_type: str  # "SET" or "ADJUST"
    direction: Optional[str] = None  # "REDUCTION" | "INCREASE" | None
    insertion_order: int = 0  # monotonic counter — later insert = higher value
    document_date: Optional[date] = None
    email_source_id: Optional[str] = None
    clause_id: Optional[str] = None


class ConstraintRule(BaseModel):
    type: str  # "CAP" or "FLOOR"
    bound: Any
    active_from: Optional[date] = None
    active_until: Optional[date] = None
    source_clause_text: str
    insertion_order: int = 0


class FieldTimeline(BaseModel):
    entries: list[TimelineEntry] = []
    constraints: list[ConstraintRule] = []
    _next_order: int = 0

    def value_at(self, query_date: date) -> Any:
        """Find the entry covering query_date with the highest insertion_order,
        then apply active constraints."""
        # Collect all entries that cover query_date
        candidates: list[TimelineEntry] = []
        for entry in self.entries:
            if entry.date > query_date:
                continue
            if entry.end_date is not None and query_date >= entry.end_date:
                continue
            candidates.append(entry)

        if not candidates:
            return None

        # Pick the one inserted last (highest insertion_order)
        winner = max(candidates, key=lambda e: e.insertion_order)
        raw_value = winner.value

        # Apply active constraints — latest of each type wins
        latest_cap: ConstraintRule | None = None
        latest_floor: ConstraintRule | None = None
        for c in self.constraints:
            if c.active_from is not None and query_date < c.active_from:
                continue
            if c.active_until is not None and query_date >= c.active_until:
                continue
            if c.type == "CAP":
                if latest_cap is None or c.insertion_order > latest_cap.insertion_order:
                    latest_cap = c
            elif c.type == "FLOOR":
                if latest_floor is None or c.insertion_order > latest_floor.insertion_order:
                    latest_floor = c

        result = raw_value
        try:
            if latest_cap is not None:
                result = min(result, latest_cap.bound)
            if latest_floor is not None:
                result = max(result, latest_floor.bound)
        except TypeError:
            pass  # incompatible types — return raw_value unconstrained
        return result

    def insert_entry(self, entry: TimelineEntry) -> None:
        """Assign insertion_order, append, and re-sort by date."""
        entry.insertion_order = self._next_order
        self._next_order += 1
        self.entries.append(entry)
        self.entries.sort(key=lambda e: e.date)

    def register_constraint(self, constraint: ConstraintRule) -> None:
        """Assign insertion_order and append to constraints list."""
        constraint.insertion_order = self._next_order
        self._next_order += 1
        self.constraints.append(constraint)

    def find_transitions(
        self,
        direction: str,
        scope_date: Optional[date],
        scope_mode: Optional[str],
    ) -> list[TimelineEntry]:
        """Find entries matching direction and scope criteria.

        direction: "REDUCTION" | "INCREASE" | "ANY"
        scope_mode: None | "AT" | "FROM" | "BEFORE"
        """
        matches: list[TimelineEntry] = []
        sorted_entries = sorted(self.entries, key=lambda e: e.date)

        for i, entry in enumerate(sorted_entries):
            # Determine if this entry matches the direction
            if direction == "ANY":
                is_match = True
            elif entry.entry_type == "ADJUST":
                is_match = entry.direction == direction
            else:
                # SET entry: compare value with prior value to determine direction.
                # Skip expired entries (end_date <= this entry's date) when
                # finding the prior — a temporary waiver that ended months ago
                # shouldn't mask the real prior value.
                prior_val = None
                for j in range(i - 1, -1, -1):
                    prev = sorted_entries[j]
                    if prev.end_date is not None and prev.end_date < entry.date:
                        continue  # this entry expired well before current one starts
                    prior_val = prev.value
                    break
                if prior_val is None:
                    is_match = False
                else:
                    try:
                        if direction == "REDUCTION":
                            is_match = entry.value < prior_val
                        else:  # INCREASE
                            is_match = entry.value > prior_val
                    except TypeError:
                        is_match = False

            if not is_match:
                continue

            # Apply scope filter
            if scope_mode is None or scope_date is None:
                matches.append(entry)
            elif scope_mode == "AT" and entry.date == scope_date:
                matches.append(entry)
            elif scope_mode == "FROM" and entry.date >= scope_date:
                matches.append(entry)
            elif scope_mode == "BEFORE" and entry.date < scope_date:
                matches.append(entry)

        return matches


class EvaluationContext(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    evaluation_date: date
    document_date: Optional[date] = None
    fund_data: dict = {}


# ═══════════════════════════════════════════════════════════════════════════
# Function Registry
# ═══════════════════════════════════════════════════════════════════════════


def _fn_fund_realization_pct(
    args: list, ctx: EvaluationContext, timelines: dict
) -> float:
    tl = timelines.get("fund_percentage_realized")
    if tl is not None:
        val = tl.value_at(ctx.evaluation_date)
        if val is not None:
            return val
    realized_tl = timelines.get("fund_total_realized_capital")
    invested_tl = timelines.get("fund_total_invested_capital")
    if realized_tl and invested_tl:
        r = realized_tl.value_at(ctx.evaluation_date)
        i = invested_tl.value_at(ctx.evaluation_date)
        if r is not None and i is not None and i != 0:
            return (r / i) * 100
    return 0


def _fn_investor_realization_pct(
    args: list, ctx: EvaluationContext, timelines: dict
) -> float:
    tl = timelines.get("investor_percentage_realized")
    if tl is not None:
        val = tl.value_at(ctx.evaluation_date)
        if val is not None:
            return val
    return 0


def _fn_total_commitments(
    args: list, ctx: EvaluationContext, timelines: dict
) -> float:
    tl = timelines.get("total_fund_commitment")
    if tl is not None:
        val = tl.value_at(ctx.evaluation_date)
        if val is not None:
            return val
    return 0


def _fn_invested_capital(
    args: list, ctx: EvaluationContext, timelines: dict
) -> float:
    tl = timelines.get("fund_total_invested_capital")
    if tl is not None:
        val = tl.value_at(ctx.evaluation_date)
        if val is not None:
            return val
    return 0


def _fn_dpi(
    args: list, ctx: EvaluationContext, timelines: dict
) -> float:
    tl = timelines.get("dpi")
    if tl is not None:
        val = tl.value_at(ctx.evaluation_date)
        if val is not None:
            return val
    distributions_tl = timelines.get("fund_total_distributions")
    paid_in_tl = timelines.get("fund_total_paid_in_capital")
    if distributions_tl and paid_in_tl:
        d = distributions_tl.value_at(ctx.evaluation_date)
        p = paid_in_tl.value_at(ctx.evaluation_date)
        if d is not None and p is not None and p != 0:
            return d / p
    return 0


def _to_date(value) -> date:
    """Coerce a value to date. Handles date objects and ISO string values
    that come from timeline entries (e.g. fund_final_closing_date stored as str)."""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"Cannot coerce {type(value).__name__!r} to date: {value!r}")


def _get_fund_quarter_starts(timelines: dict, ctx: EvaluationContext) -> list[tuple[int, int]]:
    """Derive fiscal quarter start (month, day) from fund_initial_closing_date.

    PE funds define fiscal quarters anchored to the initial closing date.
    E.g., if initial closing is Jan 15, quarters start Jan 15, Apr 15,
    Jul 15, Oct 15 — NOT calendar quarters (Jan 1, Apr 1, etc.).

    Falls back to calendar quarters if fund_initial_closing_date is unavailable.
    """
    ic_tl = timelines.get("fund_initial_closing_date")
    if ic_tl is not None:
        val = ic_tl.value_at(ctx.evaluation_date)
        if val is not None:
            ic = _to_date(val) if not isinstance(val, date) else val
            d = ic.day
            # Four quarters starting from the closing date's month/day,
            # spaced 3 months apart
            m = ic.month
            starts = []
            for _ in range(4):
                starts.append((m, d))
                m += 3
                if m > 12:
                    m -= 12
            return sorted(starts)
    # Fallback: standard calendar quarters
    return [(1, 1), (4, 1), (7, 1), (10, 1)]


def _fn_next_fiscal_quarter_start(
    args: list, ctx: EvaluationContext, timelines: dict
) -> date:
    """Start of the next fiscal quarter after ref_date.

    Quarters are anchored to fund_initial_closing_date (PE convention).
    E.g., if initial closing is Jan 15 → quarters start Jan 15, Apr 15,
    Jul 15, Oct 15.
    """
    ref_date: date = _to_date(args[0])
    quarter_starts = _get_fund_quarter_starts(timelines, ctx)
    for m, d in quarter_starts:
        candidate = date(ref_date.year, m, d)
        if candidate > ref_date:
            return candidate
    # Next year, first quarter
    m, d = quarter_starts[0]
    return date(ref_date.year + 1, m, d)


def _fn_fiscal_quarter_start(
    args: list, ctx: EvaluationContext, timelines: dict
) -> date:
    """First day of a specific fund fiscal quarter.

    args[0] = quarter_num (1-4), args[1] = year.
    Quarters anchored to fund_initial_closing_date.
    """
    quarter_num: int = int(args[0])
    year: int = int(args[1])
    quarter_starts = _get_fund_quarter_starts(timelines, ctx)
    if quarter_num < 1 or quarter_num > len(quarter_starts):
        raise ValueError(f"Quarter must be 1-{len(quarter_starts)}, got {quarter_num}")
    m, d = quarter_starts[quarter_num - 1]
    return date(year, m, d)


def _fn_fiscal_quarter_end(
    args: list, ctx: EvaluationContext, timelines: dict
) -> date:
    """Last day of a specific fund fiscal quarter (day before next quarter starts).

    args[0] = quarter_num (1-4), args[1] = year.
    Quarters anchored to fund_initial_closing_date.
    """
    quarter_num: int = int(args[0])
    year: int = int(args[1])
    quarter_starts = _get_fund_quarter_starts(timelines, ctx)
    if quarter_num < 1 or quarter_num > len(quarter_starts):
        raise ValueError(f"Quarter must be 1-{len(quarter_starts)}, got {quarter_num}")
    # End of Q_n = day before start of Q_(n+1)
    next_q = quarter_num % len(quarter_starts)
    m, d = quarter_starts[next_q]
    next_year = year + 1 if next_q == 0 else year
    next_start = date(next_year, m, d)
    return next_start - timedelta(days=1)


def _fn_month_start(
    args: list, ctx: EvaluationContext, timelines: dict
) -> date:
    """First day of a specific month.

    args[0] = month_num (1-12).
    args[1] = year (int) or reference date.
    args[2] = optional hint: "current" | "next" | "nearest".
    """
    month_num = int(args[0])
    ref_or_year = args[1] if isinstance(args[1], int) else _to_date(args[1])
    hint = args[2] if len(args) > 2 else None

    if isinstance(ref_or_year, int):
        return date(ref_or_year, month_num, 1)

    ref: date = ref_or_year
    if hint == "next":
        # Next occurrence of month_num after ref
        candidate = date(ref.year, month_num, 1)
        if candidate <= ref:
            candidate = date(ref.year + 1, month_num, 1)
        return candidate
    elif hint == "nearest":
        this_year = date(ref.year, month_num, 1)
        next_year = date(ref.year + 1, month_num, 1)
        prev_year = date(ref.year - 1, month_num, 1)
        options = [prev_year, this_year, next_year]
        return min(options, key=lambda d: abs((d - ref).days))
    else:  # "current" or default
        return date(ref.year, month_num, 1)


def _fn_month_end(
    args: list, ctx: EvaluationContext, timelines: dict
) -> date:
    """Last day of a specific month. Same arg structure as MONTH_START."""
    month_num = int(args[0])
    ref_or_year = args[1] if isinstance(args[1], int) else _to_date(args[1])
    hint = args[2] if len(args) > 2 else None

    def _last_day(year: int, month: int) -> date:
        return date(year, month, calendar.monthrange(year, month)[1])

    if isinstance(ref_or_year, int):
        return _last_day(ref_or_year, month_num)

    ref: date = ref_or_year
    if hint == "next":
        candidate = _last_day(ref.year, month_num)
        if candidate <= ref:
            candidate = _last_day(ref.year + 1, month_num)
        return candidate
    elif hint == "nearest":
        options = [
            _last_day(ref.year - 1, month_num),
            _last_day(ref.year, month_num),
            _last_day(ref.year + 1, month_num),
        ]
        return min(options, key=lambda d: abs((d - ref).days))
    else:
        return _last_day(ref.year, month_num)


def _fn_anniversary(
    args: list, ctx: EvaluationContext, timelines: dict
) -> date:
    """ref_date + ordinal years."""
    ordinal = int(args[0])
    ref_date: date = _to_date(args[1])
    return ref_date + relativedelta(years=ordinal)


def _fn_days_since(
    args: list, ctx: EvaluationContext, timelines: dict
) -> int:
    """(evaluation_date - target_date).days"""
    target_date: date = _to_date(args[0])
    return (ctx.evaluation_date - target_date).days


RUNTIME_FUNCTION_REGISTRY: dict[str, callable] = {
    "FUND_REALIZATION_PCT": _fn_fund_realization_pct,
    "INVESTOR_REALIZATION_PCT": _fn_investor_realization_pct,
    "TOTAL_COMMITMENTS": _fn_total_commitments,
    "INVESTED_CAPITAL": _fn_invested_capital,
    "DPI": _fn_dpi,
    "NEXT_FISCAL_QUARTER_START": _fn_next_fiscal_quarter_start,
    "FISCAL_QUARTER_START": _fn_fiscal_quarter_start,
    "FISCAL_QUARTER_END": _fn_fiscal_quarter_end,
    "MONTH_START": _fn_month_start,
    "MONTH_END": _fn_month_end,
    "ANNIVERSARY": _fn_anniversary,
    "DAYS_SINCE": _fn_days_since,
}


# ═══════════════════════════════════════════════════════════════════════════
# AST Evaluator
# ═══════════════════════════════════════════════════════════════════════════


def evaluate_ast(
    node: ASTNode,
    timelines: dict[str, FieldTimeline],
    ctx: EvaluationContext,
) -> Any:
    """Recursively evaluate an AST node against current timelines and context."""
    nt = node.node_type

    # ── literal ───────────────────────────────────────────────────────
    if nt == "literal":
        if node.value_type == "date" and isinstance(node.value, str):
            return date.fromisoformat(node.value)
        return node.value

    # ── field_ref ─────────────────────────────────────────────────────
    if nt == "field_ref":
        field = node.field
        if field == "evaluation_date":
            return ctx.evaluation_date
        if field == "document_date":
            return ctx.document_date
        tl = timelines.get(field)
        if tl is None:
            logger.warning("field_ref '%s' not found in timelines", field)
            return None
        return tl.value_at(ctx.evaluation_date)

    # ── evaluate args (shared by most branch nodes) ───────────────────
    evaluated_args = []
    if node.args:
        evaluated_args = [evaluate_ast(a, timelines, ctx) for a in node.args]

    # ── Helper: coerce string dates in args ─────────────────────────
    def _coerce_date(val):
        """Coerce string ISO dates to date objects. Pass through others."""
        if isinstance(val, str):
            try:
                return date.fromisoformat(val)
            except ValueError:
                return val
        return val

    # ── comparison ────────────────────────────────────────────────────
    if nt == "comparison":
        left, right = _coerce_date(evaluated_args[0]), _coerce_date(evaluated_args[1])
        op = node.op
        # None safety: if either side is None, comparison returns False
        if left is None or right is None:
            return False
        try:
            if op in ("GTE", ">="):
                return left >= right
            if op in ("LTE", "<="):
                return left <= right
            if op in ("GT", ">"):
                return left > right
            if op in ("LT", "<"):
                return left < right
            if op in ("EQ", "=="):
                return left == right
            if op in ("NEQ", "!="):
                return left != right
        except TypeError:
            logger.warning(
                "Comparison %s on incompatible types: %r (%s) vs %r (%s)",
                op, left, type(left).__name__, right, type(right).__name__,
            )
            return False
        raise ValueError(f"Unknown comparison op: {op}")

    # ── logical ───────────────────────────────────────────────────────
    if nt == "logical":
        op = node.op
        if op == "AND":
            return all(evaluated_args)
        if op == "OR":
            return any(evaluated_args)
        if op == "NOT":
            return not evaluated_args[0]
        raise ValueError(f"Unknown logical op: {op}")

    # ── arithmetic ────────────────────────────────────────────────────
    if nt == "arithmetic":
        left, right = evaluated_args[0], evaluated_args[1]
        op = node.op
        # None safety: return None if either operand is None
        if left is None or right is None:
            logger.warning("Arithmetic with None operand: %s %s %s", left, op, right)
            return None
        try:
            if op == "ADD":
                return left + right
            if op == "SUB":
                return left - right
            if op == "MUL":
                return left * right
            if op == "DIV":
                return left / right
        except (TypeError, ZeroDivisionError) as exc:
            logger.warning(
                "Arithmetic %s failed: %r (%s) %s %r (%s) — %s",
                op, left, type(left).__name__, op, right, type(right).__name__, exc,
            )
            return None
        raise ValueError(f"Unknown arithmetic op: {op}")

    # ── temporal ──────────────────────────────────────────────────────
    if nt == "temporal":
        raw_base = evaluated_args[0]
        op = node.op
        # None safety: if base date is None, return None
        if raw_base is None:
            logger.warning("Temporal %s with None base date", op)
            return None
        try:
            base_date: date = _to_date(raw_base)
        except (TypeError, ValueError) as exc:
            logger.warning("Temporal %s: cannot coerce base to date: %r (%s)", op, raw_base, exc)
            return None
        try:
            amount = int(evaluated_args[1])
        except (TypeError, ValueError) as exc:
            logger.warning("Temporal %s: cannot coerce offset to int: %r (%s)", op, evaluated_args[1], exc)
            return None
        if op == "ADD_YEARS":
            return base_date + relativedelta(years=amount)
        if op == "ADD_MONTHS":
            return base_date + relativedelta(months=amount)
        if op == "ADD_DAYS":
            return base_date + timedelta(days=amount)
        raise ValueError(f"Unknown temporal op: {op}")

    # ── function_call ─────────────────────────────────────────────────
    if nt == "function_call":
        fn = RUNTIME_FUNCTION_REGISTRY.get(node.fn)
        if fn is None:
            raise ValueError(f"Unknown function: {node.fn}")
        try:
            return fn(evaluated_args, ctx, timelines)
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Function %s(%s) failed: %s",
                node.fn, evaluated_args, exc,
            )
            return None

    # ── aggregator ────────────────────────────────────────────────────
    if nt == "aggregator":
        op = node.op
        coerced = [_coerce_date(a) for a in evaluated_args]
        # Filter out None values
        coerced = [a for a in coerced if a is not None]
        if not coerced:
            return None
        try:
            if op == "MIN":
                return min(coerced)
            if op == "MAX":
                return max(coerced)
        except TypeError:
            logger.warning("Aggregator %s on incompatible types: %s", op, coerced)
            return None
        raise ValueError(f"Unknown aggregator op: {op}")

    raise ValueError(f"Unknown node_type: {nt}")


# ═══════════════════════════════════════════════════════════════════════════
# Instruction Executor
# ═══════════════════════════════════════════════════════════════════════════


def execute(
    instruction: ClauseInstruction,
    timelines: dict[str, FieldTimeline],
    ctx: EvaluationContext,
) -> None:
    """Execute one ClauseInstruction. Modifies timelines in place."""
    action = instruction.action

    # ── NO_ACTION / MANUAL_REVIEW: nothing to do ──────────────────────
    if action in ("NO_ACTION", "MANUAL_REVIEW"):
        return

    # ── Null safety: SET/ADJUST need a date to anchor to ─────────────
    if action in ("SET", "ADJUST") and ctx.document_date is None:
        if instruction.effective_date_expr is None:
            logger.error(
                "Cannot execute %s: no document_date and no effective_date_expr. "
                "Clause: %s", action, instruction.clause_text[:80]
            )
            return

    field = instruction.affected_field

    # Ensure the field timeline exists
    if field not in timelines:
        timelines[field] = FieldTimeline()

    tl = timelines[field]

    # ── Condition gate (shared by SET, ADJUST, CONSTRAIN) ─────────────
    if action in ("SET", "ADJUST", "CONSTRAIN"):
        if instruction.condition_ast is not None:
            cond_result = evaluate_ast(instruction.condition_ast, timelines, ctx)
            if not cond_result:
                return

    def _eval_date(expr):
        """Evaluate an AST expression and coerce to date if string.
        Returns None with a warning if the result cannot be coerced to a date."""
        val = evaluate_ast(expr, timelines, ctx)
        if val is None:
            return None
        if isinstance(val, date):
            return val
        if isinstance(val, str):
            try:
                return date.fromisoformat(val)
            except ValueError:
                logger.warning(
                    "AST evaluated to non-date string %r for clause: %s",
                    val, instruction.clause_text[:80],
                )
                return None
        # Non-date, non-string result (e.g., a number from FUND_REALIZATION_PCT
        # used as effective_end_date_expr by mistake)
        logger.warning(
            "AST evaluated to %s (%r) instead of date for clause: %s",
            type(val).__name__, val, instruction.clause_text[:80],
        )
        return None

    # ── SET ────────────────────────────────────────────────────────────
    if action == "SET":
        value = evaluate_ast(instruction.value_expr, timelines, ctx)

        eff_date = ctx.document_date
        if instruction.effective_date_expr is not None:
            eff_date = _eval_date(instruction.effective_date_expr)

        if eff_date is None:
            logger.error("SET: eff_date resolved to None. Skipping. Clause: %s",
                         instruction.clause_text[:80])
            return

        eff_end = None
        if instruction.effective_end_date_expr is not None:
            eff_end = _eval_date(instruction.effective_end_date_expr)
            # eff_end=None after failed eval is OK — treated as permanent

        tl.insert_entry(TimelineEntry(
            date=eff_date,
            end_date=eff_end,
            value=value,
            source_clause_text=instruction.clause_text,
            entry_type="SET",
            direction=None,
        ))

    # ── ADJUST ────────────────────────────────────────────────────────
    elif action == "ADJUST":
        delta = evaluate_ast(instruction.value_expr, timelines, ctx)

        eff_date = ctx.document_date
        if instruction.effective_date_expr is not None:
            eff_date = _eval_date(instruction.effective_date_expr)

        if eff_date is None:
            logger.error("ADJUST: eff_date resolved to None. Skipping. Clause: %s",
                         instruction.clause_text[:80])
            return

        eff_end = None
        if instruction.effective_end_date_expr is not None:
            eff_end = _eval_date(instruction.effective_end_date_expr)

        current = tl.value_at(eff_date) or 0

        # Guard: ADJUST only works on numeric values. Date-valued fields
        # (e.g., fund_term_end_date = "2034-01-15") should use SET with
        # temporal expressions, not ADJUST.
        if not isinstance(current, (int, float)):
            logger.error(
                "ADJUST on non-numeric current value %r (%s) for field %s. "
                "Skipping. Clause: %s",
                current, type(current).__name__, field,
                instruction.clause_text[:80],
            )
            return
        if not isinstance(delta, (int, float)):
            logger.error(
                "ADJUST with non-numeric delta %r (%s) for field %s. "
                "Skipping. Clause: %s",
                delta, type(delta).__name__, field,
                instruction.clause_text[:80],
            )
            return

        if instruction.adjust_mode == "multiplicative":
            new_value = current * delta
        else:
            # Default: additive
            new_value = current + delta

        tl.insert_entry(TimelineEntry(
            date=eff_date,
            end_date=eff_end,
            value=new_value,
            source_clause_text=instruction.clause_text,
            entry_type="ADJUST",
            direction=instruction.adjust_direction,
        ))

    # ── CONSTRAIN ─────────────────────────────────────────────────────
    elif action == "CONSTRAIN":
        bound = evaluate_ast(instruction.value_expr, timelines, ctx)

        active_from = None
        if instruction.effective_date_expr is not None:
            active_from = _eval_date(instruction.effective_date_expr)

        active_until = None
        if instruction.effective_end_date_expr is not None:
            active_until = _eval_date(instruction.effective_end_date_expr)

        tl.register_constraint(ConstraintRule(
            type=instruction.constraint_type,
            bound=bound,
            active_from=active_from,
            active_until=active_until,
            source_clause_text=instruction.clause_text,
        ))

    # ── GATE ──────────────────────────────────────────────────────────
    elif action == "GATE":
        # Resolve the scope date for matching transitions
        scope_date = None
        if instruction.effective_date_expr is not None:
            scope_date = _eval_date(instruction.effective_date_expr)

        # ── GATE with gate_move_to_date_expr ──────────────────────────
        if instruction.gate_move_to_date_expr is not None:
            matched = tl.find_transitions(
                direction=instruction.gate_target or "ANY",
                scope_date=scope_date,
                scope_mode=instruction.gate_scope_mode,
            )
            new_start = _eval_date(instruction.gate_move_to_date_expr)
            new_end = None
            if instruction.gate_new_end_date_expr is not None:
                new_end = _eval_date(instruction.gate_new_end_date_expr)

            # Filter matched transitions based on gate_direction:
            #   POSTPONE  — only move transitions currently before the new date
            #   PREPONE   — only move transitions currently after the new date
            #   RESCHEDULE — move all matched transitions regardless
            gd = instruction.gate_direction
            if gd == "POSTPONE":
                matched = [e for e in matched if e.date < new_start]
            elif gd == "PREPONE":
                matched = [e for e in matched if e.date > new_start]
            # RESCHEDULE: no filter, move everything matched

            moved_from = {e.date for e in matched}

            for entry in matched:
                entry.date = new_start
                if new_end is not None:
                    entry.end_date = new_end

            # Fix handoff gaps: if a surviving entry's end_date was the
            # old start of a moved entry, extend it to the new start.
            for entry in tl.entries:
                if entry not in matched and entry.end_date in moved_from:
                    entry.end_date = new_start

            # Re-sort after moving dates
            tl.entries.sort(key=lambda e: e.date)

        # ── GATE with condition_ast ───────────────────────────────────
        elif instruction.condition_ast is not None:
            matched = tl.find_transitions(
                direction=instruction.gate_target or "ANY",
                scope_date=scope_date,
                scope_mode=instruction.gate_scope_mode,
            )
            cond_result = evaluate_ast(instruction.condition_ast, timelines, ctx)
            if not cond_result:
                # FALSE → remove matched transitions
                matched_ids = {id(e) for e in matched}
                removed_starts = {e.date for e in matched}

                tl.entries = [e for e in tl.entries if id(e) not in matched_ids]

                # Fix handoff gaps: if a surviving entry's end_date was the
                # start of a removed entry, extend it to the next surviving
                # entry that starts AT OR AFTER the removed entry's position.
                # Intermediate entries (like a temporary waiver that starts
                # and ends within the surviving entry's original range) are
                # ignored — they don't represent the "next regime".
                for entry in tl.entries:
                    if entry.end_date in removed_starts:
                        handoff_date = entry.end_date  # where the removed entry was
                        # Find next surviving entry at or after the handoff point
                        next_start = None
                        for other in tl.entries:
                            if other is entry:
                                continue
                            if other.date >= handoff_date and (
                                next_start is None or other.date < next_start
                            ):
                                next_start = other.date
                        entry.end_date = next_start  # None if nothing follows


# ═══════════════════════════════════════════════════════════════════════════
# Batch Executor
# ═══════════════════════════════════════════════════════════════════════════


def execute_all(
    instructions: list[ClauseInstruction],
    seed_timelines: dict[str, list[dict]],
    evaluation_date: date,
    document_dates: dict[str, date],
    fund_data: dict,
) -> dict[str, FieldTimeline]:
    """Execute all instructions sequentially.

    Args:
        instructions: ordered list of ClauseInstruction objects.
        seed_timelines: dict mapping field name to list of seed entry dicts,
            each with keys: date, value, source (and optional end_date).
        evaluation_date: the date we're evaluating timelines for.
        document_dates: mapping clause_text =resolved document_date.
        fund_data: runtime data for function calls (realization pct, etc.).

    Returns:
        dict mapping field name to FieldTimeline.
    """
    # Deep copy seed into FieldTimeline objects
    timelines: dict[str, FieldTimeline] = {}
    for field_name, entries in seed_timelines.items():
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
                direction=None,
            ))
        timelines[field_name] = ft

    ctx = EvaluationContext(
        evaluation_date=evaluation_date,
        fund_data=fund_data,
    )

    for instruction in instructions:
        ctx.document_date = document_dates.get(instruction.clause_text)
        execute(instruction, timelines, ctx)

    return timelines


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)

    # ── Seed: management_fee_rate = 2.0 at 2024-01-15 ────────────────
    seed = {
        "management_fee_rate": [
            {"date": "2024-01-15", "value": 2.0, "source": "LPA"},
        ],
    }

    # ── Instruction 1: SET fee_rate to 1.5 at 2025-06-01 ─────────────
    instr_set = ClauseInstruction(
        clause_text="Fee rate reduced to 1.5%",
        affected_field="management_fee_rate",
        action="SET",
        value_expr=ASTNode(
            node_type="literal", value=1.5, value_type="percentage",
            op=None, field=None, fn=None, args=None,
        ),
        effective_date_expr=ASTNode(
            node_type="literal", value="2025-06-01", value_type="date",
            op=None, field=None, fn=None, args=None,
        ),
    )

    # ── Instruction 2: ADJUST by -0.25 at 2026-01-01 ─────────────────
    instr_adjust = ClauseInstruction(
        clause_text="Additional 25bps reduction",
        affected_field="management_fee_rate",
        action="ADJUST",
        value_expr=ASTNode(
            node_type="literal", value=-0.25, value_type="number",
            op=None, field=None, fn=None, args=None,
        ),
        effective_date_expr=ASTNode(
            node_type="literal", value="2026-01-01", value_type="date",
            op=None, field=None, fn=None, args=None,
        ),
        adjust_direction="REDUCTION",
    )

    doc_dates = {
        "Fee rate reduced to 1.5%": date(2025, 6, 1),
        "Additional 25bps reduction": date(2026, 1, 1),
    }

    timelines = execute_all(
        instructions=[instr_set, instr_adjust],
        seed_timelines=seed,
        evaluation_date=date(2026, 12, 31),
        document_dates=doc_dates,
        fund_data={},
    )

    tl = timelines["management_fee_rate"]
    v1 = tl.value_at(date(2024, 6, 1))
    v2 = tl.value_at(date(2025, 7, 1))
    v3 = tl.value_at(date(2026, 6, 1))

    print(f"2024-06-01 ={v1}  (expected 2.0)")
    print(f"2025-07-01 ={v2}  (expected 1.5)")
    print(f"2026-06-01 ={v3}  (expected 1.25)")

    assert v1 == 2.0, f"FAIL: expected 2.0, got {v1}"
    assert v2 == 1.5, f"FAIL: expected 1.5, got {v2}"
    assert v3 == 1.25, f"FAIL: expected 1.25, got {v3}"

    print("\nAll tests passed.")
