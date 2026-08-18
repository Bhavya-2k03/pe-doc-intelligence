"""Tests for as-of-date document scoping and accurate progress counts.

Two behaviors are pinned here:

1. extract_all_emails must return results in input order even when some
   emails are served from cache and others are extracted — a reordering bug
   would silently attach one email's clauses to another email's id.
2. Progress details must report work actually done (uncached counts), not
   the total, which is what the terminal view shows the user.
"""

from datetime import date
from unittest.mock import AsyncMock

import pytest

from engine.extractor import (
    build_email_package,
    compute_email_hash,
    extract_all_emails,
)
from engine.pipeline_models import ClauseRecord, ExtractionResult
from main import _parse_iso_date


def _email(eid, date_str="2024-01-01", body="hello"):
    return {"_id": eid, "date": date_str, "subject": f"s-{eid}", "body": body,
            "attachments": []}


def _result(eid):
    """ExtractionResult tagged with its email id via a marker clause.

    ExtractionResult itself carries no email id — provenance lives on the
    individual clauses — so ordering is asserted through the clause.
    """
    return ExtractionResult(
        extracted_fields={},
        clauses=[ClauseRecord(clause_text=f"clause-{eid}", email_source_id=eid)],
        document_intent=[],
    )


def _ids(results):
    return [r.clauses[0].email_source_id for r in results]


def _prime_cache(cache, email, result):
    """Insert an email's result into the extraction cache under its real hash."""
    cache[compute_email_hash(build_email_package(email, None))] = result


# ---------------------------------------------------------------------------
# _parse_iso_date
# ---------------------------------------------------------------------------


class TestParseIsoDate:
    def test_plain_date(self):
        assert _parse_iso_date("2030-06-15") == date(2030, 6, 15)

    def test_timestamp_form(self):
        assert _parse_iso_date("2024-12-24T10:00:00Z") == date(2024, 12, 24)

    @pytest.mark.parametrize("bad", [None, "", "not-a-date", "15/06/2030"])
    def test_unparseable_is_none(self, bad):
        assert _parse_iso_date(bad) is None


# ---------------------------------------------------------------------------
# extract_all_emails — ordering and progress
# ---------------------------------------------------------------------------


class TestExtractAllEmails:
    async def test_order_preserved_when_mixing_cached_and_fresh(self, monkeypatch):
        emails = [_email(f"e{i}", body=f"body-{i}") for i in range(5)]
        cache = {}
        # Cache the 1st and 3rd only — extraction must fill the gaps in place.
        _prime_cache(cache, emails[1], _result("e1"))
        _prime_cache(cache, emails[3], _result("e3"))

        async def fake_extract(email_data, att, reg, client, ex_cache):
            return _result(email_data["_id"])

        monkeypatch.setattr("engine.extractor.extract_email", fake_extract)

        out = await extract_all_emails(
            email_dataset=emails, attachment_texts_by_email={},
            field_registry=[], openai_client=AsyncMock(), extraction_cache=cache,
        )
        assert _ids(out) == ["e0", "e1", "e2", "e3", "e4"]

    async def test_only_uncached_emails_are_extracted(self, monkeypatch):
        emails = [_email(f"e{i}", body=f"body-{i}") for i in range(3)]
        cache = {}
        _prime_cache(cache, emails[0], _result("e0"))

        called = []

        async def fake_extract(email_data, att, reg, client, ex_cache):
            called.append(email_data["_id"])
            return _result(email_data["_id"])

        monkeypatch.setattr("engine.extractor.extract_email", fake_extract)

        await extract_all_emails(
            email_dataset=emails, attachment_texts_by_email={},
            field_registry=[], openai_client=AsyncMock(), extraction_cache=cache,
        )
        assert sorted(called) == ["e1", "e2"]

    async def test_progress_counts_uncached_not_total(self, monkeypatch):
        emails = [_email(f"e{i}", body=f"body-{i}") for i in range(4)]
        cache = {}
        for i in (0, 1, 2):
            _prime_cache(cache, emails[i], _result(f"e{i}"))

        async def fake_extract(email_data, att, reg, client, ex_cache):
            return _result(email_data["_id"])

        monkeypatch.setattr("engine.extractor.extract_email", fake_extract)

        events = []

        async def on_progress(stage, detail=""):
            events.append(detail)

        await extract_all_emails(
            email_dataset=emails, attachment_texts_by_email={},
            field_registry=[], openai_client=AsyncMock(), extraction_cache=cache,
            on_progress=on_progress,
        )
        # One email needs work, three are cached — never "4".
        assert any("Extracting 1 email (3 cached)" in e for e in events)
        assert not any("Extracting 4" in e for e in events)
        # Stage settles on a summary, not on a per-item line.
        assert events[-1] == "Extracted 1 email (3 cached)"

    async def test_all_cached_reports_cached(self, monkeypatch):
        emails = [_email(f"e{i}", body=f"body-{i}") for i in range(3)]
        cache = {}
        for i in range(3):
            _prime_cache(cache, emails[i], _result(f"e{i}"))

        async def fake_extract(*a, **k):
            raise AssertionError("must not extract when everything is cached")

        monkeypatch.setattr("engine.extractor.extract_email", fake_extract)

        events = []

        async def on_progress(stage, detail=""):
            events.append(detail)

        out = await extract_all_emails(
            email_dataset=emails, attachment_texts_by_email={},
            field_registry=[], openai_client=AsyncMock(), extraction_cache=cache,
            on_progress=on_progress,
        )
        assert _ids(out) == ["e0", "e1", "e2"]
        assert events == ["3 emails — all cached"]
