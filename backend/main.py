"""FastAPI application -- PE Document Intelligence System.

Four endpoints:
  POST /session/start              -- create session, return seed emails
  POST /session/{id}/evaluate      -- SSE stream: progress events + final result
  GET  /attachment/{file_id}       -- stream a seed PDF from DB
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sqlite3
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

from constants import emails_and_attachment_fields
from engine.extractor import extract_all_emails
from engine.pdf_parser import parse_attachments
from engine.pipeline import evaluate, start_session, SESSIONS

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# App setup
# ═══════════════════════════════════════════════════════════════════════════

app = FastAPI(title="PE Document Intelligence", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenAI client (initialized once)
openai_client: AsyncOpenAI | None = None

REQUIRED_ENV_VARS = (
    "OPENAI_API_KEY",        # extraction + clause interpretation
    "LLAMA_CLOUD_API_KEY",   # PDF parsing
    "DATABASE_URL",          # Supabase Postgres (seed emails + attachments)
)


@app.on_event("startup")
async def startup():
    """Fail-fast on missing required env vars; initialize shared clients."""
    missing = [k for k in REQUIRED_ENV_VARS if not os.getenv(k)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            f"Set them in your .env (local) or platform env (Railway/prod)."
        )

    global openai_client
    openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    logger.info("Startup OK — all required env vars present.")


# ═══════════════════════════════════════════════════════════════════════════
# Seed data loading (SQLite for demo, Postgres for prod)
# ═══════════════════════════════════════════════════════════════════════════

SEED_DB_PATH = os.getenv("SEED_DB_PATH", "db.sqlite")
DATABASE_URL = os.getenv("DATABASE_URL")  # Postgres URL (optional)


def _fetch_seed_emails_sqlite(db_path: str, package: str | None = None) -> list[dict]:
    """Load seed emails from SQLite for demo."""
    if not os.path.exists(db_path):
        logger.warning("Seed DB not found at %s — returning empty", db_path)
        return []
    if not package or package == "custom":
        return []

    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT _id, subject, body, date, attachments FROM emails WHERE package = ? LIMIT 50",
            (package,)
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    emails = []
    for r in rows:
        email = dict(r)
        att_raw = email.get("attachments")
        if att_raw and isinstance(att_raw, str):
            try:
                email["attachments"] = json.loads(att_raw)
            except json.JSONDecodeError:
                email["attachments"] = []
        elif not att_raw:
            email["attachments"] = []
        emails.append(email)

    return emails


async def _fetch_seed_emails_postgres(database_url: str, package: str | None = None) -> list[dict]:
    """Load seed emails from Postgres for prod."""
    if not package or package == "custom":
        return []

    try:
        import asyncpg
    except ImportError:
        logger.error("asyncpg not installed — cannot connect to Postgres")
        return []

    try:
        conn = await asyncpg.connect(database_url)
        rows = await conn.fetch(
            "SELECT _id, subject, body, date FROM emails WHERE package = $1 LIMIT 100",
            package,
        )
        # Fetch attachments for these emails
        email_ids = [r["_id"] for r in rows]
        att_rows = await conn.fetch(
            "SELECT email_id, file_id, name, attachment_index "
            "FROM attachments WHERE email_id = ANY($1) "
            "ORDER BY email_id, attachment_index",
            email_ids,
        )
        await conn.close()

        # Group attachments by email_id
        att_by_email: dict[str, list[dict]] = {}
        for ar in att_rows:
            eid = ar["email_id"]
            if eid not in att_by_email:
                att_by_email[eid] = []
            att_by_email[eid].append({
                "file_id": ar["file_id"],
                "name": ar["name"],
                "attachment_index": ar["attachment_index"],
            })

        emails = []
        for r in rows:
            email = dict(r)
            email["attachments"] = att_by_email.get(email["_id"], [])
            emails.append(email)

        return emails
    except Exception:
        logger.exception("Failed to fetch from Postgres")
        return []


async def fetch_seed_emails(package: str | None = None) -> list[dict]:
    """Fetch seed emails from configured source, optionally filtered by package."""
    if DATABASE_URL:
        return await _fetch_seed_emails_postgres(DATABASE_URL, package)
    return _fetch_seed_emails_sqlite(SEED_DB_PATH, package)


def _fetch_attachment_bytes_sqlite(file_id: str) -> bytes | None:
    """Load PDF bytes from SQLite attachments table."""
    db_path = SEED_DB_PATH
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        cur = conn.execute(
            "SELECT file_bytes FROM attachments WHERE file_id = ?", (file_id,)
        )
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


async def _fetch_attachment_bytes_postgres(file_id: str) -> bytes | None:
    """Load PDF bytes from Postgres attachments table."""
    try:
        import asyncpg
    except ImportError:
        return None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        row = await conn.fetchrow(
            "SELECT file_bytes FROM attachments WHERE file_id = $1", file_id
        )
        await conn.close()
        return row["file_bytes"] if row else None
    except Exception:
        logger.exception("Failed to fetch attachment from Postgres")
        return None


async def fetch_attachment_bytes(file_id: str) -> bytes | None:
    """Fetch PDF bytes from configured source."""
    if DATABASE_URL:
        return await _fetch_attachment_bytes_postgres(file_id)
    return _fetch_attachment_bytes_sqlite(file_id)


# ═══════════════════════════════════════════════════════════════════════════
# Request/Response models
# ═══════════════════════════════════════════════════════════════════════════


class AttachmentInput(BaseModel):
    name: str
    attachment_index: int
    file_id: str | None = None     # present for seed attachments (fetch from DB)
    file_data: str | None = None   # base64-encoded PDF bytes (new uploads)


class EmailInput(BaseModel):
    _id: str
    subject: str = ""
    body: str = ""
    date: str = ""
    attachments: list[AttachmentInput] = []


class EvaluateRequest(BaseModel):
    evaluation_date: str
    lp_admission_date: str | None = None
    gp_claimed_fee: float | None = None
    email_dataset: list[dict]      # raw dicts (flexible, validated downstream)


# ═══════════════════════════════════════════════════════════════════════════
# GET /attachment/{file_id}
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/attachment/{file_id}")
async def get_attachment(file_id: str):
    """Stream a seed PDF from the database."""
    file_bytes = await fetch_attachment_bytes(file_id)
    if file_bytes is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    return Response(
        content=file_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={file_id}.pdf"},
    )


# ═══════════════════════════════════════════════════════════════════════════
# POST /session/start
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/session/start")
async def session_start(package: str | None = None):
    """Create a new session and return seed emails for the selected package.

    Args:
        package: optional query param — 'mfn_flow', 'side_letter',
                 'multi_amendment', or 'custom' (empty inbox).

    Returns:
        {session_id: str, emails: list[dict]}

    Emails include attachment metadata (name, attachment_index, file_id)
    but NOT file bytes. Use GET /attachment/{file_id} to fetch PDFs.
    """
    session_id = start_session()
    emails = await fetch_seed_emails(package)

    session = SESSIONS[session_id]
    session.emails = emails

    # Return emails with attachment metadata (no file bytes)
    email_response = []
    for e in emails:
        email_response.append({
            "_id": e.get("_id"),
            "subject": e.get("subject", ""),
            "body": e.get("body", ""),
            "date": e.get("date", ""),
            "attachments": [
                {
                    "name": att.get("name"),
                    "attachment_index": att.get("attachment_index"),
                    "file_id": att.get("file_id"),
                }
                for att in e.get("attachments", [])
            ],
        })

    return {"session_id": session_id, "emails": email_response}


# ═══════════════════════════════════════════════════════════════════════════
# POST /session/{session_id}/evaluate
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/session/{session_id}/evaluate")
async def session_evaluate(session_id: str, body: EvaluateRequest):
    """Run the full pipeline with SSE progress streaming.

    Returns a Server-Sent Events stream:
      event: progress   data: {"stage": "layer1", "detail": "Extracting email 1/25..."}
      event: progress   data: {"stage": "layer2", "detail": "Interpreting clause 3/12..."}
      ...
      event: result     data: { full result JSON }
    """
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")

    session = SESSIONS[session_id]
    emails = body.email_dataset
    progress_queue: asyncio.Queue = asyncio.Queue()

    async def on_progress(stage: str, detail: str = ""):
        await progress_queue.put({"stage": stage, "detail": detail})

    async def run_pipeline():
        """Execute the full pipeline, pushing progress events to the queue."""
        try:
            # ── Log raw emails received from frontend (DEBUG_TRACE=1 only) ──
            if os.getenv("DEBUG_TRACE") == "1":
                os.makedirs("debug_output", exist_ok=True)
                with open("debug_output/frontend_emails.txt", "w", encoding="utf-8") as _f:
                    _f.write(f"FRONTEND EMAILS RECEIVED — {body.evaluation_date}\n")
                    _f.write(f"Total emails: {len(emails)}\n")
                    _f.write(f"LP admission: {body.lp_admission_date}\n")
                    _f.write(f"GP claimed fee: {body.gp_claimed_fee}\n")
                    _f.write("=" * 70 + "\n")
                    for i, em in enumerate(emails):
                        _f.write(f"\n--- Email {i} ---\n")
                        _f.write(f"  _id: {em.get('_id')}\n")
                        _f.write(f"  subject: {em.get('subject')}\n")
                        _f.write(f"  date: {em.get('date')}\n")
                        _f.write(f"  direction: {em.get('direction')}\n")
                        body_text = em.get('body', '') or ''
                        _f.write(f"  body: {body_text[:200]}\n")
                        atts = em.get('attachments', [])
                        _f.write(f"  attachments: {len(atts)}\n")
                        for a in atts:
                            _f.write(f"    [{a.get('attachment_index')}] {a.get('name')} file_id={a.get('file_id')} has_data={bool(a.get('file_data'))}\n")

            # ── Step 1: Resolve attachment bytes + parse all PDFs in parallel ──
            await on_progress("parsing", "Resolving attachments...")
            attachment_texts_by_email: dict[str, list[dict]] = {}

            # Collect all attachments across all emails
            all_attachments: list[dict] = []  # each has email_id + file info
            for email in emails:
                email_id = email.get("_id", "")
                attachments = email.get("attachments", [])
                for att in attachments:
                    file_id = att.get("file_id")
                    file_data = att.get("file_data")
                    att_name = att.get("name", "")
                    att_index = att.get("attachment_index", 0)
                    file_bytes: bytes | None = None

                    if file_id:
                        file_bytes = await fetch_attachment_bytes(file_id)
                    elif file_data:
                        try:
                            file_bytes = base64.b64decode(file_data)
                        except Exception:
                            pass

                    if file_bytes is not None:
                        all_attachments.append({
                            "email_id": email_id,
                            "name": att_name,
                            "attachment_index": att_index,
                            "file_bytes": file_bytes,
                        })

            # Parse all PDFs in one parallel batch
            if all_attachments:
                await on_progress("parsing", f"Parsing {len(all_attachments)} PDFs...")
                parsed_list = await parse_attachments(all_attachments, session.parse_cache)

                # Distribute results back by email_id
                for att_input, parsed_output in zip(all_attachments, parsed_list):
                    eid = att_input["email_id"]
                    if eid not in attachment_texts_by_email:
                        attachment_texts_by_email[eid] = []
                    attachment_texts_by_email[eid].append(parsed_output)

            # ── Step 2: Extract (Layer 1) ─────────────────────────
            await on_progress("layer1", "Starting extraction...")
            extraction_results = await extract_all_emails(
                email_dataset=emails,
                attachment_texts_by_email=attachment_texts_by_email,
                field_registry=emails_and_attachment_fields,
                openai_client=openai_client,
                extraction_cache=session.extraction_cache,
                on_progress=on_progress,
            )

            # ── Step 3: Pipeline (Layers 2-5) ─────────────────────
            # Build email_id → date map for value_as_of_condition resolution
            _email_dates_by_id = {
                em.get("_id"): em.get("date", "").split("T")[0]
                for em in emails if em.get("_id") and em.get("date")
            }

            result = await evaluate(
                session_id=session_id,
                extraction_results=extraction_results,
                evaluation_date_str=body.evaluation_date,
                openai_client=openai_client,
                lp_admission_date_str=body.lp_admission_date,
                on_progress=on_progress,
                email_dates_by_id=_email_dates_by_id,
            )

            # ── Step 4: Fee verdict ───────────────────────────────
            fee_verdict = None
            if body.gp_claimed_fee is not None and result.get("fee_calculation"):
                calculated = result["fee_calculation"]["current_period"]["total_fee"]
                delta = abs(calculated - body.gp_claimed_fee)
                tolerance = 0.01
                fee_verdict = {
                    "calculated_fee": calculated,
                    "gp_claimed_fee": body.gp_claimed_fee,
                    "match": delta <= tolerance,
                    "delta": round(delta, 2),
                    "tolerance": tolerance,
                }
            result["fee_verdict"] = fee_verdict

            # Signal completion
            await progress_queue.put({"__result__": result})

        except Exception as exc:
            logger.exception("Pipeline failed")
            await progress_queue.put({"__error__": str(exc)})

    async def event_stream():
        """Yield SSE events from the progress queue."""
        task = asyncio.create_task(run_pipeline())
        try:
            while True:
                msg = await progress_queue.get()
                if "__result__" in msg:
                    yield f"event: result\ndata: {json.dumps(msg['__result__'], default=str)}\n\n"
                    break
                elif "__error__" in msg:
                    yield f"event: error\ndata: {json.dumps({'error': msg['__error__']})}\n\n"
                    break
                else:
                    yield f"event: progress\ndata: {json.dumps(msg)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# Run
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
