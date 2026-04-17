"""Unit tests for engine/pipeline.py — Layers 3, 4, stability loop.

No LLM calls. All async functions are mocked where needed.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from engine.models import ASTNode, ClauseInstruction
from engine.pipeline import (
    _find_first_true_date,
    _recompute_ordering_and_filter,
    _snapshot_conditional_dates,
    _build_timelines,
    _execute_clauses,
    resolve_document_dates,
    resolve_confirmations,
)
from engine.pipeline_models import (
    ClauseWithContext,
    DocumentIntent,
    DocumentReference,
)
from engine.timeline_engine import (
    ConstraintRule,
    EvaluationContext,
    FieldTimeline,
    TimelineEntry,
)
from tests.conftest import (
    comparison, fn_call, lit, lit_date, lit_pct, field_ref,
)


# ═══════════════════════════════════════════════════════════════════════════
# A. _find_first_true_date
# ═══════════════════════════════════════════════════════════════════════════


class TestFindFirstTrueDate:

    def _make_timelines_with_realization(self, entries: list[tuple[str, float]]):
        """Helper: build a fund_percentage_realized timeline from (date_str, pct) pairs."""
        timelines: dict[str, FieldTimeline] = {}
        ft = FieldTimeline()
        for date_str, pct in entries:
            ft.insert_entry(TimelineEntry(
                date=date.fromisoformat(date_str),
                value=pct,
                source_clause_text="report",
                entry_type="SET",
            ))
        timelines["fund_percentage_realized"] = ft
        return timelines

    def test_true_on_signed_date(self):
        """Condition already TRUE when the document was signed."""
        timelines = self._make_timelines_with_realization([
            ("2024-01-01", 60.0),
        ])
        # realization >= 50 — already true at signed date
        ast = comparison("GTE", fn_call("FUND_REALIZATION_PCT"), lit(50))
        result = _find_first_true_date(
            ast, timelines,
            signed_date=date(2024, 1, 1),
            evaluation_date=date(2026, 1, 1),
        )
        assert result == date(2024, 1, 1)

    def test_true_mid_range(self):
        """Condition becomes TRUE only after a specific report date."""
        timelines = self._make_timelines_with_realization([
            ("2024-01-01", 10.0),
            ("2025-03-01", 55.0),
            ("2025-09-01", 70.0),
        ])
        ast = comparison("GTE", fn_call("FUND_REALIZATION_PCT"), lit(50))
        result = _find_first_true_date(
            ast, timelines,
            signed_date=date(2024, 6, 1),
            evaluation_date=date(2026, 1, 1),
        )
        # 2024-01-01 is before signed_date, 2025-03-01 is first candidate >= signed
        assert result == date(2025, 3, 1)

    def test_never_true_returns_none(self):
        """Condition never becomes TRUE up to evaluation_date."""
        timelines = self._make_timelines_with_realization([
            ("2024-01-01", 10.0),
            ("2025-03-01", 20.0),
        ])
        ast = comparison("GTE", fn_call("FUND_REALIZATION_PCT"), lit(50))
        result = _find_first_true_date(
            ast, timelines,
            signed_date=date(2024, 1, 1),
            evaluation_date=date(2026, 1, 1),
        )
        assert result is None

    def test_true_on_evaluation_date(self):
        """Condition becomes TRUE exactly on evaluation_date (edge case)."""
        timelines = self._make_timelines_with_realization([
            ("2024-01-01", 10.0),
            ("2026-06-01", 55.0),
        ])
        ast = comparison("GTE", fn_call("FUND_REALIZATION_PCT"), lit(50))
        result = _find_first_true_date(
            ast, timelines,
            signed_date=date(2024, 1, 1),
            evaluation_date=date(2026, 6, 1),
        )
        assert result == date(2026, 6, 1)

    def test_only_entry_dates_are_scanned(self):
        """Dates between timeline entries are not checked.

        If realization jumps from 10% (2024-01-01) to 55% (2025-09-01),
        the first TRUE date is 2025-09-01, not some date in between.
        """
        timelines = self._make_timelines_with_realization([
            ("2024-01-01", 10.0),
            ("2025-09-01", 55.0),
        ])
        ast = comparison("GTE", fn_call("FUND_REALIZATION_PCT"), lit(50))
        result = _find_first_true_date(
            ast, timelines,
            signed_date=date(2024, 6, 1),
            evaluation_date=date(2026, 1, 1),
        )
        # Should NOT return any date between 2024-06-01 and 2025-09-01
        assert result == date(2025, 9, 1)


# ═══════════════════════════════════════════════════════════════════════════
# B. resolve_document_dates — all branches
# ═══════════════════════════════════════════════════════════════════════════


class TestResolveDocumentDates:

    @pytest.fixture
    def empty_timelines(self):
        return {}

    @pytest.fixture
    def mock_client(self):
        return AsyncMock()

    @pytest.fixture
    def empty_cache(self):
        return {}

    def _make_ctx(self, **kwargs) -> ClauseWithContext:
        defaults = dict(
            clause_id="test:0:0",
            clause_text="test clause",
            source_signed_date="2024-06-01",
        )
        defaults.update(kwargs)
        return ClauseWithContext(**defaults)

    @pytest.mark.asyncio
    async def test_path1_effective_date_set_no_condition(
        self, empty_timelines, mock_client, empty_cache,
    ):
        """source_effective_date set, no condition → used directly."""
        ctx = self._make_ctx(source_effective_date="2025-01-15")
        result = await resolve_document_dates(
            [ctx], empty_timelines, date(2026, 1, 1),
            mock_client, empty_cache,
        )
        assert result[0].resolved_document_date == "2025-01-15"

    @pytest.mark.asyncio
    async def test_path2a_condition_date_type(
        self, mock_client, empty_cache,
    ):
        """source_effective_date_condition → AST returns date → resolved."""
        # Build timelines with fund_final_closing_date
        timelines: dict[str, FieldTimeline] = {}
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 15), value="2024-12-15",
            source_clause_text="seed", entry_type="SET",
        ))
        timelines["fund_final_closing_date"] = ft

        # ANNIVERSARY(2, fund_final_closing_date) → 2026-12-15
        date_ast = ASTNode(
            node_type="function_call", fn="ANNIVERSARY",
            args=[
                ASTNode(node_type="literal", value=2, value_type="number"),
                ASTNode(node_type="field_ref", field="fund_final_closing_date"),
            ],
        )

        ctx = self._make_ctx(
            source_effective_date_condition="effective 2nd anniversary of final closing",
        )

        with patch(
            "engine.pipeline.resolve_date_condition",
            new_callable=AsyncMock,
            return_value=("date", date_ast),
        ):
            result = await resolve_document_dates(
                [ctx], timelines, date(2027, 1, 1),
                mock_client, empty_cache,
            )

        assert result[0].resolved_document_date == "2026-12-15"

    @pytest.mark.asyncio
    async def test_path2b_condition_boolean_finds_true(
        self, mock_client, empty_cache,
    ):
        """source_effective_date_condition → boolean AST → finds first TRUE date."""
        timelines: dict[str, FieldTimeline] = {}
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=10.0,
            source_clause_text="report", entry_type="SET",
        ))
        ft.insert_entry(TimelineEntry(
            date=date(2025, 6, 1), value=55.0,
            source_clause_text="report", entry_type="SET",
        ))
        timelines["fund_percentage_realized"] = ft

        bool_ast = comparison("GTE", fn_call("FUND_REALIZATION_PCT"), lit(50))

        ctx = self._make_ctx(
            source_effective_date_condition="effective when realization hits 50%",
        )

        with patch(
            "engine.pipeline.resolve_date_condition",
            new_callable=AsyncMock,
            return_value=("boolean", bool_ast),
        ):
            result = await resolve_document_dates(
                [ctx], timelines, date(2026, 1, 1),
                mock_client, empty_cache,
            )

        assert result[0].resolved_document_date == "2025-06-01"

    @pytest.mark.asyncio
    async def test_path2c_boolean_never_true(
        self, mock_client, empty_cache,
    ):
        """Boolean condition never fires → resolved_document_date = None."""
        timelines: dict[str, FieldTimeline] = {}
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=10.0,
            source_clause_text="report", entry_type="SET",
        ))
        timelines["fund_percentage_realized"] = ft

        bool_ast = comparison("GTE", fn_call("FUND_REALIZATION_PCT"), lit(90))

        ctx = self._make_ctx(
            source_effective_date_condition="effective when realization hits 90%",
        )

        with patch(
            "engine.pipeline.resolve_date_condition",
            new_callable=AsyncMock,
            return_value=("boolean", bool_ast),
        ):
            result = await resolve_document_dates(
                [ctx], timelines, date(2026, 1, 1),
                mock_client, empty_cache,
            )

        assert result[0].resolved_document_date is None

    @pytest.mark.asyncio
    async def test_path2d_llm_raises_fallback(
        self, empty_timelines, mock_client, empty_cache,
    ):
        """LLM call raises → falls back to source_signed_date."""
        ctx = self._make_ctx(
            source_effective_date_condition="some unparseable condition",
            source_signed_date="2024-06-01",
        )

        with patch(
            "engine.pipeline.resolve_date_condition",
            new_callable=AsyncMock,
            side_effect=ValueError("LLM failed"),
        ):
            result = await resolve_document_dates(
                [ctx], empty_timelines, date(2026, 1, 1),
                mock_client, empty_cache,
            )

        assert result[0].resolved_document_date == "2024-06-01"

    @pytest.mark.asyncio
    async def test_path3_both_null_fallback_signed(
        self, empty_timelines, mock_client, empty_cache,
    ):
        """Both effective_date and condition null → falls back to source_signed_date."""
        ctx = self._make_ctx(source_signed_date="2024-03-15")
        result = await resolve_document_dates(
            [ctx], empty_timelines, date(2026, 1, 1),
            mock_client, empty_cache,
        )
        assert result[0].resolved_document_date == "2024-03-15"

    @pytest.mark.asyncio
    async def test_caching_same_condition_called_once(
        self, empty_timelines, empty_cache,
    ):
        """Same condition text on two clauses → resolve_date_condition called once."""
        date_ast = ASTNode(
            node_type="literal", value="2025-06-01", value_type="date",
        )
        mock_resolve = AsyncMock(return_value=("date", date_ast))

        ctx1 = self._make_ctx(
            clause_id="test:0:0",
            source_effective_date_condition="effective 15 June 2025",
        )
        ctx2 = self._make_ctx(
            clause_id="test:0:1",
            source_effective_date_condition="effective 15 June 2025",
        )

        with patch("engine.pipeline.resolve_date_condition", mock_resolve):
            await resolve_document_dates(
                [ctx1, ctx2], empty_timelines, date(2026, 1, 1),
                AsyncMock(), empty_cache,
            )

        # Called only once despite two clauses with same condition text
        assert mock_resolve.call_count == 1
        assert ctx1.resolved_document_date == "2025-06-01"
        assert ctx2.resolved_document_date == "2025-06-01"


# ═══════════════════════════════════════════════════════════════════════════
# C. resolve_confirmations
# ═══════════════════════════════════════════════════════════════════════════


class TestResolveConfirmations:

    @pytest.fixture
    def empty_timelines(self):
        return {}

    @pytest.fixture
    def mock_client(self):
        return AsyncMock()

    @pytest.fixture
    def empty_cache(self):
        return {}

    def _make_ctx(self, **kwargs) -> ClauseWithContext:
        defaults = dict(
            clause_id="test:0:0",
            clause_text="test clause",
            source_signed_date="2024-06-01",
            email_source_id="email_1",
        )
        defaults.update(kwargs)
        return ClauseWithContext(**defaults)

    def _make_intent(self, confirmation_required=False, intent_type="offer",
                     **kwargs) -> DocumentIntent:
        return DocumentIntent(
            intent_type=intent_type,
            confirmation_required=confirmation_required,
            **kwargs,
        )

    def _make_confirming_intent(self, target_type="offer", ref_date="2024-06-01",
                                confirmed_eff_date=None, confirmed_eff_cond=None,
                                **kwargs) -> DocumentIntent:
        return DocumentIntent(
            intent_type="confirmation",
            binding_status="binding",
            references=DocumentReference(
                document_type=target_type,
                reference_date=ref_date,
                confirmed_effective_date=confirmed_eff_date,
                confirmed_effective_date_condition=confirmed_eff_cond,
            ),
            **kwargs,
        )

    @pytest.mark.asyncio
    async def test_no_confirmation_required(
        self, empty_timelines, mock_client, empty_cache,
    ):
        """confirmation_required=False → is_confirmed=True immediately."""
        intent = self._make_intent(confirmation_required=False)
        ctx = self._make_ctx(document_intent=intent)

        result = await resolve_confirmations(
            [ctx], [], {},
            empty_timelines, date(2026, 1, 1),
            mock_client, empty_cache,
        )
        assert result[0].is_confirmed is True

    @pytest.mark.asyncio
    async def test_no_matching_confirming_intent(
        self, empty_timelines, mock_client, empty_cache,
    ):
        """confirmation_required=True, no match → is_confirmed=False."""
        intent = self._make_intent(
            confirmation_required=True, intent_type="offer",
        )
        ctx = self._make_ctx(document_intent=intent)

        result = await resolve_confirmations(
            [ctx], [], {"email_1": "2024-06-01"},
            empty_timelines, date(2026, 1, 1),
            mock_client, empty_cache,
        )
        assert result[0].is_confirmed is False

    @pytest.mark.asyncio
    async def test_confirmed_with_effective_date(
        self, empty_timelines, mock_client, empty_cache,
    ):
        """Confirming intent has confirmed_effective_date → overrides resolved_document_date."""
        intent = self._make_intent(
            confirmation_required=True, intent_type="offer",
        )
        ctx = self._make_ctx(
            document_intent=intent,
            resolved_document_date="2024-06-01",
        )

        confirming = self._make_confirming_intent(
            target_type="offer",
            ref_date="2024-06-01",
            confirmed_eff_date="2025-03-15",
        )

        result = await resolve_confirmations(
            [ctx], [(confirming, "2024-06-01")], {"email_1": "2024-06-01"},
            empty_timelines, date(2026, 1, 1),
            mock_client, empty_cache,
        )
        assert result[0].is_confirmed is True
        assert result[0].resolved_document_date == "2025-03-15"

    @pytest.mark.asyncio
    async def test_confirmed_effective_date_condition_date_type(
        self, mock_client, empty_cache,
    ):
        """confirmed_effective_date_condition with date AST → overrides resolved_document_date."""
        timelines: dict[str, FieldTimeline] = {}
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 15), value="2024-12-15",
            source_clause_text="seed", entry_type="SET",
        ))
        timelines["fund_final_closing_date"] = ft

        date_ast = ASTNode(
            node_type="function_call", fn="ANNIVERSARY",
            args=[
                ASTNode(node_type="literal", value=1, value_type="number"),
                ASTNode(node_type="field_ref", field="fund_final_closing_date"),
            ],
        )

        intent = self._make_intent(
            confirmation_required=True, intent_type="offer",
        )
        ctx = self._make_ctx(
            document_intent=intent,
            resolved_document_date="2024-06-01",
        )

        confirming = self._make_confirming_intent(
            target_type="offer",
            ref_date="2024-06-01",
            confirmed_eff_cond="effective 1st anniversary of final closing",
        )

        with patch(
            "engine.pipeline.resolve_date_condition",
            new_callable=AsyncMock,
            return_value=("date", date_ast),
        ):
            result = await resolve_confirmations(
                [ctx], [(confirming, "2024-06-01")], {"email_1": "2024-06-01"},
                timelines, date(2027, 1, 1),
                mock_client, empty_cache,
            )

        assert result[0].is_confirmed is True
        assert result[0].resolved_document_date == "2025-12-15"

    @pytest.mark.asyncio
    async def test_confirmed_effective_date_condition_boolean_type(
        self, mock_client, empty_cache,
    ):
        """confirmed_effective_date_condition with boolean AST → finds first TRUE date."""
        timelines: dict[str, FieldTimeline] = {}
        ft = FieldTimeline()
        ft.insert_entry(TimelineEntry(
            date=date(2024, 1, 1), value=10.0,
            source_clause_text="report", entry_type="SET",
        ))
        ft.insert_entry(TimelineEntry(
            date=date(2025, 9, 1), value=60.0,
            source_clause_text="report", entry_type="SET",
        ))
        timelines["fund_percentage_realized"] = ft

        bool_ast = comparison("GTE", fn_call("FUND_REALIZATION_PCT"), lit(50))

        intent = self._make_intent(
            confirmation_required=True, intent_type="offer",
        )
        ctx = self._make_ctx(
            document_intent=intent,
            resolved_document_date="2024-06-01",
        )

        confirming = self._make_confirming_intent(
            target_type="offer",
            ref_date="2024-06-01",
            confirmed_eff_cond="effective when realization hits 50%",
        )

        with patch(
            "engine.pipeline.resolve_date_condition",
            new_callable=AsyncMock,
            return_value=("boolean", bool_ast),
        ):
            result = await resolve_confirmations(
                [ctx], [(confirming, "2024-06-01")], {"email_1": "2024-06-01"},
                timelines, date(2026, 1, 1),
                mock_client, empty_cache,
            )

        assert result[0].is_confirmed is True
        assert result[0].resolved_document_date == "2025-09-01"

    @pytest.mark.asyncio
    async def test_condition_raises_preserves_existing(
        self, empty_timelines, mock_client, empty_cache,
    ):
        """LLM raises for confirmed_effective_date_condition → existing date preserved."""
        intent = self._make_intent(
            confirmation_required=True, intent_type="offer",
        )
        ctx = self._make_ctx(
            document_intent=intent,
            resolved_document_date="2024-06-01",
        )

        confirming = self._make_confirming_intent(
            target_type="offer",
            ref_date="2024-06-01",
            confirmed_eff_cond="unparseable condition",
        )

        with patch(
            "engine.pipeline.resolve_date_condition",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM failed"),
        ):
            result = await resolve_confirmations(
                [ctx], [(confirming, "2024-06-01")], {"email_1": "2024-06-01"},
                empty_timelines, date(2026, 1, 1),
                mock_client, empty_cache,
            )

        assert result[0].is_confirmed is True
        assert result[0].resolved_document_date == "2024-06-01"

    @pytest.mark.asyncio
    async def test_wrong_document_type_no_match(
        self, empty_timelines, mock_client, empty_cache,
    ):
        """Confirming intent with wrong document_type → no match."""
        intent = self._make_intent(
            confirmation_required=True, intent_type="offer",
        )
        ctx = self._make_ctx(document_intent=intent)

        confirming = self._make_confirming_intent(
            target_type="amendment",  # wrong type
            ref_date="2024-06-01",
        )

        result = await resolve_confirmations(
            [ctx], [(confirming, "2024-06-01")], {"email_1": "2024-06-01"},
            empty_timelines, date(2026, 1, 1),
            mock_client, empty_cache,
        )
        assert result[0].is_confirmed is False

    @pytest.mark.asyncio
    async def test_wrong_reference_date_no_match(
        self, empty_timelines, mock_client, empty_cache,
    ):
        """Confirming intent with wrong reference_date → no match."""
        intent = self._make_intent(
            confirmation_required=True, intent_type="offer",
        )
        ctx = self._make_ctx(document_intent=intent)

        confirming = self._make_confirming_intent(
            target_type="offer",
            ref_date="2023-01-01",  # wrong date
        )

        result = await resolve_confirmations(
            [ctx], [(confirming, "2024-06-01")], {"email_1": "2024-06-01"},
            empty_timelines, date(2026, 1, 1),
            mock_client, empty_cache,
        )
        assert result[0].is_confirmed is False

    @pytest.mark.asyncio
    async def test_wrong_binding_status_no_match(
        self, empty_timelines, mock_client, empty_cache,
    ):
        """Confirming intent with non-binding status → no match."""
        intent = self._make_intent(
            confirmation_required=True, intent_type="offer",
        )
        ctx = self._make_ctx(document_intent=intent)

        confirming = DocumentIntent(
            intent_type="confirmation",
            binding_status="pending_election",  # not binding
            references=DocumentReference(
                document_type="offer",
                reference_date="2024-06-01",
            ),
        )

        result = await resolve_confirmations(
            [ctx], [(confirming, "2024-06-01")], {"email_1": "2024-06-01"},
            empty_timelines, date(2026, 1, 1),
            mock_client, empty_cache,
        )
        assert result[0].is_confirmed is False


# ═══════════════════════════════════════════════════════════════════════════
# D. _recompute_ordering_and_filter
# ═══════════════════════════════════════════════════════════════════════════


class TestRecomputeOrderingAndFilter:

    def _make_ctx(self, **kwargs) -> ClauseWithContext:
        defaults = dict(
            clause_id="test:0:0",
            clause_text="test",
            is_confirmed=True,
            resolved_document_date="2025-01-01",
        )
        defaults.update(kwargs)
        return ClauseWithContext(**defaults)

    def test_unconfirmed_filtered_out(self):
        """Unconfirmed clause is excluded."""
        ctx = self._make_ctx(is_confirmed=False)
        result = _recompute_ordering_and_filter([ctx], date(2026, 1, 1))
        assert len(result) == 0

    def test_none_date_filtered_out(self):
        """Clause with resolved_document_date=None is excluded."""
        ctx = self._make_ctx(resolved_document_date=None)
        result = _recompute_ordering_and_filter([ctx], date(2026, 1, 1))
        assert len(result) == 0

    def test_future_date_filtered_out(self):
        """Clause with doc_date > evaluation_date is excluded."""
        ctx = self._make_ctx(resolved_document_date="2027-06-01")
        result = _recompute_ordering_and_filter([ctx], date(2026, 1, 1))
        assert len(result) == 0

    def test_valid_clauses_remain_sorted(self):
        """Valid clauses remain and are sorted by ordering key."""
        ctx1 = self._make_ctx(
            clause_id="a:0:0",
            resolved_document_date="2025-06-01",
            source_signed_date="2025-06-01",
            attachment_index=0,
        )
        ctx2 = self._make_ctx(
            clause_id="a:0:1",
            resolved_document_date="2025-01-01",
            source_signed_date="2025-01-01",
            attachment_index=0,
        )
        result = _recompute_ordering_and_filter(
            [ctx1, ctx2], date(2026, 1, 1),
        )
        assert len(result) == 2
        # ctx2 has earlier date → lower ordering key → comes first
        assert result[0].clause_id == "a:0:1"
        assert result[1].clause_id == "a:0:0"

    def test_tiebreak_attachment_then_clause(self):
        """Same date → lower attachment_index first → lower clause_index first."""
        ctx1 = self._make_ctx(
            clause_id="a:1:1",
            resolved_document_date="2025-01-01",
            attachment_index=1,
        )
        ctx2 = self._make_ctx(
            clause_id="a:0:0",
            resolved_document_date="2025-01-01",
            attachment_index=0,
        )
        result = _recompute_ordering_and_filter(
            [ctx1, ctx2], date(2026, 1, 1),
        )
        assert len(result) == 2
        assert result[0].clause_id == "a:0:0"
        assert result[1].clause_id == "a:1:1"


# ═══════════════════════════════════════════════════════════════════════════
# E. Stability loop
# ═══════════════════════════════════════════════════════════════════════════


class TestStabilityLoop:

    @pytest.mark.asyncio
    async def test_stable_after_one_pass(self):
        """Conditions don't change after execution → no re-execution.

        Mock resolve_document_dates to always return the same dates.
        _build_timelines should be called exactly once (initial).
        """
        call_count = {"build": 0}
        original_build = _build_timelines

        def counting_build(*args, **kwargs):
            call_count["build"] += 1
            return original_build(*args, **kwargs)

        with patch("engine.pipeline._build_timelines", side_effect=counting_build), \
             patch("engine.pipeline.build_clause_contexts", return_value=[]), \
             patch("engine.pipeline.run_clause_interpretation", new_callable=AsyncMock, return_value=[]), \
             patch("engine.pipeline.resolve_document_dates", new_callable=AsyncMock, return_value=[]), \
             patch("engine.pipeline.resolve_confirmations", new_callable=AsyncMock, return_value=[]), \
             patch("engine.pipeline._recompute_ordering_and_filter", return_value=[]), \
             patch("engine.pipeline._execute_clauses"):

            from engine.pipeline import evaluate, SESSIONS, SessionState
            session = SessionState("test")
            SESSIONS["test"] = session

            try:
                await evaluate("test", [], "2026-06-01", AsyncMock())
            finally:
                SESSIONS.pop("test", None)

        # Initial build + 1 fresh build for stability comparison (no re-execution rebuild)
        assert call_count["build"] == 2

    @pytest.mark.asyncio
    async def test_non_convergence_warning(self, caplog):
        """If dates change every pass → warning logged after MAX_STABILITY_PASSES."""
        pass_num = {"n": 0}

        async def shifting_resolve(contexts, *args, **kwargs):
            """Return different dates each pass."""
            for ctx in contexts:
                if ctx.source_effective_date_condition is not None:
                    ctx.resolved_document_date = f"2025-0{pass_num['n'] + 1}-01"
            pass_num["n"] += 1
            return contexts

        ctx = ClauseWithContext(
            clause_id="test:0:0",
            clause_text="test",
            source_signed_date="2024-01-01",
            source_effective_date_condition="some condition",
            is_confirmed=True,
        )

        with patch("engine.pipeline.build_clause_contexts", return_value=[ctx]), \
             patch("engine.pipeline.run_clause_interpretation", new_callable=AsyncMock, return_value=[ctx]), \
             patch("engine.pipeline.resolve_document_dates", new_callable=AsyncMock, side_effect=shifting_resolve), \
             patch("engine.pipeline.resolve_confirmations", new_callable=AsyncMock, return_value=[ctx]), \
             patch("engine.pipeline._build_timelines", return_value={}), \
             patch("engine.pipeline._recompute_ordering_and_filter", return_value=[]), \
             patch("engine.pipeline._execute_clauses"), \
             patch("engine.pipeline.insert_extracted_fields"):

            from engine.pipeline import evaluate, SESSIONS, SessionState
            session = SessionState("test-nc")
            SESSIONS["test-nc"] = session

            try:
                with caplog.at_level(logging.WARNING):
                    await evaluate("test-nc", [], "2026-06-01", AsyncMock())
            finally:
                SESSIONS.pop("test-nc", None)

        assert "did not converge" in caplog.text
