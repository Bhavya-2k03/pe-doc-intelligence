"""Push sample package emails + attachments to Supabase Postgres.

Usage:
  python push_packages.py

Reads specific emails from SQLite + PDF files from files/ dir,
tags them with a package name, and inserts into Postgres.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid

from dotenv import load_dotenv

load_dotenv()

SQLITE_PATH = "db.sqlite"
FILES_DIR = "files"
DATABASE_URL = os.getenv("DATABASE_URL")

# ── Package definitions ─────────────────────────────────────────────
# Maps package_id -> list of SQLite email _ids to include
PACKAGES = {
    "mfn_flow": ["e028", "e029", "e030"],
}

# Inline packages: defined directly here (no SQLite source).
# Each email dict: _id, date, from_entity, to_entity, subject, body,
# fund_name, attachments (list of {name, attachment_index}).
# Attachment files must exist in FILES_DIR.
INLINE_PACKAGES = {
    "mfn_flow": [
        {
            "_id": "e037",
            "date": "2028-12-01",
            "from_entity": "10x Growth Fund, L.P. (GP)",
            "to_entity": "Limited Partner",
            "subject": "Capital Account Statement - Quarter Ended December 31, 2028",
            "body": (
                "Dear Limited Partner,\n\n"
                "Please find below your Capital Account summary as of "
                "December 1, 2028.\n\n"
                "Your Invested Capital stands at $8,200,000 out of your total "
                "commitment of $10,000,000.\n\n"
                "    Capital Commitment:      $10,000,000\n"
                "    Invested Capital:        $8,200,000\n\n"
                "Please contact the General Partner with any questions.\n\n"
                "Regards,\n"
                "General Partner\n"
                "10x Growth Fund, L.P."
            ),
            "fund_name": "10x Growth Fund",
            "attachments": [],
        },
    ],
    "side_letter_flow": [
        {
            "_id": "e031",
            "date": "2024-11-17",
            "from_entity": "10x Growth Fund, L.P. (GP)",
            "to_entity": "Limited Partner",
            "subject": "Side Letter Agreement - 10x Growth Fund, L.P.",
            "body": (
                "Dear Limited Partner,\n\n"
                "Please find the attached side letter.\n\n"
                "Regards,\n"
                "General Partner\n"
                "10x Growth Fund, L.P."
            ),
            "fund_name": "10x Growth Fund",
            "attachments": [
                {"name": "SIDE_LETTER_AGREEMENT.pdf", "attachment_index": 0},
            ],
        },
        {
            "_id": "e032",
            "date": "2025-10-12",
            "from_entity": "10x Growth Fund, L.P. (GP)",
            "to_entity": "Limited Partner",
            "subject": "Q3 2025 Fund Realization Report - 10x Growth Fund, L.P.",
            "body": (
                "Dear Limited Partners,\n\n"
                "Please find the attached Q3 2025 Fund Realization Report.\n\n"
                "Regards,\n"
                "General Partner\n"
                "10x Growth Fund, L.P."
            ),
            "fund_name": "10x Growth Fund",
            "attachments": [
                {"name": "FUND_REALIZATION_Q3_2025.pdf", "attachment_index": 0},
            ],
        },
        {
            "_id": "e033",
            "date": "2028-01-16",
            "from_entity": "10x Growth Fund, L.P. (GP)",
            "to_entity": "Limited Partner",
            "subject": "Q4 2027 Fund Realization Update - 10x Growth Fund, L.P.",
            "body": (
                "Dear Limited Partners,\n\n"
                "We are pleased to share the following update regarding the Fund's "
                "performance.\n\n"
                "As of December 31, 2027, the Fund has reached a significant "
                "milestone. Cumulative distributions to Limited Partners now "
                "represent 62% of total aggregate capital commitments.\n\n"
                "    Fund Realization Percentage: 62%\n\n"
                "This reflects strong exit performance across the portfolio. A "
                "detailed quarterly report will follow in the coming weeks.\n\n"
                "Regards,\n"
                "General Partner\n"
                "10x Growth Fund, L.P."
            ),
            "fund_name": "10x Growth Fund",
            "attachments": [],
        },
        {
            "_id": "e038",
            "date": "2028-12-01",
            "from_entity": "10x Growth Fund, L.P. (GP)",
            "to_entity": "Limited Partner",
            "subject": "Capital Account Statement - Quarter Ended December 31, 2028",
            "body": (
                "Dear Limited Partner,\n\n"
                "Please find below your Capital Account summary as of "
                "December 1, 2028.\n\n"
                "Your Invested Capital stands at $8,200,000 out of your total "
                "commitment of $10,000,000.\n\n"
                "    Capital Commitment:      $10,000,000\n"
                "    Invested Capital:        $8,200,000\n\n"
                "Please contact the General Partner with any questions.\n\n"
                "Regards,\n"
                "General Partner\n"
                "10x Growth Fund, L.P."
            ),
            "fund_name": "10x Growth Fund",
            "attachments": [],
        },
    ],
    "multi_amendment": [
        {
            "_id": "e034",
            "date": "2024-03-20",
            "from_entity": "10x Growth Fund, L.P. (GP)",
            "to_entity": "Limited Partner",
            "subject": "Side Letter - Management Fee Rate Ceiling - 10x Growth Fund, L.P.",
            "body": (
                "Dear Limited Partner,\n\n"
                "Please find the attached side letter establishing a ceiling on "
                "the Management Fee rate.\n\n"
                "Regards,\n"
                "General Partner\n"
                "10x Growth Fund, L.P."
            ),
            "fund_name": "10x Growth Fund",
            "attachments": [
                {"name": "SIDE_LETTER_FEE_CAP.pdf", "attachment_index": 0},
            ],
        },
        {
            "_id": "e035",
            "date": "2028-06-15",
            "from_entity": "10x Growth Fund, L.P. (GP)",
            "to_entity": "Limited Partner",
            "subject": "Amendment No. 1 - Extension of Investment Period - 10x Growth Fund, L.P.",
            "body": (
                "Dear Limited Partner,\n\n"
                "Please find the attached Amendment No. 1 "
                "to the Limited Partnership Agreement\n\n"
                "Regards,\n"
                "General Partner\n"
                "10x Growth Fund, L.P."
            ),
            "fund_name": "10x Growth Fund",
            "attachments": [
                {"name": "AMENDMENT_IP_EXTENSION.pdf", "attachment_index": 0},
            ],
        },
        {
            "_id": "e036",
            "date": "2026-05-15",
            "from_entity": "10x Growth Fund, L.P. (GP)",
            "to_entity": "Limited Partner",
            "subject": "Management Fee Accommodation",
            "body": (
                "Dear Limited Partner,\n\n"
                "The General Partner hereby provides notice to Limited Partners "
                "of the following fee accommodation.\n\n"
                "The Management Fee rate otherwise payable by the Fund shall be "
                "reduced from 2.00% to 1.00% per annum for the period commencing "
                "January 1, 2028 and ending at the end of the Investment Period.\n\n"
                "This accommodation is intended to align the Management Fee burden "
                "with the Fund's revised deployment timeline.\n\n"
                "Please contact the General Partner with any questions.\n\n"
                "Regards,\n"
                "General Partner\n"
                "10x Growth Fund, L.P."
            ),
            "fund_name": "10x Growth Fund",
            "attachments": [],
        },
        {
            "_id": "e039",
            "date": "2030-06-15",
            "from_entity": "10x Growth Fund, L.P. (GP)",
            "to_entity": "Limited Partner",
            "subject": "Capital Account Statement - Quarter Ended June 30, 2030",
            "body": (
                "Dear Limited Partner,\n\n"
                "Please find below your Capital Account summary as of "
                "June 15, 2030.\n\n"
                "Your Invested Capital stands at $8,500,000 out of your total "
                "commitment of $10,000,000.\n\n"
                "    Capital Commitment:      $10,000,000\n"
                "    Invested Capital:        $8,500,000\n\n"
                "Please contact the General Partner with any questions.\n\n"
                "Regards,\n"
                "General Partner\n"
                "10x Growth Fund, L.P."
            ),
            "fund_name": "10x Growth Fund",
            "attachments": [],
        },
    ],
}


def ensure_package_column(cur):
    """Add 'package' column to emails table if it doesn't exist."""
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'emails' AND column_name = 'package'
            ) THEN
                ALTER TABLE emails ADD COLUMN package TEXT;
            END IF;
        END $$;
    """)


def read_emails_for_package(package_id: str, email_ids: list[str]):
    """Read specified emails from SQLite and tag with package."""
    conn = sqlite3.connect(SQLITE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row

    placeholders = ",".join("?" for _ in email_ids)
    cur = conn.execute(
        f"SELECT * FROM emails WHERE _id IN ({placeholders})", email_ids
    )
    rows = cur.fetchall()
    conn.close()

    emails = []
    attachments = []

    for row in rows:
        row = dict(row)
        email_id = row["_id"]

        emails.append({
            "_id": email_id,
            "from_entity": row.get("from_entity"),
            "to_entity": row.get("to_entity"),
            "subject": row.get("subject", ""),
            "body": row.get("body", ""),
            "date": row.get("date", ""),
            "fund_name": row.get("fund_name", ""),
            "package": package_id,
        })

        # Parse attachments
        att_json = row.get("attachments")
        if not att_json or att_json in ("[]", "None"):
            continue

        try:
            att_list = json.loads(att_json)
        except json.JSONDecodeError:
            print(f"  WARNING: bad attachments JSON for {email_id}")
            continue

        for att in att_list:
            file_path = att.get("file_path") or att.get("name")
            if not file_path:
                continue

            full_path = os.path.join(FILES_DIR, file_path)
            if not os.path.exists(full_path):
                print(f"  WARNING: PDF not found: {full_path}")
                continue

            with open(full_path, "rb") as f:
                file_bytes = f.read()

            file_id = str(uuid.uuid4())

            attachments.append({
                "file_id": file_id,
                "email_id": email_id,
                "name": att.get("name", file_path),
                "attachment_index": att.get("attachment_index", 0),
                "file_bytes": file_bytes,
            })

            print(f"  Read {full_path} ({len(file_bytes):,} bytes) -> file_id={file_id[:8]}...")

    return emails, attachments


def build_inline_package(package_id: str, email_defs: list[dict]):
    """Build emails + attachments from inline definitions."""
    emails = []
    attachments = []

    for e in email_defs:
        email_id = e["_id"]

        emails.append({
            "_id": email_id,
            "from_entity": e.get("from_entity"),
            "to_entity": e.get("to_entity"),
            "subject": e.get("subject", ""),
            "body": e.get("body", ""),
            "date": e.get("date", ""),
            "fund_name": e.get("fund_name", ""),
            "package": package_id,
        })

        for att in e.get("attachments", []):
            file_name = att["name"]
            full_path = os.path.join(FILES_DIR, file_name)
            if not os.path.exists(full_path):
                print(f"  WARNING: PDF not found: {full_path}")
                continue

            with open(full_path, "rb") as f:
                file_bytes = f.read()

            file_id = str(uuid.uuid4())

            attachments.append({
                "file_id": file_id,
                "email_id": email_id,
                "name": file_name,
                "attachment_index": att.get("attachment_index", 0),
                "file_bytes": file_bytes,
            })

            print(f"  Read {full_path} ({len(file_bytes):,} bytes) -> file_id={file_id[:8]}...")

    return emails, attachments


def push_to_postgres(emails: list[dict], attachments: list[dict]):
    """Insert emails and attachments into Postgres."""
    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
        return

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set in .env")
        return

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Ensure package column exists
    ensure_package_column(cur)
    conn.commit()

    # Insert emails
    inserted = 0
    updated = 0
    for e in emails:
        try:
            cur.execute(
                """INSERT INTO emails (_id, from_entity, to_entity, subject, body, date, fund_name, package)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (_id) DO UPDATE SET
                       from_entity = EXCLUDED.from_entity,
                       to_entity   = EXCLUDED.to_entity,
                       subject     = EXCLUDED.subject,
                       body        = EXCLUDED.body,
                       date        = EXCLUDED.date,
                       fund_name   = EXCLUDED.fund_name,
                       package     = EXCLUDED.package""",
                (e["_id"], e["from_entity"], e["to_entity"],
                 e["subject"], e["body"], e["date"], e["fund_name"], e["package"]),
            )
            if cur.statusmessage.startswith("INSERT"):
                inserted += 1
            else:
                updated += 1
        except Exception as ex:
            print(f"  ERROR inserting email {e['_id']}: {ex}")
            conn.rollback()
            continue

    conn.commit()
    print(f"\nEmails: {inserted} inserted, {updated} updated")

    # Insert attachments
    inserted_atts = 0
    skipped_atts = 0
    for a in attachments:
        try:
            cur.execute(
                """INSERT INTO attachments (file_id, email_id, name, attachment_index, file_bytes)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (email_id, attachment_index) DO NOTHING""",
                (a["file_id"], a["email_id"], a["name"],
                 a["attachment_index"], psycopg2.Binary(a["file_bytes"])),
            )
            if cur.rowcount > 0:
                inserted_atts += 1
            else:
                skipped_atts += 1
        except Exception as ex:
            print(f"  ERROR inserting attachment {a['file_id']}: {ex}")
            conn.rollback()
            continue

    conn.commit()
    print(f"Attachments: {inserted_atts} inserted, {skipped_atts} skipped")

    cur.close()
    conn.close()


def main():
    print("=" * 60)
    print("Pushing package emails to Postgres")
    print("=" * 60)

    if not os.path.exists(SQLITE_PATH):
        print(f"ERROR: SQLite DB not found at {SQLITE_PATH}")
        return

    for package_id, email_ids in PACKAGES.items():
        print(f"\n--- Package: {package_id} ({len(email_ids)} emails, SQLite) ---")
        emails, attachments = read_emails_for_package(package_id, email_ids)
        print(f"  {len(emails)} emails, {len(attachments)} attachments")
        push_to_postgres(emails, attachments)

    for package_id, email_defs in INLINE_PACKAGES.items():
        print(f"\n--- Package: {package_id} ({len(email_defs)} emails, inline) ---")
        emails, attachments = build_inline_package(package_id, email_defs)
        print(f"  {len(emails)} emails, {len(attachments)} attachments")
        push_to_postgres(emails, attachments)

    print("\nDone!")


if __name__ == "__main__":
    main()
