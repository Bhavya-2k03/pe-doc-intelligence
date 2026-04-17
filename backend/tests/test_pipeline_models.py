"""Tests for engine/pipeline_models.py — extraction result loading + Pydantic parsing."""
from __future__ import annotations

import pytest

from engine.pipeline_models import (
    ClauseRecord,
    ClauseWithContext,
    DocumentIntent,
    DocumentReference,
    ExtractionResult,
    ExtractedFieldEntry,
    load_extraction_results,
)
from engine.pipeline import DB_PATH


# ═══════════════════════════════════════════════════════════════════════════
# load_extraction_results — real DB
# ═══════════════════════════════════════════════════════════════════════════

class TestLoadExtractionResults:

    def test_loads_all_rows(self, extraction_results):
        assert len(extraction_results) == 20

    def test_each_result_is_typed(self, extraction_results):
        for r in extraction_results:
            assert isinstance(r, ExtractionResult)

    def test_clauses_are_typed(self, extraction_results):
        for r in extraction_results:
            for c in r.clauses:
                assert isinstance(c, ClauseRecord)
                assert isinstance(c.clause_text, str) and len(c.clause_text) > 0

    def test_intents_are_typed(self, extraction_results):
        for r in extraction_results:
            for d in r.document_intent:
                assert isinstance(d, DocumentIntent)

    def test_extracted_fields_are_typed(self, extraction_results):
        for r in extraction_results:
            for field_name, entries in r.extracted_fields.items():
                assert isinstance(field_name, str)
                for e in entries:
                    assert isinstance(e, ExtractedFieldEntry)

    def test_total_clauses(self, extraction_results):
        total = sum(len(r.clauses) for r in extraction_results)
        assert total >= 20  # we know there are at least 21

    def test_total_intents(self, extraction_results):
        total = sum(len(r.document_intent) for r in extraction_results)
        assert total >= 20

    def test_some_fields_exist(self, extraction_results):
        all_fields = set()
        for r in extraction_results:
            all_fields.update(r.extracted_fields.keys())
        # Known fields from the DB
        assert "fund_percentage_realized" in all_fields or len(all_fields) > 0


# ═══════════════════════════════════════════════════════════════════════════
# Pydantic model construction
# ═══════════════════════════════════════════════════════════════════════════

class TestPydanticModels:

    def test_extracted_field_entry_minimal(self):
        e = ExtractedFieldEntry(value=2600000)
        assert e.value == 2600000 and e.currency is None

    def test_extracted_field_entry_full(self):
        e = ExtractedFieldEntry(
            value=2600000, currency="USD", value_unit_type="major",
            value_type="Number", value_as_of_date="2025-11-30",
            doc_type="fund_realization_statement",
            source_context="total realized", email_source_id="e023",
            attachment_index=0,
        )
        assert e.email_source_id == "e023"

    def test_clause_record(self):
        c = ClauseRecord(clause_text="fee is 1.5%", doc_type="side_letter",
                         source_signed_date="2025-12-02")
        assert c.clause_text == "fee is 1.5%"

    def test_document_reference(self):
        r = DocumentReference(document_type="mfn_election",
                              reference_date="2025-11-20",
                              confirmed_effective_date="2025-12-01")
        assert r.confirmed_effective_date == "2025-12-01"

    def test_document_intent_with_references(self):
        ref = DocumentReference(document_type="mfn_election")
        d = DocumentIntent(intent_type="confirmation", binding_status="binding",
                           references=ref)
        assert d.references.document_type == "mfn_election"

    def test_document_intent_without_references(self):
        d = DocumentIntent(intent_type="notice")
        assert d.references is None

    def test_clause_with_context_defaults(self):
        c = ClauseWithContext(clause_text="test")
        assert c.is_confirmed is True
        assert c.ordering_key == 0
        assert c.interpreter_output is None

    def test_clause_with_context_has_clause_id(self):
        c = ClauseWithContext(clause_text="test", clause_id="e001:0:0")
        assert c.clause_id == "e001:0:0"

    def test_extraction_result_roundtrip(self):
        er = ExtractionResult(
            extracted_fields={
                "fund_percentage_realized": [
                    ExtractedFieldEntry(value=26, value_type="Percentage"),
                ],
            },
            clauses=[
                ClauseRecord(clause_text="fee reduced to 1.5%"),
            ],
            document_intent=[
                DocumentIntent(intent_type="notice", binding_status="binding"),
            ],
        )
        assert len(er.extracted_fields) == 1
        assert len(er.clauses) == 1
        assert len(er.document_intent) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Data integrity from real DB
# ═══════════════════════════════════════════════════════════════════════════

class TestDataIntegrity:

    def test_every_clause_has_email_source_id(self, extraction_results):
        for r in extraction_results:
            for c in r.clauses:
                assert c.email_source_id is not None, \
                    f"Clause missing email_source_id: {c.clause_text[:50]}"

    def test_most_clauses_have_doc_type(self, extraction_results):
        """Most clauses should have doc_type; a few may be None from extraction."""
        total = 0
        with_type = 0
        for r in extraction_results:
            for c in r.clauses:
                total += 1
                if c.doc_type is not None:
                    with_type += 1
        assert with_type / total > 0.5, \
            f"Only {with_type}/{total} clauses have doc_type"

    def test_intents_have_intent_type(self, extraction_results):
        for r in extraction_results:
            for d in r.document_intent:
                assert d.intent_type is not None

    def test_extracted_field_values_are_not_none(self, extraction_results):
        for r in extraction_results:
            for field_name, entries in r.extracted_fields.items():
                for e in entries:
                    assert e.value is not None, \
                        f"Null value in {field_name} from {e.email_source_id}"
