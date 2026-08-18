"""Tests for the as-of-evaluation-date filter on clause dispositions.

Manual Review / No Action / Unconfirmed lists must not surface clauses from
documents dated after the evaluation date — the same rule the timelines
follow. Undated clauses fail open (included), so nothing is silently dropped.
"""

from datetime import date

from engine.pipeline import _is_known_as_of
from engine.pipeline_models import ClauseWithContext

EVAL = date(2030, 9, 1)


def _ctx(resolved: str | None) -> ClauseWithContext:
    return ClauseWithContext(clause_text="x", resolved_document_date=resolved)


class TestIsKnownAsOf:
    def test_past_document_is_known(self):
        assert _is_known_as_of(_ctx("2026-05-15"), EVAL) is True

    def test_same_day_document_is_known(self):
        assert _is_known_as_of(_ctx("2030-09-01"), EVAL) is True

    def test_future_document_is_not_known(self):
        assert _is_known_as_of(_ctx("2031-01-15"), EVAL) is False

    def test_day_after_is_not_known(self):
        assert _is_known_as_of(_ctx("2030-09-02"), EVAL) is False

    def test_missing_date_fails_open(self):
        assert _is_known_as_of(_ctx(None), EVAL) is True

    def test_unparseable_date_fails_open(self):
        assert _is_known_as_of(_ctx("not-a-date"), EVAL) is True

    def test_timestamp_form_is_handled(self):
        # Email dates can carry a time component; the date part governs.
        assert _is_known_as_of(_ctx("2031-01-15T10:00:00Z"), EVAL) is False
        assert _is_known_as_of(_ctx("2026-05-15T10:00:00Z"), EVAL) is True
