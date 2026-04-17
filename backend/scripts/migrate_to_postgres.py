"""Migrate seed data from SQLite + PDF files -> Postgres.

Usage:
  1. Set DATABASE_URL in .env (e.g., from Supabase)
  2. Run: python migrate_to_postgres.py

Creates tables if they don't exist, then inserts all data.
Skips emails that already exist (idempotent).
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


def read_sqlite_data() -> tuple[list[dict], list[dict]]:
    """Read emails and build attachment records from SQLite + PDF files.

    Returns:
        (emails, attachments) where:
        - emails: list of dicts for the emails table
        - attachments: list of dicts for the attachments table
    """
    conn = sqlite3.connect(SQLITE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM emails")
    rows = cur.fetchall()
    conn.close()

    emails: list[dict] = []
    attachments: list[dict] = []

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
        })

        # Parse attachments JSON
        att_json = row.get("attachments")
        if not att_json or att_json in ("[]", ""):
            continue

        try:
            att_list = json.loads(att_json)
        except json.JSONDecodeError:
            print(f"  WARNING: bad attachments JSON for {email_id}")
            continue

        for att in att_list:
            file_path = att.get("file_path")
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

            print(f"  Read {full_path} ({len(file_bytes)} bytes) -> file_id={file_id[:8]}...")

    return emails, attachments


def migrate_postgres(emails: list[dict], attachments: list[dict]):
    """Insert data into Postgres."""
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

    # Create tables
    cur.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            _id TEXT PRIMARY KEY,
            from_entity TEXT,
            to_entity TEXT,
            subject TEXT,
            body TEXT,
            date TEXT,
            fund_name TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attachments (
            file_id TEXT PRIMARY KEY,
            email_id TEXT NOT NULL REFERENCES emails(_id),
            name TEXT NOT NULL,
            attachment_index INTEGER NOT NULL,
            file_bytes BYTEA NOT NULL,
            UNIQUE(email_id, attachment_index)
        )
    """)

    conn.commit()

    # Insert emails
    inserted_emails = 0
    skipped_emails = 0
    for e in emails:
        try:
            cur.execute(
                """INSERT INTO emails (_id, from_entity, to_entity, subject, body, date, fund_name)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (_id) DO NOTHING""",
                (e["_id"], e["from_entity"], e["to_entity"],
                 e["subject"], e["body"], e["date"], e["fund_name"]),
            )
            if cur.rowcount > 0:
                inserted_emails += 1
            else:
                skipped_emails += 1
        except Exception as ex:
            print(f"  ERROR inserting email {e['_id']}: {ex}")
            conn.rollback()
            continue

    conn.commit()
    print(f"\nEmails: {inserted_emails} inserted, {skipped_emails} skipped (already exist)")

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
    print(f"Attachments: {inserted_atts} inserted, {skipped_atts} skipped (already exist)")

    cur.close()
    conn.close()
    print("\nMigration complete!")


def main():
    print("=" * 60)
    print("Migrating SQLite -> Postgres")
    print("=" * 60)

    if not os.path.exists(SQLITE_PATH):
        print(f"ERROR: SQLite DB not found at {SQLITE_PATH}")
        return

    print(f"\nReading from {SQLITE_PATH}...")
    emails, attachments = read_sqlite_data()
    print(f"\nFound {len(emails)} emails, {len(attachments)} attachments")

    print(f"\nConnecting to Postgres...")
    migrate_postgres(emails, attachments)


if __name__ == "__main__":
    main()
