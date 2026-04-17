from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from engine.models import ClauseInstruction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. ExtractedFieldEntry — one extracted value for a field
# ---------------------------------------------------------------------------

class ExtractedFieldEntry(BaseModel):
    value: Any
    currency: str | None = None
    value_unit_type: str | None = None
    value_type: str | None = None
    value_as_of_date: str | None = None
    value_as_of_condition: str | None = None  # relative temporal qualifier (e.g., "Q2 2027", "this quarter")
    doc_type: str | None = None
    source_context: str | None = None
    email_source_id: str | None = None
    attachment_index: int | None = None


# ---------------------------------------------------------------------------
# 2. ClauseRecord — one clause from extraction
# ---------------------------------------------------------------------------

class ClauseRecord(BaseModel):
    clause_text: str
    doc_type: str | None = None
    source_signed_date: str | None = None
    source_effective_date: str | None = None
    source_effective_date_condition: str | None = None
    source_context: str | None = None
    email_source_id: str | None = None
    attachment_index: int | None = None


# ---------------------------------------------------------------------------
# 3. DocumentReference — references sub-object in document_intent
# ---------------------------------------------------------------------------

class DocumentReference(BaseModel):
    document_type: str | None = None
    reference_date: str | None = None
    reference_signals: str | None = None
    confirmed_effective_date: str | None = None
    confirmed_effective_date_condition: str | None = None


# ---------------------------------------------------------------------------
# 4. DocumentIntent — one document intent entry
# ---------------------------------------------------------------------------

class DocumentIntent(BaseModel):
    attachment_name: str | None = None
    attachment_index: int | None = None
    intent_type: str | None = None
    binding_status: str | None = None
    confirmation_required: bool = False
    references: DocumentReference | None = None
    resolutions: list | None = None  # skipped in V1
    lp_identifier: str | None = None
    gp_identifier: str | None = None


# ---------------------------------------------------------------------------
# 5. ClauseWithContext — central wrapper flowing through layers 2-5
# ---------------------------------------------------------------------------

class ClauseWithContext(BaseModel):
    # Identity
    clause_id: str | None = None

    # From ClauseRecord
    clause_text: str
    doc_type: str | None = None
    source_signed_date: str | None = None
    source_effective_date: str | None = None
    source_effective_date_condition: str | None = None
    source_context: str | None = None
    email_source_id: str | None = None
    attachment_index: int | None = None

    # Linked document intent (matched by attachment_index)
    document_intent: DocumentIntent | None = None

    # Layer 2: clause interpreter output
    interpreter_output: list[ClauseInstruction] | None = None

    # Layer 3: resolved document date
    resolved_document_date: str | None = None

    # Layer 4: confirmation status (default True — confirmed unless proven otherwise)
    is_confirmed: bool = True

    # Ordering key for sequential execution (email date · attachment · clause position)
    ordering_key: int = 0


# ---------------------------------------------------------------------------
# 6. ExtractionResult — wrapper for one row from node_a_cache
# ---------------------------------------------------------------------------

class ExtractionResult(BaseModel):
    # key = parsed_field_name, value = list of entries (one per source)
    extracted_fields: dict[str, list[ExtractedFieldEntry]]
    clauses: list[ClauseRecord]
    document_intent: list[DocumentIntent]



# ---------------------------------------------------------------------------
# 7. API Request/Response Models
# ---------------------------------------------------------------------------


class AttachmentRef(BaseModel):
    """Attachment metadata sent from frontend."""
    name: str
    attachment_index: int


class EmailData(BaseModel):
    """Email data sent from frontend on evaluate."""
    model_config = {"populate_by_name": True}

    id: str  # email _id
    subject: str = ""
    body: str = ""
    date: str = ""
    attachments: list[AttachmentRef] = []


class EvaluateRequest(BaseModel):
    """Request body for POST /session/{id}/evaluate."""
    evaluation_date: str
    lp_admission_date: str | None = None
    gp_claimed_fee: float | None = None
    email_dataset: list[EmailData]


class FeeVerdict(BaseModel):
    """Comparison of calculated fee vs GP's claimed fee."""
    calculated_fee: float
    gp_claimed_fee: float
    match: bool
    delta: float
    tolerance: float = 0.01  # 1 cent
