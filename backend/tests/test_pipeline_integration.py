"""Integration test for pipeline.py — full evaluate() with real LLM.

This test hits the OpenAI API. Run separately from unit tests:
    pytest tests/test_pipeline_integration.py -v -s

Requires OPENAI_API_KEY in .env or environment.
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

# Skip entire module if no API key
pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set — skipping LLM integration tests",
)


@pytest.fixture(scope="module")
def openai_client():
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


@pytest.fixture(scope="module")
def session_and_result(openai_client):
    """Run evaluate() once, share across all tests in this module."""
    import asyncio
    from engine.pipeline import start_session, evaluate, DB_PATH

    session_id, _ = start_session(DB_PATH)

    result = asyncio.get_event_loop().run_until_complete(
        evaluate(
            session_id=session_id,
            full_email_dataset=[],
            evaluation_date_str="2026-06-01",
            openai_client=openai_client,
        )
    )
    return session_id, result


class TestEvaluateIntegration:

    def test_result_has_timelines(self, session_and_result):
        _, result = session_and_result
        assert "timelines" in result
        assert isinstance(result["timelines"], dict)
        assert len(result["timelines"]) > 0

    def test_result_has_stats(self, session_and_result):
        _, result = session_and_result
        stats = result["stats"]
        assert stats["total_clauses"] > 0
        assert stats["executed_clauses"] >= 0
        assert stats["confirmed"] >= 0

    def test_result_has_assumptions(self, session_and_result):
        _, result = session_and_result
        assert len(result["assumptions"]) > 0

    def test_management_fee_rate_in_timelines(self, session_and_result):
        _, result = session_and_result
        assert "management_fee_rate" in result["timelines"]
        entries = result["timelines"]["management_fee_rate"]
        assert len(entries) >= 1  # at least seed
        # Seed should be 2.0
        seed_entry = entries[0]
        assert seed_entry["value"] == 2.0

    def test_seed_fields_present(self, session_and_result):
        _, result = session_and_result
        expected_seeds = [
            "management_fee_rate", "management_fee_basis",
            "fund_initial_closing_date", "fund_final_closing_date",
            "fund_investment_end_date", "fund_term_end_date",
        ]
        for field in expected_seeds:
            assert field in result["timelines"], \
                f"Seed field '{field}' missing from timelines"

    def test_extracted_fields_layered(self, session_and_result):
        """Extracted fields from DB should appear in timelines."""
        _, result = session_and_result
        # fund_percentage_realized comes from extraction, not seed
        tl = result["timelines"]
        # At least some non-seed fields should exist
        non_seed_fields = set(tl.keys()) - set([
            "management_fee_rate", "management_fee_basis",
            "carried_interest_rate", "preferred_return_rate",
            "fund_initial_closing_date", "fund_final_closing_date",
            "fund_investment_end_date", "fund_term_end_date",
        ])
        assert len(non_seed_fields) > 0, \
            "No extracted fields found beyond seed timelines"

    def test_timeline_entries_have_dates(self, session_and_result):
        _, result = session_and_result
        for field, entries in result["timelines"].items():
            for e in entries:
                assert "date" in e and e["date"] is not None, \
                    f"Entry in {field} missing date"

    def test_manual_review_items_structure(self, session_and_result):
        _, result = session_and_result
        for item in result["manual_review_items"]:
            assert "clause_text" in item
            assert "reason" in item

    def test_unconfirmed_documents_structure(self, session_and_result):
        _, result = session_and_result
        for doc in result["unconfirmed_documents"]:
            assert "clause_text" in doc
            assert "doc_type" in doc

    def test_clause_instructions_cached(self, session_and_result):
        """After evaluate(), the session's interpreter_cache should have entries."""
        from engine.pipeline import SESSIONS
        session_id, _ = session_and_result
        session = SESSIONS[session_id]
        assert len(session.interpreter_cache) > 0

    def test_no_instruction_has_null_action(self, session_and_result):
        """Every cached instruction must have a valid action."""
        from engine.pipeline import SESSIONS
        session_id, _ = session_and_result
        session = SESSIONS[session_id]
        for clause_hash, instructions in session.interpreter_cache.items():
            for instr in instructions:
                assert instr.action in (
                    "SET", "ADJUST", "CONSTRAIN", "GATE",
                    "NO_ACTION", "MANUAL_REVIEW",
                ), f"Invalid action: {instr.action}"
