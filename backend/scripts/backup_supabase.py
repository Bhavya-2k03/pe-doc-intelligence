"""Snapshot the Supabase emails + attachments tables to a local file.

The seed documents in Postgres are not versioned: scripts/push_packages.py
overwrites email rows by _id and replaces attachment rows outright, and the
PDF bytes it replaces exist nowhere else once overwritten. Rolling the code
back to an earlier deploy does not roll the documents back with it.

This script makes the documents restorable. Run it BEFORE every push:

    python scripts/backup_supabase.py            # write a snapshot
    python scripts/backup_supabase.py --list     # show existing snapshots

Restore with scripts/restore_supabase.py.

Snapshots land in backend/backups/ (gitignored — they contain PDF bytes and
would bloat the repo). Keep one off-machine before a deploy you care about.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND / ".env")

BACKUP_DIR = BACKEND / "backups"
TABLES = ("emails", "attachments")
# Snapshot format version — restore refuses anything it does not understand.
FORMAT_VERSION = 1


def _connect():
    """Open a Postgres connection, failing with an actionable message."""
    try:
        import psycopg2
    except ImportError:
        sys.exit("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")

    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("ERROR: DATABASE_URL not set in backend/.env")
    return psycopg2.connect(url)


def _encode(value):
    """Make a psycopg2 value JSON-safe.

    bytea comes back as memoryview/bytes and cannot go into JSON directly, so
    it is base64-wrapped in a tagged object that _decode reverses exactly.
    """
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes__": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def decode_value(value):
    """Reverse _encode. Shared with restore_supabase.py."""
    if isinstance(value, dict) and "__bytes__" in value:
        return base64.b64decode(value["__bytes__"])
    return value


def create_backup(label: str = "") -> Path:
    """Write a snapshot of every row in TABLES. Returns the file path.

    Columns are read from the cursor rather than hardcoded, so a schema change
    (a new column on emails, say) is captured without editing this script.
    """
    conn = _connect()
    cur = conn.cursor()

    snapshot: dict = {
        "format_version": FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "tables": {},
    }

    for table in TABLES:
        cur.execute(f"SELECT * FROM {table}")
        columns = [d[0] for d in cur.description]
        rows = [
            {col: _encode(val) for col, val in zip(columns, row)}
            for row in cur.fetchall()
        ]
        snapshot["tables"][table] = {"columns": columns, "rows": rows}

    cur.close()
    conn.close()

    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    suffix = f"_{label}" if label else ""
    path = BACKUP_DIR / f"supabase_{stamp}{suffix}.json"
    path.write_text(json.dumps(snapshot, indent=1))
    return path


def summarize(snapshot: dict) -> str:
    """One-line-per-table description of a snapshot's contents."""
    lines = []
    for table, data in snapshot["tables"].items():
        rows = data["rows"]
        detail = ""
        if table == "emails":
            pkgs: dict[str, int] = {}
            for r in rows:
                pkgs[r.get("package") or "(none)"] = pkgs.get(r.get("package") or "(none)", 0) + 1
            detail = "  " + ", ".join(f"{k}={v}" for k, v in sorted(pkgs.items()))
        elif table == "attachments":
            total = sum(
                len(decode_value(r["file_bytes"]))
                for r in rows
                if r.get("file_bytes") is not None
            )
            detail = f"  {total:,} bytes of PDF"
        lines.append(f"  {table:12s} {len(rows):3d} rows{detail}")
    return "\n".join(lines)


def list_backups() -> list[Path]:
    """Existing snapshots, newest first."""
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("supabase_*.json"), reverse=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="",
                    help="Tag appended to the filename, e.g. --label pre-push")
    ap.add_argument("--list", action="store_true",
                    help="List existing snapshots and exit (touches no DB)")
    args = ap.parse_args()

    if args.list:
        backups = list_backups()
        if not backups:
            print(f"No snapshots in {BACKUP_DIR}")
            return
        print(f"Snapshots in {BACKUP_DIR}:\n")
        for p in backups:
            try:
                snap = json.loads(p.read_text())
                created = snap.get("created_at", "?")
                counts = " ".join(
                    f"{t}={len(d['rows'])}" for t, d in snap["tables"].items()
                )
            except (json.JSONDecodeError, KeyError):
                created, counts = "?", "UNREADABLE"
            print(f"  {p.name}\n      {created}  {counts}  "
                  f"({p.stat().st_size / 1_048_576:.1f} MB)")
        return

    if args.label and not args.label.replace("-", "").replace("_", "").isalnum():
        sys.exit("ERROR: --label must be alphanumeric with - or _ (used in a filename)")

    print("Reading emails + attachments from Postgres…")
    path = create_backup(args.label)
    snapshot = json.loads(path.read_text())

    print(f"\nSnapshot written: {path}")
    print(f"  size: {path.stat().st_size / 1_048_576:.1f} MB")
    print(summarize(snapshot))
    print(f"\nRestore with:\n  python scripts/restore_supabase.py {path.name} --dry-run")


if __name__ == "__main__":
    main()
